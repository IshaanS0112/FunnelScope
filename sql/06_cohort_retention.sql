-- 06_cohort_retention.sql
-- Question: Of users first seen in week W, what share came back in each later week?
-- Method:   Weekly acquisition cohorts x weeks-since-first-seen, with cohort_size carried
--           on every row so the retention rate is computable without a second join.
-- Output:   data/processed/06_cohort_retention.csv
-- Est. scan: ~0.4 GB (two passes over user_pseudo_id + event_timestamp)
--
-- THE TRAP IN THIS OUTPUT: cohorts formed near the end of the window have almost no
-- runway left. A January cohort cannot show week-8 retention because week 8 falls outside
-- the data. Read naively, late cohorts look like a retention collapse. They are TRUNCATED,
-- not worse. scripts/analyze.py marks every (cohort, week) cell whose observation window
-- extends past the last date in the data as censored, and the dashboard greys them out
-- rather than plotting them as zeros.

WITH user_days AS (
  SELECT
    user_pseudo_id,
    DATE(TIMESTAMP_MICROS(event_timestamp)) AS event_date
  FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
  WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix
),
cohorts AS (
  SELECT
    user_pseudo_id,
    DATE_TRUNC(MIN(event_date), WEEK) AS cohort_week
  FROM user_days
  GROUP BY user_pseudo_id
),
activity AS (
  SELECT DISTINCT
    user_pseudo_id,
    DATE_TRUNC(event_date, WEEK) AS active_week
  FROM user_days
),
sizes AS (
  SELECT cohort_week, COUNT(*) AS cohort_size
  FROM cohorts
  GROUP BY cohort_week
)
SELECT
  c.cohort_week,
  s.cohort_size,
  DATE_DIFF(a.active_week, c.cohort_week, WEEK) AS weeks_since_first,
  COUNT(DISTINCT a.user_pseudo_id)              AS active_users
FROM cohorts c
JOIN activity a USING (user_pseudo_id)
JOIN sizes    s USING (cohort_week)
GROUP BY c.cohort_week, s.cohort_size, weeks_since_first
ORDER BY c.cohort_week, weeks_since_first
