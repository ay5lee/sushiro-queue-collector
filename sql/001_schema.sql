-- HK Sushiro queue collector schema (v1)
-- Matches docs/queue-data-collection-plan.md

CREATE TABLE IF NOT EXISTS stores (
    store_id      text PRIMARY KEY,
    name_en       text,
    name_zh       text,
    region        text,
    latitude      double precision,
    longitude     double precision,
    address       text,
    is_active     boolean NOT NULL DEFAULT true,
    raw_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stores_region_active
    ON stores (region, is_active);

CREATE TABLE IF NOT EXISTS queue_snapshots (
    id            bigserial PRIMARY KEY,
    store_id      text NOT NULL REFERENCES stores (store_id),
    polled_at     timestamptz NOT NULL DEFAULT now(),
    wait_minutes  integer,
    queue_number  integer,
    called_number integer,
    group_key     text,
    raw_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
    http_status   smallint,
    error         text
);

CREATE INDEX IF NOT EXISTS idx_queue_snapshots_store_polled
    ON queue_snapshots (store_id, polled_at DESC);

CREATE INDEX IF NOT EXISTS idx_queue_snapshots_polled
    ON queue_snapshots (polled_at);

CREATE INDEX IF NOT EXISTS idx_queue_snapshots_errors
    ON queue_snapshots (polled_at DESC)
    WHERE error IS NOT NULL;
