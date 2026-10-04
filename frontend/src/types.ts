export interface User { id: string; username: string; display_name: string; created_at: string }
export interface Medication { name: string; dose: string; frequency: string }
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
