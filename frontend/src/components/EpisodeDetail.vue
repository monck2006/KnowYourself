<script setup lang="ts">
import { dateLabel, outcomeLabels, severityLabels } from '../format'
import type { Episode } from '../types'
import Icon from './Icon.vue'
import EpisodeInsights from './EpisodeInsights.vue'
const props = defineProps<{ episode: Episode; deleting: boolean }>()
defineEmits<{ edit: []; remove: []; report: [] }>()
const categories = { unknown: '尚未明确', infectious: '感染性疾病', hereditary: '遗传相关疾病', other: '其他疾病' }
const diagnosisSources = { unknown: '来源未明确', self_report: '本人自述', clinician: '医生诊断' }
const adherenceLabels: Record<string, string> = { unknown: '执行情况未记录', as_recorded: '按所记用量与频率', missed: '有漏服或漏用' }
const responseLabels: Record<string, string> = { unknown: '变化尚不清楚', improving: '自述好转', unchanged: '自述无明显变化', worsened: '自述加重' }
function medicationReview(name: string) { return props.episode.analysis.medication_review?.find(item => item.name === name) }
</script>

<template>
  <div class="episode-detail">
    <div class="detail-topline"><span class="badge" :class="episode.status">{{ episode.status === 'ongoing' ? '正在记录' : '已经结束' }}</span><span class="muted">{{ episode.started_at.slice(0, 4) }} 年 · {{ dateLabel(episode.started_at) }}{{ episode.ended_at ? ` — ${dateLabel(episode.ended_at)}` : ' 起' }}</span></div>
    <h2 class="detail-title">{{ episode.chief_complaint }}</h2>
    <div class="tag-list"><span v-for="symptom in episode.symptoms" :key="symptom" class="tag">{{ symptom }}</span></div>
    <p v-if="episode.disease_category && episode.disease_category !== 'unknown'">{{ categories[episode.disease_category] }}<template v-if="episode.diagnosis_name"> · {{ episode.diagnosis_name }}（{{ diagnosisSources[episode.diagnosis_source ?? 'unknown'] }}）</template></p><p v-else-if="episode.diagnosis_name">{{ episode.diagnosis_name }} · {{ diagnosisSources[episode.diagnosis_source ?? 'unknown'] }}</p>
    <p v-if="episode.analysis.duration_days != null" class="muted">本次病程 {{ episode.analysis.duration_days }} 天</p>
    <EpisodeInsights :episode="episode" />
    <div class="detail-facts"><div><span>不适程度</span><strong>{{ severityLabels[episode.severity - 1] }} <small>{{ episode.severity }} / 5</small></strong></div><div><span>目前变化</span><strong>{{ outcomeLabels[episode.outcome] }}</strong></div></div>
    <section class="detail-section"><h3><Icon name="pulse" :size="18" />手动测量记录</h3><div class="detail-vitals"><div><span>体温</span><strong>{{ episode.vitals.temperature ?? '—' }}<small v-if="episode.vitals.temperature !== null">°C</small></strong></div><div><span>心率</span><strong>{{ episode.vitals.heart_rate ?? '—' }}<small v-if="episode.vitals.heart_rate !== null">次 / 分</small></strong></div><div><span>血氧</span><strong>{{ episode.vitals.spo2 ?? '—' }}<small v-if="episode.vitals.spo2 !== null">%</small></strong></div></div></section>
    <section class="detail-section"><h3>实际用药与自报反应</h3><p v-if="!episode.medications.length" class="muted">这次没有填写用药信息。</p><div v-for="(medication, index) in episode.medications" :key="index" class="medication-detail"><strong>{{ medication.name }}</strong><p>{{ [medication.dose, medication.frequency].filter(Boolean).join(' · ') || '未填写用量与频率' }}</p><p v-if="medication.started_at || medication.ended_at">{{ medication.started_at || '开始未记录' }} — {{ medication.ended_at || '结束未记录' }}<template v-if="medicationReview(medication.name)?.days != null"> · {{ medicationReview(medication.name)?.days }} 天</template></p><p>{{ adherenceLabels[medication.adherence ?? 'unknown'] }} · {{ responseLabels[medication.response ?? 'unknown'] }}</p><p v-if="medication.notes">{{ medication.notes }}</p><p v-if="medicationReview(medication.name)?.note" class="small-note">{{ medicationReview(medication.name)?.note }}</p></div></section>
    <section class="detail-section"><h3>补充笔记</h3><p class="detail-notes" :class="{ muted: !episode.notes }">{{ episode.notes || '这次没有添加笔记。' }}</p></section>
    <p class="detail-updated">最近更新于 {{ new Date(episode.updated_at).toLocaleString('zh-CN') }}</p>
    <button class="button secondary" :disabled="deleting" @click="$emit('report')"><Icon name="print" :size="17" />整理这次病程的就诊摘要</button>
    <div class="detail-actions"><button class="button danger-quiet" :disabled="deleting" @click="$emit('remove')"><Icon name="trash" :size="17" />{{ deleting ? '正在删除…' : '删除记录' }}</button><button class="button primary" :disabled="deleting" @click="$emit('edit')"><Icon name="edit" :size="17" />编辑记录</button></div>
  </div>
</template>
<style scoped>
.medication-detail { padding: 14px 0; border-bottom: 1px solid var(--border); line-height: 1.8; font-size: 13px; overflow-wrap: anywhere; }
.medication-detail p { margin: 5px 0 0; }
</style>
