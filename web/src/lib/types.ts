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

// ---- Skill Lifecycle Center -------------------------------------------------

export type SkillStatus =
  | 'candidate'
  | 'approved'
  | 'active'
  | 'degraded'
  | 'deprecated'
  | 'rejected';

export interface LifecycleOverview {
  counts: Partial<Record<SkillStatus, number>>;
  total_skills: number;
  degraded: Array<{
    skill_name: string;
    reason: string | null;
    rollback_target: string | null;
    since: string;
  }>;
  intervention_queue: Array<{
    skill_name: string;
    probation: boolean;
    triggers: number;
    feedback_samples: number;
    recent_acceptance: number | null;
  }>;
  recent_admissions: Array<{
    skill_name: string;
    to_status: string;
    at: string;
    actor: string | null;
    reason: string | null;
  }>;
}

export interface LibraryRow {
  skill_name: string;
  version: string;
  status: SkillStatus;
  reason: string | null;
  actor: string | null;
  rollback_target: string | null;
  probation_started_at: string | null;
  updated_at: string;
  usage_count: number;
  applied_count: number;
  feedback_samples: number;
  recent_acceptance: number | null;
  source: {
    proposal_id: string | null;
    prd_count: number;
    created_by: string;
    provenance: string;
  } | null;
}

export interface LineageVersion {
  lineage_id: string;
  skill_name: string;
  version: string;
  created_at: string | null;
  created_by: string;
  source_proposal_id: string | null;
  source_run_ids: string[];
  source_prd_hashes: string[];
  cited_excerpts: string[];
  parent_skill: string | null;
  parent_version: string | null;
  admission_decision: string | null;
  admission_actor: string | null;
  admission_at: string | null;
  validation_report_ref: string | null;
  evaluation_ref: string | null;
  provenance: string;
  recorded_at: string;
}

export interface StatusTransitionRow {
  transition_id: string;
  skill_name: string;
  from_status: string | null;
  to_status: string;
  reason: string | null;
  actor: string | null;
  at: string;
}

export interface LifecycleLineage {
  skill_name: string;
  versions: LineageVersion[];
  transitions: StatusTransitionRow[];
}

export interface GateReportT {
  report_id: string;
  proposal_id: string;
  gate: 'spec' | 'evidence' | 'novelty' | 'shadow';
  passed: boolean;
  detail: Record<string, unknown>;
  evaluator_version: string;
  created_at: string;
}
