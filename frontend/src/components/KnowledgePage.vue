<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import type { DrugLabel, DrugLabels, Episode, KnowledgeStatus, KnowledgeTopic, KnowledgeTopics, RegionalSummary } from '../types'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{ episodes?: Episode[] }>(), { episodes: () => [] })
const emit = defineEmits<{ consult: [topic: string] }>()
const region = ref<RegionalSummary | null>(null)
const regionExpanded = ref(false)
const personalReading = ref(false)
const recommendations = ref<KnowledgeTopic[]>([])
const recommendationsLoading = ref(false)
const recommendationsError = ref('')
const dismissed = ref<string[]>([])
let recommendationRequest = 0
const recommendationTerms = computed(() => [...new Set(props.episodes
  .filter(episode => episode.status === 'ongoing')
  .flatMap(episode => episode.symptoms)
  .map(term => term.trim()).filter(Boolean))].slice(0, 3))
const visibleRecommendations = computed(() => recommendations.value.filter(topic => !dismissed.value.includes(topic.id)).slice(0, 3))
async function loadRecommendations() {
  const request = ++recommendationRequest
  recommendations.value = []; recommendationsError.value = ''
  if (!personalReading.value || !recommendationTerms.value.length) { recommendationsLoading.value = false; return }
  recommendationsLoading.value = true
  try {
    const results = await Promise.all(recommendationTerms.value.map(term => api.knowledgeTopics(term, 1)))
    if (active && request === recommendationRequest && personalReading.value) {
      recommendations.value = [...new Map(results.flatMap(result => result.items.slice(0, 2)).map(item => [item.id, item])).values()]
    }
  } catch { if (active && request === recommendationRequest) recommendationsError.value = '相关阅读暂时没能加载，仍可在下方搜索。' }
  finally { if (active && request === recommendationRequest) recommendationsLoading.value = false }
}
watch([personalReading, recommendationTerms], () => { void loadRecommendations() })

type Tab = 'topics' | 'drugs'
const tab = ref<Tab>('topics')
const status = ref<KnowledgeStatus | null>(null)
const statusLoading = ref(false)
const statusError = ref('')
const topicInput = ref('')
const topicQuery = ref('')
const topicPage = ref(1)
const topics = ref<KnowledgeTopics | null>(null)
const topicsLoading = ref(false)
const topicsError = ref('')
const selectedTopicId = ref('')
const selectedTopic = ref<KnowledgeTopic | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const drugInput = ref('')
const drugQuery = ref('')
const drugs = ref<DrugLabels | null>(null)
const drugsLoading = ref(false)
const drugsError = ref('')
const selectedDrug = ref<DrugLabel | null>(null)
const detailHeading = ref<HTMLElement>()
const searchInput = ref<HTMLInputElement>()
let active = true
let statusRequest = 0
let topicRequest = 0
let drugRequest = 0
let detailRequest = 0
const topicPages = computed(() => Math.max(1, Math.ceil((topics.value?.total ?? 0) / (topics.value?.page_size || 12))))
const inDetail = computed(() => !!selectedTopicId.value || !!selectedDrug.value)
const examples = computed(() => tab.value === 'topics' ? ['高血压', '糖尿病', '哮喘'] : ['布洛芬', '对乙酰氨基酚', 'ibuprofen'])
const topicSources = computed(() => {
  if (!status.value) return []
  const info = status.value.topics
  return info.sources?.length ? info.sources : [{ ...info, source_url: info.url }]
})
function contentLang(topic: KnowledgeTopic) { return topic.language === 'Chinese' || topic.language.startsWith('zh') ? 'zh-CN' : 'en' }
function languageLabel(topic: KnowledgeTopic) { return contentLang(topic) === 'zh-CN' ? '中文原文' : '英文原文' }
function describe(error: unknown) { return error instanceof Error ? error.message : '资料暂时无法读取，请重试。' }
function officialUrl(value: string) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : undefined } catch { return undefined }
}
function timestamp(value?: string | null) {
  if (!value) return '未提供'
  const formatted = /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value
  const date = new Date(formatted)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })
}
async function loadStatus() {
  const request = ++statusRequest
  statusLoading.value = true; statusError.value = ''
  try { const result = await api.knowledgeStatus(); if (active && request === statusRequest) status.value = result }
  catch (error) { if (active && request === statusRequest) statusError.value = describe(error) }
  finally { if (active && request === statusRequest) statusLoading.value = false }
}
async function loadTopics(query = topicQuery.value, page = topicPage.value) {
  const request = ++topicRequest
  topicQuery.value = query.trim(); topicPage.value = page
  topicsLoading.value = true; topicsError.value = ''; topics.value = null
  try {
    const result = await api.knowledgeTopics(topicQuery.value, page)
    if (active && request === topicRequest && tab.value === 'topics') topics.value = result
  } catch (error) {
    if (active && request === topicRequest && tab.value === 'topics') topicsError.value = describe(error)
  } finally { if (active && request === topicRequest) topicsLoading.value = false }
}
async function loadDrugs(query: string) {
  const term = query.trim()
  if (!term) { drugsError.value = '请先输入药品通用名或商品名。'; return }
  const request = ++drugRequest
  drugQuery.value = term; drugsLoading.value = true; drugsError.value = ''; drugs.value = null; selectedDrug.value = null
  try {
    const result = await api.knowledgeDrugs(term)
    if (active && request === drugRequest && tab.value === 'drugs') drugs.value = result
  } catch (error) {
    if (active && request === drugRequest && tab.value === 'drugs') drugsError.value = describe(error)
  } finally { if (active && request === drugRequest) drugsLoading.value = false }
}
async function openTopic(id: string) {
  const request = ++detailRequest
  selectedTopicId.value = id; selectedTopic.value = null; detailLoading.value = true; detailError.value = ''
  try {
    const result = await api.knowledgeTopic(id)
    if (active && request === detailRequest && tab.value === 'topics' && selectedTopicId.value === id) {
      selectedTopic.value = result
      await nextTick()
      if (active && request === detailRequest) detailHeading.value?.focus()
    }
  } catch (error) {
    if (active && request === detailRequest && tab.value === 'topics' && selectedTopicId.value === id) detailError.value = describe(error)
  } finally { if (active && request === detailRequest) detailLoading.value = false }
}
async function openDrug(item: DrugLabel) {
  selectedDrug.value = item
  await nextTick()
  if (active && selectedDrug.value?.id === item.id) detailHeading.value?.focus()
}
async function backToList() {
  detailRequest++; selectedTopicId.value = ''; selectedTopic.value = null; selectedDrug.value = null
  detailLoading.value = false; detailError.value = ''
  await nextTick()
  if (active) searchInput.value?.focus()
}
async function switchTab(next: Tab, focus = false) {
  if (next !== tab.value) {
    topicRequest++; drugRequest++; detailRequest++
    topicsLoading.value = false; drugsLoading.value = false; detailLoading.value = false
    selectedTopicId.value = ''; selectedTopic.value = null; selectedDrug.value = null; detailError.value = ''
    tab.value = next
    if (next === 'topics' && !topics.value) void loadTopics()
  }
  if (focus) { await nextTick(); if (active) document.getElementById(`knowledge-tab-${next}`)?.focus() }
}
function fillExample(value: string) {
  if (tab.value === 'topics') { topicInput.value = value; void loadTopics(value, 1) }
  else { drugInput.value = value; void loadDrugs(value) }
}
onMounted(() => {
  void loadStatus(); void loadTopics('', 1)
  void api.healthRegion().then(result => { if (active) region.value = result }).catch(() => {})
})
onBeforeUnmount(() => { active = false; statusRequest++; topicRequest++; drugRequest++; detailRequest++; recommendationRequest++ })
</script>

<template>
  <div class="knowledge-page">
    <header class="knowledge-heading"><span class="knowledge-overline">多了解一点，多安心一点</span><h1>健康科普</h1><p>与你有关的知识，来自可靠的地方。</p></header>
    <template>
    <section v-if="!inDetail && tab === 'topics'" class="knowledge-attention" aria-label="健康观察与预防">
      <span class="attention-icon"><Icon name="leaf" :size="23" /></span>
      <div v-if="region?.enabled && region.status === 'available' && region.signals.length">
        <span class="knowledge-overline">{{ region.region_label }} · 社区症状观察</span>
        <h2>了解身边的健康变化</h2>
        <p>匿名参与者的症状变化可供参考，不代表流感疫情或个人患病风险。</p>
        <button class="text-button" :aria-expanded="regionExpanded" @click="regionExpanded = !regionExpanded">{{ regionExpanded ? '收起观察' : '看看观察' }} <Icon name="chevron" :size="14" /></button>
        <div v-if="regionExpanded" class="regional-observations"><p v-for="signal in region.signals" :key="signal.cluster"><strong>{{ signal.label }}</strong> · {{ signal.description }}<small>最近 {{ region.window_days }} 天 · {{ signal.people_band }} · {{ signal.trend === 'increased' ? '样本内较前期增加' : signal.trend === 'stable' ? '样本内较前期平稳' : '趋势尚不明确' }}</small></p><p v-if="region.notice">{{ region.notice }}</p></div>
      </div>
      <div v-else><span class="knowledge-overline">日常预防</span><h2>关注流感，先看可靠资料</h2><p>国家流感中心提供全国监测周报；当前未取得本市官方监测，不能据此判断当地风险。</p></div>
      <a class="attention-link" href="https://ivdc.chinacdc.cn/cnic/zyzx/lgzb/" target="_blank" rel="noopener noreferrer">查看官方监测 <Icon name="arrow" :size="16" /></a>
    </section>

    <section v-if="!inDetail && tab === 'topics' && props.episodes.length" class="knowledge-related">
      <div class="related-heading"><div><h2>与你有关</h2><p>由你决定，是否结合进行中的问诊记录查找相关阅读。</p></div><label class="personal-reading-toggle"><input v-model="personalReading" type="checkbox" /><span>结合我的记录</span></label></div>
      <template v-if="personalReading"><p v-if="recommendationsLoading" class="knowledge-caption" role="status">正在查找相关阅读…</p><div v-else-if="recommendationsError" class="related-empty" role="status">{{ recommendationsError }} <button class="text-button" @click="loadRecommendations">重试</button></div><div v-else-if="visibleRecommendations.length" class="related-list"><div v-for="topic in visibleRecommendations" :key="topic.id" class="related-row"><button class="related-topic" @click="openTopic(topic.id)"><Icon name="book" :size="18" /><span><strong>{{ topic.display_title || topic.title }}</strong><small>{{ topic.source || languageLabel(topic) }}</small></span><Icon name="chevron" :size="16" /></button><button class="related-dismiss" :aria-label="`不推荐：${topic.display_title || topic.title}`" title="不适合我" @click="dismissed.push(topic.id)"><Icon name="close" :size="15" /></button></div></div><p v-else class="knowledge-caption">{{ recommendationTerms.length ? '暂时没有匹配的相关阅读，可以在下方换个关键词。' : '没有进行中的症状记录，先看看下面的日常知识。' }}</p><p class="related-privacy">仅查找本站知识，不将病程发送至外部资料平台；相关阅读不代表诊断。</p></template>
    </section>

    <section class="knowledge-panel">
      <div class="knowledge-tabs" role="tablist" aria-label="官方资料类型">
        <button id="knowledge-tab-topics" role="tab" aria-controls="knowledge-topics" :aria-selected="tab === 'topics'" :tabindex="tab === 'topics' ? 0 : -1" :class="{ active: tab === 'topics' }" @click="switchTab('topics')" @keydown.left.prevent="switchTab('drugs', true)" @keydown.right.prevent="switchTab('drugs', true)" @keydown.home.prevent="switchTab('topics', true)" @keydown.end.prevent="switchTab('drugs', true)"><Icon name="book" :size="18" />疾病资料</button>
        <button id="knowledge-tab-drugs" role="tab" aria-controls="knowledge-drugs" :aria-selected="tab === 'drugs'" :tabindex="tab === 'drugs' ? 0 : -1" :class="{ active: tab === 'drugs' }" @click="switchTab('drugs')" @keydown.left.prevent="switchTab('topics', true)" @keydown.right.prevent="switchTab('topics', true)" @keydown.home.prevent="switchTab('topics', true)" @keydown.end.prevent="switchTab('drugs', true)"><Icon name="search" :size="18" />药品标签</button>
      </div>
      <div :id="`knowledge-${tab}`" role="tabpanel" :aria-labelledby="`knowledge-tab-${tab}`" class="knowledge-body">
        <template v-if="!inDetail">
          <form class="knowledge-search" @submit.prevent="tab === 'topics' ? loadTopics(topicInput, 1) : loadDrugs(drugInput)">
            <Icon name="search" :size="19" /><label class="knowledge-search-field" :for="`knowledge-query-${tab}`"><span class="knowledge-sr-only">{{ tab === 'topics' ? '查询疾病或健康主题' : '查询药品通用名或商品名' }}</span>
              <input v-if="tab === 'topics'" :id="`knowledge-query-${tab}`" ref="searchInput" v-model="topicInput" type="search" maxlength="80" placeholder="想了解什么健康知识？" aria-describedby="knowledge-search-note" />
              <input v-else :id="`knowledge-query-${tab}`" ref="searchInput" v-model="drugInput" type="search" maxlength="80" required placeholder="如：布洛芬、ibuprofen" aria-describedby="knowledge-search-note" />
            </label>
            <button type="submit" class="button primary" :disabled="tab === 'topics' ? topicsLoading : drugsLoading"><Icon name="search" :size="17" />{{ (tab === 'topics' ? topicsLoading : drugsLoading) ? '正在查询…' : '查询' }}</button>
          </form>
          <p id="knowledge-search-note" class="knowledge-caption">{{ tab === 'topics' ? '支持中文与英文关键词，查询本站资料。' : '美国 FDA 英文标签，仅供资料查阅，不能替代国内说明书。仅查询词发送至 FDA，请勿输入个人信息。' }}</p>
          <div class="knowledge-examples"><span>试试</span><button v-for="example in examples" :key="example" type="button" @click="fillExample(example)">{{ example }}</button></div>
        </template>

        <template v-if="tab === 'topics'">
          <div v-if="selectedTopicId" class="knowledge-detail" :aria-busy="detailLoading">
            <button class="text-button knowledge-back" @click="backToList">← 返回疾病列表</button>
            <p v-if="detailLoading" class="knowledge-empty" role="status">正在读取官方原文…</p>
            <div v-else-if="detailError" class="notice error knowledge-error" role="alert"><span>{{ detailError }}</span><button class="text-button" @click="openTopic(selectedTopicId)">重试</button></div>
            <article v-else-if="selectedTopic">
              <span class="knowledge-language">{{ languageLabel(selectedTopic) }}</span>
              <h2 ref="detailHeading" :lang="selectedTopic.display_title && selectedTopic.display_title !== selectedTopic.title ? 'zh-CN' : contentLang(selectedTopic)" tabindex="-1">{{ selectedTopic.display_title || selectedTopic.title }}</h2>
              <p v-if="selectedTopic.display_title !== selectedTopic.title" :lang="contentLang(selectedTopic)" class="knowledge-original-title">{{ selectedTopic.title }}</p>
              <p v-if="selectedTopic.aliases.length" class="knowledge-caption">本应用检索别名：{{ selectedTopic.aliases.join('、') }}（非官方译文）</p>
              <div class="knowledge-meta"><span v-if="selectedTopic.source">来源：{{ selectedTopic.source }}</span><span v-if="selectedTopic.published_at">发表日期：{{ timestamp(selectedTopic.published_at) }}</span><span>数据快照：{{ timestamp(selectedTopic.generated_at || topics?.generated_at) }}</span><span>本站导入：{{ timestamp(selectedTopic.imported_at || topics?.imported_at) }}</span><a v-if="officialUrl(selectedTopic.source_url)" :href="officialUrl(selectedTopic.source_url)" target="_blank" rel="noopener noreferrer">查看官方来源 ↗</a></div>
              <p v-if="(selectedTopic.image_count ?? 0) > 0" class="knowledge-data-notice">此处仅含文字，图片与图表请查看官方原文。</p>
              <p v-if="selectedTopic.summary" :lang="contentLang(selectedTopic)" class="knowledge-original">{{ selectedTopic.summary }}</p>
              <p v-else class="knowledge-original">官方导出未提供摘要，请查看官方原文。</p>
              <button class="button secondary article-consult" @click="emit('consult', selectedTopic.display_title || selectedTopic.title)"><Icon name="pulse" :size="17" />我也有类似情况，去问诊</button>
            </article>
          </div>
          <div v-else :aria-busy="topicsLoading">
            <p v-if="topicsLoading" class="knowledge-empty" role="status">正在查询本站疾病资料…</p>
            <div v-else-if="topicsError" class="notice error knowledge-error" role="alert"><span>{{ topicsError }}</span><button class="text-button" @click="loadTopics()">重试</button></div>
            <div v-else-if="topics && !topics.items.length" class="knowledge-empty" role="status"><Icon name="search" :size="28" /><h3>没有找到相关资料</h3><p>试试其他中文或英文关键词，或更简短的主题名称。未匹配到资料不能用于排除疾病。</p><button v-if="topicQuery" class="text-button" @click="topicInput = ''; loadTopics('', 1)">浏览全部主题</button></div>
            <template v-else-if="topics">
              <p class="knowledge-result-count" role="status">{{ topicQuery ? `“${topicQuery}”的查询结果` : '日常知识' }} <span>{{ topics.total }} 篇资料</span></p>
              <div class="knowledge-list"><button v-for="topic in topics.items" :key="topic.id" class="knowledge-card" @click="openTopic(topic.id)"><span class="knowledge-language">{{ languageLabel(topic) }}<template v-if="topic.source"> · {{ topic.source }}</template></span><h3 :lang="topic.display_title && topic.display_title !== topic.title ? 'zh-CN' : contentLang(topic)">{{ topic.display_title || topic.title }}</h3><p v-if="topic.display_title !== topic.title" :lang="contentLang(topic)" class="knowledge-card-subtitle">{{ topic.title }}</p><p v-if="topic.summary" :lang="contentLang(topic)" class="knowledge-preview">{{ topic.summary }}</p><p v-else class="knowledge-preview">官方导出未提供摘要，请查看官方原文。</p><span class="knowledge-read">读取资料 <Icon name="arrow" :size="16" /></span></button></div>
              <nav class="knowledge-pagination" aria-label="疾病资料分页"><span>第 {{ topics.page }} / {{ topicPages }} 页</span><div><button class="button secondary small" :disabled="topics.page <= 1" @click="loadTopics(topicQuery, topics.page - 1)">上一页</button><button class="button secondary small" :disabled="topics.page >= topicPages" @click="loadTopics(topicQuery, topics.page + 1)">下一页</button></div></nav>
            </template>
          </div>
        </template>

        <template v-else>
          <article v-if="selectedDrug" class="knowledge-detail">
            <button class="text-button knowledge-back" @click="backToList">← 返回药品列表</button>
            <span class="knowledge-language">美国药品标签 · 英文官方原文</span>
            <h2 ref="detailHeading" lang="en" tabindex="-1">{{ selectedDrug.brand_names.join(' / ') || selectedDrug.generic_names.join(' / ') || 'Drug label' }}</h2>
            <p lang="en" class="knowledge-original-title">{{ selectedDrug.generic_names.join(' / ') }}</p>
            <p v-if="drugs?.stale" class="knowledge-data-notice">当前显示较早缓存的标签，内容可能已有变化，请核实官方来源。</p>
            <div v-if="drugs" class="knowledge-meta"><span>来源：{{ drugs.source }}</span><span>源库更新：{{ timestamp(drugs.last_updated) }}</span><span>本站获取：{{ timestamp(drugs.fetched_at) }}{{ drugs.cached ? ' · 缓存' : '' }}</span></div>
            <dl class="knowledge-label-meta"><dt>标签生效日期</dt><dd>{{ timestamp(selectedDrug.effective_date) }}</dd><dt>生产企业</dt><dd lang="en">{{ selectedDrug.manufacturer_names.join(' / ') || '未提供' }}</dd><dt>美国 NDC 编码</dt><dd>{{ selectedDrug.product_ndcs.join(' / ') || '未提供' }}</dd></dl>
            <a v-if="officialUrl(selectedDrug.source_url)" :href="officialUrl(selectedDrug.source_url)" target="_blank" rel="noopener noreferrer">查看官方标签 ↗</a>
            <div v-if="selectedDrug.sections.length" class="knowledge-sections"><section v-for="(section, index) in selectedDrug.sections" :key="`${section.key}-${index}`"><h3>{{ section.title }}</h3><p lang="en" class="knowledge-original">{{ section.text }}</p></section></div>
            <p v-else class="knowledge-empty">接口未提供可展示的标签正文，请前往官方来源核实。</p>
          </article>
          <div v-else :aria-busy="drugsLoading">
            <p v-if="drugsLoading" class="knowledge-empty" role="status">正在查询美国 FDA 药品标签…</p>
            <div v-else-if="drugsError" class="notice error knowledge-error" role="alert"><span>{{ drugsError }}</span><button v-if="drugQuery" class="text-button" @click="loadDrugs(drugQuery)">重试查询</button></div>
            <template v-else-if="drugs">
              <p v-if="drugs.notice" class="knowledge-data-notice" role="status">{{ drugs.notice }}</p>
              <p v-if="drugs.stale" class="knowledge-data-notice" role="status">当前显示较早缓存的标签，内容可能已有变化，请核实官方来源。</p>
              <div class="knowledge-meta"><span>来源：{{ drugs.source }}</span><span>源库更新：{{ timestamp(drugs.last_updated) }}</span><span>本站获取：{{ timestamp(drugs.fetched_at) }}{{ drugs.cached ? ' · 缓存' : '' }}</span></div>
              <p class="knowledge-result-count" role="status">“{{ drugs.query }}” · FDA 返回 {{ drugs.total }} 条，展示 {{ drugs.items.length }} 条<span v-if="drugs.normalized_query !== drugs.query"> · 实际检索词：{{ drugs.normalized_query }}</span></p>
              <div v-if="!drugs.items.length" class="knowledge-empty"><Icon name="search" :size="28" /><h3>没有找到相关标签</h3><p>试试英文通用名。美国标签库的查询结果不代表该药品在国内的批准状态。</p></div>
              <div v-else class="knowledge-list"><button v-for="drug in drugs.items" :key="drug.id" class="knowledge-card" @click="openDrug(drug)"><span class="knowledge-language">美国药品标签 · 英文</span><h3 lang="en">{{ drug.brand_names.join(' / ') || drug.generic_names.join(' / ') || 'Drug label' }}</h3><p lang="en" class="knowledge-card-subtitle">{{ drug.generic_names.join(' / ') }}</p><p class="knowledge-caption">标签生效日期：{{ timestamp(drug.effective_date) }}</p><p lang="en" class="knowledge-preview">{{ drug.manufacturer_names.join(' / ') }}</p><span class="knowledge-read">读取标签 <Icon name="arrow" :size="16" /></span></button></div>
            </template>
            <div v-else class="knowledge-empty"><Icon name="search" :size="28" /><h3>查阅药品的官方标签</h3><p>输入药品名称并点击查询。请勿填入姓名、联系方式或病程记录。</p></div>
          </div>
        </template>
      </div>
    </section>

    <details class="knowledge-sources">
      <summary>数据来源与国内官方查询</summary>
      <p v-if="statusLoading" role="status" class="knowledge-caption">正在读取数据来源…</p>
      <div v-else-if="statusError" class="notice error knowledge-error" role="alert"><span>{{ statusError }}</span><button class="text-button" @click="loadStatus">重试</button></div>
      <template v-else-if="status">
        <p class="knowledge-caption">{{ status.topics.source }} · 已导入共 {{ status.topics.count }} 条 · {{ status.topics.available ? '可查询' : '暂不可用' }}</p>
        <div class="knowledge-source-grid">
          <section v-for="source in topicSources" :key="`${source.source}-${source.source_url}`"><h3>疾病与健康主题</h3><a v-if="officialUrl(source.source_url)" :href="officialUrl(source.source_url)" target="_blank" rel="noopener noreferrer">{{ source.source }} ↗</a><p v-else>{{ source.source }}</p><p>已导入 {{ source.count }} 条 · {{ source.language }}</p><p>数据快照：{{ timestamp(source.generated_at) }}<br />本站导入：{{ timestamp(source.imported_at) }}</p></section>
          <section><h3>美国药品标签</h3><a v-if="officialUrl(status.drugs.url)" :href="officialUrl(status.drugs.url)" target="_blank" rel="noopener noreferrer">{{ status.drugs.source }} ↗</a><p v-else>{{ status.drugs.source }}</p><p>{{ status.drugs.available ? '按需查询' : '暂不可用' }} · {{ status.drugs.language }}</p><p>标签更新及获取日期在每次查询结果中展示。</p></section>
        </div>
        <div v-if="status.directories.length" class="knowledge-directories"><h3>国内官方查询目录</h3><p class="knowledge-caption">国内批准信息与说明书请到对应官方平台核实。</p><div class="knowledge-directory-grid"><div v-for="directory in status.directories" :key="directory.url"><a v-if="officialUrl(directory.url)" :href="officialUrl(directory.url)" target="_blank" rel="noopener noreferrer">{{ directory.name }} ↗</a><p>{{ directory.description }}</p></div></div></div>
      </template>
    </details>
    </template>
  </div>
</template>

<style scoped>
.knowledge-page { min-width: 0; overflow-wrap: anywhere; }
.knowledge-view-switch { display: flex; gap: 6px; width: fit-content; padding: 5px; margin-bottom: 22px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); }
.knowledge-view-switch button { padding: 9px 18px; border-radius: var(--radius-sm); color: var(--muted); font-size: 13px; }
.knowledge-view-switch button.active { color: var(--primary-deep); background: var(--primary-soft); font-weight: 600; }
.knowledge-note { display: flex; align-items: flex-start; gap: 12px; padding: 17px 20px; margin-bottom: 24px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--primary-tint); color: var(--ink-soft); font-size: 13px; line-height: 1.8; }
.knowledge-note svg { flex-shrink: 0; margin-top: 2px; color: var(--primary); }
.knowledge-note p, .knowledge-caption, .knowledge-source-grid p, .knowledge-directories p { margin: 0; }
.knowledge-panel { overflow: hidden; }
.knowledge-tabs { display: flex; gap: 8px; padding: 16px 24px 0; border-bottom: 1px solid var(--border); }
.knowledge-tabs button { display: inline-flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 3px solid transparent; color: var(--muted); font-weight: 600; }
.knowledge-tabs button.active { color: var(--primary-deep); border-color: var(--primary); }
.knowledge-body { padding: 24px; min-width: 0; }
.knowledge-search { display: flex; align-items: flex-end; gap: 12px; }
.knowledge-search .field { flex: 1; min-width: 0; margin: 0; }
.knowledge-search input { min-width: 0; width: 100%; }
.knowledge-search .button { min-height: 44px; flex-shrink: 0; }
.knowledge-caption { color: var(--muted); font-size: 12px; line-height: 1.8; }
.knowledge-search + .knowledge-caption { margin-top: 12px; }
.knowledge-examples { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 12px 0 24px; color: var(--muted); font-size: 12px; }
.knowledge-examples button { border: 1px solid var(--border); border-radius: 20px; padding: 4px 10px; color: var(--primary-deep); background: var(--surface-soft); }
.knowledge-result-count { margin: 18px 0 12px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.knowledge-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.knowledge-card { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; padding: 20px; text-align: left; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-soft); transition: border-color .15s; }
.knowledge-card:hover { border-color: var(--primary); }
.knowledge-card h3 { margin: 8px 0; font-size: 17px; line-height: 1.5; }
.knowledge-language { display: inline-block; color: var(--primary-deep); font-size: 11px; letter-spacing: .03em; }
.knowledge-card-subtitle { margin: 0 0 8px; color: var(--muted); font-size: 13px; }
.knowledge-preview { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; margin: 4px 0 15px; font-size: 13px; line-height: 1.7; color: var(--ink-soft); }
.knowledge-read { display: inline-flex; align-items: center; gap: 7px; margin-top: auto; color: var(--primary); font-size: 12px; }
.knowledge-pagination { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 22px; color: var(--muted); font-size: 12px; }
.knowledge-pagination > div { display: flex; flex-wrap: wrap; gap: 8px; }
.knowledge-empty { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 45px 12px; color: var(--muted); text-align: center; font-size: 13px; line-height: 1.8; }
.knowledge-empty h3, .knowledge-empty p { margin: 0; }
.knowledge-empty h3 { color: var(--ink); font-size: 16px; }
.knowledge-error { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.knowledge-back { margin-bottom: 24px; }
.knowledge-detail > .knowledge-language { display: block; }
.knowledge-detail h2 { margin: 12px 0 8px; font-size: 25px; line-height: 1.5; outline-offset: 5px; }
.knowledge-original-title { margin: 0 0 14px; color: var(--ink-soft); line-height: 1.6; }
.knowledge-meta { display: flex; flex-wrap: wrap; gap: 8px 20px; margin: 16px 0; color: var(--muted); font-size: 12px; line-height: 1.8; }
.knowledge-original { margin: 24px 0 0; white-space: pre-wrap; line-height: 1.9; color: var(--ink-soft); font-size: 14px; }
.knowledge-label-meta { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 8px 18px; margin: 20px 0; font-size: 13px; line-height: 1.8; }
.knowledge-label-meta dt { color: var(--muted); }
.knowledge-label-meta dd { margin: 0; }
.knowledge-sections section { margin-top: 28px; padding-top: 22px; border-top: 1px solid var(--border); }
.knowledge-sections h3 { font-size: 16px; }
.knowledge-sections .knowledge-original { margin-top: 12px; }
.knowledge-data-notice { padding: 12px 16px; background: var(--amber-tint); border: 1px solid var(--amber-soft); border-radius: var(--radius-sm); font-size: 13px; line-height: 1.8; color: var(--ink-soft); }
.knowledge-sources { margin-top: 24px; padding: 20px 24px; font-size: 13px; }
.knowledge-sources summary { cursor: pointer; color: var(--ink); font-weight: 600; }
.knowledge-sources > .knowledge-caption, .knowledge-sources > .knowledge-error { margin-top: 18px; }
.knowledge-source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin-top: 20px; }
.knowledge-source-grid h3, .knowledge-directories h3 { margin: 0 0 8px; font-size: 13px; }
.knowledge-source-grid p { margin-top: 7px; color: var(--muted); font-size: 12px; line-height: 1.8; }
.knowledge-directories { border-top: 1px solid var(--border); padding-top: 20px; margin-top: 22px; }
.knowledge-directory-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 24px; margin-top: 14px; }
.knowledge-directory-grid p { font-size: 12px; color: var(--muted); line-height: 1.7; margin-top: 5px; }
.knowledge-page a { color: var(--primary-deep); text-decoration: underline; text-underline-offset: 3px; }
.knowledge-page button:focus-visible, .knowledge-page a:focus-visible, .knowledge-page summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; }
@media (max-width: 640px) {
  .knowledge-note { padding: 14px; font-size: 12px; }
  .knowledge-tabs { padding: 8px 12px 0; gap: 0; }
  .knowledge-tabs button { flex: 1; justify-content: center; padding: 12px 8px; }
  .knowledge-body, .knowledge-sources { padding: 18px 14px; }
  .knowledge-search { flex-wrap: wrap; }
  .knowledge-search .field { flex-basis: 100%; }
  .knowledge-search .button { width: 100%; }
  .knowledge-list, .knowledge-source-grid, .knowledge-directory-grid { grid-template-columns: minmax(0, 1fr); }
  .knowledge-pagination { flex-wrap: wrap; }
  .knowledge-card { padding: 16px; }
  .knowledge-detail h2 { font-size: 21px; }
  .knowledge-label-meta { grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .knowledge-label-meta dd { margin-bottom: 10px; }
}
@media (prefers-reduced-motion: reduce) { .knowledge-card { transition: none; } }

/* A quiet reading surface: one useful reminder, then an editorial list. */
.knowledge-page { max-width: 900px; margin: 0 auto; padding: 18px 0 34px; }
.knowledge-heading { margin-bottom: 30px; }
.knowledge-overline { display: block; color: var(--primary-deep, #18726f); font-size: 11px; line-height: 1.6; letter-spacing: .04em; }
.knowledge-heading h1 { margin: 8px 0 10px; color: var(--ink, #193c41); font-size: clamp(27px, 3vw, 34px); line-height: 1.25; font-weight: 650; letter-spacing: -.035em; }
.knowledge-heading > p { margin: 0; color: var(--muted, #73858a); font-size: 14px; }
.knowledge-attention { display: grid; grid-template-columns: 40px minmax(0, 1fr) auto; align-items: start; gap: 16px; padding: 24px; margin: 0 0 32px; border: 1px solid #dcebe7; border-radius: 20px; background: #f1f8f6; }
.attention-icon { width: 40px; height: 40px; display: grid; place-items: center; border-radius: 13px; color: #217c71; background: #fff; }
.knowledge-attention h2 { margin: 5px 0 8px; font-size: 18px; line-height: 1.5; font-weight: 600; letter-spacing: -.02em; }
.knowledge-attention p { max-width: 490px; margin: 0; color: #607a78; font-size: 12px; line-height: 1.8; }
.knowledge-page .attention-link { display: inline-flex; align-items: center; gap: 6px; margin-top: 29px; color: #277c70; text-decoration: none; font-size: 12px; white-space: nowrap; }
.knowledge-attention .text-button { display: inline-flex; align-items: center; gap: 3px; margin-top: 9px; font-size: 12px; }
.regional-observations { display: grid; gap: 13px; margin-top: 16px; padding-top: 15px; border-top: 1px solid #dcebe7; }
.regional-observations small { display: block; font-size: 11px; color: #708782; }
.knowledge-related { margin-bottom: 30px; }
.related-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; }
.related-heading h2 { margin: 0 0 6px; font-size: 17px; font-weight: 600; }
.related-heading p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.personal-reading-toggle { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; font-size: 12px; color: var(--ink-soft); cursor: pointer; }
.personal-reading-toggle input { appearance: auto; width: 15px; height: 15px; margin: 0; accent-color: var(--primary, #23877d); }
.related-list { border-top: 1px solid var(--border, #e5ecec); }
.related-row { display: flex; align-items: center; border-bottom: 1px solid var(--border, #e5ecec); }
.related-topic { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 0; padding: 15px 0; text-align: left; color: var(--primary-deep); background: none; border: 0; }
.related-topic span { flex: 1; min-width: 0; }
.related-topic strong { display: block; color: var(--ink); font-size: 14px; font-weight: 550; line-height: 1.6; }
.related-topic small { display: block; margin-top: 3px; color: var(--muted); font-size: 11px; }
.related-dismiss { display: grid; place-items: center; width: 36px; height: 40px; margin-left: 8px; color: var(--muted); border: 0; background: none; }
.related-dismiss:hover { color: var(--ink); }
.related-privacy, .related-empty { margin: 11px 0 0; font-size: 11px; color: var(--muted); line-height: 1.8; }
.knowledge-panel { border: 0; border-radius: 0; background: transparent; }
.knowledge-tabs { gap: 24px; padding: 0; }
.knowledge-tabs button { padding: 11px 0 15px; border-bottom-width: 2px; border-radius: 0; font-size: 14px; font-weight: 500; }
.knowledge-tabs button svg { display: none; }
.knowledge-body { padding: 22px 0 0; }
.knowledge-search { display: flex; align-items: center; gap: 12px; padding: 7px 8px 7px 16px; border: 1px solid var(--border, #e2e9e9); border-radius: 14px; background: var(--surface, #fff); }
.knowledge-search:focus-within { border-color: var(--primary, #25887f); box-shadow: 0 0 0 3px #25887f0b; }
.knowledge-search > svg { flex-shrink: 0; color: var(--muted); }
.knowledge-search-field { flex: 1; min-width: 0; }
.knowledge-search input { width: 100%; min-height: 36px; margin: 0; padding: 6px 0; border: 0; outline: 0; box-shadow: none; color: var(--ink); background: transparent; font-size: 14px; }
.knowledge-search .button { min-height: 36px; padding: 8px 14px; border-radius: 9px; font-size: 12px; }
.knowledge-search .button svg { display: none; }
.knowledge-search + .knowledge-caption { margin-top: 9px; font-size: 11px; }
.knowledge-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.knowledge-examples { gap: 9px; margin: 13px 0 29px; font-size: 11px; }
.knowledge-examples button { padding: 5px 11px; border-color: #e7eeec; background: #f6f9f8; color: #617c77; font-size: 11px; }
.knowledge-result-count { display: flex; justify-content: space-between; gap: 12px; margin: 20px 0 0; padding-bottom: 13px; border-bottom: 1px solid var(--border); color: var(--ink); font-size: 15px; font-weight: 550; }
.knowledge-result-count > span { color: var(--muted); font-size: 11px; font-weight: 400; }
.knowledge-list { display: block; }
.knowledge-card { position: relative; width: 100%; padding: 22px 38px 22px 0; border: 0; border-bottom: 1px solid var(--border); border-radius: 0; background: transparent; }
.knowledge-card:hover { border-color: var(--border); background: #f7faf94d; }
.knowledge-card:hover h3 { color: var(--primary-deep); }
.knowledge-card h3 { margin: 6px 0; color: var(--ink); font-size: 17px; font-weight: 550; line-height: 1.6; }
.knowledge-language { color: var(--muted); font-size: 10px; letter-spacing: 0; }
.knowledge-card-subtitle { margin: 0 0 6px; font-size: 11px; }
.knowledge-preview { -webkit-line-clamp: 2; max-width: 720px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.85; }
.knowledge-read { position: absolute; right: 3px; top: 50%; transform: translateY(-50%); color: #8aa09c; font-size: 0; }
.knowledge-pagination { padding-top: 20px; }
.knowledge-pagination .button { min-height: 34px; padding: 6px 12px; font-size: 11px; }
.knowledge-detail h2 { max-width: 720px; font-size: 27px; font-weight: 600; letter-spacing: -.025em; }
.knowledge-detail .knowledge-meta { gap: 6px 16px; font-size: 11px; }
.knowledge-original { max-width: 740px; line-height: 2; font-size: 15px; }
.knowledge-back { margin-bottom: 22px; font-size: 12px; }
.article-consult { display: inline-flex; align-items: center; gap: 7px; margin-top: 30px; font-size: 12px; }
.knowledge-sources { margin-top: 34px; padding: 18px 0; border: 0; border-top: 1px solid var(--border); border-radius: 0; background: transparent; }
.knowledge-sources summary { color: var(--muted); font-size: 12px; font-weight: 400; }
@media (max-width: 640px) {
  .knowledge-page { padding-top: 8px; }
  .knowledge-heading { margin-bottom: 23px; }
  .knowledge-heading h1 { font-size: 28px; }
  .knowledge-heading > p { font-size: 12px; }
  .knowledge-attention { grid-template-columns: 32px minmax(0, 1fr); gap: 12px; padding: 18px 16px; margin-bottom: 25px; border-radius: 16px; }
  .attention-icon { width: 32px; height: 32px; border-radius: 10px; }
  .knowledge-attention h2 { font-size: 16px; }
  .knowledge-attention p { font-size: 11px; }
  .knowledge-page .attention-link { grid-column: 2; margin: 0; font-size: 11px; }
  .related-heading { align-items: flex-start; flex-direction: column; gap: 10px; }
  .knowledge-tabs { gap: 24px; padding: 0; }
  .knowledge-tabs button { flex: 0 0 auto; padding: 10px 0 14px; }
  .knowledge-body { padding: 18px 0 0; }
  .knowledge-search { flex-wrap: nowrap; gap: 9px; padding-left: 12px; }
  .knowledge-search-field { flex: 1; }
  .knowledge-search input { font-size: 13px; }
  .knowledge-search .button { width: auto; padding: 8px 11px; }
  .knowledge-card { padding: 19px 26px 19px 0; }
  .knowledge-card h3 { font-size: 16px; }
  .knowledge-result-count { font-size: 14px; }
  .knowledge-original { font-size: 14px; }
  .knowledge-detail h2 { font-size: 23px; }
  .knowledge-sources { padding: 18px 0; }
}
</style>
