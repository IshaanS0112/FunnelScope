-- 02b_funnel_validation.sql
-- Question: Does the funnel in 02 survive being computed a completely different way?
-- Method:   Collapse each user's events into an ordered character sequence and test the
--           sequence with regex. Shares no logic with 02 beyond the source table, so an
--           error in the timestamp-comparison approach cannot hide here.
-- Output:   data/processed/02b_funnel_validation.csv
-- Est. scan: ~0.5 GB
--
-- Expected residual difference: users with two funnel events at the identical
-- microsecond. 02 uses strict `>` and drops them; the sequence here keeps whichever
-- order STRING_AGG emits. Anything beyond a fraction of a percent is a real bug,
-- not a tie. scripts/analyze.py enforces this as a hard gate.

WITH ordered_events AS (
  SELECT
    user_pseudo_id,
    STRING_AGG(
      CASE event_name
        WHEN 'view_item'      THEN 'V'
        WHEN 'add_to_cart'    THEN 'C'
        WHEN 'begin_checkout' THEN 'K'
        WHEN 'purchase'       THEN 'P'
      END,
      '' ORDER BY event_timestamp
    ) AS seq
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
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
