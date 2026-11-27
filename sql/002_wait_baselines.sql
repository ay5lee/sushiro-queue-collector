-- v1 wait-time baselines: store × weekday × hour (Asia/Hong_Kong)
-- Additive only — does not alter stores / queue_snapshots columns.
--
-- Apply against Portainer / local Postgres:
--   psql "$DATABASE_URL" -f sql/002_wait_baselines.sql
--
-- EXTRACT(DOW): Sunday=0 … Saturday=6 (PostgreSQL convention).
-- Hour: 0–23 in Asia/Hong_Kong from polled_at.

CREATE OR REPLACE VIEW wait_baselines AS
SELECT
    store_id,
    EXTRACT(DOW FROM polled_at AT TIME ZONE 'Asia/Hong_Kong')::smallint AS dow,
    EXTRACT(HOUR FROM polled_at AT TIME ZONE 'Asia/Hong_Kong')::smallint AS hour,
    COUNT(*)::bigint AS sample_count,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_minutes)::double precision
        AS wait_median,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY wait_minutes)::double precision
        AS wait_p75
FROM queue_snapshots
WHERE error IS NULL
  AND wait_minutes IS NOT NULL
GROUP BY 1, 2, 3;

COMMENT ON VIEW wait_baselines IS
    'v1 store×DOW×hour wait_minutes median/p75 (HKT); excludes error/null waits';

-- Sample lookup (replace store_id / dow / hour):
-- SELECT * FROM wait_baselines
-- WHERE store_id = '7' AND dow = 5 AND hour = 19;
