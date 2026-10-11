<script setup lang="ts">
import type { Episode, ObservationMetric } from '../types'
import { dateLabel } from '../format'
import { contextLabels, metrics, sourceLabels } from '../healthLabels'
import Icon from './Icon.vue'
defineProps<{ episode: Episode }>()
const priorityLabels = { now: '立即处理', today: '今天安排', observe: '继续观察' }
function measurement(metric: string) { return metrics[metric as ObservationMetric] }
const safeURL = (url: string) => /^https?:\/\//i.test(url) ? url : undefined
</script>
<template>
  <section class="analysis-box" :class="episode.analysis.level" aria-label="这次病程的下一步">
    <div class="analysis-title"><Icon :name="episode.analysis.level === 'emergency' ? 'alert' : 'info'" :size="21" /><h3>{{ episode.analysis.label }}</h3></div><p>{{ episode.analysis.summary }}</p>
    <ol v-if="episode.analysis.action_plan?.length" class="action-plan"><li v-for="(action, index) in episode.analysis.action_plan" :key="index" :class="action.priority"><span>{{ priorityLabels[action.priority] }}</span><div><strong>{{ action.title }}</strong><p>{{ action.detail }}</p></div></li></ol>
    <ul v-else><li v-for="reason in episode.analysis.reasons" :key="reason">{{ reason }}</li></ul>
    <details class="source-details"><summary>查看判断依据与适用范围</summary><ul v-if="episode.analysis.action_plan?.length"><li v-for="reason in episode.analysis.reasons" :key="reason">{{ reason }}</li></ul><p>{{ episode.analysis.disclaimer }}</p><a v-for="source in episode.analysis.sources" :key="source.url" :href="safeURL(source.url)" target="_blank" rel="noopener noreferrer">{{ source.title }} ↗</a><small>规则版本：{{ episode.analysis.rule_version }}</small></details>
  </section>
  <section v-if="episode.analysis.history_comparison" class="detail-section">
    <h3><Icon name="book" :size="18" />与过去相似病程比较</h3>
    <p v-if="episode.analysis.history_comparison.matched_count">找到 {{ episode.analysis.history_comparison.matched_count }} 条症状相似记录。<template v-if="episode.analysis.history_comparison.typical_duration_days != null">已结束病程典型时长 {{ episode.analysis.history_comparison.typical_duration_days }} 天<template v-if="episode.analysis.history_comparison.range_days">，范围 {{ episode.analysis.history_comparison.range_days.join('–') }} 天</template>。</template></p><p v-else class="muted">还没有可比较的相似病程；本次记录会成为以后的回顾依据。</p>
    <div v-for="record in episode.analysis.history_comparison.records" :key="record.id" class="context-reading"><strong>{{ dateLabel(record.started_at) }} · {{ record.duration_days }} 天</strong><span>当时用药：{{ record.medications.join('、') || '未记录' }}</span></div><p class="small-note">症状相似不表示病因相同，过去用药仅作记录比较。</p>
  </section>
  <section v-if="episode.analysis.device_context" class="detail-section">
    <h3><Icon name="pulse" :size="18" />本次分析使用的测量与个人基线</h3>
    <div v-for="reading in episode.analysis.device_context.readings" :key="reading.id" class="context-reading"><strong>{{ measurement(reading.metric)?.label || reading.metric }} {{ reading.value }} {{ measurement(reading.metric)?.displayUnit || reading.unit }}</strong><span>{{ sourceLabels[reading.source] || reading.source }} · {{ contextLabels[reading.context] || reading.context }} · {{ new Date(reading.measured_at).toLocaleString('zh-CN') }}</span></div>
    <p v-if="!episode.analysis.device_context.readings.length" class="muted">本次分析窗口内暂无测量：进行中取最近24小时，已结束取最后一天。</p><ul v-if="episode.analysis.device_context.deviations.length"><li v-for="item in episode.analysis.device_context.deviations" :key="item">{{ item }}</li></ul><p class="small-note">{{ episode.analysis.device_context.baseline_note }}</p>
  </section>
  <section v-if="episode.analysis.profile_context && (episode.analysis.profile_context.chronic_conditions.length || episode.analysis.profile_context.family_history.length)" class="detail-section"><h3>结合你的健康档案</h3><p v-if="episode.analysis.profile_context.chronic_conditions.length">既往慢性病：{{ episode.analysis.profile_context.chronic_conditions.join('、') }}</p><p v-if="episode.analysis.profile_context.family_history.length">家族病史：{{ episode.analysis.profile_context.family_history.join('、') }}</p></section>
  <section v-if="episode.analysis.regional_context && (episode.disease_category === 'infectious' || (episode.analysis.regional_context.enabled && episode.analysis.regional_context.signals.length > 0))" class="detail-section"><h3>所在区域的近期症状信号</h3><p v-if="episode.analysis.regional_context.region_label">{{ episode.analysis.regional_context.region_label }} · 近 {{ episode.analysis.regional_context.window_days }} 天</p><p v-for="signal in episode.analysis.regional_context.signals" :key="signal.cluster"><strong>{{ signal.label }} · {{ signal.people_band }} 人</strong><br />{{ signal.description }}</p><p v-if="episode.analysis.regional_context.status === 'disabled'" class="muted">尚未参与区域汇总，可在健康档案中设置地区并自愿开启。</p><p v-else-if="episode.analysis.regional_context.status === 'insufficient'" class="muted">尚未达到每组至少 5 位不同参与者的展示条件。</p></section>
</template>
<style scoped>
.action-plan { list-style: none; padding: 0; display: grid; gap: 14px; margin: 20px 0 12px; }
.action-plan li { display: flex; gap: 12px; align-items: flex-start; }
.action-plan li > span { flex-shrink: 0; padding: 3px 7px; border-radius: 5px; background: var(--primary-soft); color: var(--primary-deep); font-size: 11px; }
.action-plan li.now > span { background: var(--danger-soft); color: var(--danger-strong); }
.action-plan li.today > span { background: var(--amber-soft); color: var(--amber-strong); }
.action-plan li p { margin: 4px 0 0; }
.context-reading { display: flex; flex-direction: column; gap: 5px; padding: 12px 0; border-bottom: 1px solid var(--border); font-size: 13px; line-height: 1.8; overflow-wrap: anywhere; }
.context-reading span { color: var(--muted); font-size: 12px; }
</style>
