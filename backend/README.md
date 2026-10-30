# Backend

FastAPI service that ingests tickets from all sources, stores them in SQLite and runs the agent pipeline over them.

## Structure

```text
backend/
├── app/
│   ├── agents/                  # one folder per agent: everything that agent owns, nothing else
│   │   └── data_quality/
│   │       ├── verdict.py       # Verdict
│   │       ├── signals.py       # facts about a ticket, computed before any rule
│   │       ├── rules.py         # rules stage
│   │       ├── model_check.py   # model stage: DQCompleteness, dq_completeness_spec()
│   │       ├── config.py        # loads its rules document
│   │       ├── pipeline.py      # check_ticket(), run_data_quality(): rules, then the model
│   │       ├── schemas.py       # its API models
│   │       └── router.py        # POST /api/v1/data-quality/run, POST /api/v1/data-quality/tickets/{id}/check
│   ├── common/                  # shared by every agent, owned by none; never imports an agent
│   │   ├── llm/client.py        # call_model(): the one way any agent calls the model
│   │   ├── privacy/masking.py   # Presidio PII masking before any model call, and unmasking after
│   │   ├── agent_run.py         # reporter_text, fingerprint, last_run, OutageBreaker
│   │   ├── config.py            # Settings and the config version
│   │   ├── registry.py          # reference documents: load, admin overrides, register_document()
│   │   └── logging.py, middleware.py, exceptions.py
│   ├── platform/                # not an agent
│   │   ├── tickets/             # ingestion, comments, ticket endpoints
│   │   ├── admin/               # runtime_config, admin endpoints, override tables
│   │   └── health/              # GET /api/v1/health, GET /api/v1/hello
│   ├── models/ticket.py         # Ticket, AgentRun, Comment: tables every agent shares
│   ├── db/session.py            # Engine, session factory, get_db dependency
│   ├── routes.py                # mounts every router under /api/v1
│   └── main.py                  # App factory and lifespan (loads admin overrides at startup)
├── tests/                       # pytest; conftest.py gives each test an in-memory database
├── Dockerfile
├── pyproject.toml               # Project metadata, pytest and ruff config
├── requirements.txt             # Runtime dependencies
└── requirements-dev.txt         # + test and lint tools
```

Dependencies point one way: `agents/` and `platform/` use `common/`; `common/` never imports either, and agents never import each other. Only `routes.py` and `main.py` know about all of them.

### Adding an agent

1. Create `app/agents/<name>/` with the same shape: verdict, rules, model step, pipeline, schemas, router.
2. Put its documents in `data/registry/<name>/` and call `register_document()` for each, so the admin API can change and check them.
3. Use `common/agent_run.py` for the skip-if-unchanged fingerprint and the outage breaker, and `call_model()` for every model call.
4. Mount its router in `routes.py`.

## Model calls

Every agent calls the model through `call_model(spec, masked_text, masker)` in `app/common/llm/client.py`:

- It accepts only text returned by `Masker.mask()`, so unmasked ticket text cannot reach the model.
- The answer must match the spec's Pydantic schema; an invalid answer is retried (`LLM_VALIDATION_ATTEMPTS`), then raises `ModelOutputError`.
- Outages raise `ModelUnavailableError` and refusals `ModelRefusedError`; the ticket stays `pending`.
- It returns the answer with real values put back, and a `CallAudit` (model, prompt version, tokens, latency, no text).

The Data Quality model stage (`agents/data_quality/model_check.py`) runs only on tickets the rules leave `uncertain`. Its prompt comes from `data/registry/data_quality/prompts.yaml`; its answer schema, `DQCompleteness`, is code, because the eval measures it. The verdict is stored on `AgentRun.output` as `{"stage", "answer", "audit"}`.

Model calls are off by default (`LLM_ENABLED=false`): the pipeline then runs the rules only. Provider is `anthropic` (Claude API) now; `bedrock` is a config change.

## Configuration and admin

Nothing is hard-coded. Defaults come from `.env` and `data/registry/*.yaml`; an admin can override them at runtime and the next ticket uses the new value, with no restart.

| To change | Default lives in | Change it live |
|---|---|---|
| Model on/off, provider, model, effort, timeout, `LLM_TRANSPORT_RETRIES`, `LLM_VALIDATION_ATTEMPTS`, region, outage limit, log level | `.env` | `PUT /api/v1/admin/settings/{name}` |
| Data Quality prompt: text, version, ticket layout, wrapper, retry note, `max_tokens` | `data/registry/data_quality/prompts.yaml` | `PUT /api/v1/admin/documents/data_quality_prompts` |
| Data Quality rules | `data/registry/data_quality/rules.yaml` | `PUT /api/v1/admin/documents/data_quality_rules` |
| PII terms, application names (shared) | `data/registry/common/pii.yaml`, `apps.yaml` | `PUT /api/v1/admin/documents/{pii\|apps}` |
| API keys, `ADMIN_API_KEY`, `ALLOWED_AWS_REGIONS`, storage paths | Environment only | Not through the API, by design |

- `DELETE` on the same path goes back to the default; `GET /api/v1/admin/changes` lists every change.
- Every admin call sends `X-Admin-Key`; with `ADMIN_API_KEY` unset the admin endpoints answer 503.
- Bad values are refused with 422 and change nothing.
- Limits: one shared key (the `X-Admin-User` name in the history is recorded as `claimed_by`, not verified), and changes apply to the process that received them, so run one worker or restart the others.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Then load the tickets once with `POST http://localhost:8000/api/v1/ingest` (or from Swagger at `http://localhost:8000/api/v1/docs`).

To use the model, set `LLM_ENABLED=true` and `ANTHROPIC_API_KEY` in `.env` (gitignored; the environment works too). On Windows, if spaCy fails with "DLL load failed", the Visual C++ runtime is missing: install it, or `pip install msvc-runtime` and add a `.pth` file in the venv's `site-packages` containing `import os, sys; os.add_dll_directory(os.path.join(sys.prefix, "Scripts"))`. Use synthetic tickets only until the production provider and region are confirmed.

## Run with Docker

From the repo root: `docker compose up --build`. The repo's `data/` folder is mounted read-only at `/data`, and the database is kept in a named volume.

## Tests and lint

```bash
pytest
ruff check .
```
