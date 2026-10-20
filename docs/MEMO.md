# Where we lose buyers, what it costs, and what I would fix first

**To:** Product team, Google Merchandise Store
**From:** Ishaan Singh
**Re:** Conversion funnel and retention, 2020-11-01 to 2021-01-31
**Data:** bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*, 2020-11-01 to 2021-01-31. Exported 2026-09-20.

---

## TL;DR

- **50,138 of 61,252 product viewers never added one to the cart** — an 81.9% drop at the funnel's widest point. End-to-end, 3.85% of viewers buy.
- **new converts 2.80pp below returning** (3.60% vs 6.40%), the widest gap surviving Holm correction (adjusted p = 2e-24). Closing it was worth **$99,492**, upper bound.
- **Start with: rework the product page add-to-cart path.** It leads RICE at 23,398 against 4,861 next, on a reach term (50,138 users) that is measured.

## Where users drop off

| Stage | Users | % of viewers | Step conversion |
|---|---:|---:|---:|
| Viewed an item | 61,252 | 100.0% | — |
| Added to cart | 11,114 | 18.1% | 18.1% |
| Began checkout | 4,167 | 6.8% | 37.5% |
| Purchased | 2,356 | 3.8% | 56.5% |

The steepest step is **Viewed an item → Added to cart** at 81.9% lost, and it is where the most users are — which is why it dominates everything below.

**22% of conversions need a return visit.** The same funnel scoped to the session converts at 3.00% against 3.85% user-level, so a single-session optimisation would attack the wrong surface for that share of it.

## Who drops off

| Segment | Viewed | Purchased | Conversion |
|---|---:|---:|---:|
| desktop | 35,711 | 1,348 | 3.77% |
| mobile | 24,151 | 954 | 3.95% |
| tablet | 1,390 | 54 | 3.88% |
| new | 55,767 | 2,005 | 3.60% |
| returning | 5,485 | 351 | 6.40% |

**desktop** vs **mobile** (3.77% vs 3.95%) is not distinguishable from noise at this sample size — p = 0.27. Do not act on it. **new** converts 2.80pp lower than **returning** (3.60% vs 6.40%, 95% CI [-3.47, -2.14]pp). (1 further comparison is in the dashboard.)

2 of 3 comparisons survive Holm-Bonferroni correction, and it flips none of them — the survivors sit far below the adjusted thresholds. Worth stating rather than using as a reason to skip the correction.

Channels separate two problems a ranked table blurs. **<Other> / <Other>** sends 9,722 users at 3.57% — high volume, low conversion, an expectation-mismatch problem, not a checkout one. **(data deleted) / (data deleted)** converts at 5.70% on 2,265 — a scale opportunity. (Names are obfuscated by Google, not broken.)

## What it's worth

Sizing model: `users entering × improvement_pp × P(purchase | next stage) × AOV`, AOV **$63.63**. The lift applies to users *entering* — the denominator of the rate it changes. The common `users lost × pp` form is only `(1 − rate)` of this.

| Step | Users lost | Recovered at +5pp | P(purchase \| next stage) | Recoverable | 95% CI |
|---|---:|---:|---:|---:|---:|
| Viewed an item → Added to cart | 50,138 | 3,063 | 21.2% | $41,308 | $39,829 – $42,828 |
| Added to cart → Began checkout | 6,947 | 556 | 56.5% | $19,991 | $19,354 – $20,651 |
| Began checkout → Purchased | 1,811 | 208 | 100.0% | $13,257 | $12,865 – $13,645 |

**Upper bounds, not forecasts.** The model applies stage completers' purchase rate to non-completers; recovered users almost certainly convert worse. The intervals price sampling variation only — not that assumption, which dominates the error.

**Sizing prices the stages; it cannot re-rank them.** Every purchaser passed every stage, so recoverable revenue is a monotone function of step conversion: ranking by dollars and by worst drop-off are the same ordering (verified: `True`). Effort re-ranks the work — the RICE table's job. The ranking holds across the improvement assumption:

| Stage | +1pp | +2pp | +5pp | +10pp |
|---|---:|---:|---:|---:|
| Added to cart | $8,262 | $16,523 | $41,308 | $82,616 |
| Began checkout | $3,998 | $7,996 | $19,991 | $39,982 |
| Purchased | $2,651 | $5,303 | $13,257 | $26,513 |

## What I'd do first

| # | Recommendation | Reach | Impact | Conf. | Effort (wk) | RICE |
|---|---|---:|---:|---:|---:|---:|
| 1 | Rework the product page add-to-cart path | 50,138 | 2.0 | 0.7 | 3.0 | 23,398 |
| 2 | Rebalance paid spend away from the worst-converting channel: <Other> / <Other> | 9,722 | 1.0 | 0.75 | 1.5 | 4,861 |
| 3 | Reduce cart-to-checkout friction (persistent cart, single-tap checkout entry) | 6,947 | 2.0 | 0.6 | 4.0 | 2,084 |
| 4 | Shorten the checkout form and surface total cost earlier | 1,811 | 1.0 | 0.55 | 5.0 | 199 |

**Why #1 ranks first:** Largest absolute loss sits between viewing an item and adding one, and it is the widest step in the funnel by a wide margin. The visitor type split narrows where to start: new converts 2.80pp below returning, which survives correction. *Assumption to challenge:* Assumes the loss is friction on the product page rather than browsing intent — many of these users never intended to buy today. Untested; an A/B test on the product page settles it.

Reach is measured; impact, effort and confidence are stated judgement — change one and watch the ranking move.

## How I'd test it

| Step tested | Baseline | Smallest lift testable in 4 weeks | Users per arm | Runs for | Guardrails (must not fall) |
|---|---:|---:|---:|---:|---|
| Viewed an item → added to cart rate | 18.1% | +2 pts | 6,072 | 21 days | Added to cart → began checkout rate; Average order value |
| Added to cart → began checkout rate | 37.5% | +5 pts | 1,506 | 28 days | Began checkout → purchased rate; Average order value |
| Began checkout → purchased rate | 56.5% | +8 pts | 585 | 28 days | Average order value |

**Only the add-to-cart fix is testable at this traffic**: a 2-point lift in 3 weeks. Later steps see too few shoppers, so checkout changes ship on judgement.

## What I'd need to know next

This data records **what** users did, not **why**.

1. **Why new converts worse than returning.** Whether it is friction or a difference in intent is not answerable from event counts. Session recordings on that cohort would settle it.
2. **A cart-abandonment exit survey.** Cart loss looks like friction; price shock has the same signature and a different fix.
3. **The test above.** Until it runs, every figure here is a hypothesis with a size attached.

## Limitations

Ranked by threat to the conclusions, not by ease of admission:

1. **No cross-device identity.** `user_pseudo_id` is per browser, so a phone-browse / laptop-buy user is two users, one of whom never converts. That distorts every segment comparison by an unknown amount — the one limitation that could change what I do first.
2. **Recommendations are hypotheses.** No A/B test has been run; the ranking is reproducible from stated inputs, not a result.
3. **92 days, 54% of the retention grid right-censored** and excluded rather than zeroed — late cohorts are truncated, not worse.
4. **1,422 users (13% of the cart stage) are excluded by the strict ordering rule** — GA4 stamps every event in one request with the same microsecond, so carting from a listing ties with the view. Under `>=` the stage reads 12,536. Strict is the conservative reading.
5. **Public demo data,** obfuscated at source — not a problem I uncovered, and channel and item names are redacted, so no merchandising insight. Funnel and retention mechanics are unaffected.

---

*Numbers regenerate from `data/processed/metrics.json`. Two independent funnel implementations
(first-occurrence timestamps vs. event-sequence regex) agree to within 0.00%; the pipeline refuses to produce this memo if they do not.*
