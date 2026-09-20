# Where we lose buyers, what it costs, and what I would fix first

**To:** Product team, Google Merchandise Store
**From:** {{author}}
**Re:** Conversion funnel and retention, {{window_start}} to {{window_end}}
**Data:** {{provenance_line}}

---

## TL;DR

- **{{worst_step_lost}} of {{viewed}} product viewers never added one to the cart** — a {{worst_step_dropoff}} drop at the funnel's widest point. End-to-end, {{end_to_end_conversion}} of viewers buy.
- **{{gap_segment_a}} converts {{gap_pp}} below {{gap_segment_b}}** ({{gap_conv_a}} vs {{gap_conv_b}}), statistically real ({{gap_test_short}}). Closing it was worth **{{gap_value}}** in this window.
- **Fix the {{gap_segment_a}} product page first.** It leads RICE by an order of magnitude and its reach term is measured, not assumed.

## Where users drop off

{{funnel_table}}

The steepest step is **{{worst_step_label}}** at {{worst_step_dropoff}} lost, and it is where the most users are — which is why it dominates everything below.

{{scope_sentence}}

## Who drops off

{{segment_table}}

{{significance_paragraph}}

{{correction_sentence}}

The channel picture separates two problems a ranked table blurs. **{{worst_channel}}** sends {{worst_channel_users}} users at {{worst_channel_conv}} — high volume, low conversion, an expectation-mismatch problem, not a checkout one. **{{best_channel}}** converts at {{best_channel_conv}} on {{best_channel_users}} — a scale opportunity. Opposite responses: spend less on the first, more on the second.

## What it's worth

Sizing model: `users entering × improvement_pp × P(purchase | reached the next stage) × AOV`, AOV **{{aov}}**. The lift applies to users *entering* — the denominator of the rate it changes. The common `users lost × pp` form is only `(1 − rate)` of this.

{{opportunity_table}}

**Upper bounds, not forecasts.** The model applies the purchase rate of users who **did** complete a stage to users who did not; recovered users almost certainly convert worse. The intervals price sampling variation only — not that assumption, which dominates the error.

**Sizing prices the stages, it does not re-rank them.** Every purchaser passed every stage, so `P(purchase | stage j) = purchases ÷ users at stage j` and recoverable revenue is a monotone function of step conversion. Ranking by dollars and by worst drop-off are the same ordering, necessarily (verified: `{{sizing_equivalence}}`), so treating them as two findings double-counts one fact. Effort re-ranks the work — the RICE table's job. The ranking also holds across the improvement assumption; only the absolute figures move:

{{sensitivity_table}}

## What I'd do first

{{rice_table}}

{{rice_reasoning}}

Reach is measured from the funnel. Impact, effort and confidence are judgement — no engineering estimates exist behind them. They are stated so you can change one and watch the ranking move.

## What I'd need to know next

This data records **what** users did and is silent on **why**.

1. **Session recordings for the {{gap_segment_a}} product page.** The gap is real; whether it is layout friction or different visit intent is not answerable from event counts.
2. **A cart-abandonment exit survey.** Cart loss looks like friction, but price shock has an identical signature and a different fix.
3. **An A/B test on the top recommendation.** Everything above is a hypothesis with a size attached.

## Limitations

Ranked by threat to the conclusions, not by how easy each is to admit.

1. **No cross-device identity.** `user_pseudo_id` is per browser, so a phone-browse / laptop-buy user is two users, one of whom never converts. That inflates the device gap by an unknown amount — and the device gap is the headline finding. The one limitation that could change what I do first.
2. **Recommendations are hypotheses.** Sizing figures are upper bounds and no A/B test has been run. The ranking is reproducible from stated inputs, not a result.
3. **{{window_days}} days, {{censored_share}} of the retention grid right-censored** and excluded rather than zeroed. Late cohorts are truncated, not worse.
4. **Public demo data,** with obfuscated items — Google's GA4 sample export, not a problem I uncovered. No merchandising-level insight; funnel and retention mechanics are unaffected.

---

*Numbers regenerate from `data/processed/metrics.json`. Two independent funnel implementations
({{xval_note}}) agree to within {{xval_max_diff}}; the pipeline refuses to produce this memo if they do not.*
