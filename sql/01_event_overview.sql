-- 01_event_overview.sql
-- Question: What events exist, how many of each, over what date range, from how many users?
-- Purpose:  Establishes the denominator for everything downstream and confirms the
--           window actually contains the four funnel events before any funnel is built.
-- Output:   data/processed/01_event_overview.csv
-- Est. scan: ~0.4 GB  (2 columns across 92 daily tables)

SELECT
  event_name,
  COUNT(*)                                              AS events,
  COUNT(DISTINCT user_pseudo_id)                        AS users,
  MIN(DATE(TIMESTAMP_MICROS(event_timestamp)))          AS first_date,
  MAX(DATE(TIMESTAMP_MICROS(event_timestamp)))          AS last_date
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
GROUP BY event_name
ORDER BY events DESC
