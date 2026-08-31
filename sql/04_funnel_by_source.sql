-- 04_funnel_by_source.sql
-- Question: Which acquisition channels bring users who convert, versus users who merely arrive?
-- Method:   Same funnel as 02, cut by first-touch traffic_source.source / medium.
--           Channels below @min_users are folded into '(long tail)' so the segment table
--           does not fragment into statistically meaningless rows.
-- Output:   data/processed/04_funnel_by_source.csv
-- Est. scan: ~0.7 GB
--
-- The insight this query exists to support: high traffic + low conversion is a
-- landing-page / expectation-mismatch problem. Low traffic + high conversion is an
-- acquisition-scale opportunity. They demand opposite responses, so they must be
-- distinguishable in the output.

WITH user_journey AS (
  SELECT
    user_pseudo_id,
    ARRAY_AGG(
      CONCAT(IFNULL(traffic_source.source, '(none)'), ' / ', IFNULL(traffic_source.medium, '(none)'))
      IGNORE NULLS ORDER BY event_timestamp LIMIT 1
    )[SAFE_OFFSET(0)]                                             AS source_medium,
    MIN(IF(event_name = 'view_item',      event_timestamp, NULL)) AS view_ts,
    MIN(IF(event_name = 'add_to_cart',    event_timestamp, NULL)) AS cart_ts,
    MIN(IF(event_name = 'begin_checkout', event_timestamp, NULL)) AS checkout_ts,
    MIN(IF(event_name = 'purchase',       event_timestamp, NULL)) AS purchase_ts
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
  GROUP BY user_pseudo_id
),
sized AS (
  -- Columns are named explicitly rather than SELECT *: BigQuery bills per column
  -- scanned, and an unqualified star here would also silently absorb any column added
  -- to user_journey later.
  SELECT
    source_medium,
    view_ts,
    cart_ts,
    checkout_ts,
    purchase_ts,
    COUNT(*) OVER (PARTITION BY source_medium) AS channel_users
  FROM user_journey
  WHERE view_ts IS NOT NULL
)
SELECT
  'source_medium' AS segment_type,
  IF(channel_users >= @min_users, source_medium, '(long tail)') AS segment_value,
  COUNT(*)                            AS viewed,
  COUNTIF(cart_ts > view_ts)          AS added_to_cart,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts)      AS began_checkout,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts
      AND purchase_ts > checkout_ts)  AS purchased
FROM sized
GROUP BY segment_value
ORDER BY viewed DESC
