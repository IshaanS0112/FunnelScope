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
-- WHY first_events, AND WHY THE TIE-BREAK IS stage_rank DESC:
--   Aggregating EVERY event into the sequence asks "did this user EVER cart after EVER
--   viewing", while 02 asks "did the FIRST cart follow the FIRST view". Those differ
--   whenever a user repeats a step, and in this dataset they repeat constantly
--   (6.3 view_item per user, 4.67 add_to_cart per carting user). Measured on the real
--   export, the all-events form ran 9.6% / 16.2% / 17.3% above 02.
--
--   GA4 also stamps every event in one network request with the same event_timestamp,
--   so carting straight from a listing ties with the view: 1,422 users, 11.3% of
--   carters. 02's strict `>` drops them; STRING_AGG ordered only by time keeps about
--   half, which left a further 6.7% gap. Ordering by (first_ts, stage_rank DESC) emits
--   the later stage first on a tie, so the regex fails — exactly what `>` does.
--
--   Both fixes together bring the two methods to zero difference. The check is slightly
--   weaker for it (both read MIN(event_timestamp)) but it is correct, and a predicate
--   that is not cumulative still cannot survive a sequence regex. A gate comparing two
--   different definitions is not a stronger gate.
--
--   sql/10_timestamp_ties.sql measures how many users the strict rule excludes.

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
