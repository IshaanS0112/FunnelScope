-- 05_funnel_new_vs_returning.sql
-- Question: Do first-time visitors convert differently from users already familiar with the site?
-- Method:   A user is 'new' if a first_visit event falls inside the window; otherwise 'returning'.
-- Output:   data/processed/05_funnel_by_visitor_type.csv
-- Est. scan: ~0.5 GB
--
-- LIMITATION to state, not bury: 'returning' here means "no first_visit inside this
-- 3-month window". Users whose genuine first visit predates 2020-11-01 are correctly
-- returning; users whose first_visit event simply failed to fire are misclassified as
-- returning. This inflates the returning cohort slightly. Direction of the bias is known,
-- magnitude is not.

WITH user_journey AS (
  SELECT
    user_pseudo_id,
    IF(COUNTIF(event_name = 'first_visit') > 0, 'new', 'returning')  AS visitor_type,
    MIN(IF(event_name = 'view_item',      event_timestamp, NULL)) AS view_ts,
    MIN(IF(event_name = 'add_to_cart',    event_timestamp, NULL)) AS cart_ts,
    MIN(IF(event_name = 'begin_checkout', event_timestamp, NULL)) AS checkout_ts,
    MIN(IF(event_name = 'purchase',       event_timestamp, NULL)) AS purchase_ts
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    AND event_name IN ('first_visit', 'view_item', 'add_to_cart', 'begin_checkout', 'purchase')
  GROUP BY user_pseudo_id
)
SELECT
  'visitor_type'                      AS segment_type,
  visitor_type                        AS segment_value,
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
