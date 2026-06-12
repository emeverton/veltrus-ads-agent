# AGENTS.md

## Cursor Cloud specific instructions

Scope: the runnable product in this repo is the **Python backend** — the FastAPI
API (`api/main.py`) plus the LangGraph agent (`agent/`). The `dashboard/` Next.js
app is currently an **empty scaffold** (every source file except `package.json`
is 0 bytes), so it cannot be built or run yet. Standard run commands live in
`README.md`; only the non-obvious caveats are below.

### Python environment
- Dependencies are installed into a local virtualenv at `.venv/` (created by the
  startup update script via `python3 -m venv .venv` + `pip install -r requirements.txt`).
- Run things with the venv interpreter and `PYTHONPATH=.` from the repo root, e.g.
  `PYTHONPATH=. .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000`.

### `.env` is required to even import the app (non-obvious)
- `agent/config.py` defines `Settings` with **required** fields
  (`anthropic_api_key`, `supabase_url`, `supabase_service_role_key`, `api_secret_key`).
  Importing `api.main` (or anything under `agent/`) instantiates `settings = Settings()`
  at module load, so a missing `.env` makes the whole app fail to import.
- A gitignored `.env` with placeholder values already exists for local dev. If it is
  ever missing, recreate it with `cp .env.example .env` — placeholder/example values
  are enough to import and boot the API. Replace with real values (or set Cursor
  Secrets) to enable live Supabase/Anthropic/Meta/Google/Brevo calls.
- `agent/tools/supabase_client.py` creates the Supabase client **at import time**, but
  it does not connect then; calls only hit the network when an endpoint queries the DB.
  With placeholder creds, DB-backed endpoints (e.g. `GET /decisions`) return HTTP 503
  ("Name or service not known") — this is expected and means auth + routing worked.

### Running / testing notes
- API smoke check without external services: `GET /health` → 200; `GET /decisions`
  with no/invalid `X-API-Key` → 401/403; with the configured key → reaches the DB layer
  (503 on placeholder creds). `POST /run` and `POST /run-email` require the `X-API-Key`
  header (value = `API_SECRET_KEY`).
- The pure-logic core (`agent/tools/normalizer.py` — the Unified Marketing Schema) runs
  fully offline and is a good smoke test of agent business logic (ROAS/CPA/CTR).
- There are **no automated tests yet** — `tests/` contains only `__init__.py` files, so
  `pytest` collects nothing (exit code 5).
- There is **no Python linter configured** (no ruff/flake8/pyproject). Use
  `.venv/bin/python -m compileall agent api scripts` as a basic check.
- `scripts/setup.sh` and `scripts/deploy.sh` are empty placeholders; the real entry
  points are documented in `README.md`.
