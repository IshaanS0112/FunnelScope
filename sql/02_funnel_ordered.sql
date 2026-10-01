-- 02_funnel_ordered.sql
-- Question: Of users who viewed an item, how many progressed through cart -> checkout -> purchase,
--           with each step required to happen AFTER the previous one?
-- Method:   Per-user first-occurrence timestamps, then cumulative ordering predicates.
-- Output:   data/processed/02_funnel_overall.csv
-- Est. scan: ~0.5 GB
--
-- WHY CUMULATIVE PREDICATES:
--   The naive form writes each stage independently, e.g. COUNTIF(checkout_ts > cart_ts).
--   That counts a user who began checkout after adding to cart even if their cart never
--   followed their view. Stages stop being nested subsets and the funnel can go
--   non-monotonic. Each stage below re-asserts every prior condition.
--   Cross-checked by 02b_funnel_validation.sql via a completely different technique.

WITH user_journey AS (
  SELECT
    user_pseudo_id,
    MIN(IF(event_name = 'view_item',      event_timestamp, NULL)) AS view_ts,
    MIN(IF(event_name = 'add_to_cart',    event_timestamp, NULL)) AS cart_ts,
    MIN(IF(event_name = 'begin_checkout', event_timestamp, NULL)) AS checkout_ts,
    MIN(IF(event_name = 'purchase',       event_timestamp, NULL)) AS purchase_ts
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
  GROUP BY user_pseudo_id
)
SELECT
  'all' AS segment_type,
  'all' AS segment_value,
  COUNT(*)                                     AS viewed,
  COUNTIF(cart_ts > view_ts)                   AS added_to_cart,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts)               AS began_checkout,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts
      AND purchase_ts > checkout_ts)           AS purchased
FROM user_journey
WHERE view_ts IS NOT NULL
