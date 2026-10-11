export interface User { id: string; username: string; display_name: string; created_at: string }
export interface Medication {
  name: string; dose: string; frequency: string
  started_at?: string | null; ended_at?: string | null
  adherence?: 'unknown' | 'as_recorded' | 'missed'
  response?: 'unknown' | 'improving' | 'unchanged' | 'worsened'
  notes?: string
}
export type EpisodeStatus = 'ongoing' | 'ended'
export type Outcome = 'ongoing' | 'improving' | 'resolved' | 'worsened'
export interface EpisodeInput {
  chief_complaint: string
  symptoms: string[]
  severity: number
  started_at: string
  ended_at: string | null
  status: EpisodeStatus
  outcome: Outcome
  vitals: { temperature: number | null; heart_rate: number | null; spo2: number | null }
  medications: Medication[]
  notes: string
  disease_category?: 'unknown' | 'infectious' | 'hereditary' | 'other'
  diagnosis_name?: string
  diagnosis_source?: 'self_report' | 'clinician' | 'unknown'
  infection_group?: 'unspecified' | 'respiratory' | 'gastrointestinal'
  observation_ids?: string[]
  assessment_answers?: AssessmentAnswer[]
}
export type AnswerValue = 'yes' | 'no' | 'unknown'
export interface AssessmentAnswer { question_id: string; answer: AnswerValue }
export interface ModelStatus { status: 'ready' | 'not_configured'; model: string; cloud: boolean; provider: string; prompt_version: string; notice: string; capabilities?: { text: boolean; images: boolean; audio: boolean } }
export interface IntakeContext { client_time: string; timezone: string; timezone_offset_minutes: number }
export interface AssessmentEvidence { id: string; kind: string; label: string; value: unknown; state: 'present' | 'absent' | 'unknown' | 'conflicting'; source: string; measured_at?: string }
export interface AssessmentKnowledge { id: string; title: string; excerpt: string; source_url: string; source: string; published_at?: string | null; imported_at?: string | null; matched_terms: string[] }
export interface Assessment {
  rule_version: string; episode_version: number; generated_at: string
  triage: Pick<Analysis, 'level' | 'label' | 'summary' | 'reasons' | 'action_plan'>
  questions: { id: string; text: string; reason: string; priority: string; answer: AnswerValue | null; options: { value: AnswerValue; label: string }[] }[]
  evidence: AssessmentEvidence[]; knowledge: AssessmentKnowledge[]; limitations: string[]
  monitoring: { metrics: { metric: string; label: string; points: { at: string; value: number; source: string }[]; unit: string; note: string }[]; next_check_in: string; escalation_signs: string[] }
  medication_checks: { name: string; status: 'review' | 'duplicate' | 'reported_reaction'; detail: string }[]
  model: ModelStatus; model_input: unknown
}
export interface ModelExplanation {
  status: 'generated' | 'unavailable' | 'not_configured' | 'skipped'; model: string; prompt_version: string; episode_version: number; generated_at: string; notice: string
  explanations?: { text: string; evidence_ids: string[]; knowledge_ids: string[] }[]; uncertainties?: string[]; consultation_notes?: string[]
}
export interface IntakeDraft {
  chief_complaint: string
  symptoms: string[]
  severity: number | null
  started_at: string
  status: 'ongoing' | 'ended'
  ended_at: string
  outcome: 'ongoing' | 'improving' | 'resolved' | 'worsened'
  notes: string
  disease_category: 'unknown' | 'infectious' | 'hereditary' | 'other'
  diagnosis_name: string
  diagnosis_source: 'unknown' | 'self_report' | 'clinician'
  infection_group: 'unspecified' | 'respiratory' | 'gastrointestinal'
  vitals: { temperature: number | null; heart_rate: number | null; spo2: number | null }
}
export interface IntakeTurn {
  status: 'generated' | 'unavailable' | 'not_configured' | 'complete'
  prompt_version: string; model: string; notice: string
  reply: string; question: string
  tool: 'chief_complaint' | 'severity' | 'symptoms' | 'started_at' | 'next_step' | 'none' | ''
  draft: IntakeDraft; missing_fields: string[]; complete: boolean
  triage?: Analysis
}
export interface Analysis {
  level: 'emergency' | 'attention' | 'recorded'
  label: string
  summary: string
  reasons: string[]
  matched_count: number
  disclaimer: string
  rule_version: string
  sources: { title: string; url: string }[]
  duration_days?: number | null
  action_plan?: { priority: 'now' | 'today' | 'observe'; title: string; detail: string }[]
  history_comparison?: { matched_count: number; typical_duration_days: number | null; range_days: [number, number] | null; records: { id: string; started_at: string; duration_days: number; medications: string[] }[] }
  device_context?: { readings: Observation[]; deviations: string[]; baseline_note: string }
  regional_context?: RegionalSummary
  profile_context?: { chronic_conditions: string[]; family_history: string[]; disease_category: string; diagnosis_name: string; diagnosis_source: string }
  medication_review?: { name: string; days: number | null; adherence: string; response: string; note: string }[]
}
export interface Episode extends EpisodeInput {
  id: string
  version: number
  created_at: string
  updated_at: string
  analysis: Analysis
}
export interface Overview {
  episode_count: number
  ongoing_count: number
  patterns: { symptoms: string[]; occurrences: number; last_seen: string }[]
  recent_episodes: Episode[]
}
export interface AuthResponse { user: User; access_token: string; token_type: string; expires_at: string }
export interface Workspace extends Overview { episodes: Episode[] }
export interface ExportData { schema_version: number; user: User; episodes: Episode[]; exported_at: string }

export interface HealthRegion { province: string; city: string; district: string; code: string; label: string }
export interface HealthProfile { version: number; birth_year: number | null; chronic_conditions: string[]; family_history: string[]; region: HealthRegion; regional_consent: boolean; updated_at: string }
export type ObservationMetric = 'heart_rate' | 'spo2' | 'temperature' | 'steps' | 'sleep_minutes'
  | 'dietary_energy' | 'hydration' | 'active_energy' | 'basal_energy' | 'hrv_sdnn' | 'hrv_rmssd' | 'vo2max'
  | 'distance_run' | 'distance_cycle' | 'exercise_minutes'
export interface ObservationInput { source: string; source_id: string; metric: string; value: number; unit: string; measured_at: string; context: string; device_name: string }
export interface Observation extends ObservationInput { id: string }
export interface Observations {
  items: Observation[]; total: number
  baseline: Record<string, { sample_count: number; reading_count: number; median: number | null; p10: number | null; p90: number | null; unit?: string }>
  latest: Record<string, Observation>; notice?: string
}
export interface RegionalSummary {
  enabled: boolean; region_label: string; status: 'disabled' | 'insufficient' | 'available'; window_days: number
  signals: { cluster: string; label: string; level: 'present' | 'elevated'; people_band: string; trend: 'increased' | 'stable' | 'unknown'; description: string }[]
  notice: string
}
export interface HealthContext { profile: HealthProfile; observations: Observations; region: RegionalSummary }

export interface KnowledgeTopic {
  id: string
  title: string
  display_title: string
  aliases: string[]
  summary: string
  groups: string[]
  source_url: string
  source?: string
  published_at?: string | null
  image_count?: number
  language: string
  generated_at?: string | null
  imported_at?: string | null
}
export interface KnowledgeTopics {
  items: KnowledgeTopic[]
  total: number
  page: number
  page_size: number
  generated_at: string | null
  imported_at: string | null
}
export interface DrugLabel {
  id: string
  brand_names: string[]
  generic_names: string[]
  manufacturer_names: string[]
  product_ndcs: string[]
  effective_date: string
  source_url: string
  sections: { key: string; title: string; text: string }[]
}
export interface DrugLabels {
  items: DrugLabel[]
  query: string
  normalized_query: string
  source: string
  source_url: string
  last_updated: string | null
  fetched_at: string | null
  stale: boolean
  cached: boolean
  notice: string
  total: number
}
export interface KnowledgeTopicSource {
  source: string
  source_url: string
  count: number
  generated_at: string | null
  imported_at: string | null
  language: string
}
export interface KnowledgeStatus {
  topics: { source: string; url: string; count: number; generated_at: string | null; imported_at: string | null; language: string; available: boolean; sources?: KnowledgeTopicSource[] }
  drugs: { source: string; url: string; available: boolean; language: string }
  directories: { name: string; url: string; description: string }[]
}
export type CompetitionDatasetId = 'cmeie' | 'cmeee'
export type CompetitionSplit = 'train' | 'dev' | 'test'
export interface CompetitionDataset {
  id: CompetitionDatasetId
  name: string
  source_url: string
  imported_at: string
  sha256: string
  sample_count: number
  split_counts: Record<CompetitionSplit, number>
  schema_count: number
  entity_count: number
  notice: string
}
export interface CompetitionStatus { datasets: CompetitionDataset[]; notice: string }
export interface CompetitionSample {
  id: string
  dataset: CompetitionDatasetId
  split: CompetitionSplit
  text: string
  relations: { subject: string; predicate: string; object: string; subject_type: string; object_type: string }[]
  entities: { text: string; type: string; start: number; end: number }[]
}
export interface CompetitionSamples {
  items: CompetitionSample[]
  total: number
  page: number
  page_size: number
  dataset: CompetitionDatasetId
  split: CompetitionSplit
  notice: string
}
