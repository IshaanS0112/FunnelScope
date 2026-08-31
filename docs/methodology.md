# Methodology

Every analytical choice in this project, why it was made, and what it costs.
If a number in `MEMO.md` is wrong, the reason is in here.

---

## 1. Ordered vs unordered funnel

**Choice: ordered.** Each stage must occur strictly after the previous one.

An unordered funnel asks "did this user ever do all four things?" That counts a user who
purchased on Monday and browsed more items on Friday as a completed
view → cart → checkout → purchase journey. It inflates conversion for free, and the
inflation is largest exactly where you care most — among engaged, repeat users.

Ordering is enforced by taking each user's **first occurrence** of each event and
comparing timestamps.

### The cumulative-predicate detail

The obvious way to write the stages is independently:

```sql
COUNTIF(cart_ts     > view_ts)      AS added_to_cart
COUNTIF(checkout_ts > cart_ts)      AS began_checkout   -- wrong
COUNTIF(purchase_ts > checkout_ts)  AS purchased        -- wrong
```

This is subtly broken. Row 2 counts a user whose checkout followed their cart even if
that user's cart did **not** follow their view. The stages stop being nested subsets, and
the funnel can go non-monotonic — more users beginning checkout than ever added to cart.
Each stage must re-assert every earlier condition:

```sql
COUNTIF(cart_ts > view_ts)                                                AS added_to_cart
COUNTIF(cart_ts > view_ts AND checkout_ts > cart_ts)                      AS began_checkout
COUNTIF(cart_ts > view_ts AND checkout_ts > cart_ts
        AND purchase_ts > checkout_ts)                                    AS purchased
```

`funnelscope.funnel.check_monotonic` fails the pipeline if this invariant ever breaks,
and `tests/test_sql_and_pipeline.py` greps the SQL itself for the missing predicates.

### Cross-validation

The funnel is computed a second time by a method that shares no logic with the first:
each user's events are collapsed into an ordered string (`V`, `C`, `K`, `P`) and tested
with a sequence regex (`sql/02b_funnel_validation.sql`). The pipeline refuses to produce
metrics if the two disagree by more than 0.5%.

The only expected source of drift is users with two funnel events at the identical
microsecond: method A uses strict `>` and drops them, method B keeps whatever order
`STRING_AGG` emits. Anything larger is a bug.

### What this funnel is not

It is **user-level, not session-level**. A user who views on Monday and buys three weeks
later counts as converted. A session-scoped funnel (partitioning on `ga_session_id`) would
be stricter and would produce lower conversion. Neither is more correct; they answer
different questions. Ours answers "does this user ever get there", which is the right
frame for prioritising product fixes and the wrong frame for evaluating a single campaign
landing experience.

---

## 2. Segment attribution

| Query | Attribution | Why |
|---|---|---|
| `03_funnel_by_device` | First event in the window | A funnel follows one journey; splitting a journey across two device rows would double-count the top of the funnel. |
| `04_funnel_by_source` | First event in the window | Acquisition channel is a property of how the journey started. |
| `07_revenue_by_segment` | The purchase event itself | Revenue belongs to the transaction where it happened. |

Mixing these conventions inside one figure would be an error; using each where it belongs
is not. Stated here because an interviewer should ask.

**Channels below 500 users fold into `(long tail)`.** A channel with 40 users and one
purchase has a 2.5% conversion rate with a confidence interval wide enough to contain
almost anything. Reporting it as a finding would be noise dressed as signal.

---

## 3. New vs returning

A user is **new** if a `first_visit` event falls inside the window, **returning** otherwise.

Known bias: users whose genuine first visit predates 2020-11-01 are correctly classified
returning, but so are users whose `first_visit` event simply failed to fire. The returning
cohort is therefore somewhat inflated. Direction of the bias is known; magnitude is not.

---

## 4. Retention and right-censoring

Weekly acquisition cohorts, `DATE_TRUNC(..., WEEK)`, retention measured as
*any activity* in week N — not purchase, not session count.

**The censoring correction is the part that matters.** In a fixed three-month window, a
cohort formed in week 10 cannot show week-8 retention: week 18 lies outside the data.
Plotted naively those cells read as zero and the late cohorts look like a collapse.

Every `(cohort, week)` cell whose seven-day observation window ends after the last date in
the data is tagged `censored` and is excluded from every average, curve and chart. The
heatmap reindexes over the full week range so a censored cell shows as a visible blank
rather than a missing column — "not yet observable" rather than "no data".

The pooled curve is `Σ active ÷ Σ cohort_size`, not the mean of per-cohort rates, so a
100-user cohort cannot swing the curve as hard as a 5,000-user one.

---

## 5. Opportunity sizing

```
users_recovered(S, x) = min(users_entering_S × x, users_lost_at_S)
recoverable(S, x)     = users_recovered × P(purchase | completed S) × AOV
```

### Correction to the standard formula

The usual write-up is `users_lost × improvement_pp × downstream × AOV`. That is wrong.
A percentage-point improvement is a change in the stage's **conversion rate**, whose
denominator is users *entering*, not users *lost*. Raising a 30% step to 35% recovers
`users_entering × 0.05`. The `users_lost` form understates the same lift by a factor of
`1/(1 − rate)` — 43% too low at a 30% step, and worse as the rate rises.
Both bases are implemented (`basis="entering"` default, `basis="lost"` available); they
are different claims and are labelled as such.

### This model cannot re-rank the stages

A common claim about opportunity sizing is that the largest recoverable revenue is usually
*not* at the worst percentage drop-off, and that the gap between the two is the finding.
**In a strictly ordered funnel that gap cannot exist.** Every purchaser passed through
every stage, so

```
P(purchase | completed stage j) = total_purchases / count_j
```

with `total_purchases` constant across stages, and therefore

```
recoverable_i  ∝  count_i / count_j  =  1 / step_conversion_i
```

which is strictly monotone in step conversion. The two rankings are identical, always.
`tests/test_sizing_and_rice.py::test_sizing_cannot_rerank_stages` asserts this over
random funnels so that a future change to the model which breaks the equivalence fails
loudly rather than silently manufacturing a finding.

Sizing still earns its place, for two reasons that are not re-ranking:
1. it converts a rate into a currency figure that can be weighed against **effort**,
   which is where real re-prioritisation happens (`funnelscope/rice.py`); and
2. **across segments** at the same stage it does carry independent information, because
   traffic volume and downstream conversion vary between segments in ways step conversion
   alone does not capture (`sizing.segment_gap_value`).

### Everything here is an upper bound

The model applies the purchase rate of users who **did** complete a stage to users who did
not. Recovered users are, by construction, the ones who needed recovering; they almost
certainly convert worse. Presenting these figures as a forecast would be overclaiming.
Presenting them as a ceiling for comparing stages is not.

---

## 6. Significance testing

Pooled two-proportion z-test, two-sided, α = 0.05, with an unpooled Wald confidence
interval on the difference. Implemented in `funnelscope/stats.py` against
`math.erfc` and checked against `scipy.stats.norm` in the test suite.

**Why it is here at all:** with tens of thousands of users almost any difference is
significant, and the test looks like a formality. It stops being a formality on the small
segments — a channel with 600 users, a tablet cohort — which is exactly where an
unguarded analysis invents findings. Reporting the interval alongside the point estimate
is what keeps a 0.3pp difference from being written up as a discovery.

**Not corrected for multiple comparisons.** Several segment comparisons are run; at
α = 0.05 that inflates the family-wise error rate. For the headline comparisons the
p-values are small enough that no correction would change the conclusion, but a
borderline result from this pipeline should not be trusted without one.

---

## 7. RICE prioritisation

`RICE = (Reach × Impact × Confidence) ÷ Effort`, Intercom's impact scale
(3 / 2 / 1 / 0.5 / 0.25), effort in person-weeks.

**Reach is measured** — users affected, straight from the funnel.
**Impact, Confidence and Effort are judgement.** There is no engineering team attached to
this analysis and no estimate to draw on. They are declared in
`scripts/analyze.py::INTERVENTION_CATALOG` with the assumption behind each one, so a
reader who disagrees can change a single number and watch the ranking move.

The value of the framework here is not that the scores are right. It is that the ranking
is reproducible from stated inputs instead of asserted.

---

## 8. BigQuery cost control

1. `_TABLE_SUFFIX BETWEEN` on every wildcard query. Without it, every daily table in the
   dataset is scanned.
2. No `SELECT *` anywhere, enforced by a test. BigQuery is columnar and bills per column.
3. `LIMIT` does not reduce cost — it truncates results, not the scan.
4. `WHERE event_name = ...` does not reduce cost either — it reduces rows, not columns.
5. `python scripts/run_queries.py --dry-run` reports exact bytes per query, unbilled.

Full refresh ≈ 4 GB against a 1 TiB monthly free allowance.

---

## 9. Limitations, ranked by how much they threaten the conclusions

1. **No cross-device identity.** `user_pseudo_id` is per browser. A user who browses on
   mobile and buys on desktop appears as two users, one of whom never converts. This
   inflates the measured mobile/desktop gap by an unknown amount and is the single
   largest threat to the headline finding.
2. **Three-month window.** Adequate for funnel work, short for retention; late cohorts
   are censored and handled as described above.
3. **Public demo dataset.** This is Google's obfuscated sample export, not a business
   problem personally uncovered. Stated plainly in the README.
4. **Obfuscated items.** No real product names, so no merchandising-level insight.
   Funnel and retention mechanics are unaffected.
5. **No experiment.** Every recommendation is a hypothesis with a size attached.
