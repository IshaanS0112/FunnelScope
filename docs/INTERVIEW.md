# FunnelScope — Interview Defence Sheet

Everything you need to present and defend this project for business-analyst, data-analyst
and product-analyst interviews. Read sections 1–4 the night before; use 5–8 as a question bank.

---

## 1. The pitch

**30 seconds**

> I analysed 4.3 million raw Google Analytics 4 events in BigQuery to find where an
> ecommerce store loses buyers. Four in five shoppers who view a product never add it to
> cart — 85% of all lost shoppers leave at that one step. I tested every segment gap for
> significance: returning shoppers convert at 1.8× new ones, but the mobile-versus-desktop gap
> everyone expects turned out to be noise. I sized each fix, ranked them with RICE, and
> designed the A/B test — which showed the top fix is also the only one this store's traffic
> can actually validate.

**2 minutes** — add, in this order:

1. **Data.** Google's public GA4 export: nested, event-level, one row per user action. Real
   SQL with `UNNEST`, not a cleaned CSV.
2. **Correctness.** I computed the funnel twice by unrelated methods. On the real data they
   disagreed by 17%, which uncovered two GA4 behaviours — repeat events and batched
   timestamps. After fixing, they agree exactly, and the pipeline refuses to publish otherwise.
3. **Statistics.** Two-proportion z-tests with Holm correction across all comparisons.
4. **Value.** Fixing add-to-cart by 5 points is worth up to $41k — an upper bound.
5. **Decision.** Rework the product page; run a 3-week, 50/50 test with guardrails.
6. **Delivery.** A decision memo, a live report website and a dashboard, all from one
   metrics file so they can never disagree.

---

## 2. Numbers to memorise

| Metric | Value |
|---|---|
| Events analysed | **4,295,584** (1 Nov 2020 – 31 Jan 2021, 92 days) |
| Funnel | **61,252** viewed → **11,114** carted → **4,167** checkout → **2,356** bought |
| End-to-end conversion | **3.85%** |
| View → cart drop | **81.9%** lost — **85%** of all lost shoppers |
| Later steps | cart → checkout keeps **37%**, checkout → purchase keeps **57%** |
| New vs returning | **3.60% vs 6.40%** → returning convert **1.8×**, adjusted p = 2e-24 |
| Desktop vs mobile | **3.77% vs 3.95%**, p = **0.27** → noise |
| Week-1 retention | **4.3%**; **22%** of purchases need a return visit |
| Biggest opportunity | up to **$41k** (5-point lift at add-to-cart, upper bound) |
| RICE | top option **23,398** vs next **4,861** → **4.8×** |
| A/B test | **+2 points** detectable, **6,072** per arm, **21 days** |
| Timestamp ties excluded | **1,422** users (12.8% of the cart stage) |
| BigQuery cost | **2.7 GB** per full refresh — 0.26% of the free tier |
| Tests | **175** |

---

## 3. Resume bullets

- Analysed 4.3M raw GA4 events in BigQuery SQL to build an ordered purchase funnel, finding
  that 81.9% of product viewers never add to cart — 85% of all lost shoppers.
- Validated the funnel with two independent SQL implementations; resolved a 17% discrepancy
  caused by repeated events and batched GA4 timestamps, reaching exact agreement.
- Tested segment differences with Holm-corrected z-tests, showing a 1.8× returning-customer
  gap was real while the expected device gap was noise (p = 0.27).
- Sized opportunities (up to $41k), prioritised fixes with RICE, and designed a 3-week A/B
  test with guardrail metrics from measured traffic.

---

## 4. Demo script (5 minutes)

1. **Open the live report.** Read the headline and the four snapshot numbers.
2. **01 Funnel.** Point at the one blue bar — the step where the loss happens.
3. **02 Segments.** The forest plot: device crosses zero, new-vs-returning does not.
   *"This is why I don't recommend a mobile project."*
4. **07 Test plan.** Drag the slider. *"A 1-point lift would take 10 weeks; 2 points takes 3."*
   Switch to Checkout. *"Too little traffic to test — that is a prioritisation input."*
5. **08 Method.** Open "The two real-data behaviours the check caught".
6. **Open the SQL** — `sql/02_funnel_ordered.sql`, show the cumulative conditions.
7. **Close on the memo** — the recommendation and the limitations.

---

## 5. Question bank — the funnel

**Walk me through the funnel. Where's the biggest drop?**
View → cart: 81.9% lost. It is both the worst rate and where the most people are, so it holds
85% of all lost shoppers. Later steps keep 37% and 57%.

**Ordered or unordered funnel — why?**
Ordered. An unordered funnel asks "did they ever do all four?", which counts someone who
bought on Monday and browsed on Friday as a full journey and inflates conversion.

**Why does each stage repeat the earlier conditions?**
If "checkout after cart" is checked alone, it counts people whose cart never followed a view.
Stages stop being subsets and checkout can exceed cart — silently. A monotonicity check fails
the pipeline if that ever happens.

**How do you know the funnel is right?**
I compute it twice: once comparing timestamps, once with a regex over each shopper's event
sequence. Different logic, same answer. If they differ by more than 0.5%, nothing publishes.

**Did that check ever catch anything?** *(Steer the interview here.)*
Yes — 17% on the first real export. Two causes:
- **Repeat events.** Shoppers view 6.3 items each, so "first cart after first view" and "ever
  carted after ever viewing" are different questions. One pattern alone added 938 users.
- **Batched timestamps.** GA4 gives events sent together the same microsecond, so carting from
  a listing ties with the view. 1,422 shoppers tie.

Fixed both; the methods now agree exactly. My synthetic test data had missed both, so I
rebuilt it to include them.

**What did the strict ordering rule cost you?**
1,422 shoppers — 12.8% of the cart stage. With "at or after" the stage would read 12,536, not
11,114. I kept the strict rule because equal timestamps don't prove order, and I report the
cost instead of hiding it.

**User-level or session-level?**
Both. User-level asks "does this person ever buy?" — right for product fixes. Session-level
asks "does this visit convert?" — right for landing pages. 22% of purchases need a return
visit, so single-visit fixes miss a fifth of the funnel.

**How do you read a value out of `event_params`?**
A correlated subquery over `UNNEST(event_params)`, filtered by key, picking the typed field
(`int_value`, `string_value`). There is no dot-path.

---

## 6. Question bank — statistics

**How did you know the segment gap was real?**
Two-proportion z-test with a 95% interval on the difference, then Holm–Bonferroni across all
comparisons. New vs returning survives with adjusted p = 2e-24.

**What about mobile vs desktop?**
Not real — 3.77% vs 3.95%, p = 0.27, interval crosses zero, on 60,000 users. That is the
point of testing: it stopped a mobile project nobody needed.

**Why correct for multiple comparisons?**
Three tests at 5% each give roughly a 14% chance of at least one false positive. Holm keeps
the family at 5%. Here it changed no conclusion — I say so rather than skipping it.

**Why Holm instead of Bonferroni?**
Same guarantee, more power. Sort p-values, compare the k-th to α/(m−k), stop at the first
failure.

**Why write the z-test yourself?**
Keeps the runtime light (Python's standard library). The tests check it against SciPy and
Holm against statsmodels.

---

## 7. Question bank — value, prioritisation, testing

**How did you size the opportunity?**
Users entering the step × lift × chance they go on to buy × average order value, capped at
the users actually lost. Labelled as an upper bound: it assumes rescued shoppers buy like
those who completed unaided, and they probably won't.

**Why "users entering" and not "users lost"?**
A lift changes the conversion rate, and the rate's denominator is users entering. The
"lost" version is only (1 − rate) of the right figure — 30% short at a 30% step.

**Did sizing change your ranking?** *(Best question you'll get.)*
No, and it can't. Every buyer passed every step, so recoverable revenue is a function of step
conversion alone — ranking by dollars equals ranking by drop-off. Sizing prices the steps;
**effort** re-ranks them, which is RICE's job. A test checks this over random funnels.

**Why RICE?**
It makes the ranking reproducible. Reach is measured; impact, confidence and effort are
judgement, written down so anyone can change one and see the ranking move.

**How would you run the A/B test?**
50/50 on the product page. Primary metric: add-to-cart rate (18.1%). At 666 viewers a day, a
2-point lift needs 6,072 per arm — 3 weeks. Guardrails: cart → checkout rate and average order
value must not fall. Minimum two weeks so weekday patterns don't fake a result.

**Why those guardrails?**
A better product page pushes less-committed shoppers into the cart; they may abandon later.
And more orders at smaller baskets isn't a win.

**Could you test the checkout fixes?**
Not usefully — 121 and 45 shoppers a day. The smallest lift detectable in a month would be 5
and 8 points. So testability supports doing the product page first.

---

## 8. Question bank — retention and engineering

**Why do later cohorts look worse?** *(Trap.)*
They don't. A January cohort can't show week-8 retention — week 8 is outside the data. Those
cells are censored, excluded and drawn hatched, not plotted as zero.

**How did you check censoring actually works?**
It didn't at first. The query only returns weeks where someone came back, so zero weeks and
unobservable weeks looked identical and censoring read 0%. I fill in the full grid first. A
test pins it.

**How did you control BigQuery cost?**
Filter `_TABLE_SUFFIX` on every query, never `SELECT *`, dry-run first. `LIMIT` and `WHERE`
don't cut bytes scanned. A full run is 2.7 GB.

**Why export CSVs instead of querying live?**
Sandbox tables expire in 60 days and anyone can open the report without Google credentials.

**How do you stop test data being shown as real?**
Every export writes a provenance stamp. The memo, website and dashboard read it and show a red
"NOT AN ANALYSIS" banner for synthetic data. A test checks both directions.

---

## 9. Traps and how to handle them

| They say | You say |
|---|---|
| "Later cohorts retain worse." | Censored, not worse — those weeks haven't happened in the data. |
| "Mobile clearly underperforms." | 0.18 points, p = 0.27 — noise. That's why I tested it. |
| "So this fix makes $41k." | Up to $41k — an upper bound for comparing steps, not a forecast. |
| "Sizing shows checkout matters more." | It can't re-rank steps; dollars follow drop-off. Effort decides. |
| "Big sample, so everything's significant." | Device wasn't, on 60,000 users. Large n finds real small effects; it doesn't invent them. |

---

## 10. Weaknesses — say them before they do

| Weakness | Answer |
|---|---|
| Public demo data | "Yes — it shows SQL on real event structure and the reasoning. The README says so." |
| No A/B test run | "Right. Recommendations are hypotheses; I designed the test that would settle it." |
| One browser = one user | "The biggest threat. A phone-browse, laptop-buy shopper counts as two people, which distorts every segment gap. It's first in my limitations." |
| 3-month window | "Fine for funnels, short for retention — late cohorts are censored, not misread." |
| Obfuscated names | "Limits merchandising insight; funnel mechanics are unaffected." |

---

## 11. What I'd do next

1. Session recordings on new shoppers' product pages — friction or intent?
2. A cart-abandonment exit survey — friction looks the same as price shock in event data.
3. Run the 3-week test.
4. Join a customer ID to fix cross-device identity.

---

## 12. Night-before checklist

- [ ] Say the 30-second pitch out loud twice
- [ ] Know the 14 numbers in section 2
- [ ] Open the live report and drag the test-plan slider once
- [ ] Re-read "Did that check ever catch anything?" and "Did sizing change your ranking?"
- [ ] Have `sql/02_funnel_ordered.sql` ready to share
