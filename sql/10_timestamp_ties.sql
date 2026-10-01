-- 10_timestamp_ties.sql
-- Question: How many users does the funnel's STRICT ordering exclude because two of
--           their funnel events carry the identical microsecond timestamp?
-- Method:   Per-user first-occurrence timestamps, counting exact equality at each step
--           alongside the strict and non-strict versions of the same predicate.
-- Output:   data/processed/10_timestamp_ties.csv
-- Est. scan: ~0.2 GB
--
-- WHY THIS QUERY EXISTS:
--   GA4 stamps every event in one network request with the same event_timestamp, so
--   carting straight from a product listing ties with the view. 02 requires each step to
--   be strictly later than the last, so those users never enter the funnel.
--
--   That is the conservative reading — an equal timestamp is not evidence of an ordering
--   — but it is a choice, and on this dataset not a small one. Reporting the magnitude
--   turns an undisclosed assumption into a stated one.
--
--   counted_at_or_after is what the funnel would read under `>=`. It is NOT the headline
--   number; mixing the two inside one funnel would be the error.

WITH per_user AS (
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
  'viewed -> added_to_cart'              AS step,
  COUNTIF(cart_ts > view_ts)             AS counted_strict,
  COUNTIF(cart_ts = view_ts)             AS excluded_by_tie,
  COUNTIF(cart_ts >= view_ts)            AS counted_at_or_after
FROM per_user
WHERE view_ts IS NOT NULL

UNION ALL

SELECT
  'added_to_cart -> began_checkout',
  COUNTIF(cart_ts > view_ts AND checkout_ts > cart_ts),
  COUNTIF(cart_ts > view_ts AND checkout_ts = cart_ts),
  COUNTIF(cart_ts > view_ts AND checkout_ts >= cart_ts)
FROM per_user
WHERE view_ts IS NOT NULL

UNION ALL

SELECT
  'began_checkout -> purchased',
  COUNTIF(cart_ts > view_ts AND checkout_ts > cart_ts AND purchase_ts > checkout_ts),
  COUNTIF(cart_ts > view_ts AND checkout_ts > cart_ts AND purchase_ts = checkout_ts),
  COUNTIF(cart_ts > view_ts AND checkout_ts > cart_ts AND purchase_ts >= checkout_ts)
FROM per_user
WHERE view_ts IS NOT NULL
