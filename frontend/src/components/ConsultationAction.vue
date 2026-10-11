<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api'
import type { DrugLabel } from '../types'
import Icon from './Icon.vue'

export interface ActionItem { priority: 'now' | 'today' | 'observe'; title: string; detail: string }
export interface ActionSource { title: string; url: string }

const props = defineProps<{
  level: 'emergency' | 'attention' | 'recorded'
  label: string
  summary: string
  actions: ActionItem[]
  reasons?: string[]
  sources?: ActionSource[]
  knowledge?: { id?: string; title: string; excerpt: string; source_url: string; source?: string }[]
  monitoring?: { next_check_in: string; escalation_signs: string[] } | null
  facts?: { complaint: string; startedAt: string }
}>()

const priorityLabel: Record<ActionItem['priority'], string> = { now: '立即处理', today: '今天安排', observe: '持续观察' }
const heading = computed(() => props.level === 'emergency' ? '先处理危险信号' : props.level === 'attention' ? '今天需要优先处理' : '接下来的处理')
const copyState = ref('')
const drugQuery = ref('')
const drugs = ref<DrugLabel[]>([])
const drugNotice = ref('')
const drugsLoading = ref(false)
const drugError = ref('')
const selectedDrug = ref<DrugLabel | null>(null)

/** Only confirmed facts are placed in the script; unknown parts stay as blanks for the caller to fill. */
const callScript = computed(() => {
  const place = '【详细地址或附近地标】'
  const who = '【患者】'
  const complaint = props.facts?.complaint?.trim() || '【已确认的主要情况】'
  const start = props.facts?.startedAt?.trim() ? `${props.facts.startedAt}` : '【已知的起病时间】'
  return `我在${place}，${who}现在${complaint}，从${start}开始。我的联系电话是【你的号码】。`
})

async function copy(text: string, tag: string) {
  try { await navigator.clipboard.writeText(text); copyState.value = tag; setTimeout(() => { if (copyState.value === tag) copyState.value = '' }, 2500) }
  catch { copyState.value = 'fail' }
}

async function searchDrugs() {
  const term = drugQuery.value.trim()
  if (!term) { drugError.value = '请输入药品通用名或商品名。'; return }
  drugsLoading.value = true; drugError.value = ''; drugNotice.value = ''; drugs.value = []; selectedDrug.value = null
  try {
    const result = await api.knowledgeDrugs(term)
    drugs.value = result.items; drugNotice.value = result.notice
    if (!result.items.length) drugError.value = '知识库没有该名称的药品标签。请核对名称，或向医生、药师确认。'
  } catch (error) { drugError.value = error instanceof Error ? error.message : '查询未完成，请稍后重试。' }
  finally { drugsLoading.value = false }
}
</script>

<template>
  <section class="action-box" :class="level" aria-label="当前建议行动">
    <header class="action-head">
      <span class="action-icon"><Icon :name="level === 'emergency' ? 'alert' : 'shield'" :size="22" /></span>
      <div><span class="action-kicker">{{ label }}</span><h2>{{ heading }}</h2></div>
    </header>
    <p class="action-summary">{{ summary }}</p>

    <ol v-if="actions.length" class="action-list">
      <li v-for="(item, index) in actions" :key="index" :class="item.priority">
        <span class="action-tag">{{ priorityLabel[item.priority] }}</span>
        <div><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div>
      </li>
    </ol>

    <details v-if="reasons?.length" class="action-details">
      <summary>为什么这样提示（{{ reasons.length }} 条依据）</summary>
      <ul><li v-for="(reason, index) in reasons" :key="index">{{ reason }}</li></ul>
    </details>

    <div v-if="level === 'emergency'" class="emergency">
      <div class="emergency-call">
        <a class="button danger" href="tel:120"><Icon name="phone" :size="17" />拨打 120</a>
        <button class="button secondary" @click="copy('120', 'number')">{{ copyState === 'number' ? '已复制号码' : '复制号码 120' }}</button>
      </div>
      <p class="emergency-hint">由你主动拨号，应用不会自动代拨，也不会显示已接通或已派车。桌面环境无法拨号时，请用手机拨打 120。</p>
      <details class="call-script">
        <summary>通话时怎么说</summary>
        <p>{{ callScript }}</p>
        <button class="text-button" @click="copy(callScript, 'script')">{{ copyState === 'script' ? '已复制通话提示' : '复制通话提示' }}</button>
        <small>方括号内为你本人需要补充的信息（地址、号码等）。意识、呼吸、既往病史仅在已确认时才说明，不确定就照实告知并按调度员问题回答。</small>
      </details>
    </div>

    <details v-if="monitoring" class="action-details">
      <summary>复评与升级条件</summary>
      <p>{{ monitoring.next_check_in }}</p>
      <ul><li v-for="(sign, index) in monitoring.escalation_signs" :key="index">{{ sign }}</li></ul>
    </details>

    <details class="action-details">
      <summary>附近医院与就医选择</summary>
      <p>本应用不提供医院名录，也不会虚构名称、距离、开放状态或挂号能力。需要就近就医时，请使用你信任的地图或当地医疗平台查找，并在出发前电话确认。</p>
      <a class="button secondary" href="https://map.baidu.com/search/%E9%99%84%E8%BF%91%E7%9A%84%E5%8C%BB%E9%99%A2" target="_blank" rel="noopener noreferrer"><Icon name="pin" :size="16" />打开外部地图查找附近医院</a>
    </details>

    <details class="action-details">
      <summary>用药参考（按名称查询真实药品标签）</summary>
      <p class="action-muted">这里仅按你输入的药品名称，查询已授权的官方药品标签原文，用于就医前核对；不会给出剂量、疗程或用药建议。标签来源与适用地区以标签页面为准。</p>
      <form class="drug-search" @submit.prevent="searchDrugs">
        <label class="sr-only" for="action-drug-input">药品通用名或商品名</label>
        <input id="action-drug-input" v-model="drugQuery" maxlength="80" placeholder="输入药品通用名或商品名，例如 布洛芬" />
        <button class="button primary small" :disabled="drugsLoading">{{ drugsLoading ? '查询中…' : '查询' }}</button>
      </form>
      <p v-if="drugError" class="action-error" role="alert">{{ drugError }}</p>
      <p v-if="drugNotice && drugs.length" class="action-muted">{{ drugNotice }}</p>
      <ul v-if="drugs.length" class="drug-list">
        <li v-for="drug in drugs" :key="drug.id">
          <button class="drug-name" @click="selectedDrug = selectedDrug?.id === drug.id ? null : drug">{{ drug.generic_names[0] || drug.brand_names[0] || '未命名药品' }}<small v-if="drug.brand_names.length">商品名：{{ drug.brand_names.join('、') }}</small></button>
          <div v-if="selectedDrug?.id === drug.id" class="drug-body">
            <section v-for="section in drug.sections" :key="section.key"><h4>{{ section.title }}</h4><p>{{ section.text }}</p></section>
            <a :href="drug.source_url" target="_blank" rel="noopener noreferrer">查看标签原文（{{ drug.effective_date }}）</a>
          </div>
        </li>
      </ul>
    </details>

    <details v-if="knowledge?.length" class="action-details">
      <summary>相关可信资料（{{ knowledge.length }} 篇）</summary>
      <ul class="knowledge-list">
        <li v-for="(item, index) in knowledge" :key="item.id || index">
          <strong>{{ item.title }}</strong>
          <p>{{ item.excerpt }}</p>
          <a :href="item.source_url" target="_blank" rel="noopener noreferrer">{{ item.source || '查看官方原文' }}</a>
        </li>
      </ul>
    </details>

    <details v-if="sources?.length" class="action-details">
      <summary>来源</summary>
      <ul class="source-list"><li v-for="source in sources" :key="source.url"><a :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }}</a></li></ul>
    </details>
  </section>
</template>

<style scoped>
.action-box { display:grid; gap:14px; width:100%; padding:18px; border:1px solid var(--border); border-left:4px solid var(--recorded); border-radius:14px; background:var(--surface); }
.action-box.attention { border-left-color:var(--attention); background:var(--amber-tint); }
.action-box.emergency { border-left-color:var(--emergency); background:var(--danger-tint); }
.action-head { display:flex; align-items:center; gap:12px; }
.action-icon { display:grid; place-items:center; width:38px; height:38px; flex:none; border-radius:11px; color:var(--recorded); background:var(--recorded-soft); }
.action-box.attention .action-icon { color:var(--attention); background:var(--attention-soft); }
.action-box.emergency .action-icon { color:var(--emergency); background:var(--emergency-soft); }
.action-kicker { font-size:11px; color:var(--muted); letter-spacing:.02em; }
.action-head h2 { margin:3px 0 0; font-size:16px; }
.action-summary { margin:0; font-size:14px; line-height:1.85; }
.action-list { list-style:none; margin:0; padding:0; display:grid; gap:12px; }
.action-list li { display:flex; gap:11px; align-items:flex-start; }
.action-tag { flex:none; font-size:11px; padding:3px 8px; border-radius:999px; color:var(--primary-deep); background:var(--primary-tint); }
.action-list li.now .action-tag { color:var(--emergency); background:var(--emergency-soft); }
.action-list li.today .action-tag { color:var(--attention); background:var(--attention-soft); }
.action-list strong { font-size:14px; }
.action-list p { margin:4px 0 0; font-size:13px; line-height:1.8; color:var(--ink-soft); }
.action-details { border-top:1px solid var(--border-faint); padding-top:12px; font-size:13px; line-height:1.85; }
.action-details summary { cursor:pointer; font-size:13px; color:var(--ink-soft); }
.action-details p { margin:10px 0; color:var(--muted); }
.action-details ul { margin:10px 0 0; padding-left:18px; color:var(--muted); }
.action-muted { font-size:12px; color:var(--muted); line-height:1.8; }
.action-error { margin:8px 0 0; font-size:12px; color:var(--danger); }
.emergency { display:grid; gap:10px; padding:14px; border-radius:11px; background:var(--surface); border:1px solid var(--emergency-soft); }
.emergency-call { display:flex; flex-wrap:wrap; gap:10px; }
.emergency-hint { margin:0; font-size:11px; color:var(--muted); line-height:1.7; }
.call-script p { color:var(--ink); font-size:14px; line-height:1.9; background:var(--surface-sunken); padding:12px; border-radius:9px; }
.call-script small { display:block; margin-top:8px; font-size:11px; color:var(--muted); line-height:1.7; }
.drug-search { display:flex; gap:9px; margin:10px 0; }
.drug-search input { flex:1; min-width:0; }
.drug-list { list-style:none; margin:0; padding:0; }
.drug-list li { border-top:1px solid var(--border-faint); padding:10px 0; }
.drug-name { display:grid; gap:3px; width:100%; text-align:left; font-size:13px; color:var(--primary-deep); }
.drug-name small { color:var(--muted); }
.drug-body { margin-top:10px; display:grid; gap:10px; }
.drug-body h4 { margin:0; font-size:12px; }
.drug-body p { margin:3px 0 0; font-size:12px; line-height:1.8; color:var(--muted); max-height:200px; overflow:auto; }
.drug-body a,.knowledge-list a { font-size:12px; color:var(--primary-deep); }
.knowledge-list { list-style:none; margin:0; padding:0; display:grid; gap:12px; }
.knowledge-list li { border-top:1px solid var(--border-faint); padding-top:10px; }
.knowledge-list strong { font-size:13px; }
.knowledge-list p { margin:4px 0 0; font-size:12px; color:var(--muted); line-height:1.8; }
.source-list a { font-size:12px; color:var(--primary-deep); }
@media(max-width:640px){
  .action-box { padding:15px; gap:12px; }
  .action-summary { font-size:14px; }
  .emergency { padding:12px; }
  .emergency-call { flex-direction:column; }
  .emergency-call .button { width:100%; justify-content:center; }
  .drug-search { flex-wrap:wrap; }
  .drug-search input { flex:1 1 160px; }
  .drug-search .button { flex:none; }
  .drug-body p { max-height:none; }
}
</style>
