-- 08_event_params_reference.sql
-- Question: How do you pull a scalar out of GA4's nested event_params, and what is actually
--           in there for the funnel events?
-- Purpose:  Reference / interview-demo query. Not consumed by the dashboard.
-- Output:   data/processed/08_event_params_sample.csv
-- Est. scan: ~1.2 GB  (event_params is the widest column in the schema -- keep the
--            date range narrow when running this one; the LIMIT does NOT reduce bytes scanned)
--
-- THE PATTERN: a correlated subquery over UNNEST(event_params) selecting the typed
-- value for one key. GA4 stores parameters as an ARRAY<STRUCT<key STRING,
-- value STRUCT<string_value STRING, int_value INT64, double_value FLOAT64, ...>>>,
-- so there is no direct dot-path to a parameter -- you must unnest and filter by key,
-- and you must know which typed field the value lives in.

SELECT
  user_pseudo_id,
  event_name,
  TIMESTAMP_MICROS(event_timestamp) AS event_time,
  (SELECT value.int_value    FROM UNNEST(event_params) WHERE key = 'ga_session_id')     AS ga_session_id,
  (SELECT value.int_value    FROM UNNEST(event_params) WHERE key = 'ga_session_number') AS session_number,
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')     AS page_location,
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_title')        AS page_title,
  (SELECT value.int_value    FROM UNNEST(event_params) WHERE key = 'engagement_time_msec')
                                                                                        AS engagement_time_msec,
  device.category                   AS device_category,
  traffic_source.source             AS source,
  traffic_source.medium             AS medium
FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE _TABLE_SUFFIX BETWEEN @sample_start_suffix AND @sample_end_suffix
  AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
LIMIT 500
