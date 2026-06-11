# Sheetgo A2A Agent

A human-in-the-loop [Agent-to-Agent (A2A)](https://a2a-protocol.org/) agent for
**Google Gemini Enterprise**. It discovers, governs, and analyzes
spreadsheet-driven operational workflows powered by Sheetgo, and answers
free-text questions about that data using **Vertex AI Gemini 2.5 Flash**.

It exposes two complementary surfaces:

- **Typed skills** — structured operations a Gemini Enterprise (or any LLM)
  router can call directly, declared in the Agent Card and an OpenAPI 3.1 spec:
  - `search_workflows` — find Sheetgo workflows by name
  - `get_workflow_context` — a workflow's spreadsheets
  - `query_spreadsheet_data` — a spreadsheet's columns + rows

- **Conversational data analysis (fallback)** — when no typed skill matches a
  `message/send`, a **Google ADK `LlmAgent`** takes over and the *model* decides
  what to do across two tools:
  - `load_dataset(name)` — searches the user's Google Sheets via the Sheetgo
    Core API, loads the first match, and pushes it into a **Vertex content
    cache** (only the cache reference is kept in session state — rows never enter
    the conversation or the session store).
  - `analyze(question)` — answers over the cached dataset with the conversation
    history, on a tool-free `generate_content` call that references the cache.

Conversations are **multi-turn per Gemini `contextId`**, persisted in memcached so
state survives across Cloud Run instances. Each OAuth client uses its **own
Sheetgo API key** (multi-tenant).

> Architecture diagram: [`agent_diagram.png`](./agent_diagram.png).
> Deeper design notes live in the workspace docs (`docs/gemini-agent.md`).

## How it works (request flow)

```
Gemini Enterprise ──(OAuth2 bearer)──▶ POST /  (JSON-RPC 2.0, A2A)
   │
   ├─ matches a typed skill ─────────▶ /skills/* (mock workflow/spreadsheet data)
   │
   └─ message/send, no skill match ──▶ ADK LlmAgent (gemini-2.5-flash, Vertex)
                                          ├─ load_dataset → Sheetgo Core API → Vertex cache
                                          └─ analyze      → generate_content(cached_content + history)
```

`client_id` is baked into the OAuth JWT, flows to the request via `flask.g`, into
the ADK session state, and is used by `load_dataset` to pick that client's Sheetgo
key from `constants.py:SHEETGO_API_KEYS`. An unmapped client is told it is not
authenticated for Sheetgo (there is no shared `SHEETGO_API_KEY` env var).

## Requirements

- **Python 3.11+**
- A **memcached** instance (multi-turn sessions + conversation history)
- A **GCP project with Vertex AI** enabled; the runtime service account needs
  `roles/aiplatform.user` (auth is via Application Default Credentials, not an API
  key)
- A reachable **Sheetgo Core API** base URL (file search + fetch)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1. Environment variables (`.env` at the project root)

| Variable | Required | Purpose |
|---|---|---|
| `JWT_SECRET` | ✅ | Signs/verifies OAuth access tokens (HS256) |
| `MEMCACHED_URL` | ✅ | Memcached endpoint for ADK sessions + history |
| `GCP_PROJECT_ID` | ✅ | Vertex AI project (mapped to `GOOGLE_CLOUD_PROJECT`) |
| `GCP_LOCATION` | ✅ | Vertex AI region (mapped to `GOOGLE_CLOUD_LOCATION`) |
| `CORE_API_BASE_URL` | ✅ | Sheetgo Core API base for `/rest/beta/files/*` |
| `ACCESS_TOKEN_EXP` | – | Access-token lifetime in seconds |
| `CODE_EXPIRATION` | – | OAuth authorization-code lifetime |
| `AGENT_CONV_TTL` | – | Session/cache TTL (default `3600`) |
| `AGENT_HISTORY_MAX_TURNS` | – | History window kept per conversation |
| `AGENT_CONTEXT_MAX_BYTES` | – | Cap on inlined Gemini-Enterprise context |
| `AGENT_LLM_RETRY_ATTEMPTS` / `AGENT_LLM_RETRY_INITIAL_DELAY` | – | Per-call Vertex retry (429/503/504) |
| `LOCAL`, `DEBUG_BRIDGE_URL` | – | Local-dev / debug-bridge helpers |

Example `.env`:

```
JWT_SECRET=your-jwt-secret
MEMCACHED_URL=localhost:11211
GCP_PROJECT_ID=your-gcp-project
GCP_LOCATION=us-central1
CORE_API_BASE_URL=https://api.sheetgo.com
```

### 2. Clients and per-client Sheetgo keys (`sheetgo_agent/constants.py`)

Two maps drive multi-tenant auth (MVP source of truth — a database lookup later):

- `CLIENTS` — `client_id → client_secret` for OAuth2.
- `SHEETGO_API_KEYS` — `client_id → Sheetgo API key`. A client missing here can
  authenticate via OAuth but gets a "not authenticated for Sheetgo" response when
  it tries to load data.

> ⚠️ This file holds real secrets for the MVP. Keep it out of any public repo.

## Running locally

```bash
source .venv/bin/activate
python -m sheetgo_agent.app
```

The agent starts on `http://localhost:8080`; the Agent Card is served at
`http://localhost:8080/.well-known/agent.json` and the OpenAPI spec at
`http://localhost:8080/openapi.json`. A reachable `MEMCACHED_URL` is needed for
multi-turn conversations.

## Running tests

```bash
JWT_SECRET=test python -m pytest sheetgo_agent/ --ignore=sheetgo_agent/test_agent.py -q
```

`JWT_SECRET` must be set (the auth module reads it at import). `test_agent.py` is
excluded — it has pre-existing import errors unrelated to the current agent and is
not part of the runnable suite.

## Deploy to Cloud Run

The container runs under Gunicorn (`sheetgo_agent.app:app`, see `Dockerfile`).

```bash
chmod +x deploy_cloud_run.sh
./deploy_cloud_run.sh
```

`deploy_cloud_run.sh` reads `.env` and requires `JWT_SECRET`, `MEMCACHED_URL`,
`GCP_PROJECT_ID`, `GCP_LOCATION`, and `CORE_API_BASE_URL`. It deploys the
`sheetgo-agent` service to `us-central1`. Ensure the service account has
`roles/aiplatform.user` and that the service can reach memcached (e.g. via a VPC
connector). `deploy_cloud_run_prototype.sh` is an alternate prototype target.

## A2A Endpoints

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/.well-known/agent.json` | GET | No | Agent Card (discovery) |
| `/openapi.json`, `/.well-known/openapi.json` | GET | No | OpenAPI 3.1 spec for typed skills |
| `/auth` | GET | No | OAuth2 authorization page |
| `/auth/confirm` | POST | No | OAuth2 consent confirmation |
| `/token` | POST | No | OAuth2 token exchange (issues a JWT carrying `client_id`) |
| `/` | POST | Bearer | JSON-RPC 2.0 dispatch |
| `/skills/search_workflows` | POST | Bearer | Typed skill: search workflows |
| `/skills/get_workflow_context` | POST | Bearer | Typed skill: workflow spreadsheets |
| `/skills/query_spreadsheet_data` | POST | Bearer | Typed skill: spreadsheet data |
| `/ping`, `/test` | * | No | Health / debug helpers |

### Supported JSON-RPC methods

- `message/send` — send a message; matches a typed skill or falls back to the
  conversational ADK data-analysis agent, and returns the completed result.

### Core API consumed (by the data-analysis fallback)

- `GET /rest/beta/files/search?q=` — Google Sheets matching a name.
- `GET /rest/beta/files/{id}` — a file's first tab as a JSON array of objects.

Both authenticate with the caller's per-client Sheetgo key (`Bearer`).

