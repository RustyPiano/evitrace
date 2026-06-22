export interface TaskFile {
  id: string;
  task_id: string;
  original_name: string;
  stored_name: string;
  extension: string;
  mime_type: string | null;
  size_bytes: number;
  modality: string;
  status: string;
  error_message: string | null;
  created_at?: string | null;
}

export interface EvidenceItem {
  id: string;
  display_id: string;
  file: TaskFile;
  modality: string;
  evidence_type: string;
  content_summary: string;
  locator: Record<string, unknown>;
}

export interface TaskDetail {
  id: string;
  name: string;
  objective: string;
  description: string | null;
  owner_id: string;
  owner_username: string | null;
  status: string;
  last_error: string | null;
  file_count: number;
  evidence_count: number;
  created_at: string;
  updated_at: string;
  files: TaskFile[];
}

export interface RunStatus {
  run_id: string;
  status: string;
  plan_json?: unknown;
  progress: number;
  current_step: string | null;
  warnings: string[];
  error_message: string | null;
}

export interface AnalysisEntity {
  type: string;
  name: string;
  confidence?: number | null;
  evidence_ids?: string[];
}

export interface AnalysisEvent {
  event_id: string;
  event_key?: string;
  title: string;
  time_text?: string | null;
  time_normalized: string | null;
  location: string | null;
  evidence_ids: string[];
  confidence?: number | null;
}

export interface TimelineItem {
  event_id: string;
  event_key?: string;
  title: string;
  time_text?: string | null;
  time_normalized: string | null;
  time_group?: string;
  location: string | null;
  evidence_ids: string[];
  confidence?: number | null;
}

export interface ConflictSide {
  value: string;
  event_id: string;
  evidence_ids: string[];
}

export interface AnalysisConflict {
  conflict_id: string;
  type: "time" | "location" | "quantity" | string;
  event_key: string;
  description: string;
  left: ConflictSide;
  right: ConflictSide;
  status: "unreviewed" | "confirmed" | "ignored" | string;
}

export interface CitationCheck {
  used_citations?: string[];
  invalid_citations: string[];
  valid_citation_count?: number;
  invalid_citation_count?: number;
  citation_coverage: number;
  conclusion_paragraph_count?: number;
  cited_conclusion_paragraph_count?: number;
  uncited_sections?: string[];
  uncited_fact_count?: number;
}

export interface AnalysisResult {
  id: string;
  task_id: string;
  run_id: string;
  entities: AnalysisEntity[];
  events: AnalysisEvent[];
  timeline: TimelineItem[];
  conflicts: AnalysisConflict[];
  report_markdown: string | null;
  citation_check: CitationCheck;
  created_at: string | null;
  updated_at: string | null;
}
