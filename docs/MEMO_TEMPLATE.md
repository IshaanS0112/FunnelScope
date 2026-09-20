# Where we lose buyers, what it costs, and what I would fix first

**To:** Product team, Google Merchandise Store
**From:** {{author}}
**Re:** Conversion funnel and retention, {{window_start}} to {{window_end}}
**Data:** {{provenance_line}}

---

## TL;DR

- **{{worst_step_lost}} of {{viewed}} product viewers never added one to the cart** — {{worst_step_article}} {{worst_step_dropoff}} drop at the funnel's widest point. End-to-end, {{end_to_end_conversion}} of viewers buy.
- {{gap_headline}}
- {{priority_bullet}}

## Where users drop off

{{funnel_table}}

The steepest step is **{{worst_step_label}}** at {{worst_step_dropoff}} lost, and it is where the most users are — which is why it dominates everything below.

{{scope_sentence}}

## Who drops off

{{segment_table}}

{{significance_paragraph}}

{{correction_sentence}}

Channels separate two problems a ranked table blurs. **{{worst_channel}}** sends {{worst_channel_users}} users at {{worst_channel_conv}} — high volume, low conversion, an expectation-mismatch problem, not a checkout one. **{{best_channel}}** converts at {{best_channel_conv}} on {{best_channel_users}} — a scale opportunity. (Names are obfuscated by Google, not broken.)

## What it's worth

Sizing model: `users entering × improvement_pp × P(purchase | next stage) × AOV`, AOV **{{aov}}**. The lift applies to users *entering* — the denominator of the rate it changes. The common `users lost × pp` form is only `(1 − rate)` of this.

{{opportunity_table}}

**Upper bounds, not forecasts.** The model applies stage completers' purchase rate to non-completers; recovered users almost certainly convert worse. The intervals price sampling variation only — not that assumption, which dominates the error.

**Sizing prices the stages, it does not re-rank them.** Every purchaser passed every stage, so `P(purchase | stage j) = purchases ÷ users at stage j` and recoverable revenue is a monotone function of step conversion. Ranking by dollars and by worst drop-off are the same ordering, necessarily (verified: `{{sizing_equivalence}}`) — treating them as two findings double-counts one fact. Effort re-ranks the work; that is the RICE table's job. The ranking also holds across the improvement assumption:

{{sensitivity_table}}

## What I'd do first

{{rice_table}}

{{rice_reasoning}}

Reach is measured; impact, effort and confidence are judgement, stated so you can change one and watch the ranking move.

## What I'd need to know next

This data records **what** users did, not **why**.

1. {{next_investigation}}
2. **A cart-abandonment exit survey.** Cart loss looks like friction; price shock has the same signature and a different fix.
3. **An A/B test on the top recommendation.** Everything above is a hypothesis with a size attached.

## Limitations

Ranked by threat to the conclusions, not by ease of admission:

1. **No cross-device identity.** `user_pseudo_id` is per browser, so a phone-browse / laptop-buy user is two users, one of whom never converts. That distorts every segment comparison by an unknown amount — the one limitation that could change what I do first.
2. **Recommendations are hypotheses.** No A/B test has been run; the ranking is reproducible from stated inputs, not a result.
3. **{{window_days}} days, {{censored_share}} of the retention grid right-censored** and excluded rather than zeroed — late cohorts are truncated, not worse.
4. {{tie_sentence}}
5. **Public demo data,** obfuscated at source — not a problem I uncovered, and channel and item names are redacted, so no merchandising insight. Funnel and retention mechanics are unaffected.

---

*Numbers regenerate from `data/processed/metrics.json`. Two independent funnel implementations
({{xval_note}}) agree to within {{xval_max_diff}}; the pipeline refuses to produce this memo if they do not.*
