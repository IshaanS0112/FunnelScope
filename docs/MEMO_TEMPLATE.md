# Where we lose buyers, what it costs, and what I would fix first

**To:** Product team, Google Merchandise Store
**From:** {{author}}
**Re:** Conversion funnel and retention, {{window_start}} to {{window_end}}
**Data:** {{provenance_line}}

---

## TL;DR

- **{{worst_step_lost}} of the {{viewed}} users who viewed a product never added one to the cart** — a {{worst_step_dropoff}} drop at the single widest point in the funnel. End-to-end, {{end_to_end_conversion}} of viewers buy.
- **{{gap_segment_a}} converts {{gap_pp}} lower than {{gap_segment_b}}** ({{gap_conv_a}} vs {{gap_conv_b}}). The difference is statistically real, not sampling noise ({{gap_test_short}}). Closing it would have been worth **{{gap_value}}** in this window.
- **Fix the {{gap_segment_a}} product page first.** It ranks first on RICE by an order of magnitude, and its reach term is measured rather than assumed.

## Where users drop off

{{funnel_table}}

The steepest step is **{{worst_step_label}}** at {{worst_step_dropoff}} lost — and it is also where the most users are, which is why it dominates everything below.

## Who drops off

{{segment_table}}

{{significance_paragraph}}

The channel picture separates two problems that look alike in a summary table. **{{worst_channel}}** sends {{worst_channel_users}} users converting at {{worst_channel_conv}} — high volume, low conversion, an expectation-mismatch or targeting problem, not a checkout problem. **{{best_channel}}** converts at {{best_channel_conv}} on {{best_channel_users}} users — an acquisition-scale opportunity. Opposite responses: spend less on the first, more on the second.

## What it's worth

Sizing model: `users entering × improvement_pp × P(purchase | reached the next stage) × AOV`, with AOV of **{{aov}}**. A percentage-point lift applies to the stage's conversion rate, whose denominator is users *entering* — the common `users lost × pp` form understates the same lift by a factor of `1/(1−rate)`.

{{opportunity_table}}

**Upper bounds, not forecasts.** The model applies the purchase rate of users who **did** complete a stage to users who did not; recovered users almost certainly convert worse.

**Sizing prices the stages, it does not re-rank them.** Every purchaser passed every stage, so `P(purchase | stage j) = purchases ÷ users at stage j`, and recoverable revenue collapses to a monotone function of step conversion. Ranking by dollars and by worst drop-off are the same ordering, necessarily (verified: `{{sizing_equivalence}}`). Treating them as two pieces of evidence double-counts one fact. Effort is what re-ranks the work, which is the RICE table's job.

Ranking is stable across the improvement assumption; only the absolute figures move:

{{sensitivity_table}}

## What I'd do first

{{rice_table}}

{{rice_reasoning}}

Reach is measured from the funnel. Impact, effort and confidence are judgement — there are no engineering estimates behind them. They are stated so you can change one and watch the ranking move, rather than argue with a conclusion.

## What I'd need to know next

This data records **what** users did and is silent on **why**.

1. **Session recordings for the {{gap_segment_a}} product page.** The gap is real; whether it is layout friction or different visit intent is not answerable from event counts.
2. **A cart-abandonment exit survey.** Cart loss looks like friction, but price shock produces an identical signature and needs a different fix.
3. **An A/B test on the top recommendation.** Everything above is a hypothesis with a size attached, not a result.

## Limitations

- **Public demo data.** Google's obfuscated GA4 sample export, not a business problem I uncovered. The analysis is real; the business is not mine.
- **{{censored_share}} of the retention grid is right-censored** and excluded rather than plotted as zeros. Late cohorts are truncated, not worse.
- **No cross-device identity.** `user_pseudo_id` is per browser, so someone who browses on a phone and buys on a laptop appears as two users, one of whom never converts. This inflates the measured device gap by an unknown amount — the largest single threat to the headline finding.
- **Obfuscated items,** so nothing merchandising-level can be said. Funnel and retention mechanics are unaffected.
- **{{window_days}} days.** Long enough for funnel work, short for retention.

---

*Numbers regenerate from `data/processed/metrics.json`. Two independent funnel implementations
({{xval_note}}) agree to within {{xval_max_diff}}; the pipeline refuses to produce this memo if they do not.*
