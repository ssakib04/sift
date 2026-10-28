# Sift

Sift is an AI recruitment desk. A recruiter drafts a job, locks a scoring checklist, and receives CVs by upload or email. The system ranks applicants, sends interview links, runs a live video interview (a human recruiter or an AI interviewer), gives a short skill quiz, and writes the reports used to compare candidates.

The website is a Next.js app. The API is FastAPI. PostgreSQL stores the data. Docker Compose runs the whole stack.

## Run it

Docker Desktop must be running, and the machine needs free disk space. The Python images are large; a full disk makes `docker compose` fail while saving images.

```bash
cp .env.example backend/.env
# Fill in the keys you actually use. Leave unused keys blank.

docker compose up --build -d
```

Then open:

| What | URL |
| --- | --- |
| Website | http://localhost:3000 |
| API | http://localhost:8000 |
| Local mail inbox (Mailpit) | http://localhost:8025 |
| Postgres (from the host) | `127.0.0.1:5433` |

The recruiter signs in with `RECRUITER_PASSWORD` from `backend/.env`. Candidates do not get a password. They open the invite link that Sift emails.

On first start the API container runs database migrations (`alembic upgrade head`) before it serves requests.

Stop the stack with:

```bash
docker compose down
```

## What you need configured

Copy `.env.example` to `backend/.env`. The app starts with empty optional keys. These are the ones that change behavior:

- `RECRUITER_PASSWORD` and `JWT_SECRET` — recruiter login. Change both before any real interview.
- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` — cloud language models. Sift tries Claude, then Gemini, then a local Ollama model.
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` — video rooms. Without these, the call screen cannot join a room.
- Mail settings (`IMAP_*`, `SMTP_*`) — inbox polling and invitation email. In local Docker, Mailpit catches outgoing mail at http://localhost:8025.
- `GROQ_API_KEY` — optional cloud speech. Local Whisper and Kokoro/Piper still run in the interviewer container.

Do not commit `backend/.env`.

After the stack is up, pull the local model the interviewer is sized for:

```bash
docker compose exec ollama ollama pull llama3.2:1b
```

## How a hiring case moves

1. The recruiter creates a job. A LangGraph pipeline retrieves company-policy excerpts, drafts the description, and writes ten checklist questions. The job stays a draft until it is approved.
2. Approving locks that checklist. Locked jobs can be published (Telegram, the MCP tool server, or PostAJob, depending on which credentials are set).
3. CVs arrive by upload on the job page, or by email. The worker container polls the inbox. Each file is parsed (native text, then layout, then OCR), scored against the locked checklist, and ranked.
4. The recruiter chooses who to invite. Sift reserves a time slot and emails a one-time link.
5. The candidate opens the link, consents, and passes a face check when the CV contained a usable photo.
6. The call runs in a LiveKit room. If a recruiter is already in the room, a transcriber writes the transcript. Otherwise the AI interviewer asks the checklist questions.
7. The candidate takes a short quiz built from that job's checklist.
8. Ending the call writes the reports: question-and-answer analysis, CV-claim check, interview score, interview quality, and one combined assessment.

## Services

`docker-compose.yml` starts one image for the website and one backend image under five commands.

| Service | Role | Host port |
| --- | --- | --- |
| `frontend` | Next.js website | 3000 |
| `api` | FastAPI. Migrates the database, then serves `/api/v1` | 8000 |
| `worker` | Polls the mailbox and scores matching CVs | — |
| `interviewer` | AI interviewer (speech in, speech out) | — |
| `transcriber` | Transcript when a human recruiter is in the room | — |
| `mcp` | Tool server used when publishing a locked job | 8081 |
| `postgres` | PostgreSQL 16 with pgvector | 5433 |
| `redis` | Queue and buffer | 6379 |
| `ollama` | Local language model | 11435 |
| `mailpit` | Development mailbox | 8025 (view), 1025 (send) |
| `coturn` | TURN server for video calls | 3478 |

CV files live in the `cv_data` volume (`/data/cvs` inside the API and worker). Policy files live in `policy_data`. Speech models live in `speech_data`.

## Repository map

```text
backend/app/api/v1/     HTTP routes. Recruiter routes require a login token.
backend/app/services/   The work behind each route.
backend/app/graphs/     The four LangGraph pipelines.
backend/app/models/     Database tables.
frontend/src/app/       Website pages. A folder with page.tsx is a URL.
frontend/src/lib/api.ts The website's calls to the API.
docs/                   Architecture notes and presentation PDFs.
```

The four graphs are:

- `job_creation_graph.py` — policy retrieval, job description, checklist, validation.
- `cv_screening_graph.py` — parse a CV and score it against the locked checklist.
- `qa_analysis_graph.py` — turn a transcript into scored question-and-answer pairs.
- `master_assessment_graph.py` — combine CV, quiz, and interview into one suitability result.

Website routes worth knowing: `/login`, `/jobs`, `/candidates`, `/interviews`, `/practice`, `/invite/[token]`, `/interview/[roomId]`. `/login`, `/invite`, and `/interview` are open. Every other page requires the recruiter token.

## Tests

Backend tests:

```bash
cd backend
python -m pytest
```

The frontend check covers interviewer audio routing:

```bash
cd frontend
npm test
```

## Further reading

`docs/architecture.md` is the long technical specification. The PDFs in `docs/` are the presentation set: system architecture, each LangGraph workflow, the innovation rationale, and token-cost notes.
