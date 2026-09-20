# Defending this project

The questions this project actually attracts, and the honest answer to each. Written down
because an answer you have not written down is an answer you have not finished thinking.

If you only read one section, read **"Did sizing change your priority ordering?"** and
**"Why did retention look worse for later cohorts?"** — the first is the best question
you will get, and the second is a trap.

---

## The funnel

**Walk me through your funnel — where's the biggest drop-off?**
61,252 users viewed an item, 11,114 carted, 4,167 began checkout, 2,356 bought — 3.85%
end to end. View → cart is the widest gap at 81.9% lost, and it dominates everything
downstream because it is both the steepest rate and where the most users are. The query
is `sql/02_funnel_ordered.sql`.

**Ordered or unordered funnel, and why?**
Ordered. Each stage must occur after the previous one. An unordered funnel asks "did this
user ever do all four things", which counts someone who bought on Monday and browsed more
items on Friday as a completed journey. That inflates conversion for free, and the
inflation is largest exactly among engaged repeat users — where you least want it.

**Why are your stage predicates cumulative?**
Because independent predicates let the funnel go non-monotonic. `COUNTIF(checkout_ts >
cart_ts)` on its own counts a user whose checkout followed their cart *even if that user's
cart never followed their view*. The stages stop being nested subsets and a later stage
can exceed an earlier one. It raises no error — it just produces a better-looking number.
Each stage re-asserts every earlier condition, `funnelscope.funnel.check_monotonic`
fails the pipeline if the invariant ever breaks, and a test greps the SQL itself for the
missing predicates.

**How do you know the two funnel implementations agree?**
The pipeline refuses to emit metrics if they diverge by more than 0.5%. One computes
first-occurrence timestamps and compares them; the other collapses each user's events
into an ordered string and matches a sequence regex. The funnel logic is independent, so
an error in timestamp comparison cannot hide inside regex matching.

**Did the gate ever actually fire?** *(Ask me this one.)*
Yes — on the first real BigQuery export, by 17%. Neither query had a bug; they were
answering different questions, and my synthetic fixture could not show it because every
fake user did each step once at a distinct timestamp.

Two causes, both specific to real GA4 data. First, **repeat events**: a regex over every
event asks "ever carted after ever viewing", while the funnel asks "did the first cart
follow the first view". Users repeat constantly here — 6.3 view_item events per user,
4.67 add_to_cart per carting user — and one pattern alone, carted then browsed then
carted again, accounted for 938 extra users. Second, **GA4 batches events**: everything
in one network request shares an `event_timestamp`, so adding to cart from a listing ties
with the view. 1,422 users tie, 12.8% of carters. Strict `>` drops all of them;
`STRING_AGG` ordered only by timestamp kept about half.

Fixed by restricting the validation query to first occurrences and breaking ties by stage
rank descending, which reproduces the strict-`>` rule exactly. The two methods now agree
to zero difference at every stage. I also rewrote the fixture to generate both behaviours
and added tests asserting it still does, because finding this in production data rather
than in the fixture means the fixture was not testing anything.

**Doesn't restricting to first occurrences make the check weaker?**
Slightly — both methods now read `MIN(event_timestamp)`. But the funnel logic on top is
still wholly independent, and that is what the gate is for: a stage predicate that is not
cumulative cannot survive a sequence regex. A gate that compares two different
definitions is not a stronger gate, it is a broken one that happens to be loud.

**How much did your own ordering rule throw away?**
1,422 users, 12.8% of the cart stage — the ones whose view and cart share a microsecond
because GA4 batched them. Under `>=` the stage reads 12,536 instead of 11,114. I kept the
strict reading because an equal timestamp is not evidence of an ordering, but I measure
it in `sql/10_timestamp_ties.sql` and state the number in the memo's limitations. A
conservative choice you do not quantify is just an undisclosed one.

**User-level or session-level?**
Both, and the gap between them is reported. The user-scoped funnel answers "does this user
ever get there", which is the right frame for deciding what to fix in the product — someone
who returns three days later and buys was not lost. The session-scoped funnel answers
"does this visit complete", which is the right frame for judging a landing experience.
Session-scoped conversion is necessarily no higher, so the gap measures how much of the
funnel runs on return visits — and a single-session optimisation would be attacking the
wrong surface for that share of it.

**How do you extract a value from `event_params`?**
Correlated subquery over `UNNEST`, filtered by key, selecting the correct typed field.
GA4 stores parameters as `ARRAY<STRUCT<key STRING, value STRUCT<string_value, int_value,
double_value, …>>>`, so there is no dot-path — you must unnest, filter by key, and know
which typed field the value lives in. `sql/08_event_params_reference.sql` is the worked
example.

---

## Statistics

**How did you know the device difference was real?**
*It wasn't.* Desktop 3.77% vs mobile 3.95%, p = 0.27 — inside the noise, and the memo says
"do not act on it" rather than writing it up. That is the whole reason the test is there:
the device split is the cut everyone expects to be the finding, and on this dataset it is
not one. The gap that does survive is new vs returning, 3.60% vs 6.40%, adjusted
p = 2e-24.

Pooled two-proportion z-test for the statistic, unpooled Wald interval for the CI on the
difference, two-sided at α = 0.05, Holm-corrected across the comparison family.

**How does the memo avoid asserting a finding the data rejects?**
It does not pick the headline gap in advance. `analyze.py` sizes every segment gap it
compared, keeps only those surviving Holm, and the memo leads with the largest survivor —
or states plainly that none survived. An earlier version hardcoded the device narrative
into the template, which would have published a device finding the z-test had already
rejected, and the fixture could not catch it because the fixture was generated with a
device effect baked in.

**Why bother testing at n = 60,000, where everything is significant?**
Because it isn't. The device comparison has 35,711 desktop users against 24,151 mobile —
enormous by any standard — and still comes back at p = 0.27. That is the answer to the
question: large n makes small *real* effects detectable, it does not manufacture effects
that are not there. The 0.18pp device difference is what an unguarded analysis writes up
as "mobile underperforms" and then spends a quarter fixing. Reporting the interval
alongside the point estimate is what stops that.

**Why Holm and not Bonferroni?**
Uniformly more powerful under the same assumptions, so it costs nothing. Sort the
p-values ascending, compare the k-th against `α/(m−k)`, and **stop at the first failure** —
every remaining hypothesis is retained whatever its own p-value. That step-down stop is
the whole difference, and dropping it turns a valid procedure into an invalid one. Here
the p-values are small enough that the correction changes no conclusion, which the memo
states rather than using as an excuse to omit it.

**Why did you implement the z-test by hand?**
So the runtime has no SciPy dependency for one normal-tail lookup. `math.erfc` is in the
standard library. The test suite checks it against `scipy.stats.norm`, and Holm against
`statsmodels` — the heavier dependencies belong in tests, not in the thing that has to run.

---

## Sizing

**How did you size the opportunity?**
`users_entering × improvement_pp × P(purchase | reached the next stage) × AOV`, capped at
the users actually lost — you cannot recover more users than left. Stated as an upper
bound, because it applies completers' behaviour to non-completers.

**Why users entering and not users lost?**
A percentage-point lift changes the conversion *rate*, and that rate's denominator is
users entering. Raising a 30% step to 35% recovers `entering × 0.05`. The lost-basis form
gives `entering × (1 − rate) × 0.05`, which is only `(1 − rate)` of the correct figure —
**30% short at a 30% step, half at a 50% step**. Correcting it means multiplying by
`1/(1 − rate)`, which is **1.43× at a 30% step**. Those are two different numbers and it
is easy to quote the correction factor as if it were the error; an earlier draft of this
repo did exactly that, and the fix is in the git history.

**Did sizing change your priority ordering?**
No — and it provably can't, which is the more interesting answer. In a strictly ordered
funnel every purchaser passed through every stage, so
`P(purchase | stage j) = purchases ÷ count_j` with purchases constant across stages.
Recoverable revenue therefore reduces to `count_i / count_j = 1 / step_conversion_i`,
strictly monotone in step conversion. Ranking by dollars and ranking by worst drop-off are
the same ordering, necessarily, for every funnel. So the popular claim that "the biggest
recoverable revenue is rarely the worst drop-off stage, and that gap is the finding" is
not a finding — it is impossible. I verified it over 20,000 random funnels, and there is a
property test in the suite so a future change to the model that breaks the equivalence
fails loudly instead of quietly manufacturing a finding.

Sizing still earns its place twice over: it converts a rate into a currency figure that
can be weighed against **effort**, which is where the real re-prioritisation happens; and
*across segments* at the same stage it does carry independent information, because traffic
volume and downstream conversion vary between segments in ways step conversion does not
capture.

**Your confidence intervals look narrow. Are the numbers that precise?**
No, and the interval is not claiming they are. It prices sampling variation in the counts
and nothing else — not the improvement assumption, which is chosen rather than measured,
and not the model's load-bearing assumption that recovered users purchase like unaided
completers. That assumption dominates the error and is not random, so no resampling scheme
can touch it. A tight interval here means the counts are large, not that the number is
right.

**Why publish a sweep instead of one number?**
Because the absolute figures move with the improvement assumption and the ranking does
not. The stability is the defensible claim; a single number invites a precision that is
not there.

---

## Retention

**Why did retention look worse for later cohorts?**
It doesn't. Those cells are right-censored by the three-month window — a cohort formed in
week 10 physically cannot show week-8 retention, because week 18 is outside the data. They
are excluded from every average and chart rather than plotted as zeros, and the heatmap is
reindexed over the full week range so a censored cell is a visible blank. A missing column
reads as "no data collected"; a blank cell reads as "not yet observable", and only the
second is true.

**How do you know your censoring logic actually fires?**
Because it did not, at first. The retention query joins cohorts to activity, so it emits
no row at all for a week in which nobody returned — which makes a real zero and an
unobservable cell indistinguishable, and censoring can only be marked on rows that exist.
On that sparse grid the censored share is computed over observed cells only; on a grid
that ends near a week boundary it comes out as exactly 0% while appearing to work.
`densify()` expands the grid to the full cohort × week rectangle before censoring is
marked, and a regression test asserts the censored count is zero on the sparse grid and
non-zero on the dense one.

**How is the pooled curve computed?**
`Σ active ÷ Σ cohort_size`, not the mean of per-cohort rates, so a 100-user cohort cannot
swing the curve as hard as a 5,000-user one. It is a one-line bug with a
plausible-looking output, so there is an explicit test.

---

## Engineering

**What was the most expensive thing you found?**
`ga_session_id` lives inside `event_params`, and BigQuery cannot read one key out of a
repeated record without reading the record. The session-scoped funnel therefore scans
982 MB for a single integer — more than the next four queries combined, and 5.7× the
identical funnel partitioned on `user_pseudo_id`. That is in `docs/QUERY_COSTS.md`
alongside the header estimate it disproved.

**How did you control BigQuery costs?**
`_TABLE_SUFFIX BETWEEN` on every wildcard query — without it you scan every daily table in
the dataset, and that is the mistake that burns the free tier. No `SELECT *` anywhere,
including inside CTEs, because BigQuery is columnar and bills per column. Dry-run before
every run. And knowing what does *not* help: `LIMIT` truncates the result, not the scan,
and `WHERE event_name = ...` reduces rows, not columns. Neither saves a byte. A full
refresh is 2.7 GB measured against a 1 TiB monthly allowance — about 380 free
re-runs a month, logged per query in `docs/QUERY_COSTS.md`.

**Why export to CSV instead of querying BigQuery from the dashboard?**
Two sandbox constraints force it — tables and views expire after 60 days and DML is
blocked — but it is the right call regardless. Because the front ends read committed
exports, anyone can open them with no GCP account. A live-query dashboard would run for
exactly one person and be dead in 60 days.

**How do you stop fixture numbers being mistaken for findings?**
Structurally, not by discipline. Every write of `data/processed/` stamps a manifest with
`bigquery` or `synthetic-fixture`, and every consumer derives its banner from that same
file. Fixture output carries an unmissable "NOT AN ANALYSIS" banner it cannot lose,
because the banner and the numbers come from one source. A test asserts the linkage in
both directions.

**What stops the notebook and the memo disagreeing?**
There is exactly one implementation of the maths, in `funnelscope/`. The notebook, the
memo renderer, the Streamlit app and the static site all import it and re-implement
nothing. The moment two of them compute the same rate independently, both become
worthless.

**How do you know a re-export didn't break something?**
`analyze.py` diffs the new `metrics.json` against the previous one and prints every
headline metric that moved, with the percentage change. A re-export that moves a number
you did not expect to move is a broken query until proven otherwise.

---

## The honest ones

**What can't this data tell you?**
Intent, friction cause, and cross-device identity. It records what users did and is silent
on why. Next steps: session recordings on the weakest device's product page, a
cart-abandonment exit survey, and an A/B test on the top recommendation.

**What's the biggest weakness of the whole thing?**
`user_pseudo_id` is per browser, not per person. Someone who browses on a phone and buys
on a laptop is two users, one of whom never converts. That distorts every segment
comparison by an unknown amount — including the new-vs-returning gap that is the headline
finding, since a returning user on a second device looks new. It is first in the memo's
limitations for that reason, ranked by threat rather than by how easy it is to admit.

**This is a public demo dataset, not a problem you found.**
Correct, and the README says so in its second paragraph. It exists to demonstrate SQL
against real event structure and product-analytical reasoning. The analysis is real; the
business is not mine.

**No A/B test, so none of this is validated.**
Right. That is in "what I'd need to know next". Recommendations here are hypotheses with a
size attached, not conclusions, and the memo says that rather than claiming an impact
figure it cannot support.
