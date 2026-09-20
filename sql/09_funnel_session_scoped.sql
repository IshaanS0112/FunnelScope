-- 09_funnel_session_scoped.sql
-- Question: How much of the measured conversion depends on users coming back in a LATER
--           session, rather than completing the journey in one sitting?
-- Method:   The same cumulative-ordering funnel as 02, but partitioned on
--           (user_pseudo_id, ga_session_id) instead of user_pseudo_id. A session is the
--           unit; a user with four sessions contributes four rows.
-- Output:   data/processed/09_funnel_session_scoped.csv
-- Est. scan: ~0.9 GB  (adds event_params for ga_session_id, which is not a cheap column)
--
-- WHY BOTH FUNNELS EXIST, and why neither is "the correct one":
--   02 answers "does this user EVER get there", which is the right frame for deciding
--   what to fix in the product -- a user who returns three days later and buys was not
--   lost, and counting them as lost would send you chasing a drop-off that isn't one.
--   This query answers "does this VISIT complete", which is the right frame for judging
--   a landing experience or a single campaign, where a user who leaves and comes back
--   a week later is, for that campaign's purposes, a failure.
--
--   THE COMPARISON IS THE FINDING. Session-scoped conversion is necessarily <= the
--   user-scoped figure (a user converts if ANY of their sessions does, so collapsing
--   sessions to users can only add conversions). The size of the gap is a direct
--   measure of how much of this funnel runs on return visits. A small gap means the
--   journey completes in one sitting and session-level fixes are the whole game; a
--   large gap means retention and re-engagement are doing much of the selling, and a
--   single-session optimisation would be attacking the wrong surface.
--
--   funnelscope.funnel.session_gap computes that comparison; scripts/analyze.py records
--   it in metrics.json and the memo quotes it.

WITH session_journey AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    MIN(IF(event_name = 'view_item',      event_timestamp, NULL)) AS view_ts,
    MIN(IF(event_name = 'add_to_cart',    event_timestamp, NULL)) AS cart_ts,
    MIN(IF(event_name = 'begin_checkout', event_timestamp, NULL)) AS checkout_ts,
    MIN(IF(event_name = 'purchase',       event_timestamp, NULL)) AS purchase_ts
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
  GROUP BY user_pseudo_id, ga_session_id
)
SELECT
  'scope'                             AS segment_type,
  'session'                           AS segment_value,
  COUNT(*)                            AS viewed,
  COUNTIF(cart_ts > view_ts)          AS added_to_cart,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts)      AS began_checkout,
  COUNTIF(cart_ts > view_ts
      AND checkout_ts > cart_ts
      AND purchase_ts > checkout_ts)  AS purchased
FROM session_journey
WHERE view_ts IS NOT NULL
  AND ga_session_id IS NOT NULL
