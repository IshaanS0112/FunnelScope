-- 07_revenue_by_segment.sql
-- Question: What is purchase volume, revenue and AOV per device and per acquisition channel?
-- Method:   Purchase events only, attributed to the device / source on the purchase event
--           itself (revenue belongs to the transaction, not to first touch).
-- Output:   data/processed/07_revenue_by_segment.csv
-- Est. scan: ~0.3 GB (purchase rows are a small slice, but BigQuery still scans the
--            selected columns across all 92 daily tables — the filter reduces rows, not bytes)
--
-- NOTE on the attribution split vs. 03/04: those queries assign a user to their FIRST
-- device/channel because a funnel follows one journey. This one attributes revenue to the
-- purchase event because that is where the money actually happened. Mixing the two
-- conventions inside one number would be the error; using each where it belongs is not.
-- AOV computed here is therefore transaction-weighted, and that is what the sizing model
-- in funnelscope/sizing.py consumes.

SELECT
  IFNULL(device.category, 'unknown') AS device_category,
  CONCAT(IFNULL(traffic_source.source, '(none)'), ' / ',
         IFNULL(traffic_source.medium, '(none)')) AS source_medium,
  COUNT(*)                                                     AS purchases,
  COUNT(DISTINCT user_pseudo_id)                               AS purchasing_users,
  ROUND(SUM(IFNULL(ecommerce.purchase_revenue_in_usd, 0)), 2)  AS revenue_usd
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
  AND event_name = 'purchase'
GROUP BY device_category, source_medium
ORDER BY revenue_usd DESC
