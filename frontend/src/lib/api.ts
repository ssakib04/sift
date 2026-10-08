export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  constructor(message: string) {
    super(message);
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: { message?: string } | string } | null;
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new ApiError(message || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}
