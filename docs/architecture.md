Master Architecture & Technical Specification v2.0
AI-Powered Recruitment & Interview Intelligence Platform

0. Foundational Authentication & Role Management
Purpose
Centralized authentication and role-based access control (RBAC) enforcing strict separation of capabilities between administrative/recruiter roles and candidate interactions.

Role Specifications
Super-Admin:


Full system administration, user management, and raw database access.


System health, log monitoring, and container infrastructure access.


UI redacts all production API keys and secrets.


Admin / Recruiter:


Recruiter Dashboard access (job creation, CV batch upload, rank review, interview scheduling, Master Assessment review).


Blocked from raw backend configurations and system-level operations.


Client / Candidate:


Token-gated, single-purpose access via short-lived Magic Links.


Restricted strictly to assigned MCQ Quiz, assigned WebRTC room, and candidate-facing post-quiz answer summaries.


Strictly blocked from recruiter notes, CV rankings, comparative scoreboards, and candidate reports.


Security & Audit Implementation
Backend Authorization: FastAPI Depends dependency injection enforcing route guards and role checks.


Token Architecture: JWT containing claims: role, candidate_id, job_id, session_id, exp.


Password Hashing: passlib with bcrypt for recruiter/admin accounts.


Audit Logging: Structured logging in PostgreSQL capturing access events without storing PII.


1. Job Creation, Policy RAG & Locked Evaluation Checklist
(LangGraph Workflow 1)

Purpose
Assists recruiters in generating job descriptions (JDs) integrated with company policies while locking a versioned, deterministic requirement checklist for repeatable candidate scoring.

Workflow Execution
Recruiter opens Job Creation UI and inputs core parameters (title, seniority, required/preferred skills, qualifications, minimum experience).


System retrieves policy constraints from uploaded PDFs (salary bands, remote work policies, diversity guidelines) using vector search.


LangGraph Workflow 1 executes:

$$\text{RetrievePolicyRules} \longrightarrow \text{SynthesizeJD} \longrightarrow \text{GenerateScoringWeights} \longrightarrow \text{ValidateSchema}$$
Recruiter reviews, modifies, and locks the job profile.


System freezes the locked checklist as the permanent scoring source for that job version.


Locked Job Requirement Checklist Structure
For each job version, 10 structured evaluation queries are generated and frozen.

Query ID
Evaluation Query
Dimension
Type
Weight
Q1
Does candidate have experience building LLM-powered applications?
Technical
Must-have
High
Q2
Does candidate have experience with MCP, tool calling, or agents?
Technical
Preferred
Medium
Q3
Has candidate used LangGraph, LangChain, or equivalent frameworks?
Technical
Must-have
High
Q4
Does candidate have FastAPI or Python API development experience?
Technical
Must-have
High
Q5
Has candidate implemented RAG pipelines?
Technical
Preferred
High
Q6
Has candidate worked with vector databases (pgvector, ChromaDB)?
Technical
Preferred
Medium
Q7
Does candidate have Docker / containerization experience?
Technical
Must-have
Medium
Q8
Does candidate meet minimum years of experience?
Experience
Must-have
High
Q9
Does candidate possess relevant academic/professional qualifications?
Qualification
Must-have
Medium
Q10
Is there verifiable evidence of production project delivery?
Experience
Preferred
Medium

Query Schema Definition
JSON
{
  "query_id": "Q1",
  "question": "Does candidate have experience building LLM-powered applications?",
  "dimension": "technical",
  "requirement_type": "must_have",
  "weight": 0.15,
  "evidence_hints": ["LLM", "GPT", "Claude", "Gemini", "RAG", "prompt engineering"],
  "scoring_rubric": "Met if CV shows practical implementation or production usage. Partial if theoretical. Unmet if missing."
}

Configurable Weighting & Versioning
Recruiter specifies weight distribution across dimensions (e.g., Technical: 0.50, Experience: 0.30, Qualification: 0.20).


Every job revision increments job_requirement_version. Existing candidate score snapshots remain tied to the specific version against which they were evaluated.


2. Dual Candidate Ingestion Engine
Purpose
Supports candidate intake through manual batch uploader or background email inbox ingestion.

┌───────────────────────────────────────┐      ┌───────────────────────────────────────┐
│     Manual Batch File Upload UI       │      │   Email Worker (IMAP / Attachment)    │
└───────────────────┬───────────────────┘      └───────────────────┬───────────────────┘
                    │                                              │
                    └───────────────────────┬──────────────────────┘
                                            ▼
                             ┌─────────────────────────────┐
                             │ File Validation & SHA-256   │
                             │ Duplicate Hash Detection    │
                             └──────────────┬──────────────┘
                                            ▼
                             ┌─────────────────────────────┐
                             │   Docker Storage Volume     │
                             │ (/data/cvs/raw, processed)  │
                             └──────────────┬──────────────┘
                                            ▼
                             ┌─────────────────────────────┐
                             │ Async Celery / ARQ Queue    │
                             └─────────────────────────────┘

Technical Controls
Validation: File MIME type, extension (.pdf, .docx), size limits, and SHA-256 hash deduplication.


Storage: Docker-mounted persistent storage volumes (/data/cvs/raw, /data/cvs/processed, /data/cvs/failed).


Async Processing: Ingestion tasks are pushed to Celery/ARQ workers backed by Redis to prevent UI thread blocking.


3. Tiered CV Parsing & Imperfect Input Handling
Purpose
Ensures fault-tolerant text extraction across non-standard layouts, multi-column formats, scanned documents, and image-heavy PDFs.

Tiered Extraction Pipeline
Tier 1 (Native Text Extraction): pdfplumber / PyMuPDF for digital PDFs; python-docx for Word documents.


Tier 2 (Layout-Aware Extraction): PyMuPDF spatial block ordering and heuristic header detection for multi-column documents.


Tier 3 (OCR Fallback): Triggered when extracted text density falls below minimum thresholds. Utilizes Tesseract OCR (pytesseract, Pillow).


Parse Confidence Output
JSON
{
  "parse_method": "ocr_fallback",
  "parse_confidence": 0.62,
  "warnings": [
    "Low text density on page 1",
    "Possible scanned document",
    "Fallback OCR executed"
  ]
}

Fault Isolation Rule
A parsing failure in a single file marks the record as parse_failed and logs an alert, allowing batch execution to continue without crashing.

4. Core Pre-Interview Intelligence Engine
(LangGraph Workflow 2)

Purpose
Executes candidate evaluation, checklist query verification, fairness checks, scoring, and deterministic ranking in a single stateful graph.

Graph Topology & State Flow
    ┌───────────────────────┐
     │  IngestAndValidateCV  │
     └───────────┬───────────┘
                 ▼
     ┌───────────────────────┐
     │  ParseAndNormalizeCV  │
     └───────────┬───────────┘
                 ▼
     ┌───────────────────────┐
     │  ExtractCVAttributes  │
     └───────────┬───────────┘
                 ▼
     ┌───────────────────────┐
     │ LoadLockedJobChecklist│
     └───────────┬───────────┘
                 ▼
┌─────────────────────────────────┐
│ SemanticMatchAndCriteriaScorer │
└────────────────┬────────────────┘
                 ▼
  ┌─────────────────────────────┐
  │   ChecklistQueryEvaluator   │
  └──────────────┬──────────────┘
                 ▼
  ┌─────────────────────────────┐
  │    FairnessAndBiasGuard     │
  └──────────────┬──────────────┘
                 ▼
  ┌─────────────────────────────┐
  │    GenerateJustifications   │
  └──────────────┬──────────────┘
                 ▼
  ┌─────────────────────────────┐
  │   BatchRankerAndPositioner  │
  └──────────────┬──────────────┘
                 ▼
  ┌─────────────────────────────┐
  │    PersistScoreSnapshot     │
  └─────────────────────────────┘

Python
class CVScreeningState(TypedDict):
    candidate_id: str
    job_id: str
    job_version_id: str
    file_id: str
    file_type: str
    parse_method: str
    parse_confidence: float
    raw_text: str
    extracted_attributes: dict
    locked_checklist: list
    semantic_matches: list
    query_evaluations: list
    dimension_scores: dict
    aggregate_score: float
    justifications: list
    fairness_flags: list
    rank: int | None
    errors: list
    retry_count: int

Node Details
IngestAndValidateCV: Checks file validity, calculates SHA-256 hash, binds candidate to job ID.


ParseAndNormalizeCV: Executes Tier 1–3 extraction, normalizes whitespace, computes parse_confidence.


ExtractCVAttributes: Extracts structured JSON (contact, skills, work history, education, experience years).


LoadLockedJobChecklist: Loads frozen checklist queries and dimensional weights for the active job_version_id.


SemanticMatchAndCriteriaScorer: Computes cosine similarity between local vector embeddings (HuggingFace all-MiniLM-L6-v2) of CV sections and JD requirements.


ChecklistQueryEvaluator: Evaluates CV against each locked query, assigning status (met, partially_met, unmet, insufficient_evidence) with confidence ratings.


FairnessAndBiasGuard: Detects and strips protected characteristics (age, gender, ethnicity, religion, disability) to prevent scoring bias.


GenerateJustifications: Generates natural language reasoning citing direct CV quote evidence.


BatchRankerAndPositioner: Applies weights and orders candidates deterministically.


PersistScoreSnapshot: Stores full snapshot parameters in PostgreSQL.


Deterministic Tie-Breaker Hierarchy
Higher Aggregate Weighted Score


Higher Must-Have Requirement Fulfillment Ratio


Higher Technical Dimension Score


Higher Experience Dimension Score


Higher Qualification Dimension Score


Earlier Candidate Creation Timestamp


Lexicographical Candidate UUID


5. Automated Interview Link Dispatch
Purpose
Dispatches secure, token-gated access links to shortlisted candidates.

Session Lifecycle API Endpoints
POST /api/v1/interview-sessions: Initializes session linked to candidate and job version.


GET /api/v1/interview-sessions/{id}: Resolves session details.


POST /api/v1/interview-sessions/{id}/start: Registers candidate consent and initializes WebRTC context.


POST /api/v1/interview-sessions/{id}/end: Terminates session and triggers post-interview processing.


GET /api/v1/interview-sessions/{id}/status: Provides status updates.


Delivery Stack
Python secrets module, PyJWT, smtplib, Mailpit/Mailhog for local SMTP testing.

6. Dynamic MCQ Skill Quiz
(F11 Innovation Feature)

Purpose
Administers a 10-question multiple-choice technical assessment tailored to the candidate's CV attributes and the job's locked checklist queries.

Workflow
Candidate authenticates via token-gated Magic Link.


System loads candidate-specific quiz schema forced via Pydantic JSON outputs.


Candidate completes 10 technical questions.


Candidate views localized results showing their answers versus correct answers with explanations.


Integer score persists to database and merges into Master Assessment Workflow.


Documentation Requirements
Maintained at /docs/innovation-feature-rationale.md detailing problem definition, target user benefits, design rationale, and comparative alternatives.

7. Live Video Interview Environment
(BID F3)

Purpose
Browser-based WebRTC real-time video/audio interview environment with role-based UI controls and dual-channel audio capture.

Role Controls Matrix
Control / View
Admin (Recruiter)
Client (Candidate)
Mute Audio / Toggle Camera
Yes
Yes
Terminate Call Session
Yes
Yes
View Live Transcript Stream
Yes
Restricted
View In-Call Agentic Copilot
Yes
Restricted
View Candidate Profile Panel
Yes
Restricted
Network Reconnection Status
Yes
Yes

Audio Capture & Network Resilience Strategy
Audio Channel Splitting: Captured via Web Audio API into Channel A (Interviewer) and Channel B (Candidate).


Chunking: Streamed in 5-second WebM audio chunks over FastAPI WebSockets.


Network Interruption Buffer: Browser-side IndexedDB buffers chunks during connection drops and flushes upon reconnection.


8. Real-Time Speech Recognition & Transcription Engine
(BID F4)

Purpose
Transcribes participant audio with low latency, providing speaker attribution and timestamped segments.

Data Model
JSON
{
  "transcript_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "session_id": "a1b2c3d4-e5f6-7890-1234-56789abcdef0",
  "speaker": "candidate",
  "start_time": 13.2,
  "end_time": 17.8,
  "text": "I built a RAG pipeline using FastAPI and pgvector.",
  "confidence": 0.89
}

Execution Stack
faster-whisper local model, Python asyncio worker queue, Redis buffer, FastAPI WebSockets, PostgreSQL.

9. In-Call Agentic Copilot
Purpose
Provides recruiters with real-time assistance during interviews by tracking topic coverage against locked job requirements.

Context Integration
Combines live transcript streams, CV attribute JSON, JD requirements, and the locked evaluation checklist.

UI Capabilities
Displays live requirements coverage:

Explored Competencies: Python API Development, RAG Architecture.


Unexplored / Coverage Gaps: Tool Calling (MCP), Docker Deployments.


Suggested Follow-Ups: "The candidate mentioned RAG but omitted evaluation metrics. Ask: 'How did you measure retrieval precision?'"


10. Post-Interview Q&A Evaluation
(LangGraph Workflow 3 / BID F5)

Purpose
Segments interview transcripts into structured Q&A pairs, evaluating candidate responses against job criteria.

Graph Topology
$$\text{LoadTranscript} \longrightarrow \text{SegmentTranscriptIntoQA} \longrightarrow \text{ClassifyQuestionIntent} \longrightarrow \text{EvaluateCandidateResponse} \longrightarrow \text{MapQAToJobChecklist} \longrightarrow \text{IdentifyCoverageGaps} \longrightarrow \text{GenerateQ\&AJustifications} \longrightarrow \text{PersistQ\&AAnalysis}$$
JSON
{
  "qa_pair_id": "QA_04",
  "question": "How do you handle vector store index updates in production?",
  "candidate_response": "We implemented an asynchronous Celery task that re-embeds document updates...",
  "evaluations": {
    "relevance": 9.0,
    "factual_accuracy": 8.5,
    "technical_accuracy": 9.0,
    "completeness": 8.0,
    "articulation": 8.5
  },
  "mapped_checklist_queries": ["Q5", "Q6"],
  "evidence_citations": ["Transcript turn 18:22-19:05"]
}

11. Consolidated Candidate Assessment & Comparison
(LangGraph Workflow 4 / BID F6)

Purpose
Synthesizes pre-interview screening, MCQ quiz scores, and post-interview evaluations into a consolidated report.

Graph Topology
$$\text{LoadCandidateData} \longrightarrow \text{LoadCVScreeningSnapshot} \longrightarrow \text{LoadMCQScore} \longrightarrow \text{LoadQ\&AAnalysis} \longrightarrow \text{SynthesizeStrengthsAndWeaknesses} \longrightarrow \text{IdentifyEvidenceGaps} \longrightarrow \text{CalculateOverallSuitability} \longrightarrow \text{GenerateTraceableAssessmentNarrative} \longrightarrow \text{PersistConsolidatedAssessment}$$
Assessment Output
JSON
{
  "candidate_id": "cand_8821",
  "overall_suitability": "strong_fit",
  "overall_score": 83.4,
  "component_scores": {
    "cv_screening": 85.0,
    "mcq_quiz": 80.0,
    "interview_qa": 82.5,
    "technical_dimension": 86.0,
    "experience_dimension": 81.0,
    "qualification_dimension": 80.0
  },
  "strengths": ["Demonstrated production RAG experience", "Strong API design fundamentals"],
  "weaknesses": ["Limited hands-on MCP integration"],
  "evidence_gaps": [],
  "traceability": [
    {
      "claim": "Candidate has strong FastAPI experience.",
      "source_type": "cv",
      "source_reference": "work_history_2",
      "evidence": "Built REST APIs using FastAPI and PostgreSQL."
    }
  ]
}

Recruiter Dashboard & Side-by-Side Comparison Matrix
Provides interactive side-by-side comparison tables and generates PDF/HTML assessment exports using Jinja2 templates and WeasyPrint.

Candidate
Overall Score
Technical
Experience
Qualification
MCQ Score
Interview Q&A
Key Gap
Candidate A
84.2
88.0
80.0
78.0
70.0
82.0
Tool Calling (MCP)
Candidate B
79.5
81.0
77.0
82.0
80.0
74.0
Docker Deployment

12. Privacy, Deletion, Fairness & Data Governance
Candidate Data Erasure (BID N19)
Provides automated cascading deletion via endpoint DELETE /api/v1/admin/candidates/{candidate_id} or command line script (python scripts/delete_candidate.py --candidate-id <ID>). Cascades deletions across candidate records, raw CV files, parsed documents, vector embeddings, quiz results, audio chunks, transcripts, and assessment snapshots.

Data Minimization & Repository Hygiene (BID N14, N16)
Audio buffers are purged immediately after transcription processing unless configured otherwise.


.gitignore prevents check-in of .env, data/, cvs/, audio/, transcripts/, and database binaries.


Demonstration screenshots and logs use synthetic IDs (e.g., Candidate 007).


Third-Party Data Disclosure Matrix (BID N18)
Service
Data Transmitted
Purpose
Anthropic API
Anonymized CV text, transcript turns, job profiles
LLM generation and evaluation
Gemini API
Anonymized CV text, transcript turns, job profiles
Secondary LLM fallback
Local Ollama
Anonymized CV text, transcript turns, job profiles
Tertiary offline LLM fallback
Local Whisper
Raw audio WebM chunks
Real-time speech transcription
Mailpit
Candidate emails, magic link tokens
Local SMTP test routing

13. Security, Observability & Reliability
Security Standards
Secrets are loaded from environment variables (.env).


API inputs are validated using Pydantic schemas.


API exception handlers redact internal traces and return standard error responses:


JSON
{
  "error_code": "CV_PARSE_FAILED",
  "message": "The uploaded CV could not be processed.",
  "request_id": "req_9921"
}

Observability
Uses structlog for JSON-formatted logging without PII. Task updates are served via polling or SSE endpoints.

3-Tier LLM Fallback Mechanism
Automatic fallback handling: Anthropic Claude-3.5-Sonnet  Gemini 1.5 Pro  Local Ollama (Llama3.2). Fallback occurrences are flagged in evaluation snapshots.

14. Dockerization & Infrastructure Stack
Orchestration Architecture
Configured for single-command deployment via docker compose up --build.

YAML
services:
  api:
    build: ./backend
    depends_on: [postgres, redis]
  worker:
    build: ./backend
    command: celery -A app.worker worker
    depends_on: [redis, postgres]
  frontend:
    build: ./frontend
    depends_on: [api]
  postgres:
    image: postgres:16
  redis:
    image: redis:7
  vector:
    image: pgvector/pgvector:pg16
  mailpit:
    image: axllent/mailpit
  ollama:
    image: ollama/ollama
  tesseract:
    build: ./services/ocr

Named Volumes
postgres_data, redis_data, cv_data, audio_data, vector_data.

15. Persistence & Database Schema
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                   PostgreSQL Database                                  │
├──────────────────┬──────────────────┬──────────────────┬─────────────────┬──────────────┤
│  Users & Auth    │  Jobs & Rules    │  Candidates      │  Interviews     │ Assessments  │
├──────────────────┼──────────────────┼──────────────────┼─────────────────┼──────────────┤
│ users            │ jobs             │ candidates       │ interview_      │ consolidated_│
│ roles            │ job_versions     │ candidate_       │   sessions      │   assessments│
│ sessions         │ job_requirement_ │   documents      │ interview_      │ assessment_  │
│ magic_links      │   profiles       │ candidate_parse_ │   participants  │   component_ │
│ audit_logs       │ job_checklist_   │   results        │ audio_chunks    │   scores     │
│                  │   queries        │ screening_runs   │ transcript_     │ assessment_  │
│                  │ policy_documents │ score_snapshots  │   segments      │   strengths  │
│                  │ policy_chunks    │ query_           │ qa_pairs        │ assessment_  │
│                  │                  │   evaluations    │ qa_evaluations  │   weaknesses │
│                  │                  │ mcq_attempts     │ coverage_gaps   │ evidence_    │
│                  │                  │                  │                 │   links      │
└──────────────────┴──────────────────┴──────────────────┴─────────────────┴──────────────┘

Structured using SQLAlchemy / SQLModel ORM with Alembic database migrations.

16. Documentation & Deliverables
Directory Structure
Plaintext
/
├── docker-compose.yml
├── README.md
├── /backend
├── /frontend
├── /docs
│   ├── clarification-document.md
│   ├── wbs.md
│   ├── architecture.md
│   ├── risk-register.md
│   └── innovation-feature-rationale.md
└── /test-data
    └── /synthetic

OpenAPI Documentation
Served automatically at /docs (Swagger UI) and /redoc.

Appendix A: BID Requirements Traceability Matrix
BID Requirement
Category
Architecture Section
F1
CV Screening & Requirement-Based Ranking
Sections 1, 2, 3, 4


F2
AI-Based Candidate Scoring
Sections 1, 4


F3
AI-Powered Video Interview
Sections 5, 7


F4
Real-Time Speech Recognition & Transcription
Sections 7, 8


F5
AI-Based Interview Q&A Analysis
Sections 9, 10


F6
Consolidated Candidate Assessment
Sections 10, 11


F11
Innovation Feature (Dynamic MCQ Quiz)
Section 6


N1–N6
Throughput, Latency, API Quality, Concurrency, Fault Tolerance
Sections 2, 4, 7, 8, 13


N7–N12
Security, Secret Injection, Role Boundaries, Error Handling
Sections 0, 2, 13


N13–N20
Privacy, Data Erasure, Anonymization, Fairness Controls
Sections 4, 12


N21–N26
Dockerization, Reproducibility, Observability, Persistence
Sections 13, 14, 15, 16



Appendix B: Master Technology Stack Summary
Backend Engine: Python 3.11+, FastAPI, Pydantic, Uvicorn, Celery/ARQ, Redis.


LangGraph Workflows: LangGraph StateGraph, LangChain context helpers.


Document Processing: pdfplumber, PyMuPDF, python-docx, pytesseract, Tesseract OCR.


LLM & Vectors: Anthropic Claude-3.5-Sonnet, Gemini 1.5 Pro, Local Ollama, HuggingFace all-MiniLM-L6-v2, pgvector / ChromaDB.


Audio & Speech: Web Audio API, MediaRecorder, faster-whisper, WebSockets.


Frontend UI: Next.js, React Context / Zustand, Tailwind CSS, Recharts.


Reporting: Jinja2 templates, WeasyPrint PDF engine.


Database & DevOps: PostgreSQL 16, Docker Compose, Mailpit SMTP.

