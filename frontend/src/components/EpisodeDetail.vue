<script setup lang="ts">
import { dateLabel, outcomeLabels, severityLabels } from '../format'
import type { Episode } from '../types'
import Icon from './Icon.vue'
defineProps<{ episode: Episode; deleting: boolean }>()
defineEmits<{ edit: []; remove: [] }>()
const safeURL = (url: string) => /^https?:\/\//i.test(url) ? url : undefined
</script>

<template>
  <div class="episode-detail">
    <div class="detail-topline"><span class="badge" :class="episode.status">{{ episode.status === 'ongoing' ? '正在记录' : '已经结束' }}</span><span class="muted">{{ episode.started_at.slice(0, 4) }} 年 · {{ dateLabel(episode.started_at) }}{{ episode.ended_at ? ` — ${dateLabel(episode.ended_at)}` : ' 起' }}</span></div>
    <h2 class="detail-title">{{ episode.chief_complaint }}</h2>
    <div class="tag-list"><span v-for="symptom in episode.symptoms" :key="symptom" class="tag">{{ symptom }}</span></div>
    <section class="analysis-box" :class="episode.analysis.level" aria-label="健康信息提示"><div class="analysis-title"><Icon :name="episode.analysis.level === 'emergency' ? 'alert' : 'info'" :size="21" /><h3>{{ episode.analysis.label }}</h3></div><p>{{ episode.analysis.summary }}</p><ul v-if="episode.analysis.reasons.length"><li v-for="reason in episode.analysis.reasons" :key="reason">{{ reason }}</li></ul><p class="analysis-disclaimer">{{ episode.analysis.disclaimer }}</p><details v-if="episode.analysis.sources.length" class="source-details"><summary>查看提示依据</summary><a v-for="source in episode.analysis.sources" :key="source.url" :href="safeURL(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }} ↗</a><small>规则版本：{{ episode.analysis.rule_version }}</small></details></section>
    <div class="detail-facts"><div><span>不适程度</span><strong>{{ severityLabels[episode.severity - 1] }} <small>{{ episode.severity }} / 5</small></strong></div><div><span>目前变化</span><strong>{{ outcomeLabels[episode.outcome] }}</strong></div></div>
    <section class="detail-section"><h3><Icon name="pulse" :size="18" />手动测量记录</h3><div class="detail-vitals"><div><span>体温</span><strong>{{ episode.vitals.temperature ?? '—' }}<small v-if="episode.vitals.temperature !== null">°C</small></strong></div><div><span>心率</span><strong>{{ episode.vitals.heart_rate ?? '—' }}<small v-if="episode.vitals.heart_rate !== null">次 / 分</small></strong></div><div><span>血氧</span><strong>{{ episode.vitals.spo2 ?? '—' }}<small v-if="episode.vitals.spo2 !== null">%</small></strong></div></div></section>
    <section class="detail-section"><h3>用药记录</h3><p v-if="!episode.medications.length" class="muted">这次没有填写用药信息。</p><div v-for="(medication, index) in episode.medications" :key="index" class="detail-medication"><strong>{{ medication.name }}</strong><span>{{ [medication.dose, medication.frequency].filter(Boolean).join(' · ') || '未填写用量与频率' }}</span></div></section>
    <section class="detail-section"><h3>补充笔记</h3><p class="detail-notes" :class="{ muted: !episode.notes }">{{ episode.notes || '这次没有添加笔记。' }}</p></section>
    <p class="detail-updated">最近更新于 {{ new Date(episode.updated_at).toLocaleString('zh-CN') }}</p>
    <div class="detail-actions"><button class="button danger-quiet" :disabled="deleting" @click="$emit('remove')"><Icon name="trash" :size="17" />{{ deleting ? '正在删除…' : '删除记录' }}</button><button class="button primary" :disabled="deleting" @click="$emit('edit')"><Icon name="edit" :size="17" />编辑记录</button></div>
  </div>
</template>
