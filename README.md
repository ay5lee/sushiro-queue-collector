# HK Sushiro Queue Collector (v1)

Local Docker + Postgres poller that snapshots every Hong Kong Sushiro store’s queue state from the unofficial **SUSHI-PASS** APIs. Prediction / “when to leave” is **out of scope** for v1.

**Repo:** [ay5lee/sushiro-queue-collector](https://github.com/ay5lee/sushiro-queue-collector)  
**Image:** `ghcr.io/ay5lee/sushiro-queue-collector`

## Terms / caveats

- Endpoints are SUSHI-PASS app backends, **not** a public product API. They can change, throttle, or break without notice.
- Polling may conflict with Sushiro / SUSHI-PASS terms. Use for **personal / research** only. Do not scrape aggressively or redistribute as an official feed.
- Wait times and called numbers reflect whatever the app exposes at poll time — not ground-truth seating.

## Clone + local compose (Mac / Docker)

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

## GHCR image

GitHub Actions (`.github/workflows/docker-publish.yml`) builds and pushes on every push to `main`, on tags `v*`, and via **workflow_dispatch**:

| Tag | When |
|-----|------|
| `latest` | push to `main` |
| `1.2.3`, `1.2` | semver from tag `v1.2.3` |
| `sha-<short>` | every build |

Pull:

```bash
docker pull ghcr.io/ay5lee/sushiro-queue-collector:latest
```

Auth uses `GITHUB_TOKEN` with `packages: write` — no extra secrets required for the workflow.

### Package visibility

The repo is **public**, but the first GHCR publish often creates a **private** package. For anonymous / Portainer pulls without a PAT, after the first successful `docker-publish` run:

1. Open [github.com/ay5lee?tab=packages](https://github.com/ay5lee?tab=packages) (or the package link from the Actions log).
2. Open **sushiro-queue-collector** → **Package settings** → **Change visibility** → **Public**.

If you keep it private, Portainer needs a GHCR registry credential (PAT with `read:packages`).

### First Actions run

On a brand-new repo you may need to:

1. Enable Actions if GitHub prompts (Settings → Actions → General → allow workflows).
2. Approve the first workflow run if the account/org requires approval for first-time workflows.
3. Confirm the default `GITHUB_TOKEN` can write packages (Settings → Actions → General → Workflow permissions → Read and write, or rely on the workflow’s `permissions: packages: write`).

## Portainer deploy

1. Wait until `ghcr.io/ay5lee/sushiro-queue-collector:latest` exists (green `docker-publish` run).
2. Set package visibility (public preferred) or add a Portainer registry for `ghcr.io`.
3. **Stacks → Add stack** → paste [`deploy/portainer-stack.yml`](deploy/portainer-stack.yml) (or upload).
4. Add env vars from [`deploy/portainer.env.example`](deploy/portainer.env.example) — change `POSTGRES_PASSWORD` / `DATABASE_URL`.
5. Deploy. Poller waits for Postgres health, applies schema, then sweeps on the store-hours schedule.

Local Mac development still uses `docker-compose.yml` (`build: .`), not the Portainer stack.

## What it collects

| Table | Role |
|-------|------|
| `stores` | Upserted from `storelist` (metadata + last raw JSON) |
| `queue_snapshots` | Append-only polls (`wait_minutes`, `queue_number`, `called_number`, `raw_json`) |

Schema: [`sql/001_schema.sql`](sql/001_schema.sql).

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
├── Dockerfile                 # poller image
├── docker-compose.yml         # local Postgres + build
├── .env.example
├── requirements.txt
├── sql/001_schema.sql
├── poller/                    # Python package (python -m poller)
├── scripts/smoke_api_map.py
├── deploy/
│   ├── portainer-stack.yml    # GHCR pull stack for Portainer
│   └── portainer.env.example
└── .github/workflows/
    ├── ci.yml                 # pytest + import smoke
    └── docker-publish.yml     # → ghcr.io/ay5lee/sushiro-queue-collector
```

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
