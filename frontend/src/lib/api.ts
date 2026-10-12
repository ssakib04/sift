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
  parse_status: string;
  parse_method: string;
  invited: boolean;
  evaluations: CandidateEvaluation[];
  job_id: string | null;
  job_title: string;
};

export type CandidateGroup = {
  job_id: string;
  job_title: string;
  mail_subject: string;
  candidates: CandidateRecord[];
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
};

export type TranscriptTurn = {
  id: string;
  speaker: string;
  start_time: number;
  end_time: number;
  text: string;
  confidence: number;
};

export type InterviewCopilot = {
  explored: string[];
  gaps: string[];
  suggested_question: string;
};

export type InterviewAnalysis = {
  relevance: number;
  technical_accuracy: number;
  completeness: number;
  articulation: number;
  gaps: string[];
  summary: string;
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
