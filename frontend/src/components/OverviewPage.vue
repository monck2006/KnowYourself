<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Episode, HealthContext, ObservationMetric, Overview, User } from '../types'
import { api } from '../api'
import { dateLabel } from '../format'
import { metrics, sourceLabels } from '../healthLabels'
import Icon from './Icon.vue'
const props = defineProps<{ user: User; overview: Overview | null; episodes: Episode[]; loading: boolean }>()
defineEmits<{ open: [episode: Episode]; create: []; navigate: [page: 'consultation' | 'history' | 'health' | 'knowledge'] }>()
const ongoing = computed(() => props.episodes.filter(item => item.status === 'ongoing').sort((a, b) => b.started_at.localeCompare(a.started_at)).slice(0, 3))
const context = ref<HealthContext | null>(null), contextError = ref(''), contextLoading = ref(false)
const latest = computed(() => Object.values(context.value?.observations.latest ?? {}).sort((a, b) => b.measured_at.localeCompare(a.measured_at)).slice(0, 4))
const priorityLabels = { now: '立即处理', today: '今天安排', observe: '继续观察' }
let active = true, generation = 0
async function loadContext() {
  const request = ++generation
  contextLoading.value = true; contextError.value = ''
  try { const result = await api.healthContext(); if (active && request === generation) context.value = result }
  catch (reason) { if (active && request === generation) contextError.value = reason instanceof Error ? reason.message : '健康摘要暂时无法读取。' }
  finally { if (active && request === generation) contextLoading.value = false }
}
watch(() => props.episodes, () => { void loadContext() })
onMounted(() => { void loadContext() })
onBeforeUnmount(() => { active = false; generation++ })
</script>

<template>
  <div class="overview-workbench">
    <section class="page-heading"><div><span class="eyebrow">个人健康工作台</span><h1>健康总览</h1><p>{{ user.display_name }}，在这里梳理当前不适，跟进病程与身体变化。</p></div><button class="text-button" @click="$emit('navigate', 'history')">查看完整病程<Icon name="arrow" :size="16" /></button></section>
    <section class="consultation-entry" aria-labelledby="consultation-entry-title"><div class="entry-icon"><Icon name="pulse" :size="28" /></div><div class="entry-copy"><span>从当前需要出发</span><h2 id="consultation-entry-title">把症状讲清楚，让下一步更有依据。</h2><p>结合这次症状、过去病程和真实测量，逐步补全信息，整理就诊前需要了解的事。</p><div class="entry-actions"><button class="button primary" @click="$emit('navigate', 'consultation')">进入问诊工作区<Icon name="arrow" :size="18" /></button><button class="text-button" @click="$emit('create')">直接记录病程</button></div></div><ol class="care-flow" aria-label="问诊流程"><li><span>01</span>描述当前症状</li><li><span>02</span>补充病程与用药</li><li><span>03</span>比较测量与历史</li><li><span>04</span>整理下一步与就诊摘要</li></ol></section>
    <dl class="overview-status"><div><dt>正在持续的病程</dt><dd>{{ overview?.ongoing_count ?? '—' }}<small>条</small></dd></div><div><dt>累计病程记录</dt><dd>{{ overview?.episode_count ?? '—' }}<small>条</small></dd></div><div><dt>近 30 天测量</dt><dd>{{ context?.observations.total ?? '—' }}<small>条</small></dd></div><div><dt>个人健康档案</dt><dd class="status-text">{{ context ? context.profile.version ? '已建立' : '待完善' : '读取中' }}</dd></div></dl>
    <div class="overview-columns-workbench">
      <div class="overview-main-column">
        <section class="panel workbench-section"><header class="section-heading"><div><span class="section-kicker">当前关注</span><h2>正在跟进的病程</h2></div><span class="section-total">{{ overview?.ongoing_count ?? 0 }} 条持续中</span></header><p v-if="loading && !overview" class="overview-empty" role="status">正在读取病程…</p><div v-else-if="!ongoing.length" class="overview-empty"><Icon name="check" :size="28" /><h3>{{ overview?.episode_count ? '目前没有持续中的病程' : '还没有病程记录' }}</h3><p>出现新的身体变化时，记下开始时间、症状和实际用药。</p><button class="button secondary small" @click="$emit('create')">记录一次病程</button></div><article v-for="episode in ongoing" :key="episode.id" class="ongoing-row" :class="episode.analysis.level"><div class="ongoing-heading"><h3>{{ episode.chief_complaint }}</h3><span class="badge" :class="episode.status">持续中</span></div><p class="ongoing-date">{{ dateLabel(episode.started_at) }} 开始<template v-if="episode.analysis.duration_days != null"> · 已持续 {{ episode.analysis.duration_days }} 天</template></p><p class="ongoing-summary">{{ episode.analysis.summary }}</p><div v-if="episode.analysis.action_plan?.[0]" class="next-action"><span>{{ priorityLabels[episode.analysis.action_plan[0].priority] }}</span><div><strong>{{ episode.analysis.action_plan[0].title }}</strong><p>{{ episode.analysis.action_plan[0].detail }}</p></div></div><button class="text-button" @click="$emit('open', episode)">查看完整病程与下一步<Icon name="arrow" :size="15" /></button></article></section>
        <section class="panel workbench-section recent-section"><header class="section-heading"><div><span class="section-kicker">连续记录</span><h2>最近病程</h2></div><button class="text-button" @click="$emit('navigate', 'history')">全部记录</button></header><p v-if="!overview?.recent_episodes.length" class="overview-empty compact">你的症状、用药和恢复经过，将按时间保存在这里。</p><button v-for="episode in overview?.recent_episodes ?? []" :key="episode.id" class="overview-record" @click="$emit('open', episode)"><span class="record-day"><strong>{{ episode.started_at.slice(8, 10) }}</strong><small>{{ Number(episode.started_at.slice(5, 7)) }} 月</small></span><span class="record-copy"><strong>{{ episode.chief_complaint }}</strong><small>{{ episode.symptoms.slice(0, 3).join(' · ') || '未填写症状标签' }}</small></span><span class="badge" :class="episode.status">{{ episode.status === 'ongoing' ? '持续中' : '已结束' }}</span><Icon name="chevron" :size="16" /></button></section>
      </div>
      <aside class="panel personal-health-summary" aria-label="个人健康摘要"><section class="summary-section"><header class="section-heading"><div><span class="section-kicker">真实测量</span><h2>最近身体数据</h2></div><Icon name="pulse" :size="20" /></header><p v-if="contextLoading && !context" class="summary-empty" role="status">正在读取健康数据…</p><div v-else-if="contextError" class="summary-empty" role="alert"><p>{{ contextError }}</p><button class="text-button" @click="loadContext">重新读取</button></div><p v-else-if="!latest.length" class="summary-empty">尚无测量记录。可以连接健康设备，或手动记录实测值。</p><div v-for="reading in latest" :key="reading.id" class="latest-reading"><div><span>{{ metrics[reading.metric as ObservationMetric]?.label || reading.metric }}</span><strong>{{ reading.value }}<small>{{ metrics[reading.metric as ObservationMetric]?.displayUnit || reading.unit }}</small></strong></div><p>{{ sourceLabels[reading.source] || reading.source }}<br /><time :datetime="reading.measured_at">{{ new Date(reading.measured_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }}</time></p></div><button class="text-button" @click="$emit('navigate', 'health')">查看测量与连接设备<Icon name="arrow" :size="15" /></button></section>
        <section class="summary-section"><header class="section-heading"><h2>健康档案摘要</h2><Icon name="user" :size="19" /></header><dl v-if="context" class="profile-summary"><div><dt>出生年份</dt><dd>{{ context.profile.birth_year || '未填写' }}</dd></div><div><dt>既往慢性病</dt><dd>{{ context.profile.chronic_conditions.join('、') || '未填写' }}</dd></div><div><dt>家族病史</dt><dd>{{ context.profile.family_history.join('、') || '未填写' }}</dd></div><div><dt>所在区域</dt><dd>{{ context.profile.region.label || '未选择' }}</dd></div></dl><p v-else class="summary-empty">完善既往情况后，病程分析会结合你的个人健康背景。</p><button class="text-button" @click="$emit('navigate', 'health')">管理健康档案<Icon name="arrow" :size="15" /></button></section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.overview-workbench { min-width: 0; overflow-wrap: anywhere; }
.consultation-entry { display: flex; align-items: flex-start; gap: 20px; padding: 28px; border: 1px solid #c8dddf; border-radius: 12px; background: linear-gradient(110deg, #edf6f7, #f8fbfc); }
.entry-icon { display: grid; place-items: center; height: 54px; width: 54px; border-radius: 12px; background: #d9ebee; color: var(--primary-deep); flex-shrink: 0; }
.entry-copy { flex: 1; min-width: 0; }
.entry-copy > span { font-size: 12px; font-weight: 650; color: var(--primary); }
.entry-copy h2 { font-size: 23px; margin: 7px 0 10px; line-height: 1.5; }
.entry-copy > p { font-size: 14px; color: var(--ink-soft); line-height: 1.8; max-width: 620px; }
.entry-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 20px; margin-top: 20px; }
.care-flow { display: grid; gap: 15px; list-style: none; margin: 5px 0 0; padding: 0 0 0 24px; border-left: 1px solid #cbdee2; font-size: 12px; color: var(--ink-soft); flex-shrink: 0; }
.care-flow li { display: flex; align-items: center; gap: 9px; }
.care-flow span { color: var(--primary); font-size: 11px; font-weight: 700; }
.overview-status { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 22px 0; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 0; }
.overview-status > div { padding: 0 24px; border-right: 1px solid var(--border); }
.overview-status > div:last-child { border: 0; }
.overview-status dt { color: var(--muted); font-size: 12px; }
.overview-status dd { display: flex; align-items: baseline; gap: 8px; margin: 9px 0 0; font-size: 28px; font-weight: 650; line-height: 1.2; }
.overview-status dd small { font-size: 12px; color: var(--muted); font-weight: 400; }
.overview-status dd.status-text { font-size: 18px; padding-top: 6px; }
.overview-columns-workbench { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(280px, 1fr); gap: 22px; align-items: start; }
.overview-main-column { display: grid; gap: 22px; min-width: 0; }
.workbench-section { padding: 24px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.section-heading h2 { margin: 0; font-size: 17px; }
.section-kicker { display: block; margin-bottom: 6px; color: var(--muted); font-size: 11px; letter-spacing: .05em; }
.section-heading > svg { color: var(--primary); }
.section-total { color: var(--muted); font-size: 12px; }
.ongoing-row { padding: 22px 0; border-bottom: 1px solid var(--border); }
.ongoing-row:last-child { padding-bottom: 0; border: 0; }
.ongoing-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ongoing-heading h3 { font-size: 16px; margin: 0; line-height: 1.6; }
.ongoing-date { font-size: 12px; color: var(--muted); margin: 7px 0 12px; }
.ongoing-summary { font-size: 13px; color: var(--ink-soft); line-height: 1.8; }
.next-action { display: flex; align-items: flex-start; gap: 12px; margin: 16px 0; padding: 14px; border-left: 3px solid var(--primary); background: var(--primary-tint); font-size: 13px; }
.next-action > span { font-size: 11px; color: var(--primary-deep); flex-shrink: 0; padding-top: 2px; }
.next-action p { margin: 5px 0 0; color: var(--ink-soft); line-height: 1.8; }
.ongoing-row.emergency .next-action { border-color: var(--danger); background: var(--danger-tint); }
.ongoing-row.emergency .next-action > span { color: var(--danger); }
.overview-record { display: flex; align-items: center; gap: 14px; width: 100%; text-align: left; padding: 18px 0; border-bottom: 1px solid var(--border); }
.overview-record:last-child { border: 0; padding-bottom: 0; }
.record-day { display: grid; text-align: center; width: 38px; flex-shrink: 0; gap: 4px; }
.record-day strong { font-size: 22px; font-weight: 500; }.record-day small { color: var(--muted); font-size: 11px; }
.record-copy { display: grid; gap: 7px; flex: 1; min-width: 0; }.record-copy strong { font-size: 14px; }.record-copy small { font-size: 12px; color: var(--muted); line-height: 1.6; }
.personal-health-summary { min-width: 0; }
.summary-section { padding: 24px; border-bottom: 1px solid var(--border); }.summary-section:last-child { border: 0; }
.summary-section > .text-button { margin-top: 20px; font-size: 12px; }
.latest-reading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 17px 0; border-bottom: 1px solid var(--border-faint); }.latest-reading > div { display: grid; gap: 7px; }.latest-reading > div > span { font-size: 12px; color: var(--muted); }.latest-reading strong { font-size: 24px; font-weight: 600; }.latest-reading strong small { margin-left: 6px; font-size: 11px; color: var(--muted); font-weight: 400; }.latest-reading > p { margin: 0; font-size: 10px; line-height: 1.8; text-align: right; color: var(--muted); }
.profile-summary { display: grid; gap: 15px; margin: 20px 0 0; font-size: 13px; }.profile-summary dt { color: var(--muted); font-size: 12px; margin-bottom: 5px; }.profile-summary dd { margin: 0; line-height: 1.7; }
.summary-empty { font-size: 13px; color: var(--muted); line-height: 1.9; margin-top: 20px; }
.overview-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; padding: 32px 8px; color: var(--muted); font-size: 13px; line-height: 1.8; }.overview-empty h3 { font-size: 15px; color: var(--ink); margin: 0; }.overview-empty p { margin: 0 0 8px; }.overview-empty.compact { padding: 24px 8px 8px; }
@media (max-width: 1180px) { .care-flow { display: none; } .overview-columns-workbench { grid-template-columns: minmax(0, 1.6fr) minmax(260px, 1fr); } }
@media (max-width: 760px) { .overview-columns-workbench { grid-template-columns: minmax(0, 1fr); }.consultation-entry { padding: 22px; gap: 15px; }.entry-icon { display: none; }.entry-copy h2 { font-size: 21px; }.overview-status { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 0; }.overview-status > div { padding: 18px 20px; border-bottom: 1px solid var(--border); }.overview-status > div:nth-child(2) { border-right: 0; }.overview-status > div:nth-child(3) { border-bottom: 0; }.workbench-section, .summary-section { padding: 20px; } }
@media (max-width: 420px) { .overview-record { gap: 10px; }.record-day { display: none; }.entry-actions { gap: 16px; }.entry-actions > .button { width: 100%; }.next-action { flex-direction: column; gap: 8px; } }
</style>
