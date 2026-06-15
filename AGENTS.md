# AGENTS.md

## Cursor Cloud specific instructions

Durable, non-obvious notes for running/developing this repo in Cursor Cloud. The
update script already creates the Python venv and installs `requirements.txt`, so
this section focuses on how to run things and the gotchas — not on installing deps.

### What actually runs

| Service | Command (from repo root, venv active) | Notes |
|---|---|---|
| FastAPI API | `PYTHONPATH=. uvicorn api.main:app --reload --port 8000` | Core app. Routers: `/decisions`, `/run`, `/run-email`, `/health`. Swagger at `/docs`. |
| Agent scheduler | `python -m agent.main` | APScheduler loop; one cycle via `python -m agent.run`. Needs Supabase + a real `ANTHROPIC_API_KEY`. |
| Kill switch | `PYTHONPATH=. python scripts/kill_switch.py --dry-run` | Independent safety script. |
| Dashboard (`dashboard/`) | — | **Not runnable**: all `.tsx`/`.ts` and config files are empty 0-byte scaffolding (only `package.json` is populated, and it lists non-existent packages like `@radix-ui/react-badge`). Do not try to `npm run dev` it. |

Activate the env first: `source venv/bin/activate`.

### Config / boot gotchas

- `agent/config.py` instantiates `Settings()` at import time and **requires**
  `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and
  `API_SECRET_KEY` to be present. Without a `.env` providing these, importing
  `api.main` / the agent fails immediately. A local `.env` (gitignored) with any
  non-empty placeholder values is enough to **boot** the API and serve `/health`,
  `/docs`, and the auth checks; valid Supabase/Anthropic values are only needed for
  data/LLM flows.
- The Supabase client is created at import via `lru_cache` (`agent/tools/supabase_client.py`).
  A placeholder `SUPABASE_URL` does not make a network call at import, but any DB
  query will then fail at request time.
- `uvicorn --reload` watches `*.py`, **not** `.env`. After changing `.env`, restart
  the server (kill the process on port 8000 and relaunch) — reload alone won't pick
  it up.
- No Python linter is configured (no ruff/flake8/pyproject lint config). `tests/`
  contains only empty `__init__.py` files, so `pytest` collects 0 tests — that is
  expected, not a failure.
- No lockfiles exist; `requirements.txt` uses `>=` floors, so installs resolve to
  current latest (e.g. LangGraph 1.x even though code was written against 0.2.x).
  The graphs still import/compile fine under the newer versions.

### Full DB-backed testing with local Supabase (optional)

The DB-backed flows (e.g. `GET /decisions`) work end-to-end against a local Supabase
stack. This requires Docker + the `supabase` CLI (one-time system installs, not in
the update script). `supabase/config.toml` is committed so `supabase start` works.

1. `supabase start` — applies `supabase/migrations/*.sql` and prints local keys.
2. Point `.env` at the local stack: `SUPABASE_URL=http://127.0.0.1:54321` and
   `SUPABASE_SERVICE_ROLE_KEY` = the `SERVICE_ROLE_KEY` from `supabase status -o env`.
3. **Gotcha:** with recent Supabase CLI versions, the `service_role` DB role may lack
   privileges on migration-created tables (PostgREST returns `42501 permission denied`).
   Fix once after `supabase start`:
   ```
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO service_role;
   GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO service_role;
   ```
   (run via `docker exec -e PGPASSWORD=postgres supabase_db_workspace psql -U postgres -d postgres -c "..."`).
4. Seed: `PYTHONPATH=. python -m scripts.seed_test_data` (creates client/account/campaign/metrics).
   It does **not** create `agent_decisions` rows — insert one manually for `GET /decisions`
   to return data.
5. Restart the API so it reloads `.env`, then call with header `X-API-Key: <API_SECRET_KEY>`.

### External services for real runs

Real agent cycles and approvals need real credentials (set in Cursor Secrets):
`ANTHROPIC_API_KEY` (LLM), a real Supabase project, and `META_*` / `GOOGLE_ADS_*`
for actually reading/acting on campaigns. `BREVO_API_KEY` powers `/run-email`.
`AGENT_AUTONOMOUS_MODE=false` keeps the agent read-only (human approval required).
