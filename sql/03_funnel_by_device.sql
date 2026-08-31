-- 03_funnel_by_device.sql
-- Question: Does the ordered funnel differ by device category, and where does the gap open?
-- Method:   Same cumulative-ordering funnel as 02, cut by the device recorded on the user's
--           FIRST event in the window.
-- Output:   data/processed/03_funnel_by_device.csv
-- Est. scan: ~0.6 GB
--
-- ASSUMPTION worth defending: device is assigned per user, not per event. A user who
-- browses on mobile and buys on desktop is counted as mobile. GA4's user_pseudo_id is
-- per-device-per-browser anyway, so cross-device journeys are already invisible in this
-- dataset — assigning first-touch device makes that limitation explicit rather than
-- silently splitting one person's funnel across two segments.

WITH user_journey AS (
  SELECT
    user_pseudo_id,
    ARRAY_AGG(device.category IGNORE NULLS ORDER BY event_timestamp LIMIT 1)[SAFE_OFFSET(0)]
                                                                  AS device_category,
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
  'device'                            AS segment_type,
  IFNULL(device_category, 'unknown')  AS segment_value,
  COUNT(*)                            AS viewed,
  COUNTIF(cart_ts > view_ts)          AS added_to_cart,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts)      AS began_checkout,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts
      AND purchase_ts > checkout_ts)  AS purchased
FROM user_journey
WHERE view_ts IS NOT NULL
GROUP BY segment_value
ORDER BY viewed DESC
