# StudyPilot

An adaptive, offline-resilient AI study copilot. StudyPilot builds a personalised roadmap from a student's goals and diagnostic results, grounds its tutoring in the student's own uploaded materials (hybrid RAG), and schedules reviews with spaced repetition.

## Features

- **Intake & diagnostics**: learner profile plus a diagnostic quiz to find starting knowledge.
- **Roadmap generation**: a dependency-aware (DAG) study plan, rescheduled when the student falls behind.
- **Materials pipeline**: upload textbooks (PDF), scans or photos of notebooks (OCR), Markdown/text notes and Jupyter notebooks. A background job extracts the text, builds an outline (PDF bookmarks → font-size headings → Markdown headings → LLM segmentation → page windows), summarizes each section, and indexes section-aware chunks for hybrid retrieval. Progress, re-index and delete are in the Library.
- **Curriculum from your materials**: pick uploaded materials and the curriculum is built from their outline. Sections become chapters (grouped by the LLM, validated in code, with a reading-order fallback), hours come from word counts, front/back matter is skipped by default, and over-budget plans get suggested skips. Chapters stay linked to their pages, so notes, guides, exams and the tutor are grounded in them.
- **Study schedule**: a deterministic day-by-day plan across tracks: prerequisite order, ≤50-minute sessions, a daily review block for earlier chapters, a buffer day each week, and final review + mock exams before the deadline. Missed work is re-packed on rebuild.
- **Agentic tutor**: a streaming, tool-using Socratic tutor. It searches your notes with hybrid keyword + semantic retrieval and cites them, reads chapter notes and your progress, and logs misconceptions to the Mistake Notebook. Built with LangChain `create_agent` on the LangGraph runtime, with guardrail middleware and a deepagents research subagent for multi-source questions. See `app/services/agent/`.
- **Mistake notebook**: records errors and misconceptions, with targeted drills.
- **Exam simulator**: timed mock exams with browser proctoring (tab switches, fullscreen exits, clipboard use and a heartbeat feed a 100-point integrity score).
- **Admin console** (`/admin`): platform dashboard, live exam proctoring (warn, terminate, review flagged attempts), users & roles, and LLM token management.
- **Token quotas**: every Gemini call (generation, streaming, embeddings, agent turns) is metered per user and feature. Users get a monthly budget (platform default or a per-user override) and see their usage on the AI usage page; over-limit requests get HTTP 429.
- **Brain map**: concept graph with a retention forecast.
- **Study sessions & coach**: energy-aware scheduling and a weekly report.
- **Leaderboard**: consistency-based study rooms.
- **Offline sync**: offline bundles and result sync.

## Tech stack

| Layer    | Tools |
|----------|-------|
| Backend  | FastAPI, SQLAlchemy (async), Pydantic v2, SQLite (PostgreSQL supported) |
| Jobs     | ARQ + Redis workers (in-process fallback without Redis) |
| Storage  | Chroma (MVP) or pgvector (PostgreSQL) for vectors; local disk or S3/R2/MinIO for files |
| AI       | Google Gemini (text, embeddings, vision OCR), LangChain, LangGraph, deepagents, networkx |
| Documents| pypdf, pdfplumber, pypdfium2, Tesseract (offline OCR), filetype |
| Frontend | React 19, React Router, TypeScript, Vite |
| Tests    | pytest, pytest-asyncio, httpx |

## Project layout

```
app/
  api/        # FastAPI routers (one per feature)
  core/       # config, database, security, vector store, RAG store
  models/     # SQLAlchemy entities
  schemas/    # Pydantic request/response models
  services/   # business logic (LLM, roadmap, RAG, scheduling, ...)
  main.py     # app entry point
  worker.py   # ARQ worker (ingestion jobs)
frontend/     # React + Vite client
tests/        # unit, integration and e2e tests
DOCS/         # specs and system design
```

## Getting started

### Backend

Requires Python 3.11+ (developed on 3.13).

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit values
uvicorn app.main:app --reload
```

The API runs at http://localhost:8000. Interactive docs are at `/docs`, and a health check is at `/health`. All feature routes are under `/api`.

Without `REDIS_URL`, uploads are processed by an in-process background task, which is fine for development. For production, run Redis and one or more workers:

```bash
docker compose up -d                 # Redis (add --profile postgres / --profile s3 for pgvector and S3 storage)
python -m app.worker                 # ARQ worker; same .env as the API
```

Scanned pages and photos are read with Gemini vision when a key is set, otherwise with Tesseract (`brew install tesseract` / `apt install tesseract-ocr`) if it is installed. Existing per-user JSON indexes from before the vector store are migrated automatically on startup.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server proxies `/api` to `http://localhost:8000`, so start the backend first.

## Configuration

Set these in `.env` (see [.env.example](.env.example)):

| Variable | Purpose | Default |
|----------|---------|---------|
| `APP_ENV` | `production` refuses to start with the development `SECRET_KEY` | `development` |
| `SECRET_KEY` | Signs bearer tokens (HMAC). **Change in production.** | dev key |
| `AUTH_TOKEN_TTL_HOURS` | Bearer token lifetime | `168` |
| `ADMIN_USERNAMES` | JSON list of usernames promoted to admin on register/login | `[]` |
| `DEFAULT_MONTHLY_TOKEN_LIMIT` | Monthly LLM tokens per user (0 = unlimited); admins can change it at runtime | `500000` |
| `PROCTOR_LIVE_WINDOW_SECONDS` | How recent an exam heartbeat must be to count as live | `45` |
| `STATIC_DIR` | Built frontend to serve from the API (the Docker image sets it) | empty |
| `DATABASE_URL` | SQLAlchemy URL (SQLite or PostgreSQL; libpq URLs with `sslmode`, as Neon gives, are accepted) | `sqlite+aiosqlite:///./studypilot.db` |
| `GOOGLE_API_KEY` | Gemini API key | none |
| `GEMINI_MODEL` / `GEMINI_FAST_MODEL` | Main and fast models | `gemini-3.8-flash` / `gemini-3.5-flash-lite` |
| `GEMINI_EMBED_MODEL` / `EMBED_DIM` | Embedding model for semantic retrieval | `gemini-embedding-001` / `768` |
| `GEMINI_AGENT_MODEL` | Tutor agent model; empty uses `GEMINI_MODEL` | empty |
| `AGENT_MAX_STEPS` | Tool-call rounds per tutor turn | `5` |
| `AGENT_THINKING_BUDGET` | Reasoning budget for agent turns (0 off, -1 dynamic) | `1024` |
| `AGENT_TOOL_TIMEOUT_SECONDS` | Per-tool timeout | `20` |
| `AGENT_RESEARCH_MAX_STEPS` | Tool-call rounds for the research subagent per task | `3` |
| `AGENT_SUBAGENT_TIMEOUT_SECONDS` | Timeout for one delegated research task | `90` |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | Gemini request timeout and retries with backoff | `60` / `3` |
| `CHROMA_PERSIST_DIR` | Chroma location (also where legacy JSON indexes are migrated from) | `./chroma_data` |
| `UPLOAD_DIR` / `MAX_UPLOAD_SIZE_MB` | Local upload location and per-file size limit | `./uploads` / `25` |
| `REDIS_URL` | Run ingestion on ARQ workers (`python -m app.worker`) | empty (in-process) |
| `INGEST_MODE` | `auto`, `arq`, `background` or `inline` | `auto` |
| `VECTOR_BACKEND` / `PGVECTOR_URL` | `chroma` or `pgvector`; pgvector uses `PGVECTOR_URL` or a PostgreSQL `DATABASE_URL` | `chroma` |
| `STORAGE_BACKEND` | `local` or `s3` (with `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`) | `local` |
| `OCR_PROVIDER` | `auto` (Gemini, Tesseract offline), `gemini`, `tesseract` or `none` | `auto` |
| `MAX_UPLOAD_PAGES` | Pages per file | `800` |
| `DEFAULT_STORAGE_PAGE_LIMIT` | Pages per user across all materials (0 = unlimited); admins can change it at runtime | `3000` |
| `MAX_OUTLINE_SECTIONS` | Outline size cap (deeper levels collapse first) | `200` |
| `OCR_TOKENS_PER_PAGE` | Token estimate per scanned page, checked against the quota before OCR | `1500` |

## API overview

| Prefix | Description |
|--------|-------------|
| `/api/auth` | register, login, current user |
| `/api/intake` | profile, diagnostic, submit diagnostic |
| `/api/roadmap` | generate and fetch the roadmap; `from-materials` previews a curriculum from uploads |
| `/api/chapters` | chapter notes |
| `/api/materials` | upload (202, processed in the background), list, status, outline, re-index, delete, storage, hybrid search |
| `/api/schedule` | build/rebuild the day-by-day plan, list tasks, mark done/skipped |
| `/api/tutor` | Socratic chat |
| `/api/mistakes` | log, list, resolve, drill |
| `/api/exam` | generate and submit mock exams, proctoring heartbeat, my attempts |
| `/api/usage` | the signed-in user's token quota and usage |
| `/api/admin` | overview, users & roles, token report/limits, storage limits, materials pipeline, proctoring (admin role required) |
| `/api/brain-map` | concept graph and retention forecast |
| `/api/session` | start/end sessions, reschedule |
| `/api/coach` | weekly report |
| `/api/leaderboard` | study-room leaderboard |
| `/api/sync` | offline bundle and results |

## Testing

```bash
pip install -r requirements-dev.txt
pytest                  # all tests
pytest tests/unit       # unit only
pytest tests/e2e        # full student flow
pytest tests/quality    # retrieval quality gate (hit rate + citation pages) on a known textbook
RAG_QUALITY_LIVE=1 pytest tests/quality                 # same, with live Gemini embeddings
PGVECTOR_TEST_URL=postgresql+asyncpg://studypilot:studypilot@localhost:5432/pgv_test pytest tests/integration/test_storage_backends.py
```

Tests process uploads inline and give each test its own Chroma store and upload directory. Re-run the quality gate whenever chunking, retrieval or the embedding model changes.

## Deployment

The [Dockerfile](Dockerfile) builds one image: FastAPI serves the API and the built frontend, so there is no CORS setup. The target is Cloud Run, with managed services that have free tiers:

| Piece | Service | Notes |
|-------|---------|-------|
| API + frontend | Cloud Run | `--no-cpu-throttling` so uploads keep processing after the request returns; `--max-instances 1` |
| Database + vectors | Neon Postgres (free plan) | `VECTOR_BACKEND=pgvector`; pgvector is available on the free plan |
| Uploaded files | Cloud Storage | through its S3-compatible API with HMAC keys; free tier applies in `us-central1`/`us-east1`/`us-west1` |
| Secrets | Secret Manager | database URL, `SECRET_KEY`, Gemini key, HMAC keys |
| LLM | Gemini API | key from Google AI Studio |

Ingestion runs inside the API instance (`INGEST_MODE=background`), so no Redis is needed. Materials left half-processed when an instance stops are resumed on the next startup. To scale past one instance, run Redis and `python -m app.worker` instead.

```bash
gcloud auth login
PROJECT_ID=my-project BUCKET=my-project-uploads ./deploy/gcp.sh setup   # once; prompts for the Neon URL and Gemini key
cp deploy/env.example.yaml deploy/env.yaml                              # set S3_BUCKET and ADMIN_USERNAMES
PROJECT_ID=my-project ./deploy/gcp.sh deploy                            # prints the service URL
```

To try the image locally: `docker build -t study-copilot . && docker run -p 8080:8080 --env-file .env -e SECRET_KEY=... study-copilot`.

## Documentation

Specs and architecture notes live in [DOCS/](DOCS/), including [StudyPilot_System_Design_Architecture.md](DOCS/StudyPilot_System_Design_Architecture.md).
