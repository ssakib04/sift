# Sift, Phases 1–3

Personal walkthrough of what the system does through Phase 3. This is not application code. It follows the product in the order a recruiter and an applicant move through it, and names the database tables, backend files, functions, and screens involved.

The running app is Docker Compose. The API is FastAPI on port 8000. The frontend is Next.js on port 3000. Postgres (with pgvector) holds the data. Redis is up for the stack. Ollama is the local model. Mailpit is the local inbox used when Gmail is not configured. A worker process polls the mailbox. A separate MCP process posts approved jobs.

Code changes are copied into images at build time. `docker compose up -d --build` from the project folder rebuilds every service that bakes in code and starts the rest.

---

## 1. Shared machinery

These pieces are used by more than one stage.

### Settings

`backend/app/core/config.py`

`Settings` reads `backend/.env` and the repo `.env`. It holds the database URL, the three model names and keys, the embedding backend (`minilm` by default, model `sentence-transformers/all-MiniLM-L6-v2`), IMAP and SMTP for the apply mailbox, the public app URL, the company name, Telegram and MCP posting settings, and where policy files and CVs are stored on disk.

`get_settings()` is what the API and the worker call.

### Database session

`backend/app/core/database.py`

`get_session()` opens one async SQLAlchemy session per HTTP request. Alembic creates the tables. The three migrations are:

- `b7e1c4a2d901_enable_pgvector.py` turns on the pgvector extension.
- `c3a91e7b2f10_job_and_policy_tables.py` creates policies and jobs.
- `d8e4a1c57b20_candidate_screening.py` creates candidates, scores, invites, and intake records.

Models live in `backend/app/models/`. `Base` is in `models/base.py`.

### HTTP API

`backend/app/main.py` builds the FastAPI app, allows the frontend origin, and mounts every route under `/api/v1`.

`backend/app/api/router.py` attaches the route groups: health, policies, jobs, careers, copilot, screening, invites.

`backend/app/api/deps.py` hands each request the settings, the LLM manager (`get_llm`), the embedder (`get_embedder`), and the job poster (`get_poster`).

`GET /api/v1/health` in `backend/app/api/v1/health.py` checks that the API can talk to Postgres.

### Models, in fallback order

`backend/app/core/llm_fallback.py`

`FallbackLLMManager.complete()` tries Claude, then Gemini, then Ollama. The first one that returns text wins. `fallback_used` is true when Claude was skipped. If all three fail, screening or job creation stops with `LLMFallbackExhaustedError`.

`complete_local()` calls only Ollama. The CV recheck uses this. A failure there does not fail the whole score.

`AnthropicProvider`, `GeminiProvider`, and `OllamaProvider` are the three clients. `create_fallback_manager()` builds them from settings.

### Embeddings

`backend/app/services/embeddings.py`

Vectors are 384 numbers, matching the `policy_chunks.embedding` column.

`create_embedder()` returns `MiniLMEmbedder` unless `EMBEDDING_BACKEND` is `hashing`. MiniLM is `fastembed` with `all-MiniLM-L6-v2`. `HashingEmbedder` is a deterministic stand-in used in tests. Both return unit-length vectors. `embed()` takes a list of texts and returns one vector each.

Similarity in the CV graph is a dot product of those unit vectors (`_dot` in the CV graph). It is stored on each checklist answer. It does not, by itself, mark a question met or unmet.

### Frontend call helper

`frontend/src/lib/api.ts`

`apiRequest()` calls `http://localhost:8000` plus the path. It throws `ApiError` when the API is not OK. The same file holds the TypeScript shapes for jobs, checklist questions, candidates, evaluations, policies, and public jobs.

`frontend/src/components/section-links.tsx` is the nav: Home, Policies, Jobs, Candidates, Careers.

`frontend/src/app/layout.tsx` wraps every page and mounts the copilot.

`frontend/src/app/page.tsx` is the home screen. It only links into the other sections.

---

## 2. Company policies

This is the knowledge the job drafter is supposed to respect.

### What you do

Open **Policies** (`/docs`). Upload a PDF or DOCX, at most 10 MB.

### Frontend

`frontend/src/app/docs/page.tsx`

On load, `refresh()` calls `GET /api/v1/policies`. `onSubmit()` posts the file as multipart form data to `POST /api/v1/policies`, then reloads the list. The page shows each file name and how many chunks were stored.

### Backend

`backend/app/api/v1/policies.py`

`upload_policy()` checks size and type, then calls `ingest_policy()`. `read_policies()` returns the list.

`backend/app/services/policy_ingest.py`

`ingest_policy()`:

1. `extract_text()` in `backend/app/services/documents.py` reads the PDF (`pypdf`) or DOCX (`python-docx`) and collapses whitespace. Anything else raises `UnsupportedDocumentError`. An empty file raises `EmptyDocumentError`.
2. `chunk_text()` cuts the text into pieces of about 800 characters with 100 characters of overlap.
3. The embedder turns each chunk into a 384-number vector.
4. The original file is written under the policy storage directory, named by the document id.

### Database

`policy_documents`: id, filename, media type, storage path, created time.

`policy_chunks`: document id, chunk index, the chunk text, and the vector.

`list_policies()` reads documents with their chunks, newest first.

`PgPolicyRetriever.search()` embeds the query and orders chunks by cosine distance. Job creation and the copilot use this. The CV screener does not.

---

## 3. Draft a job

Two doors lead to the same draft: the Jobs form, and the copilot.

### What you do on Jobs

Open **Jobs** (`/jobs`). Fill title, seniority, required and preferred skills, qualifications, minimum years, the three dimension weights, contract, and category. Press **Generate draft**.

### Frontend

`frontend/src/app/jobs/page.tsx`, function `JobsPageContent`.

`onCreate()` posts JSON to `POST /api/v1/jobs`. On success, `applyJob()` keeps that job on the page and puts `?job=` in the address bar. A load effect also calls `GET /api/v1/jobs` so existing jobs can be opened from the list. Opening one with a job id in the URL calls `GET /api/v1/jobs/{id}`.

The draft section shows the generated description and the ten questions. You can edit both while the version is still `draft`.

`saveDraft()` sends `PATCH /api/v1/jobs/{id}/versions/{n}` with the description and questions.

### Backend route

`backend/app/api/v1/jobs.py`

`create_job_route()` builds a `PgPolicyRetriever` and calls `create_job()` in `backend/app/services/job_service.py`.

### The job-creation graph

`backend/app/graphs/job_creation_graph.py`, built by `build_job_creation_graph()`. `state_from_request()` copies the form into `JobCreationState` (`backend/app/graphs/state.py`).

The graph runs four steps, in order:

1. `retrieve_policy_rules` calls `retriever.search()` with the title and skills. The closest policy chunks become `policy_excerpts`.
2. `synthesize_jd` asks the LLM (through the Claude → Gemini → Ollama chain) for a job description of at least 100 characters. `parse_json_object()` pulls the JSON out of the reply.
3. `generate_scoring_weights` asks for exactly ten checklist questions, Q1 through Q10. Each question has a dimension (`technical`, `experience`, or `qualification`), a type (`must_have` or `preferred`), a weight, evidence hints, and a scoring rubric.
4. `validate_schema` checks that payload with `ChecklistQuerySet` in `backend/app/schemas/job.py`.

`ChecklistQuerySet.exactly_ten_unique_queries()` requires Q1–Q10 once each. Weights must be positive; if the model returns zeros or a total that is not 1, the weights are repaired so they sum to 1. Rubrics that come back as objects or lists are flattened to one string.

If the description is too short or the checklist is invalid, `JobGraphError` stops the request. Nothing is saved.

### What is written

`create_job()` inserts:

- one `jobs` row: id, title, `mail_subject` (the title, trimmed), created time.
- one `job_versions` row, version 1, status `draft`, plus seniority, skills, qualifications, minimum years, the three weights, contract, category, the generated description, the policy excerpts, which model tier was used, and whether fallback was used. `locked_at` is empty.
- ten `job_checklist_queries` rows: `query_id`, question, dimension, requirement type, weight, evidence hints, scoring rubric.

`update_draft()` is allowed only while status is `draft` (`ensure_editable()` in `backend/app/services/job_rules.py`). It replaces the description and, if you sent questions, deletes the old ten rows and inserts the edited ones. A locked checklist cannot be patched.

### Copilot, the other door

The chat button is `PersistentChatbot` in `frontend/src/components/persistent-chatbot.tsx`. It is hidden on `/login`. Sending a message posts the conversation to `POST /api/v1/copilot/messages`.

`backend/app/api/v1/copilot.py` → `run_copilot_turn()` in `backend/app/services/copilot.py`.

The model must return a plan (`plan_from_model_text()`): `create_job`, `list_jobs`, `list_policies`, or a plain reply.

- `list_jobs` uses `list_jobs()` and `summarize_jobs()`.
- `list_policies` uses `list_policies()`.
- `create_job` turns the plan into a `JobCreateRequest` (`job_request_from_plan()`), filling Mid-Level, Full Time, Information Technology, and zero minimum years only when you did not say them. It then calls the same `create_job()` as the form. The checklist is still a draft. The chat shows a card; approving from the card calls the approve route below.

---

## 4. Lock the checklist and post the job

### What you do

On the open draft, press **Approve and post**. The page first saves the draft if it is still `draft`, then calls `POST /api/v1/jobs/{id}/versions/{n}/approve`.

Later, **New version** calls `POST /api/v1/jobs/{id}/versions`. That is allowed only when the latest version is locked (`ensure_can_open_version()`). It copies the locked version into a new draft. The locked checklist stays frozen. Mail matching uses the newest locked version, not this new draft, until you approve the new one.

### Backend

`approve_job_version()` → `approve_version()` in `job_service.py`.

`approve_version()` sets `job_versions.status` to `locked` and sets `locked_at`. The public apply URL is `{PUBLIC_APP_URL}/careers/{version id}`.

`_publish()` then tries to announce the job, in this order:

1. If `MCP_SERVER_URL` is set, `_publish_mcp()` calls `publish_via_mcp()` in `backend/app/services/mcp_publish.py`. That talks to the MCP server’s `post_job` tool.
2. Else if Telegram is configured, `_publish_telegram()` uses `TelegramPoster` in `backend/app/services/telegram.py`. `build_channel_text()` is the channel message. `channel_message_url()` is the link stored as the posting detail.
3. Else if a PostAJob key is set, `PostAJobPoster.publish()` in `backend/app/services/postajob.py` sends `build_campaign_body()`.
4. Else the posting is stored as `not_configured`. A description under 100 characters is stored as `skipped` and is not sent anywhere.

The MCP process is `backend/app/mcp_jobs/server.py`. `build_job_server()` exposes one tool, `post_job`, which calls the same poster (Telegram in the current setup). `backend/app/mcp_jobs/__main__.py` starts that process.

### Database

One `job_postings` row per locked version: provider (`mcp`, `telegram`, or `postajob`), external id, status, the careers apply URL, and a short detail (often the Telegram link).

The checklist rows are not copied or changed at lock time. They are simply no longer editable.

`_to_job_read()` / `_to_version_read()` add the apply email and the mail subject onto the JSON the Jobs page shows, so you can see where applicants should write.

---

## 5. Public careers page

Applicants do not get an upload form. They see the role and the mailbox.

### Frontend

`frontend/src/app/careers/page.tsx` loads `GET /api/v1/careers` and links each role to `/careers/{version id}`.

`frontend/src/app/careers/[versionId]/page.tsx` loads `GET /api/v1/careers/{version id}` and shows the description, contract, category, and the apply email plus the subject line to use.

### Backend

`backend/app/api/v1/careers.py`

`read_public_jobs()` → `list_public_jobs()`. `read_public_job()` → `get_public_job()`.

Both only return versions whose status is `locked`. `list_public_jobs()` orders them by `locked_at`, newest first. `_to_public()` in `job_service.py` builds `PublicJobRead`: title, seniority, description, contract, category, company, country, minimum years, job id, apply email, and apply subject. Checklist questions are not public.

---

## 6. Mail arrives

Two things can pull the inbox. They call the same function.

- The worker, `backend/app/worker.py`, `poll_forever()`, sleeps `MAIL_POLL_SECONDS` (20 by default) and calls `ingest_inbox()`.
- **Check inbox** on the Jobs page posts `POST /api/v1/screening/poll`. `poll_inbox()` in `backend/app/api/v1/screening.py` calls the same `ingest_inbox()` and returns how many CVs were newly scored.

The button is the **Gmail inbox** block at the top of `frontend/src/app/jobs/page.tsx`, function `checkInbox()`. It does not require a job to be open. If one is open and that job has a locked version, it reloads that job’s applicants afterward.

### Which mailbox

`mailbox_from_settings()` in `backend/app/services/gmail_mailbox.py`.

If IMAP username and password are set, it uses `GmailMailbox` (IMAP, normally `imap.gmail.com`, port 993). `list_summaries()` searches `ALL` and keeps the latest 50 messages. Fetches use `BODY.PEEK`, so Gmail is not marked read.

If IMAP is empty, it uses `MailpitMailbox` in `backend/app/services/mailpit.py`, which is the local test inbox.

`parse_gmail_message()` walks the MIME parts and keeps every part that has a filename, plus its bytes.

### Matching a message to a job

`ingest_inbox()` and `_handle_summary()` in `backend/app/services/email_worker.py`.

`load_mail_keys()` in `backend/app/services/screening.py` loads every job that has a locked version. For each job it keeps the locked version with the latest `locked_at`. The key is job id, mail subject, version id, title, and lock time.

For each of the 50 messages, newest first:

1. `message_seen()` looks up `intake_messages` by the mailbox message id. If the row exists, the message is skipped. A new email is a new id. Renaming the attachment does not make a new id by itself, but sending again does.
2. If the sender is the invite-from address, the message is recorded as `ignored` so interview mail is not screened as a CV.
3. `match_job()` binds the subject. A subject that contains the job id wins immediately. Otherwise the subject must contain a saved mail subject of at least two characters. If several jobs match, the longest subject wins. If those are still tied, the newest `locked_at` wins.
4. No match: the function returns `unmatched` and does **not** write `intake_messages`, so a later poll can try again after you lock a job with that subject.
5. `read_message()` plus `_cv_attachment()` pick a PDF or DOCX attachment. No CV file: recorded as `ignored`.
6. `download()` gets the bytes. `validate_cv()` in `backend/app/services/ocr_service.py` requires a real PDF (`%PDF`) or DOCX (`PK`) of at most 8 MB.
7. `accept_cv()` scores it. `record_intake()` stores the outcome on `intake_messages`: `scored`, `duplicate`, `parse_failed`, or `ignored`, plus the job version id when there is one.

`ingest_inbox()` commits after each message. One bad message is logged and does not stop the rest. The poll result’s `processed` count is only messages whose outcome was `scored`.

---

## 7. Store the CV, or reject a duplicate

`accept_cv()` in `backend/app/services/screening.py`.

The file bytes are hashed with SHA-256. The filename is not part of the hash.

If `candidates` already has that hash for this **job version**, the function returns `duplicate`. It does not score again and does not add a row. It does call `_dispatch_invites()` again so a top-3 invite that failed to send can be retried. This is why sending the same PDF again, even with a new name, subject, or sender, does not create a second candidate and does not refresh the score. A small change inside the file changes the hash.

If the version is no longer locked, the outcome is `ignored`.

Otherwise:

- `_store_cv()` writes the bytes under the CV storage directory, folder `raw`, named `{hash}{extension}`.
- A `candidates` row is inserted: job version id, sender email, empty full name, the hash, the mailbox message id, created time. The unique rule is `(job_version_id, content_sha256)`.
- A `candidate_documents` row stores the original filename, media type, path, and size.

Then the screening graph runs.

---

## 8. Parse and score the CV

`build_cv_screening_graph()` in `backend/app/graphs/cv_screening_graph.py`. State is `CVScreeningState` in `backend/app/graphs/state.py`. The graph is given the LLM manager and the embedder. The locked checklist is the ten query rows turned into dicts by `_query_payload()`.

If the graph raises, or it returns errors or empty text, a `candidate_parse_results` row is stored with status `failed` and the file is copied to the `failed` folder. Outcome: `parse_failed`. The candidate row still exists, so the same bytes will not be tried forever as a new person; they are already stored. (A failed parse still inserted the candidate before the graph ran.)

### Step 1. `parse_and_normalize`

Calls `parse_cv()` in `backend/app/services/ocr_service.py`.

- Tier 1, `native`: pdfplumber for PDF, python-docx for DOCX. Confidence 0.92 if the text is at least 80 characters.
- Tier 2, `layout`, PDFs only: PyMuPDF block positions, read in page and position order. Confidence 0.78.
- Tier 3, `ocr_fallback`, PDFs only: render pages and run Tesseract. Confidence 0.6. Warnings say it may be a scan.

DOCX that is too short stops after tier 1. Empty text becomes an error and scoring stops.

### Step 2. `extract_cv_attributes`

One LLM call. The model must return JSON: full name, email, skills, work history, education, and a years number. Work history is supposed to be one object per job, with title, company, start, end (`YYYY-MM` or `present`), and summary.

`coerce_work_history()` in `backend/app/services/cv_facts.py` accepts that shape and also a plain string. If start and end are missing, `_range_in_text()` looks for a date range inside the sentence (`January 2014 - January 2018`, `2014-2018`, `present`).

`computed_experience_years()` turns those dates into one number. Overlapping jobs are merged so two jobs at the same time are not added twice. Year-only dates use 1 January as the start and 31 December as the end. `present` means today. If no dates can be read, the model’s own years number is kept. That computed number is what later experience questions use. The model’s glance at the CV is not.

### Step 3. `load_locked_checklist`

Requires exactly ten queries. Otherwise the graph records an error and the later steps do nothing.

### Step 4. `semantic_match`

Embeds the whole CV once and each question once. `_dot()` is the similarity stored as `semantic_score` on that question. A single skill in a long CV is easy to dilute, so this score is context, not the decision.

### Step 5. `checklist_evaluator`

One LLM call per question, ten calls. The prompt includes:

- `screening_facts()`: the computed total years, each role, and the skill list. The model is told to use that total for overall years and not to add the dates again.
- `_top_excerpts()`: the CV is split with `chunk_text()` (600 characters, 80 overlap). If there are more than three chunks, the three closest to the question are included. The full CV text (up to 12,000 characters) is still included.

The model returns `met`, `partially_met`, `unmet`, or `insufficient_evidence`, plus a confidence and a short quote.

`reconcile_evaluation()` in `cv_facts.py` then corrects that answer:

- `resolve_evidence()` keeps the status only when the quote’s words, or a distinctive phrase inside the quote, actually occur in the CV. `pgvector` and `PG Vector` match. A quote about a company that is not on the CV is dropped and the status becomes `insufficient_evidence`.
- For an experience question that asks for N years, `_available_years()` uses the computed total when the question is about professional experience in general. If the question names a skill (“5 years with pgvector”), only roles whose text contains that skill are summed. If that total is at least N, a weak status is raised to `met`, and `tenure_quote()` attaches a snippet of the CV that contains a year. This does not invent years.
- If the status is still `insufficient_evidence` and the question is not a years threshold, `supporting_skill_span()` marks it `met` when a skill from the CV (or a specific evidence hint) is named in the question and also appears in the CV. Generic words such as “experience” and “project” do not count. This catches “the CV says pgvector” when the quote was messy. It does not treat FastAPI as the word Python. That case is the next step.

`score_checklist()` in `backend/app/services/ranking.py` turns the ten statuses into numbers. `met` is 1, `partially_met` is 0.5, `unmet` and `insufficient_evidence` are 0. Each is multiplied by that question’s weight.

- `aggregate_score` is the weighted sum.
- `must_have_ratio` is the same, using only `must_have` questions.
- `technical_score`, `experience_score`, and `qualification_score` are that dimension’s points divided by that dimension’s total weight.

### Step 6. `local_skill_recheck`

Runs only when something is not `met`.

`open_for_local_review()` skips every `met` item. It also skips experience questions that ask for a number of years, because step 5 already decided those from the dates.

The leftover questions go to Ollama in **one** call via `complete_local()`. The prompt includes the similarity number as a hint and tells the model that a library can imply its language (FastAPI implies Python). It may only propose `met` or `partially_met`. A related tool should be `partially_met`. The requirement stated in the CV’s own words should be `met`.

`upgrade_open_evaluations()` applies a proposal only when the new status is higher and the quote is really in the CV. It never lowers a score. A missing or invented quote is ignored. If Ollama is down or the JSON is bad, the step logs `local_skill_recheck_skipped` and the scores from step 5 stay.

Totals are recalculated with `score_checklist()` after any raise.

### Step 7. `fairness_guard`

A fixed list of words (gender, religion, ethnicity, disability, and “N years old”) is searched in the raw CV. Matches are stored as `fairness_flags`. The same words are replaced with `[redacted]` inside the extracted attributes. The flags are a record that the CV contained them. They are not a separate score.

### Step 8. `generate_justifications`

One line per question: the query id, the status, and the quote if there is one. If a years total was computed, a first line states that total after merging overlaps. Protected words in those lines are redacted.

### What is written after a successful score

- `candidates.full_name` is filled from the extraction when the model returned one.
- The file is also stored under `processed` (same hash name).
- `candidate_parse_results`: status `parsed`, method (`native`, `layout`, or `ocr_fallback`), confidence, warnings, and the raw text.
- `score_snapshots`: the five scores, fairness flags, justifications, model tier, whether fallback was used, and a rank that is filled in the next step. One snapshot per candidate.
- `query_evaluations`: one row per question, with status, confidence, evidence quote, and semantic score.

Outcome returned to the mailbox loop: `scored`.

---

## 9. Rank and invite the top three

Still inside `accept_cv()`, after the snapshot is saved.

`_rerank()` loads every score snapshot for that job version and calls `rank_candidates()` in `ranking.py`.

Sort order, strongest first:

1. higher aggregate score
2. higher must-have ratio
3. higher technical score
4. higher experience score
5. higher qualification score
6. earlier `created_at`
7. candidate id, so the order is stable

Rank 1 is the strongest. The rank is written onto `score_snapshots.rank`.

`_dispatch_invites()` then calls `invite_ids()`. Anyone ranked 1, 2, or 3 who does not already have a `magic_links` row, and whose email contains `@`, gets an email.

`SmtpInviteSender.send()` in `backend/app/services/invites.py` sends through SMTP. When a username and password exist (SMTP settings, or the same Gmail app password as IMAP), it uses STARTTLS and logs in. The body is `invitation_body()`: company, job title, and a link `{PUBLIC_APP_URL}/invite/{token}`.

Two rows are inserted:

- `magic_links`: the token, unique, one per candidate.
- `interview_sessions`: status `invited`, tied to the candidate and the job version.

A person already invited is not invited again when someone else is scored and the ranks move. Only a newly entered top 3 gets a mail. The interview session is not a live interview. Phase 3 stops at “invited”.

---

## 10. Recruiter looks at candidates

### All applicants

`frontend/src/app/candidates/page.tsx` loads `GET /api/v1/candidates`.

`read_candidate_groups()` → `list_candidate_groups()` in `screening.py`. Candidates are grouped by job. Each group has the job title, the mail subject, and the people, ordered by rank.

### One job’s applicants

On the Jobs page, once a job with any locked version is open, an effect loads `GET /api/v1/jobs/{job id}/candidates`. `read_candidates()` → `list_ranked_candidates()`, which uses the **latest locked** version of that job, not a newer draft. The list shows rank, name, email, parse status, aggregate score, and whether they were invited. `checkInbox()` refreshes this list after a poll when a job is open.

### One person

A name on the candidates page links to `/candidates/{id}`.

`frontend/src/app/candidates/[candidateId]/page.tsx` loads `GET /api/v1/candidates/{id}`.

`read_candidate()` → `get_candidate()` → `_to_candidate_read()`. The profile shows identity, rank, the dimension scores, fairness flags, justifications, and each checklist line. The question text is joined from `job_checklist_queries` onto `query_evaluations` by `query_id`, so the page shows the locked question, the status, the quote, and the semantic score. That join is why the profile can show “Python experience” rather than only “Q3”.

---

## 11. The applicant opens the invite

`frontend/src/app/invite/[token]/page.tsx` loads `GET /api/v1/invites/{token}`.

`read_invite()` → `resolve_invite()` in `screening.py`. It finds `magic_links.token`, then the candidate, the job title, and the company name. The page shows that the invitation exists. There is no interview room in Phase 3.

An unknown token is an error on the page.

---

## 12. Tables, in the order they get rows

| Table | When a row appears |
| --- | --- |
| `policy_documents`, `policy_chunks` | A policy PDF or DOCX is uploaded |
| `jobs` | A draft is generated |
| `job_versions` | Draft version 1, and each later **New version** |
| `job_checklist_queries` | With each version, ten rows |
| `job_postings` | That version is approved |
| `intake_messages` | A mailbox message was ignored, scored, duplicate, or failed. Unmatched mail is not stored |
| `candidates` | A CV’s bytes were accepted for that locked version |
| `candidate_documents` | With the candidate, original filename and path |
| `candidate_parse_results` | After parse, success or failure |
| `score_snapshots` | After a successful score |
| `query_evaluations` | Ten rows on that snapshot |
| `magic_links`, `interview_sessions` | The candidate enters the top 3 and the invite mail is sent |

Files on disk, not in Postgres: the original policy upload, and the CV under `raw`, then `processed` or `failed`.

---

## 13. What Phase 3 does not do

- It does not rescore a CV whose bytes were already stored for that job version.
- It does not run an interview. `interview_sessions.status` stays `invited`.
- The embedding score does not decide met or unmet. The checklist model does, then the years math, the quote check, and the local Ollama raise.
- FastAPI counts as Python only in that local raise, and only as `partially_met` when the model says the link is indirect.
- Unmatched mail is left for a later poll. Ignored and duplicate mail is not retried as a new message.
- Drive is not used for scoring.
