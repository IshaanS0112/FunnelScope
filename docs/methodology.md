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

### Cross-validation, and the two things it caught

The funnel is computed a second time by a method that shares no funnel logic with the
first: each user's events are collapsed into an ordered string (`V`, `C`, `K`, `P`) and
tested with a sequence regex (`sql/02b_funnel_validation.sql`). The pipeline refuses to
produce metrics if the two disagree by more than 0.5%.

**It fired on the first real BigQuery export, and it was right to.** The two methods
differed by 9.6% / 16.2% / 17.3% across the three lower stages. Neither query had a bug.
They were answering different questions, and the fixture could not show it because every
synthetic user did each step exactly once at a distinct timestamp.

**Cause 1 — repeat events.** `STRING_AGG` over *every* event makes
`REGEXP_CONTAINS(seq, 'V.*C')` ask "did this user EVER cart after EVER viewing", while
`02` asks "did this user's FIRST cart follow their FIRST view". Those diverge the moment
a user repeats a step, and in this dataset they repeat constantly: **6.3 `view_item`
events per user, and 4.67 `add_to_cart` events per user who carts at all.** One pattern
alone — carted, browsed more, carted again — accounted for 938 extra users at the cart
stage. `02b` now aggregates first occurrences only.

**Cause 2 — GA4 batches events.** Every event in one network request carries the same
`event_timestamp`. Adding to cart straight from a product listing sends `view_item` and
`add_to_cart` together, so they tie exactly. **1,422 users tie at that step, 12.8% of
everyone who carts.** `02` uses strict `>` and drops all of them; `STRING_AGG` ordered
only by timestamp emits an arbitrary order and kept roughly half, leaving a 6.7%
residual gap. `02b` now orders by `first_ts, stage_rank DESC`, so a tie renders as `CV`
and fails the regex — exactly what `cart_ts > view_ts` does.

With both fixed the two methods agree **exactly**: 61,252 / 11,114 / 4,167 / 2,356, zero
difference at every stage. The check is marginally weaker for it, since both now read
`MIN(event_timestamp)`, but it is *correct*, and the bug the gate exists to catch —
stage predicates that are not cumulative — still cannot survive a sequence regex. A gate
that compares two different definitions is not a stronger gate; it is a broken one.

**The fixture now reproduces both behaviours** (`scripts/make_fixture.py`: repeat views
and carts, and a 12% rate of same-microsecond cart events), with
`tests/test_fixture_realism.py` asserting it still does. Finding this in the real export
rather than in the fixture is the failure mode PART 7 of the spec warns about, and the
tests exist so it cannot happen twice.

### The cost of strict ordering, stated rather than assumed

Dropping 1,422 users because two of their events share a microsecond is a choice. It is
the conservative one — an equal timestamp is not evidence of an ordering — and it is
what "each step must occur *after* the previous one" means. But it is not a small
choice: under `>=` the cart stage would read 12,536 rather than 11,114.

`sql/10_timestamp_ties.sql` measures it per step and `metrics.json` carries the result,
so the memo can state the magnitude in its limitations. Ties at the other two steps:
zero. An unquantified conservative choice is just an undisclosed one.

### User-scoped and session-scoped, and why both are reported

The headline funnel is **user-level**: a user who views on Monday and buys three weeks
later counts as converted. `sql/09_funnel_session_scoped.sql` runs the identical
cumulative-ordering funnel partitioned on `(user_pseudo_id, ga_session_id)` instead, so
the unit is the visit.

Neither is more correct; they answer different questions. The user-scoped funnel answers
*"does this user ever get there"*, which is the right frame for deciding what to fix in
the product — someone who returns three days later and buys was not lost, and counting
them as lost sends you chasing a drop-off that isn't one. The session-scoped funnel
answers *"does this visit complete"*, which is the right frame for judging a landing
experience or a single campaign, where a user who leaves and returns a week later is, for
that campaign's purposes, a failure.

**The comparison is the finding.** Session-scoped conversion is necessarily no higher
than user-scoped conversion — a user converts if *any* of their sessions does, so
collapsing sessions into users can only add conversions. `funnelscope.funnel.session_gap`
asserts that inequality (a violation means one of the two queries is wrong) and reports
the gap, which is a direct measure of how much of this funnel runs on return visits. A
small gap means the journey completes in one sitting and session-level fixes are the whole
game; a large gap means re-engagement is doing much of the selling, and optimising a
single session would be attacking the wrong surface.

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

### Densify before censoring

`06_cohort_retention.sql` joins cohorts to activity, so it emits a row only where
`active_users > 0`. A week in which nobody from a cohort came back produces **no row at
all** — which makes a genuinely-zero cell indistinguishable from a cell that lies outside
the data. Censoring can only be marked on rows that exist, so on that sparse grid the
censored share is computed over observed cells only and comes out far too low. On a grid
that happens to end near a week boundary it comes out as exactly **zero**, and the entire
censoring apparatus silently tests nothing while still printing a reassuring number.

`funnelscope.retention.densify` therefore expands the grid to the full
cohort × week rectangle first, filling absent cells with zero, using the earliest
cohort's runway as the horizon. Only then is censoring marked. That separates the two
cases properly:

| Case | Before densifying | After |
|---|---|---|
| Observable, nobody returned | missing row — invisible | real 0%, included in the average |
| Not observable yet | missing row — invisible | censored, excluded from the average |

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
`users_entering × 0.05`. How far off is the other form? Work it through rather than
asserting a number:

```
lost           = entering × (1 − rate)
lost_basis     = entering × (1 − rate) × pp
entering_basis = entering × pp

lost_basis ÷ entering_basis = (1 − rate)
```

The `users_lost` form is only `(1 − rate)` of the correct figure — **30% short at a 30%
step, half at a 50% step** — and correcting it means multiplying by `1/(1 − rate)`,
which is **1.43× at a 30% step**. Those are two different numbers, 0.70 and 1.43, and an
earlier draft of this document conflated them by calling the lost-basis figure "43% too
low". That was the correction factor misread as the size of the error. It is 30% short;
the correction is 1.43×.

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

### Confidence intervals, and what they do not cover

`funnelscope.sizing.bootstrap_recoverable` puts a 95% interval on each stage's
recoverable revenue. The funnel is a chain of nested binomials, so each resample redraws
that chain from the observed step rates and re-runs the sizing model on the redrawn
counts; the interval is the 2.5th–97.5th percentile of the result. It is a *parametric*
bootstrap because the export is aggregate counts — the per-user rows never leave
BigQuery — so a nonparametric resample of users is not available downstream.

**Read the interval for what it is.** It prices sampling variation in the counts and
nothing else. It does not price `improvement_pp`, which is chosen rather than measured
(that is the sensitivity sweep's job), and it does not price the model's load-bearing
assumption that recovered users purchase at the rate of unaided completers. That
assumption dominates the error and is not random, so no resampling scheme can touch it.
A tight interval here means "the counts are large", not "the number is right".

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

### Which comparison leads the memo

Nothing decides that in advance. `scripts/analyze.py` sizes every segment gap it tested,
keeps the ones surviving Holm, and the memo leads with the largest survivor — or states
that none survived.

This is not hypothetical tidiness. An earlier version always sized the **device** gap,
because the device split is usually the largest and most actionable cut in an ecommerce
funnel, and the memo template had a device narrative written into its TL;DR. On this
dataset the device gap is **not significant** — desktop 3.77% vs mobile 3.95%, p = 0.27,
on 35,711 and 24,151 users respectively — so the memo would have led with a finding this
pipeline's own z-test rejects. The synthetic fixture could never have caught it, because
the fixture is generated with a device effect deliberately baked in.

The gap that does survive is **new vs returning**: 3.60% against 6.40%, adjusted
p = 2e-24, worth about $99k in this window as an upper bound.

### Multiple comparisons

Several segment comparisons are run, and at α = 0.05 each the family-wise error rate is
not 0.05 but `1 − (1 − α)^m` — with four comparisons, 18.5%. An analysis that cuts a
funnel four ways and reports whatever came back significant is manufacturing findings at
a rate it has not disclosed.

**Holm–Bonferroni is applied across the whole comparison family** and both raw and
adjusted p-values are reported (`funnelscope.stats.holm_bonferroni`,
`adjusted_p_values`, `correct_family`). Holm rather than plain Bonferroni because it is
uniformly more powerful under the same assumptions: sort the p-values ascending, compare
the k-th against `α/(m−k)`, and stop at the first failure. That step-down stop is the
whole difference, and dropping it turns a valid procedure into an invalid one.

For the headline comparisons the p-values are small enough that the correction changes
nothing — which is worth saying explicitly rather than using it as an excuse to omit the
correction. `metrics.json` records how many comparisons survived it and names any that
did not, so a borderline result cannot be quoted as if it had.

---

## 6b. Designing the test

Every recommendation ends in "validate with an A/B test", so the pipeline designs that
test (`funnelscope/experiment.py`):

- **Primary metric** — the conversion rate of the step being changed, at its measured
  baseline.
- **Sample size** — Cohen's h, two-sided, α 0.05, power 0.80, 50/50 split; matches
  `statsmodels` `NormalIndPower` in the test suite.
- **Traffic** — users entering the step ÷ the 92-day window.
- **Duration** — at least 14 days (two weekly cycles, so a weekday pattern cannot pass for
  a treatment effect) and at most 28.
- **Guardrails** — the next step's conversion rate (the extra shoppers a fix lets through
  are the least committed, the same reason sizing is an upper bound) and AOV.

**The finding it produced:** at 666 product viewers a day, a 2-point lift in add-to-cart
is detectable in three weeks. The steps after it see 121 and 45 shoppers a day, so
nothing under 5 and 8 points is detectable within four weeks. The option that leads RICE
is therefore also the only one that can be validated before it ships — testability works
as a prioritisation input, and checkout changes would have to ship on judgement.

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
   mobile and buys on desktop appears as two users, one of whom never converts — and a
   returning user arriving on a second device is classified as new. That distorts every
   segment comparison by an unknown amount, including the new-vs-returning gap the memo
   leads with, and it is the single largest threat to the conclusions.
2. **Three-month window.** Adequate for funnel work, short for retention; late cohorts
   are censored and handled as described above.
3. **Public demo dataset.** This is Google's obfuscated sample export, not a business
   problem personally uncovered. Stated plainly in the README.
4. **Obfuscated items.** No real product names, so no merchandising-level insight.
   Funnel and retention mechanics are unaffected.
5. **No experiment.** Every recommendation is a hypothesis with a size attached.

---

## 10. Reproducibility and provenance

**The manifest.** Every write of `data/processed/` stamps `_manifest.json` with
`source: "bigquery"` or `source: "synthetic-fixture"`, the window, and a timestamp. The
memo renderer, the dashboard, the static site and the notebook all read that stamp and
label themselves from it. Fixture numbers therefore cannot render as a clean analysis —
not by convention, but because the banner is derived from the same file the numbers are.
`tests/` asserts the linkage in both directions: fixture data ⇒ banner present, real data
⇒ banner absent.

**The fixture is a real simulation, not a shortcut.** `scripts/make_fixture.py` emits a
per-user event log with timestamps and session ids, then aggregates it *twice* — once by
first-occurrence timestamps, once by event-sequence regex — exactly as `02` and `02b` do
against BigQuery. A fixture that wrote the funnel CSV directly would satisfy the
cross-validation gate trivially and test nothing.

**Re-export diff.** `scripts/analyze.py` compares the new `metrics.json` against the
previous one and prints every headline metric that moved, with the percentage change. A
pipeline that silently produces different numbers on a re-run is the failure this catches:
a query edited by hand, a window quietly widened, a channel that vanished because a source
stopped firing. A re-export that moves a number you did not expect to move is a broken
query until proven otherwise.

**Gate ordering.** Monotonicity and cross-validation run *before* any metric is computed,
and both raise. It is structurally impossible to produce `metrics.json` — and therefore a
memo, a dashboard or a site — from a funnel that failed validation.
