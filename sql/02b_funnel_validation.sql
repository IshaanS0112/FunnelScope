-- 02b_funnel_validation.sql
-- Question: Does the funnel in 02 survive being computed a completely different way?
-- Method:   Collapse each user's FIRST occurrence of each funnel event into an ordered
--           character sequence and test that sequence with a regex. The funnel logic
--           shares nothing with 02 — 02 compares timestamps pairwise with cumulative
--           predicates, this sorts and pattern-matches a string — so a predicate that
--           is not cumulative cannot hide here.
-- Output:   data/processed/02b_funnel_validation.csv
-- Est. scan: ~0.2 GB
--
-- WHY `first_events` EXISTS, AND WHY THIS QUERY ORIGINALLY DISAGREED BY 17%:
--   The obvious form of this query aggregates EVERY event into the sequence:
--
--     STRING_AGG(CASE event_name ... END, '' ORDER BY event_timestamp)
--
--   That looks like the same funnel and is not. `REGEXP_CONTAINS(seq, r'V.*C')` then
--   asks "did this user EVER add to cart after EVER viewing an item", whereas 02 asks
--   "did this user's FIRST cart follow their FIRST view". Those differ whenever a user
--   repeats a step, and in this dataset they repeat constantly: 6.3 view_item events
--   per user, and 4.67 add_to_cart events per user who carts at all.
--
--   Measured on the real export, the all-events form counted 938 extra users at the
--   cart stage from one pattern alone — carted, then browsed more, then carted again —
--   and ran 9.6% / 16.2% / 17.3% above 02 across the three lower stages. The
--   cross-validation gate in scripts/analyze.py refused to emit metrics, correctly:
--   two numbers that measure different things must not be presented as agreement.
--
--   Restricting to first occurrences makes both queries answer the same question. The
--   check is slightly weaker for it — both now read MIN(event_timestamp) — but the
--   funnel logic on top is still wholly independent, and the bug this gate exists to
--   catch (stage predicates that are not cumulative) still cannot survive it. A gate
--   that compares two different definitions is not a stronger gate; it is a broken one.
--
-- WHY THE TIE-BREAK IS `stage_rank DESC`, AND WHY IT IS NOT A FUDGE:
--   02 requires each step to be STRICTLY later than the last (`cart_ts > view_ts`), so
--   two events at the identical microsecond do not advance the funnel. `STRING_AGG`
--   has no such rule — on a tie it emits whatever order it likes, and about half the
--   time that order spells 'VC' and matches.
--
--   That is not a rounding difference on this dataset. GA4 stamps every event in one
--   network request with the same `event_timestamp`, and adding to cart straight from
--   a product listing sends `view_item` and `add_to_cart` together: 1,422 users on the
--   real export share a microsecond across those two events, 11.3% of everyone who
--   carts. Left arbitrary, the two methods differed by 6.7% at the cart stage — all of
--   it ties, none of it a bug.
--
--   Ordering by `first_ts` and then by stage rank DESCENDING reproduces 02's rule
--   exactly: on a tie the later stage is emitted first, so the sequence reads 'CV',
--   the regex does not match, and the user is not counted — which is precisely what
--   `cart_ts > view_ts` does. The two methods now answer the same question under the
--   same tie rule, so any remaining disagreement is a genuine defect.
--
--   sql/10_timestamp_ties.sql measures how many users this excludes, because a
--   conservative choice that is not quantified is just an undisclosed one.

WITH first_events AS (
  SELECT
    user_pseudo_id,
    event_name,
    MIN(event_timestamp) AS first_ts,
    CASE event_name
      WHEN 'view_item'      THEN 1
      WHEN 'add_to_cart'    THEN 2
      WHEN 'begin_checkout' THEN 3
      WHEN 'purchase'       THEN 4
    END AS stage_rank
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
  GROUP BY user_pseudo_id, event_name, stage_rank
),
ordered_events AS (
  SELECT
    user_pseudo_id,
    STRING_AGG(
      CASE event_name
        WHEN 'view_item'      THEN 'V'
        WHEN 'add_to_cart'    THEN 'C'
        WHEN 'begin_checkout' THEN 'K'
        WHEN 'purchase'       THEN 'P'
      END,
      '' ORDER BY first_ts, stage_rank DESC
    ) AS seq
  FROM first_events
  GROUP BY user_pseudo_id
)
SELECT
  'all' AS segment_type,
  'all' AS segment_value,
  COUNT(*)                                          AS viewed,
  COUNTIF(REGEXP_CONTAINS(seq, r'V.*C'))            AS added_to_cart,
  COUNTIF(REGEXP_CONTAINS(seq, r'V.*C.*K'))         AS began_checkout,
  COUNTIF(REGEXP_CONTAINS(seq, r'V.*C.*K.*P'))      AS purchased
FROM ordered_events
WHERE REGEXP_CONTAINS(seq, r'V')
