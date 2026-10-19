export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function apiBase(): string {
  if (typeof window === "undefined") {
    return API_URL;
  }
  try {
    const url = new URL(API_URL);
    if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
      url.hostname = window.location.hostname;
    }
    return url.origin;
  } catch {
    return API_URL;
  }
}

export function websocketBase(): string {
  return apiBase().replace(/^http/i, "ws");
}

export type ChecklistQuery = {
  query_id: string;
  question: string;
  dimension: string;
  requirement_type: string;
  weight: number;
  evidence_hints: string[];
  scoring_rubric: string;
};

export type JobVersion = {
  id: string;
  version_number: number;
  status: string;
  description: string;
  queries: ChecklistQuery[];
  posting_status: string | null;
  posting_detail: string | null;
  external_posting_id: string | null;
  apply_url: string | null;
  llm_tier: string;
  fallback_used: boolean;
};

export type JobRecord = {
  id: string;
  title: string;
  mail_subject: string;
  apply_email: string;
  versions: JobVersion[];
};

export type CandidateEvaluation = {
  query_id: string;
  question: string;
  status: string;
  confidence: number;
  evidence: string;
  semantic_score: number;
};

export type CandidateRecord = {
  id: string;
  email: string;
  full_name: string;
  rank: number | null;
  aggregate_score: number | null;
  mcq_score: number | null;
  parse_status: string;
  parse_method: string;
  invited: boolean;
  evaluations: CandidateEvaluation[];
  job_id: string | null;
  job_title: string;
};

export type CvUploadResult = {
  scored: number;
  duplicate: number;
  parse_failed: number;
  invalid: number;
  failed: number;
  items: { filename: string; outcome: string }[];
};

export type CandidateGroup = {
  job_id: string;
  job_title: string;
  mail_subject: string;
  candidates: CandidateRecord[];
};

export type AssessmentScores = {
  cv_screening: number | null;
  mcq_quiz: number | null;
  interview_qa: number | null;
  technical_dimension: number | null;
  experience_dimension: number | null;
  qualification_dimension: number | null;
};

export type AssessmentTrace = {
  claim: string;
  source_type: string;
  source_reference: string;
  evidence: string;
};

export type ClaimFlag = {
  claim_id: string;
  kind: string;
  statement: string;
  status: "contradiction" | "unverified" | "not_discussed";
  cv_quote: string;
  interview_quote: string;
  follow_up: string;
};

export type ClaimVerification = {
  candidate_id: string;
  llm_tier: string;
  fallback_used: boolean;
  supported_count: number;
  flags: ClaimFlag[];
};

export type MasterAssessment = {
  candidate_id: string;
  full_name: string;
  job_title: string;
  overall_suitability: "strong_fit" | "moderate_fit" | "unsuited" | "insufficient_evidence";
  suitability_label: string;
  overall_score: number | null;
  component_scores: AssessmentScores;
  strengths: string[];
  weaknesses: string[];
  evidence_gaps: string[];
  traceability: AssessmentTrace[];
  narrative: string;
  cv_weight: number;
  mcq_weight: number;
  interview_weight: number;
};

export type ComparisonRow = {
  candidate_id: string;
  full_name: string;
  overall_score: number | null;
  suitability_label: string;
  technical_dimension: number | null;
  experience_dimension: number | null;
  qualification_dimension: number | null;
  mcq_score: number | null;
  interview_qa: number | null;
  key_gap: string;
};

export type JobComparison = {
  job_id: string;
  job_title: string;
  cv_weight: number;
  mcq_weight: number;
  interview_weight: number;
  rows: ComparisonRow[];
};

export type ProgressCard = {
  candidate_id: string;
  full_name: string;
  rank: number | null;
  detail: string;
  interview_status: string;
};

export type ProgressColumn = {
  stage: "received" | "screened" | "invited" | "interview" | "quiz" | "assessed";
  label: string;
  cards: ProgressCard[];
};

export type ProgressBoard = {
  job_id: string;
  job_title: string;
  applicant_count: number;
  columns: ProgressColumn[];
};

export type CopilotChip = {
  label: string;
  kind: "navigate" | "prompt" | "report";
  href: string;
  prompt: string;
  candidate_id: string | null;
};

export type CopilotNavigation = {
  href: string;
  label: string;
};

export type CopilotTurn = {
  message: string;
  job: JobRecord | null;
  navigation: CopilotNavigation | null;
  chips: CopilotChip[];
  report_candidate_id: string | null;
};

export type InviteRecord = {
  job_title: string;
  company_name: string;
  status: string;
};

export type IceServer = {
  urls: string;
  username?: string;
  credential?: string;
};

export type OpenedInterview = {
  session_id: string;
  token: string;
  role: "candidate" | "recruiter";
  status: string;
  job_title: string;
  company_name: string;
  ice_servers: IceServer[];
  livekit_url: string;
  livekit_token: string;
};

export type InterviewDetail = {
  session_id: string;
  role: "candidate" | "recruiter";
  status: string;
  job_title: string;
  company_name: string;
  ice_servers: IceServer[];
  livekit_url: string;
  livekit_token: string;
  consented_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  processing_status: string;
  biometric_consented_at?: string | null;
};

export type IdentityProfile = {
  candidate_id: string;
  full_name: string;
  headline: string;
  skills: string[];
  pre_interview_score: number | null;
  probe_areas: string[];
};

export type IdentificationAck = {
  status: string;
  concluded: boolean;
  sample_count: number;
  sample_limit: number;
};

export type Identification = {
  status: string;
  message: string;
  similarity: number | null;
  invited_similarity: number | null;
  invited_name: string;
  matched_name: string | null;
  hint_name: string | null;
  profile: IdentityProfile | null;
  concluded?: boolean;
  sample_count?: number;
  sample_limit?: number;
};

export type TranscriptTurn = {
  id: string;
  speaker: string;
  start_time: number;
  end_time: number;
  text: string;
  confidence: number;
  is_final?: boolean;
};

export type PracticeInterview = OpenedInterview & {
  guest_url: string;
};

export type InterviewCopilot = {
  explored: string[];
  gaps: string[];
  suggested_question: string;
  profile_available?: boolean;
};

export type CopilotAnswer = {
  reply: string;
  questions: string[];
  profile_available: boolean;
};

export type QAPair = {
  pair_id: string;
  question: string;
  answer: string;
  intent: string;
  citation: string;
  query_ids: string[];
  relevance: number;
  technical_accuracy: number;
  completeness: number;
  articulation: number;
};

export type QAJustification = {
  claim: string;
  citation: string;
};

export type InterviewAnalysis = {
  relevance: number;
  technical_accuracy: number;
  completeness: number;
  articulation: number;
  gaps: string[];
  discrepancies: string[];
  summary: string;
  justifications: QAJustification[];
  pairs: QAPair[];
};

export type QuizQuestion = {
  question_id: string;
  prompt: string;
  options: string[];
};

export type QuizReviewItem = {
  question_id: string;
  prompt: string;
  options: string[];
  selected_index: number | null;
  correct_index: number;
  explanation: string;
  correct: boolean;
};

export type CandidateQuiz = {
  status: "in_progress" | "submitted";
  seconds_remaining: number;
  time_limit_seconds: number;
  questions: QuizQuestion[];
  review: QuizReviewItem[] | null;
};

export type RecruiterQuiz = {
  candidate_id: string;
  status: "not_started" | "in_progress" | "submitted";
  score: number | null;
  correct_count: number | null;
  time_limit_seconds: number | null;
  submitted_at: string | null;
  review: QuizReviewItem[];
};

export type PolicyRecord = {
  id: string;
  filename: string;
  media_type: string;
  created_at: string;
  chunk_count: number;
};

export type PublicJob = {
  version_id: string;
  title: string;
  seniority: string;
  description: string;
  contract: string;
  category: string;
  company_name: string;
  company_country: string;
  minimum_years: number;
  job_id: string;
  apply_email: string;
  apply_subject: string;
};

export class ApiError extends Error {
  code: string;

  constructor(message: string, code = "") {
    super(message);
    this.code = code;
  }
}

export const RECRUITER_TOKEN_KEY = "sift-recruiter-token";

export function recruiterToken(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return sessionStorage.getItem(RECRUITER_TOKEN_KEY) ?? "";
}

export function rememberRecruiter(token: string) {
  sessionStorage.setItem(RECRUITER_TOKEN_KEY, token);
}

export function forgetRecruiter() {
  sessionStorage.removeItem(RECRUITER_TOKEN_KEY);
}

export function bearer(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export function rememberInterview(sessionId: string, token: string, role: string) {
  sessionStorage.setItem(`sift-interview-token:${sessionId}`, token);
  sessionStorage.setItem(`sift-interview-role:${sessionId}`, role);
}

export function rememberPracticeLink(sessionId: string, url: string) {
  sessionStorage.setItem(`sift-practice-link:${sessionId}`, url);
}

export function recallPracticeLink(sessionId: string): string {
  if (typeof window === "undefined") {
    return "";
  }
  return sessionStorage.getItem(`sift-practice-link:${sessionId}`) ?? "";
}

export function recallInterview(sessionId: string): { token: string; role: "candidate" | "recruiter" } | null {
  const token = sessionStorage.getItem(`sift-interview-token:${sessionId}`);
  const role = sessionStorage.getItem(`sift-interview-role:${sessionId}`);
  if (!token || (role !== "candidate" && role !== "recruiter")) {
    return null;
  }
  return { token, role };
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Authorization")) {
    const token = recruiterToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  const response = await fetch(`${apiBase()}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: { message?: string; error_code?: string } | string;
    } | null;
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    const code = typeof detail === "string" ? "" : detail?.error_code || "";
    if (
      code === "RECRUITER_AUTH_REQUIRED" &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/login") &&
      !window.location.pathname.startsWith("/invite") &&
      !window.location.pathname.startsWith("/interview")
    ) {
      forgetRecruiter();
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    throw new ApiError(message || `Request failed (${response.status})`, code);
  }
  return (await response.json()) as T;
}

export async function downloadAssessmentReport(candidateId: string): Promise<void> {
  const headers = new Headers();
  const token = recruiterToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${apiBase()}/api/v1/candidates/${candidateId}/assessment/report`, { headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: { message?: string } } | null;
    const detail = payload?.detail;
    throw new ApiError(detail?.message || `Request failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `assessment-${candidateId}.html`;
  anchor.click();
  URL.revokeObjectURL(url);
}
