<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ApiError, api } from '../api'
import { toEpisodeInput } from '../episodeInput'
import { dateLabel } from '../format'
import type { AnswerValue, Assessment, Episode, ModelExplanation } from '../types'
import Icon from './Icon.vue'
import { sourceLabels } from '../healthLabels'

const props = defineProps<{ episodes: Episode[] }>()
const emit = defineEmits<{ create: []; open: [episode: Episode]; changed: [] }>()
const selectedId = ref('')
const current = ref<Episode | null>(null)
const assessment = ref<Assessment | null>(null)
const answers = ref<Record<string, AnswerValue>>({})
const tab = ref<'questions' | 'evidence' | 'preparation'>('questions')
const busy = ref(false), saving = ref(false), generating = ref(false)
const error = ref(''), conflict = ref(false), consent = ref(false)
const explanation = ref<ModelExplanation | null>(null)
const evidencePanel = ref<HTMLElement>()
let requestId = 0
const ordered = computed(() => [...props.episodes].sort((a, b) => Number(b.status === 'ongoing') - Number(a.status === 'ongoing') || b.started_at.localeCompare(a.started_at)))
const answered = computed(() => assessment.value?.questions.filter(q => answers.value[q.id] != null).length ?? 0)
const dirty = computed(() => !!current.value && JSON.stringify(answerList()) !== JSON.stringify([...(current.value.assessment_answers ?? [])].sort((a, b) => a.question_id.localeCompare(b.question_id))))
const immediateDanger = computed(() => ['breathing_difficulty', 'chest_pain', 'confusion'].some(id => answers.value[id] === 'yes'))
const labels = { present: '已记录', absent: '自述否认', unknown: '待补充', conflicting: '信息有矛盾' }
const priority = { now: '立即处理', today: '今天安排', observe: '持续观察' }
function answerList() { return Object.entries(answers.value).sort(([a], [b]) => a.localeCompare(b)).map(([question_id, answer]) => ({ question_id, answer })) }
function message(e: unknown) { return e instanceof Error ? e.message : '读取未完成，请重试。' }
function displayValue(value: unknown): string {
  const words: Record<string, string> = { yes: '是', no: '否', unknown: '不清楚', ongoing: '持续中', ended: '已结束', improving: '有所好转', resolved: '已恢复', worsened: '有所加重', unchanged: '无明显变化', as_recorded: '按记录执行', missed: '有漏用' }
  if (value == null) return '未提供'
  if (Array.isArray(value)) return value.map(displayValue).join('、')
  if (typeof value === 'object') {
    const item = value as Record<string, unknown>
    if ('duration_days' in item) return `已记录第 ${item.duration_days} 天 · ${displayValue(item.status)} · 变化：${item.outcome === 'ongoing' ? '尚未补充' : displayValue(item.outcome)}`
    if ('name' in item) return `${item.name} · ${item.started_at ? `${item.started_at} 开始` : '开始日期未填'} · 自述变化：${displayValue(item.response)} · ${displayValue(item.adherence)}`
    return Object.values(item).map(displayValue).join(' · ')
  }
  return words[String(value)] ?? String(value)
}
async function load() {
  if (!selectedId.value) return
  const id = ++requestId, selected = selectedId.value
  busy.value = true; error.value = ''; conflict.value = false; explanation.value = null; consent.value = false
  try {
    const [episode, result] = await Promise.all([api.episode(selected), api.assessment(selected)])
    if (id !== requestId) return
    if (episode.version !== result.episode_version) throw new Error('病程刚刚发生更新，请重新读取。')
    current.value = episode; assessment.value = result
    answers.value = Object.fromEntries((episode.assessment_answers ?? []).map(item => [item.question_id, item.answer]))
  } catch (e) { if (id === requestId) { current.value = null; assessment.value = null; error.value = message(e) } }
  finally { if (id === requestId) busy.value = false }
}
function selectCase(event: Event) {
  const select = event.target as HTMLSelectElement
  if (dirty.value && !window.confirm('这次补问尚未保存，确定切换病程吗？')) { select.value = selectedId.value; return }
  selectedId.value = select.value
}
async function saveAnswers() {
  if (!current.value || saving.value || generating.value) return
  const id = ++requestId
  saving.value = true; error.value = ''; explanation.value = null
  try {
    const saved = await api.update(current.value.id, { ...toEpisodeInput(current.value), assessment_answers: answerList() }, current.value.version)
    const result = await api.assessment(saved.id)
    if (id !== requestId) return
    current.value = saved; assessment.value = result; emit('changed')
  } catch (e) { if (id === requestId) { error.value = message(e); conflict.value = e instanceof ApiError && e.status === 409 } }
  finally { if (id === requestId) saving.value = false }
}
async function generate() {
  if (!current.value || !assessment.value || generating.value || dirty.value) return
  const id = requestId
  generating.value = true; error.value = ''; explanation.value = null
  try {
    const result = await api.explainAssessment(current.value.id, current.value.version, consent.value)
    if (id === requestId) { assessment.value = result.assessment; explanation.value = result.explanation }
  } catch (e) { if (id === requestId) { error.value = message(e); conflict.value = e instanceof ApiError && e.status === 409 } }
  finally { if (id === requestId) generating.value = false }
}
function points(values: { value: number }[]) {
  const min = Math.min(...values.map(p => p.value)), max = Math.max(...values.map(p => p.value))
  return values.map((p, i) => `${12 + i * 276 / Math.max(1, values.length - 1)},${63 - (p.value - min) * 48 / Math.max(1, max - min)}`).join(' ')
}
function evidenceName(id: string) { return assessment.value?.evidence.find(item => item.id === id)?.label || id }
function knowledgeName(id: string) { return assessment.value?.knowledge.find(item => item.id === id)?.title || id }
async function showEvidence() { tab.value = 'evidence'; await nextTick(); evidencePanel.value?.focus(); evidencePanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
watch(() => props.episodes, () => {
  if (!selectedId.value || !props.episodes.some(item => item.id === selectedId.value)) selectedId.value = ordered.value[0]?.id ?? ''
}, { immediate: true })
watch(selectedId, () => { current.value = null; assessment.value = null; tab.value = 'questions'; void load() }, { immediate: true })
</script>

<template>
  <section class="page-heading"><div><span class="eyebrow">CARE WORKSPACE</span><h1>问诊工作区</h1><p>补齐关键线索，跟踪真实变化，把本次就诊准备清楚。</p></div><button class="button primary" @click="emit('create')"><Icon name="plus" :size="18" />新建病程</button></section>
  <section v-if="!episodes.length" class="panel consultation-empty"><Icon name="book" :size="36" /><h2>从你这次的不适开始</h2><p>先记录症状、起始时间和实际用药。系统将据此选择补问，并关联你自己的测量与资料库。</p><button class="button primary" @click="emit('create')">记录本次症状<Icon name="arrow" :size="17" /></button></section>
  <template v-else>
    <div class="case-selector"><label for="care-case">当前病程</label><select id="care-case" :value="selectedId" :disabled="saving || generating" @change="selectCase"><option v-for="item in ordered" :key="item.id" :value="item.id">{{ item.chief_complaint }} · {{ dateLabel(item.started_at) }} · {{ item.status === 'ongoing' ? '持续中' : '已结束' }}</option></select><button class="icon-button" aria-label="重新读取问诊评估" :disabled="busy || saving || generating" @click="load"><Icon name="refresh" :class="{ spinning: busy }" /></button></div>
    <div v-if="error" class="notice error" role="alert">{{ error }}<button class="text-button" :disabled="saving || generating" @click="load">{{ conflict ? '重新载入最新记录' : '重试读取' }}</button></div>
    <p v-if="busy" class="care-loading" role="status">正在关联本次病程、测量和本地知识库…</p>
    <template v-else-if="assessment && current">
      <div v-if="immediateDanger && dirty" class="notice error" role="alert"><Icon name="alert" /><span>你刚确认了危险信号。若正在出现严重呼吸困难、持续胸痛或突然意识异常，请立即拨打 120 或前往急诊，不要等待保存或模型结果。</span></div>
      <section class="care-priority" :class="assessment.triage.level" aria-label="当前处理优先级"><span class="care-priority-icon"><Icon :name="assessment.triage.level === 'emergency' ? 'alert' : 'shield'" :size="25" /></span><div><span class="care-kicker">当前处理优先级 · {{ assessment.triage.label }}</span><h2>{{ assessment.triage.summary }}</h2><p>{{ current.chief_complaint }} · {{ dateLabel(current.started_at) }} 起 · {{ assessment.rule_version }}</p></div><button class="button secondary small" @click="emit('open', current)">编辑病程</button></section>
      <div class="care-layout">
        <section class="panel care-main">
          <div class="care-tabs" role="tablist" aria-label="问诊步骤"><button id="care-tab-questions" role="tab" :aria-selected="tab === 'questions'" aria-controls="care-panel-questions" :class="{ active: tab === 'questions' }" @click="tab = 'questions'"><span>01</span>关键补问<small>{{ answered }}/{{ assessment.questions.length }}</small></button><button id="care-tab-evidence" role="tab" :aria-selected="tab === 'evidence'" aria-controls="care-panel-evidence" :class="{ active: tab === 'evidence' }" @click="tab = 'evidence'"><span>02</span>数据与依据</button><button id="care-tab-preparation" role="tab" :aria-selected="tab === 'preparation'" aria-controls="care-panel-preparation" :class="{ active: tab === 'preparation' }" @click="tab = 'preparation'"><span>03</span>就诊准备</button></div>
          <div v-if="tab === 'questions'" id="care-panel-questions" class="care-section" role="tabpanel" aria-labelledby="care-tab-questions">
            <div class="section-intro"><h2>把影响下一步的问题问清楚</h2><p>按本次症状选择问题。没有回答的项目会保留为未知；回答有变化时可再次更新。</p></div>
            <form @submit.prevent="saveAnswers"><fieldset :disabled="saving || generating || conflict"><div v-for="q in assessment.questions" :key="q.id" class="care-question" role="group" :aria-labelledby="`question-${q.id}`"><div><strong :id="`question-${q.id}`">{{ q.text }}</strong><p>{{ q.reason }}</p></div><div class="answer-options"><label v-for="option in q.options" :key="option.value" :class="{ selected: answers[q.id] === option.value }"><input v-model="answers[q.id]" type="radio" :name="q.id" :value="option.value" />{{ option.label }}</label></div></div></fieldset><div class="care-save"><span>{{ dirty ? '有尚未保存的回答' : '回答已与本次病程关联' }}</span><button class="button primary" :disabled="saving || generating || conflict || !dirty">{{ saving ? '正在保存并重评…' : '保存回答并更新评估' }}</button></div></form>
          </div>
          <div v-else-if="tab === 'evidence'" id="care-panel-evidence" ref="evidencePanel" class="care-section" role="tabpanel" aria-labelledby="care-tab-evidence" tabindex="-1">
            <div class="section-intro"><h2>每条线索，都有出处</h2><p>本人记录、设备读数和科普资料分别列出。信息不足或矛盾会明确保留。</p></div>
            <div class="evidence-list"><div v-for="item in assessment.evidence" :key="item.id" class="evidence-row"><span class="evidence-state" :class="item.state">{{ labels[item.state] }}</span><div><strong>{{ item.label }}</strong><p>{{ displayValue(item.value) }}</p><small>{{ sourceLabels[item.source] || item.source }}<template v-if="item.measured_at"> · {{ new Date(item.measured_at).toLocaleString('zh-CN') }}</template></small></div></div></div>
            <h3 class="care-subheading">本地知识库检索 · {{ assessment.knowledge.length }} 条相关资料</h3><p v-if="!assessment.knowledge.length" class="care-muted">未检索到对应资料。这不代表排除了任何疾病。</p><details v-for="item in assessment.knowledge" :key="item.id" class="care-source"><summary><span>{{ item.title }}<small>{{ item.source }} · {{ item.published_at || '原文未标日期' }}</small></span><Icon name="chevron" :size="16" /></summary><p>{{ item.excerpt }}</p><small>匹配：{{ item.matched_terms.join('、') }} · 入库：{{ item.imported_at ? new Date(item.imported_at).toLocaleDateString('zh-CN') : '未标注' }}</small><a :href="item.source_url" target="_blank" rel="noopener noreferrer">阅读原始资料<Icon name="arrow" :size="14" /></a></details>
          </div>
          <div v-else id="care-panel-preparation" class="care-section" role="tabpanel" aria-labelledby="care-tab-preparation"><div class="section-intro"><h2>带着完整线索去就诊</h2><p>先核对记录，再从病程详情生成可打印的就诊摘要。</p></div><ol class="visit-checklist"><li><strong>症状经过</strong><p>{{ current.chief_complaint }}；{{ current.symptoms.join('、') || '尚未填写症状标签' }}；{{ dateLabel(current.started_at) }} 起，{{ current.status === 'ongoing' ? '目前仍在持续' : '已结束' }}。</p></li><li><strong>实际用药</strong><p>{{ current.medications.length ? current.medications.map(m => m.name).join('、') : '没有填写用药；请核对是否确实未使用。' }}</p></li><li><strong>需要进一步核实</strong><p v-for="q in assessment.questions.filter(q => !answers[q.id] || answers[q.id] === 'unknown')" :key="q.id">{{ q.text }}</p><p v-if="assessment.questions.every(q => answers[q.id] && answers[q.id] !== 'unknown')">补问已填写。仍需结合检查核实病因。</p></li></ol><button class="button secondary" @click="emit('open', current)"><Icon name="book" :size="17" />打开病程与就诊摘要</button></div>
        </section>
        <aside class="care-aside"><section class="panel care-next"><div class="panel-heading"><h2>接下来做什么</h2><Icon name="arrow" :size="18" /></div><ol><li v-for="(action, index) in assessment.triage.action_plan" :key="index"><span :class="action.priority">{{ priority[action.priority] }}</span><strong>{{ action.title }}</strong><p>{{ action.detail }}</p></li></ol><div class="check-in"><Icon name="clock" :size="17" /><p>{{ assessment.monitoring.next_check_in }}</p></div><details><summary>哪些变化需要及时升级处理</summary><ul><li v-for="item in assessment.monitoring.escalation_signs" :key="item">{{ item }}</li></ul></details></section><section v-if="assessment.medication_checks.length" class="panel care-medications"><h2>用药核对</h2><div v-for="(item, i) in assessment.medication_checks" :key="i"><strong>{{ item.name }}</strong><p>{{ item.detail }}</p></div></section></aside>
      </div>
      <section class="panel care-trends"><div class="panel-heading"><div><h2>本次病程的测量趋势</h2><p class="care-muted">最近七天内已记录日期的摘要；缺失日期不补零，测量来源可逐项核对。</p></div><Icon name="pulse" /></div><div v-if="assessment.monitoring.metrics.length" class="trend-grid"><article v-for="(series, index) in assessment.monitoring.metrics" :key="index" class="trend-item"><div><h3>{{ series.label }}</h3><strong>{{ series.points.at(-1)?.value }} <small>{{ series.unit }}</small></strong></div><svg v-if="series.points.length > 1" viewBox="0 0 300 80" role="img" :aria-label="`${series.label}，${series.points.length} 个记录日期，详见下方数据`"><line x1="12" y1="73" x2="288" y2="73" stroke="var(--border)" /><polyline :points="points(series.points)" fill="none" stroke="currentColor" stroke-width="2.5" /></svg><p v-else class="care-muted">目前仅有一个记录日期，继续记录后可比较变化。</p><p class="trend-note">{{ series.note }}</p><details><summary>查看日期、数值与来源</summary><table><thead><tr><th>日期</th><th>数值</th><th>来源</th></tr></thead><tbody><tr v-for="(point, i) in series.points" :key="i"><td>{{ point.at.slice(0, 10) }}</td><td>{{ point.value }}</td><td>{{ sourceLabels[point.source] || point.source }}</td></tr></tbody></table></details></article></div><p v-else class="care-muted">这次病程尚无可用的设备或手动测量。可在“健康档案”添加数据后重新读取。</p></section>
      <section class="panel care-model"><div class="panel-heading"><div><span class="eyebrow">EVIDENCE ASSISTANT</span><h2>让模型把已有线索讲清楚</h2></div><span class="model-status" :class="{ ready: assessment.model.status === 'ready' }">{{ assessment.model.status === 'ready' ? assessment.model.model : '模型待配置' }}</span></div><p class="care-muted">{{ assessment.model.notice }} 模型仅整理证据和就诊问题，当前处理优先级始终显示在顶部。</p><details class="model-scope"><summary>查看本次发送范围与约束</summary><p>发送当前必要的症状、补问、病程和测量事实，以及最多五篇资料片段。账户信息、姓名、位置、自由备注和整份历史不会发送。</p><p>禁止编造检查、确诊、药物处方或剂量；引用必须对应已有证据。生成失败或未通过校验时保留本地评估。</p><pre>{{ JSON.stringify(assessment.model_input, null, 2) }}</pre></details><template v-if="assessment.model.status === 'ready'"><label v-if="assessment.model.cloud" class="consent"><input v-model="consent" type="checkbox" :disabled="generating" /><span>同意本次将上述必要健康信息发送到 {{ assessment.model.provider }} 生成解释。</span></label><button class="button primary" :disabled="generating || saving || dirty || assessment.triage.level === 'emergency' || (assessment.model.cloud && !consent)" @click="generate"><Icon name="pulse" :size="17" />{{ generating ? '正在整理证据…' : '生成本次证据解释' }}</button><p v-if="dirty" class="care-muted">请先保存补问，使解释基于最新回答。</p><p v-if="assessment.triage.level === 'emergency'" class="care-muted">存在紧急信号，请先处理；此时暂停模型生成。</p></template><div v-if="explanation" class="model-result" role="status"><p :class="{ 'care-muted': explanation.status !== 'generated' }">{{ explanation.notice }}</p><template v-if="explanation.status === 'generated'"><article v-for="(item, index) in explanation.explanations" :key="index"><p>{{ item.text }}</p><div class="citation-links"><button v-for="id in item.evidence_ids" :key="id" @click="showEvidence">{{ evidenceName(id) }}</button><button v-for="id in item.knowledge_ids" :key="id" @click="showEvidence">{{ knowledgeName(id) }}</button></div></article><h3 v-if="explanation.uncertainties?.length">目前还不清楚</h3><ul><li v-for="text in explanation.uncertainties" :key="text">{{ text }}</li></ul><h3 v-if="explanation.consultation_notes?.length">就诊时可核实</h3><ul><li v-for="text in explanation.consultation_notes" :key="text">{{ text }}</li></ul></template></div></section>
      <details class="care-limitations"><summary>本次评估范围与资料局限</summary><ul><li v-for="text in assessment.limitations" :key="text">{{ text }}</li></ul><small>评估时间：{{ new Date(assessment.generated_at).toLocaleString('zh-CN') }}</small></details>
    </template>
  </template>
</template>

<style scoped>
.consultation-empty { padding: 52px 28px; text-align: center; }.consultation-empty > svg { color: var(--primary); }.consultation-empty p { color: var(--muted); max-width: 520px; margin: 16px auto 24px; line-height: 1.8; }.consultation-empty .button { margin: auto; }
.case-selector { display: flex; gap: 14px; align-items: center; margin-bottom: 20px; }.case-selector label { font-size: 13px; white-space: nowrap; color: var(--muted); }.case-selector select { flex: 1; min-width: 0; }.care-loading { padding: 60px 20px; text-align: center; color: var(--muted); }
.care-priority { display: flex; align-items: center; gap: 16px; padding: 22px; background: var(--primary-tint); border: 1px solid var(--border); border-left: 4px solid var(--primary); border-radius: 12px; margin-bottom: 24px; }.care-priority.attention { background: #fffbeb; border-left-color: #a16207; }.care-priority.emergency { background: #fff1f2; border-left-color: #be123c; }.care-priority-icon { color: var(--primary-deep); flex-shrink: 0; }.care-priority > div { flex: 1; min-width: 0; }.care-kicker { font-size: 12px; font-weight: 650; }.care-priority h2 { font-size: 17px; line-height: 1.7; margin: 6px 0; }.care-priority p { font-size: 12px; color: var(--muted); margin: 0; }.care-layout { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(270px, 1fr); gap: 22px; align-items: start; }.care-main { min-width: 0; overflow: hidden; }.care-tabs { display: flex; border-bottom: 1px solid var(--border); padding: 0 16px; background: var(--surface-soft); }.care-tabs button { display: flex; align-items: center; justify-content: center; gap: 7px; padding: 18px 10px; flex: 1; font-size: 13px; white-space: nowrap; border-bottom: 2px solid transparent; }.care-tabs button.active { color: var(--primary-deep); border-bottom-color: var(--primary); font-weight: 650; }.care-tabs button > span { font-size: 11px; color: var(--muted); }.care-tabs small { font-size: 10px; }.care-section { padding: 24px; }.section-intro h2,.care-next h2,.care-medications h2,.care-trends h2,.care-model h2 { font-size: 17px; margin: 0 0 8px; }.section-intro > p,.care-muted { font-size: 13px; color: var(--muted); line-height: 1.8; }.section-intro { margin-bottom: 8px; }.care-question { padding: 22px 0; border-bottom: 1px solid var(--border); }.care-question strong { font-size: 14px; line-height: 1.7; }.care-question p { color: var(--muted); font-size: 12px; margin: 7px 0 14px; line-height: 1.7; }.answer-options { display: flex; gap: 8px; flex-wrap: wrap; }.answer-options label { display: flex; align-items: center; gap: 7px; border: 1px solid var(--border); border-radius: 7px; padding: 8px 14px; cursor: pointer; font-size: 13px; }.answer-options label.selected { background: var(--primary-tint); border-color: var(--primary); color: var(--primary-deep); }.answer-options input { width: 14px; height: 14px; padding: 0; accent-color: var(--primary); }.care-save { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 12px; padding-top: 22px; }.care-save > span { font-size: 12px; color: var(--muted); }.care-aside { display: grid; gap: 20px; min-width: 0; }.care-next,.care-medications { padding: 22px; }.care-next ol { padding: 0; list-style: none; margin: 0; }.care-next li { display: grid; gap: 8px; padding: 16px 0; border-bottom: 1px solid var(--border); font-size: 14px; }.care-next li > span { font-size: 11px; color: var(--primary-deep); }.care-next li > span.now { color: var(--danger); }.care-next li > span.today { color: #a16207; }.care-next li > p,.care-medications p { font-size: 13px; color: var(--muted); line-height: 1.8; margin: 0; }.check-in { display: flex; gap: 9px; align-items: start; padding: 16px 0; }.check-in svg { flex-shrink: 0; margin-top: 4px; color: var(--primary); }.check-in p { margin: 0; font-size: 13px; line-height: 1.8; }.care-next details { font-size: 12px; line-height: 1.9; color: var(--muted); }.care-medications > div { padding: 14px 0; border-top: 1px solid var(--border); }.care-medications strong { font-size: 13px; }.care-trends,.care-model { margin-top: 22px; padding: 24px; }.trend-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 18px; }.trend-item { min-width: 0; padding: 18px; background: var(--surface-soft); border-radius: 8px; }.trend-item > div { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }.trend-item h3 { font-size: 13px; margin: 0; font-weight: 550; }.trend-item strong { font-size: 24px; font-variant-numeric: tabular-nums; }.trend-item small { font-size: 11px; color: var(--muted); font-weight: 400; }.trend-item svg { display: block; width: 100%; max-height: 90px; margin-top: 12px; color: var(--primary); }.trend-note { font-size: 11px; color: var(--muted); line-height: 1.8; }.trend-item details { font-size: 11px; line-height: 1.7; }.trend-item table { width: 100%; border-collapse: collapse; margin-top: 12px; }.trend-item th,.trend-item td { text-align: left; padding: 6px 3px; border-top: 1px solid var(--border); overflow-wrap: anywhere; }.evidence-row { display: flex; gap: 12px; padding: 16px 0; border-bottom: 1px solid var(--border); }.evidence-row strong { font-size: 13px; }.evidence-row p { font-size: 14px; line-height: 1.8; margin: 5px 0; overflow-wrap: anywhere; }.evidence-row small { font-size: 11px; color: var(--muted); }.evidence-state { flex-shrink: 0; font-size: 10px; border-radius: 4px; padding: 4px 6px; height: fit-content; color: var(--primary-deep); background: var(--primary-tint); }.evidence-state.unknown { color: var(--muted); background: var(--surface-soft); }.evidence-state.conflicting { color: #a16207; background: #fef3c7; }.care-subheading { font-size: 14px; margin: 28px 0 12px; }.care-source { border-top: 1px solid var(--border); padding: 16px 0; }.care-source summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: pointer; font-size: 13px; font-weight: 600; }.care-source summary small { display: block; font-weight: 400; font-size: 11px; color: var(--muted); margin-top: 7px; }.care-source p { white-space: pre-line; font-size: 13px; line-height: 1.9; }.care-source > small { font-size: 11px; color: var(--muted); }.care-source a { display: flex; align-items: center; gap: 5px; width: fit-content; font-size: 12px; color: var(--primary-deep); margin-top: 12px; }.visit-checklist { padding-left: 20px; font-size: 14px; }.visit-checklist li { padding: 12px 0; }.visit-checklist p { color: var(--muted); line-height: 1.8; font-size: 13px; }.model-status { font-size: 11px; background: var(--surface-soft); color: var(--muted); border-radius: 20px; padding: 7px 11px; overflow-wrap: anywhere; }.model-status.ready { color: var(--primary-deep); background: var(--primary-tint); }.model-scope { font-size: 12px; margin: 18px 0; line-height: 1.9; color: var(--muted); }.model-scope pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 280px; overflow: auto; background: var(--surface-soft); padding: 14px; border-radius: 8px; font-size: 11px; }.care-model .consent { margin: 18px 0; }.model-result { margin-top: 24px; border-top: 1px solid var(--border); padding-top: 16px; font-size: 14px; line-height: 1.9; }.model-result article { padding-bottom: 14px; }.model-result article p { margin-bottom: 8px; }.model-result h3 { font-size: 14px; }.citation-links { display: flex; flex-wrap: wrap; gap: 6px; }.citation-links button { font-size: 11px; padding: 3px 7px; background: var(--primary-tint); border-radius: 4px; color: var(--primary-deep); text-align: left; }.care-limitations { margin: 24px 0; font-size: 12px; line-height: 1.9; color: var(--muted); }
@media (max-width: 1150px) { .care-layout { grid-template-columns: minmax(0,1fr); }.care-aside { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 640px) { .care-priority { flex-wrap: wrap; padding: 16px; gap: 10px; }.care-priority h2 { font-size: 15px; }.care-priority > .button { margin-left: 34px; }.care-tabs { padding: 0 5px; }.care-tabs button { font-size: 12px; padding: 16px 4px; gap: 4px; }.care-tabs button > span { display: none; }.care-section,.care-next,.care-medications,.care-trends,.care-model { padding: 18px 16px; }.care-aside,.trend-grid { grid-template-columns: minmax(0,1fr); }.case-selector { gap: 8px; }.case-selector label { display: none; }.care-save .button { width: 100%; }.care-model .panel-heading { flex-wrap: wrap; gap: 12px; }.model-status { max-width: 100%; }.answer-options label { padding: 8px 11px; } }
</style>
