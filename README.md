# Aether

Aether is a personal AI assistant built in phases according to `AETHER_MASTER_BLUEPRINT.md`.

## Foundation and implemented phases

This repository contains:

- Nuxt 4 frontend at `frontend/`
- FastAPI backend at `backend/`
- Local MySQL development using Laragon on `localhost:3306`
- Account registration/login, owner-scoped conversations, and MySQL migrations
- OpenRouter chat with general/coding models and server-side tool calls
- Supervisor/worker agent workflow with MySQL event and recovery checkpoints
- User-approved task creation, task APIs, and user-controlled memory
- Authenticated WebSocket activity replay and reconnect

## Quick start

### MySQL (Laragon)

- Start MySQL in Laragon.
- Ensure MySQL is running on `localhost:3306` and the `aether_db` database exists.
- If Laragon credentials differ from `root` with an empty password, change `DATABASE_URL` in `backend/.env`.

### Backend

```bash
cd backend
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Before starting the backend, set a unique `JWT_SECRET` and your OpenRouter key in `backend/.env`.
The interactive API is available at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment files

- Frontend: `frontend/.env.example`
- Backend: `backend/.env.example`

## Notes

- Real secrets must never be committed.
- Replace `JWT_SECRET` in `backend/.env` with a unique random value of at least 32 characters before starting the backend. A value can be generated with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- `OPENROUTER_API_KEY` is only read by the backend and must never be added to frontend runtime configuration.

## Authentication and AI chat

- Register with `POST /api/v1/auth/register` using `email`, `password` (at least 12 characters), and `name`.
- Log in with `POST /api/v1/auth/login`; send its `access_token` as `Authorization: Bearer <token>`.
- Use `GET /api/v1/auth/me` to verify the authenticated account.
- Send a message using `POST /api/v1/chat` with `{"message":"Hello","model_role":"general"}`. Use `"coding"` for the coding model. Omit `conversation_id` to start a conversation or pass the returned ID to continue it.
- List owned conversations at `GET /api/v1/conversations` and messages at `GET /api/v1/conversations/{conversation_id}/messages`.
- The response includes `run_id`, `selected_agent`, and `pending_approval_id` when an agent action needs a decision.
- Review pending actions at `GET /api/v1/approvals`, then approve/reject with `POST /api/v1/approvals/{approval_id}/decision` and `{"approve":true}` or `{"approve":false}`. A task is not created until it is approved.
- Manage owned tasks at `/api/v1/tasks`. Manage explicit, user-approved memories at `/api/v1/memory`; memories are not captured automatically, and credential-like values are rejected.
- Connect to `/ws/chat/{conversation_id}` using the `aether` and `aether.bearer.<access_token>` WebSocket subprotocols. The optional `after` query parameter is a JSON object mapping run IDs to their last received sequence, e.g. `{"run-id":12}`. Events are replayed from MySQL and new events are polled from the database, so reconnect does not depend on in-memory server state.
- Resume failed workflows with `POST /api/v1/agents/runs/{run_id}/resume`; inspect persisted activity at `GET /api/v1/agents/runs/{run_id}/events`.
- Passwords use Argon2id hashing; chat messages and conversations are scoped to their owner in MySQL.
- OpenRouter reasoning details are preserved server-side for model continuation and are not included in chat API responses.
- The Nuxt homepage provides account registration/login, conversation history, model selection, live agent activity, approval actions, and memory controls. Its bearer token stays in tab memory and is cleared on refresh/sign-out.

## Verification

Run backend tests and apply/check migrations from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

Build the frontend from `frontend/` with `npm run build`.
