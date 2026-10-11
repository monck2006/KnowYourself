import type { EpisodeInput, IntakeDraft, Medication } from './types'
function today() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` }

function numberOrNull(value: unknown) { return value === '' || value == null ? null : Number(value) }
export function medicationInput(value: Partial<Medication> = {}): Medication {
  return { name: (value.name ?? '').trim(), dose: (value.dose ?? '').trim(), frequency: (value.frequency ?? '').trim(),
    started_at: value.started_at || null, ended_at: value.ended_at || null,
    adherence: value.adherence ?? 'unknown', response: value.response ?? 'unknown', notes: (value.notes ?? '').trim() }
}
// Explicit input fields prevent server-only properties leaking back after a conflict reload.
export function toEpisodeInput(value: Partial<EpisodeInput> = {}): EpisodeInput {
  return {
    chief_complaint: (value.chief_complaint ?? '').trim(), symptoms: [...(value.symptoms ?? [])],
    severity: value.severity ?? 2, started_at: value.started_at ?? today(),
    ended_at: value.status === 'ended' ? value.ended_at || null : null,
    status: value.status ?? 'ongoing', outcome: value.outcome ?? 'ongoing',
    vitals: { temperature: numberOrNull(value.vitals?.temperature), heart_rate: numberOrNull(value.vitals?.heart_rate), spo2: numberOrNull(value.vitals?.spo2) },
    medications: (value.medications ?? []).map(medicationInput), notes: value.notes ?? '',
    disease_category: value.disease_category ?? 'unknown', diagnosis_name: (value.diagnosis_name ?? '').trim(),
    diagnosis_source: value.diagnosis_source ?? 'unknown', infection_group: value.disease_category === 'infectious' ? value.infection_group ?? 'unspecified' : 'unspecified',
    observation_ids: [...(value.observation_ids ?? [])],
    assessment_answers: (value.assessment_answers ?? []).map(item => ({ question_id: item.question_id, answer: item.answer })),
  }
}

export function emptyIntakeDraft(): IntakeDraft {
  return {
    chief_complaint: '', symptoms: [], severity: null, started_at: '', status: 'ongoing', ended_at: '',
    outcome: 'ongoing', notes: '', disease_category: 'unknown', diagnosis_name: '',
    diagnosis_source: 'unknown', infection_group: 'unspecified',
    vitals: { temperature: null, heart_rate: null, spo2: null },
  }
}

/** Only the server-validated draft is converted; the final save still goes through POST /episodes. */
export function intakeDraftToEpisodeInput(draft: IntakeDraft): EpisodeInput {
  if (!draft.started_at || draft.severity == null || !draft.chief_complaint.trim() || !draft.symptoms.length) {
    throw new Error('请先确认主要不适、症状、开始日期和不适程度。')
  }
  const hadVitals = Object.values(draft.vitals).some(value => value != null)
  return {
    ...toEpisodeInput({
      chief_complaint: draft.chief_complaint, symptoms: draft.symptoms,
      severity: draft.severity, started_at: draft.started_at,
      status: draft.status, ended_at: draft.ended_at || null, outcome: draft.outcome,
      vitals: draft.vitals, notes: draft.notes, disease_category: draft.disease_category,
      diagnosis_name: draft.diagnosis_name, diagnosis_source: draft.diagnosis_source,
      infection_group: draft.infection_group,
    }),
    // Preserve the provenance that these vitals came from the guided conversation.
    vitals: hadVitals ? { ...draft.vitals } : { temperature: null, heart_rate: null, spo2: null },
  }
}
