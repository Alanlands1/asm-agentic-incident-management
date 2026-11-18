# Backend

FastAPI service that ingests tickets from all sources, stores them in PostgreSQL (Supabase) and runs the agent pipeline over them.

## Structure

```text
backend/
├── app/
│   ├── api/v1/
│   │   ├── router.py            # mounts every router under /api/v1
│   │   └── endpoints/           # health, hello, tickets, data_quality
│   ├── core/                    # config (Settings, config version), registry, logging, middleware, exceptions
│   ├── services/                # ingestion, comments, data_quality (check_ticket, run_data_quality: rules, then the model)
│   ├── schemas/                 # API models: common, ticket, data_quality
│   ├── privacy/masking.py       # Presidio PII masking before any model call, and unmasking after
│   ├── agents/data_quality/
│   │   ├── signals.py           # facts about a ticket, computed before any rule
│   │   ├── rules.py             # rules stage
│   │   ├── config.py            # loads dq_rules.yaml
│   │   ├── verdict.py           # Verdict
│   │   └── model_check.py       # model stage: DQCompleteness, dq_completeness_spec()
│   ├── llm/client.py            # call_model(): the one way any agent calls the model
│   ├── admin/                   # runtime_config, admin endpoints, override tables
│   ├── models/ticket.py         # Ticket, AgentRun, Comment
│   ├── db/session.py            # Engine, session factory, get_db dependency
│   └── main.py                  # App factory and lifespan (loads admin overrides at startup)
├── tests/                       # pytest; conftest.py gives each test an in-memory database
├── Dockerfile
├── pyproject.toml               # Project metadata, pytest and ruff config
├── requirements.txt             # Runtime dependencies
└── requirements-dev.txt         # + test and lint tools
```

### Where new code goes

Existing code stays where it is. New code goes in its own folder:

| Adding | Goes in |
|---|---|
| An agent | `app/agents/<name>/`: verdict, rules, model step, pipeline, `schemas.py`, `router.py`; mount the router in `api/v1/router.py` |
| A feature that is not an agent | `app/<name>/`, like `admin/`: `router.py`, `schemas.py`, its logic, `models.py` if it has tables |
| An editable rules, terms or prompt file | `data/registry/`, registered with `register_document()` so the admin API can change and check it |
| A model call | a `CallSpec` and `call_model()` from `app/llm`; its prompt as an entry in `data/registry/prompts.yaml` |
| Tests | `tests/test_<name>.py` |

## Model calls

Every agent calls the model through `call_model(spec, masked_text, masker)` in `app/llm/client.py`:

- It accepts only text returned by `Masker.mask()`, so unmasked ticket text cannot reach the model.
- The answer must match the spec's Pydantic schema; an invalid answer is retried (`LLM_VALIDATION_ATTEMPTS`), then raises `ModelOutputError`.
- Outages raise `ModelUnavailableError` and refusals `ModelRefusedError`; the ticket stays `pending`.
- It returns the answer with real values put back, and a `CallAudit` (model, prompt version, tokens, latency, no text).

The Data Quality model stage (`agents/data_quality/model_check.py`) runs only on tickets the rules leave `uncertain`. Its prompt comes from `data/registry/prompts.yaml`; its answer schema, `DQCompleteness`, is code, because the eval measures it. The verdict is stored on `AgentRun.output` as `{"stage", "answer", "audit"}`.

Model calls are off by default (`LLM_ENABLED=false`): the pipeline then runs the rules only. Provider is `anthropic` (Claude API) now; `bedrock` is a config change.

## Configuration and admin

Nothing is hard-coded. Defaults come from `.env` and `data/registry/*.yaml`; an admin can override them at runtime and the next ticket uses the new value, with no restart.

| To change | Default lives in | Change it live |
|---|---|---|
| Model on/off, provider, model, effort, timeout, `LLM_TRANSPORT_RETRIES`, `LLM_VALIDATION_ATTEMPTS`, region, outage limit, log level | `.env` | `PUT /api/v1/admin/settings/{name}` |
| Data Quality prompt: text, version, ticket layout, wrapper, retry note, `max_tokens` | `data/registry/prompts.yaml` | `PUT /api/v1/admin/documents/data_quality_prompts` |
| Data Quality rules | `data/registry/dq_rules.yaml` | `PUT /api/v1/admin/documents/data_quality_rules` |
| PII terms, application names (shared) | `data/registry/pii.yaml`, `apps.yaml` | `PUT /api/v1/admin/documents/{pii\|apps}` |
| API keys, `ADMIN_API_KEY`, `ALLOWED_AWS_REGIONS`, storage paths | Environment only | Not through the API, by design |

- `DELETE` on the same path goes back to the default; `GET /api/v1/admin/changes` lists every change.
- Every admin call sends `X-Admin-Key`; with `ADMIN_API_KEY` unset the admin endpoints answer 503.
- Bad values are refused with 422 and change nothing.
- Limits: one shared key (the `X-Admin-User` name in the history is recorded as `claimed_by`, not verified), and changes apply to the process that received them, so run one worker or restart the others.

## Documentation

For architectural patterns, database standards (Supabase/PostgreSQL async conventions), and guidelines for building agent workflows, refer to [DEVELOPMENT.md](DEVELOPMENT.md).

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
