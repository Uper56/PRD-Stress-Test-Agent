/** Shared API types — mirror the FastAPI response shapes in api/. */

export interface Critique {
  critic_id: string;
  severity: string;
  finding: string;
  evidence?: string;
  suggested_fix?: string;
  claim_id?: string;
  skill_id?: string | null;
  /** Stable id computed by the server — used for discuss + feedback. */
  uid?: string;
}

export interface Challenge {
  round?: number;
  challenger?: string;
  target_critique_id?: string;
  counter_finding?: string;
  [key: string]: unknown;
}

export interface Verdict {
  executive_summary?: string;
  p0_blockers?: string[];
  p1_concerns?: string[];
  p2_suggestions?: string[];
  conflict_resolutions?: string[];
  [key: string]: unknown;
}

export interface HistoryItem {
  run_id: string;
  timestamp: string;
  prd_filename: string | null;
  excerpt: string;
  summary?: string | null;
  p0: number;
  p1: number;
  p2: number;
  critique_count: number;
  skill_hits: number;
  skill_misses: number;
}

export interface HistoryDetail extends HistoryItem {
  critiques: Critique[];
  challenges: Challenge[];
  supervisor_verdict: Verdict;
  prd_text_hash: string;
  retrieved_skill_ids: string[];
  skill_hits_list: string[];
  skill_misses_list: string[];
  total_tokens: number;
  total_cost_usd: number;
}

export interface Skill {
  name: string;
  description?: string;
  usage_count?: number;
  version?: string;
  created_by?: string;
  injected_into?: string[];
  status?: string;
  [key: string]: unknown;
}

export interface Proposal {
  proposal_id: string;
  proposed_name: string;
  proposed_skill_md: string;
  injected_into: string[];
  generalization_score: number;
  evidence: Array<Record<string, unknown>>;
  pattern_frequency: number;
  created_at: string;
  status: string;
}

export interface Meta {
  provider: string;
  model: string;
  rate: {
    disabled: boolean;
    remaining_global: number;
    remaining_ip: number;
    per_day: number;
    per_hour: number;
  };
}

export interface RunFinal {
  run_id: string;
  history_run_id: string | null;
  finished: boolean;
  verdict: Verdict | null;
  error: string | null;
}

export interface AblationJob {
  job_id: string;
}

export interface AblationJobStatus {
  status: 'running' | 'done' | 'failed';
  message: string | null;
}
