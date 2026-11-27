# HK Sushiro Queue Collector (v1)

Local Docker + Postgres poller that snapshots every Hong Kong Sushiro store’s queue state from the unofficial **SUSHI-PASS** APIs. A first-cut **wait baseline** (store × weekday × hour median / p75 + leave-by helper) is included; no ML.

- **GitHub:** https://github.com/ay5lee/sushiro-queue-collector
- **Image:** `ghcr.io/ay5lee/sushiro-queue-collector`

## Terms / caveats

- Endpoints are SUSHI-PASS app backends, **not** a public product API. They can change, throttle, or break without notice.
- Polling may conflict with Sushiro / SUSHI-PASS terms. Use for **personal / research** only. Do not scrape aggressively or redistribute as an official feed.
- Wait times and called numbers reflect whatever the app exposes at poll time — not ground-truth seating.

## Quick start (Mac)

```bash
git clone https://github.com/ay5lee/sushiro-queue-collector.git
cd sushiro-queue-collector
cp .env.example .env
docker compose up --build
```

- Postgres: `localhost:5432` (user/pass/db from `.env`)
- Poller: structured JSON logs on stdout; schema applied on startup
- Default cadence: **60s** full sweeps, concurrency **4**, polite backoff on 429/5xx

Stop with `Ctrl+C` or `docker compose down`. Data persists in the `sushiro_pgdata` volume.

Smoke outside store hours (Asia/Hong_Kong): set `FORCE_POLL=1` in `.env`.

API mapping only (no Docker):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/smoke_api_map.py
```

## What it collects

| Table | Role |
|-------|------|
| `stores` | Upserted from `storelist` (metadata + last raw JSON) |
| `queue_snapshots` | Append-only polls (`wait_minutes`, `queue_number`, `called_number`, `raw_json`) |

Schema: [`sql/001_schema.sql`](sql/001_schema.sql). Wait baselines (additive view): [`sql/002_wait_baselines.sql`](sql/002_wait_baselines.sql).

### Field mapping (live API + OSS)

| Snapshot column | Source | Notes |
|-----------------|--------|-------|
| `wait_minutes` | `storelist[].wait` | Estimated wait minutes. Refreshed each sweep via one storelist call. |
| `called_number` | max walk-in base from `groupqueues` arrays (`storeQueue`, `boothQueue`, `counterQueue`, `mixedQueue`, …) | Ticket strings like `"74"` / `"74-1"`. Bases ≥ 1000 treated as reservation and skipped (same heuristic as scmlewis/sushiro-hk-live). |
| `queue_number` | derived: `called_number + waitingGroup` when both known | **Last issued is not a dedicated API field.** Approximation only; full payloads always in `raw_json`. |
| `group_key` | `"walkin"` | Per party-size rows deferred; all queue arrays kept in `raw_json`. |

Store metadata: `id` → `store_id`, `name` → `name_zh`, `nameEn` → `name_en`, `region`/`area`, lat/lng, `address`.

References (mapping only): [scmlewis/sushiro-hk-live](https://github.com/scmlewis/sushiro-hk-live), [angus6b23/sushiro-vue](https://github.com/angus6b23/sushiro-vue).

### Store hours

`storelist` has **no per-store opening hours**. The poller uses a configurable HK default window (`DEFAULT_OPEN_TIME` / `DEFAULT_CLOSE_TIME`, default **10:30–22:00** Asia/Hong_Kong) and optional `STORE_HOURS_JSON` overrides. Outside that window it **pauses** overnight (unless `FORCE_POLL=1`). Stores with an active queue (`wait`/`waitingGroup` > 0) are still swept even if slightly outside the static table.

## Layout

```
.
├── Dockerfile
├── docker-compose.yml         # local Postgres + build
├── .env.example
├── requirements.txt
├── sql/
│   ├── 001_schema.sql
│   └── 002_wait_baselines.sql # store×DOW×hour median/p75 view
├── poller/                    # python -m poller
├── scripts/
│   ├── smoke_api_map.py
│   └── wait_baseline.py       # expected wait + leave-by CLI
├── deploy/
│   ├── portainer-stack.yml    # Portainer / GHCR stack
│   └── portainer.env.example
└── .github/workflows/
    ├── ci.yml
    └── docker-publish.yml     # → ghcr.io/ay5lee/sushiro-queue-collector
```

## GHCR + Portainer

On push to `main` (and tags `v*`), [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml) builds and pushes:

- `ghcr.io/ay5lee/sushiro-queue-collector:latest` (main)
- semver tags from `v*`
- `sha-…` tags

**Portainer (GitOps):**

1. Create a stack from the Git repo. Set **Compose path** to `deploy/portainer-stack.yml` (not root `docker-compose.yml`).
2. Paste env vars from [`deploy/portainer.env.example`](deploy/portainer.env.example) into the Portainer stack **Environment variables** UI (change `POSTGRES_PASSWORD` / `DATABASE_URL`). There is **no** `env_file: .env` and no checked-in `.env` — GitOps clones do not include one.
3. If the package is private, register `ghcr.io` with a PAT that has `read:packages`.

After the first successful publish, you can mark the GHCR package public (GitHub → Packages) if you want unauthenticated pulls.

## Wait baselines (v1)

Read-only first cut: **median** and **p75** of `wait_minutes` from `queue_snapshots`, bucketed by `store_id` × weekday (`EXTRACT(DOW)`, Sunday=0) × hour in **Asia/Hong_Kong**. Rows with `error IS NOT NULL` or `wait_minutes IS NULL` are excluded. Leave-by is a simple helper:

`leave_at ≈ target_arrive − travel_minutes − expected_wait`

**Caveats:** a few days of polls → rough / noisy buckets (sparse evenings, holidays, store events). This is not a model — just historical percentiles. Empty buckets print `baseline=none`.

### Apply the view (Portainer / local Postgres)

From a machine that can reach the Postgres published by the stack (Portainer host port or `docker exec` into the db container):

```bash
# Example: local compose / Portainer-published 5432
export DATABASE_URL=postgresql://sushiro:CHANGE_ME@127.0.0.1:5432/sushiro_queue
psql "$DATABASE_URL" -f sql/002_wait_baselines.sql

# Or via the CLI (creates/replaces the view, then looks up):
python scripts/wait_baseline.py --store-id 7 --apply-view
```

Ad-hoc:

```sql
SELECT * FROM wait_baselines
WHERE store_id = '7' AND dow = 5 AND hour = 19;
```

### Expected wait + leave-by CLI

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://sushiro:CHANGE_ME@127.0.0.1:5432/sushiro_queue

# Expected wait for store 7 at now (HKT)
python scripts/wait_baseline.py --store-id 7

# Leave-by: arrive 19:00 HKT, 25 min travel (uses median; add --p75 for p75)
python scripts/wait_baseline.py --store-id 7 --travel-minutes 25 --arrive 19:00

# Explicit local datetime for the bucket
python scripts/wait_baseline.py --store-id 7 --at 2026-11-27T19:30:00+08:00
```

The CLI runs the same aggregation inline, so it works even if you have not applied the view yet.

## Config

See [`.env.example`](.env.example). Important knobs:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SWEEP_INTERVAL_SECONDS` | `60` | Full sweep cadence |
| `CONCURRENCY` | `4` | In-flight `groupqueues` requests (3–5 recommended) |
| `MAX_REQUESTS_PER_MINUTE` | `90` | Hard ceiling |
| `DEFAULT_OPEN_TIME` / `DEFAULT_CLOSE_TIME` | `10:30` / `22:00` | HK poll window |
| `FORCE_POLL` | `0` | Ignore hours gate (smoke only) |

## License / ownership

Personal research collector for Adrian Lee — Project **Sushiro Predictive Ticketing**. Not affiliated with Food & Life Companies / Sushiro.
