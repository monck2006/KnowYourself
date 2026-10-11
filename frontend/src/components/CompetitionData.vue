<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import type { CompetitionDatasetId, CompetitionSamples, CompetitionSplit, CompetitionStatus } from '../types'
import Icon from './Icon.vue'

const dataset = ref<CompetitionDatasetId>('cmeie')
const split = ref<CompetitionSplit>('train')
const input = ref('')
const query = ref('')
const requestedPage = ref(1)
const status = ref<CompetitionStatus | null>(null)
const statusLoading = ref(false)
const statusError = ref('')
const samples = ref<CompetitionSamples | null>(null)
const loading = ref(false)
const error = ref('')
let active = true
let statusRequest = 0
let sampleRequest = 0
const datasetNames: Record<CompetitionDatasetId, string> = { cmeie: 'CMeIE · 医学关系抽取', cmeee: 'CMeEE · 医学实体识别' }
const splitNames: Record<CompetitionSplit, string> = { train: 'train · 训练集', dev: 'dev · 验证集', test: 'test · 评测集' }
const currentDataset = computed(() => status.value?.datasets.find(item => item.id === dataset.value))
const missingDataset = computed(() => status.value !== null && !currentDataset.value)
const pageCount = computed(() => Math.max(1, Math.ceil((samples.value?.total ?? 0) / (samples.value?.page_size || 10))))
function describe(reason: unknown) { return reason instanceof Error ? reason.message : '数据暂时无法读取，请重试。' }
function sourceUrl(value: string) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : undefined } catch { return undefined }
}
function importedAt(value: string) {
  if (!value) return '未提供'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}
async function loadStatus() {
  const request = ++statusRequest
  statusLoading.value = true; statusError.value = ''
  try { const result = await api.competitionStatus(); if (active && request === statusRequest) status.value = result }
  catch (reason) { if (active && request === statusRequest) statusError.value = describe(reason) }
  finally { if (active && request === statusRequest) statusLoading.value = false }
}
async function loadSamples(page = 1, term = query.value) {
  const request = ++sampleRequest
  const requestedDataset = dataset.value, requestedSplit = split.value
  requestedPage.value = page; query.value = term.trim()
  loading.value = true; error.value = ''; samples.value = null
  try {
    const result = await api.competitionSamples(requestedDataset, requestedSplit, query.value, page)
    if (active && request === sampleRequest && dataset.value === requestedDataset && split.value === requestedSplit) samples.value = result
  } catch (reason) {
    if (active && request === sampleRequest && dataset.value === requestedDataset && split.value === requestedSplit) error.value = describe(reason)
  } finally { if (active && request === sampleRequest) loading.value = false }
}
function reload() { void loadStatus(); void loadSamples(requestedPage.value) }
onMounted(() => { void loadStatus(); void loadSamples() })
onBeforeUnmount(() => { active = false; statusRequest++; sampleRequest++ })
</script>

<template>
  <div class="competition-data">
    <div class="competition-notice" role="note"><Icon name="info" :size="21" /><p><strong>中文医学信息抽取训练语料，非诊疗指南，不用于生成用药建议。</strong><br />数据来自脑启官方平台。此处仅浏览本站已导入的真实样本和标注，不向外发送健康记录或检索词。</p></div>

    <details class="panel competition-status" open>
      <summary>脑启官方平台 · 数据集导入情况</summary>
      <p v-if="statusLoading" class="competition-caption" role="status">正在读取导入统计…</p>
      <div v-else-if="statusError" class="notice error competition-error" role="alert"><span>{{ statusError }}</span><button class="text-button" @click="loadStatus">重试</button></div>
      <template v-else-if="status">
        <p v-if="status.notice" class="competition-caption">{{ status.notice }}</p>
        <p v-if="!status.datasets.length" class="competition-empty" role="status">尚未导入脑启平台数据。请先完成官方数据下载和本地导入；这里不会用示例数据代替真实样本。</p>
        <div v-else class="competition-datasets">
          <section v-for="item in status.datasets" :key="item.id" class="competition-dataset">
            <h3>{{ item.name }}</h3>
            <a v-if="sourceUrl(item.source_url)" :href="sourceUrl(item.source_url)" target="_blank" rel="noopener noreferrer">脑启官方来源 ↗</a>
            <p>已导入 <strong>{{ item.sample_count.toLocaleString('zh-CN') }}</strong> 条样本</p>
            <p class="competition-counts"><span>train：{{ item.split_counts.train.toLocaleString('zh-CN') }}</span><span>dev：{{ item.split_counts.dev.toLocaleString('zh-CN') }}</span><span>test：{{ item.split_counts.test.toLocaleString('zh-CN') }}</span></p>
            <p v-if="item.schema_count || item.entity_count"><span v-if="item.schema_count">{{ item.id === 'cmeee' ? '实体类别' : '关系类型' }}：{{ item.schema_count }}</span><span v-if="item.schema_count && item.entity_count"> · </span><span v-if="item.entity_count">{{ item.id === 'cmeee' ? '实体标注' : '实体索引' }}：{{ item.entity_count.toLocaleString('zh-CN') }}</span></p>
            <p class="competition-caption">导入时间：{{ importedAt(item.imported_at) }}（北京时间）</p>
            <details v-if="item.sha256" class="competition-hash"><summary>查看 SHA-256 校验值</summary><code>{{ item.sha256 }}</code></details>
            <p v-if="item.notice" class="competition-caption">{{ item.notice }}</p>
          </section>
        </div>
      </template>
    </details>

    <section class="panel competition-browser" aria-labelledby="competition-browser-heading">
      <h2 id="competition-browser-heading">查看原始样本与标注</h2>
      <form class="competition-filters" @submit.prevent="loadSamples(1, input)">
        <label class="field">数据集<select v-model="dataset" @change="loadSamples(1)"><option v-for="(name, id) in datasetNames" :key="id" :value="id">{{ name }}</option></select></label>
        <label class="field">数据划分<select v-model="split" @change="loadSamples(1)"><option v-for="(name, id) in splitNames" :key="id" :value="id">{{ name }}</option></select></label>
        <label class="field competition-query">本地关键词<input v-model="input" type="search" maxlength="80" placeholder="搜索样本文本，如：糖尿病" aria-describedby="competition-query-note" /></label>
        <button type="submit" class="button primary" :disabled="loading"><Icon name="search" :size="17" />查询</button>
      </form>
      <p id="competition-query-note" class="competition-caption">输入不会自动触发查询；提交后仅检索本站已导入语料。每页最多显示 10 条。</p>
      <p v-if="split === 'test'" class="competition-evaluation" role="note"><strong>当前为 test 评测集，仅用于评测，不混入训练。</strong>评测集可能不提供关系或实体标注；空标注不代表医学事实不存在。</p>
      <p v-else-if="split === 'dev'" class="competition-caption competition-split-note">当前为 dev 验证集，用于模型开发验证，请与训练集保持区分。</p>
      <div :aria-busy="loading">
        <p v-if="loading" class="competition-empty" role="status">正在读取 {{ datasetNames[dataset] }} · {{ splitNames[split] }}…</p>
        <div v-else-if="missingDataset" class="competition-empty" role="status"><p>所选数据集尚未导入。请先从脑启官方平台下载并完成本地导入，再读取真实样本。</p><button class="text-button" @click="reload">重新检查导入</button></div>
        <div v-else-if="error" class="notice error competition-error" role="alert"><span>{{ error }}</span><button class="text-button" @click="loadSamples(requestedPage)">重试</button></div>
        <template v-else-if="samples">
          <p v-if="samples.notice" class="competition-caption competition-split-note">{{ samples.notice }}</p>
          <p class="competition-result-count" role="status">{{ datasetNames[samples.dataset] }} · {{ splitNames[samples.split] }} · {{ query ? `“${query}”匹配 ` : '共 ' }}{{ samples.total.toLocaleString('zh-CN') }} 条</p>
          <div v-if="!samples.items.length" class="competition-empty"><Icon name="search" :size="28" /><p>{{ query ? '没有匹配的真实样本，请尝试其他关键词。' : '当前划分暂无已导入样本，请检查官方文件与导入情况。' }}</p><button v-if="query" class="text-button" @click="input = ''; loadSamples(1, '')">清除关键词</button></div>
          <div v-else class="competition-samples">
            <article v-for="(sample, index) in samples.items" :key="sample.id" class="competition-sample">
              <div class="competition-sample-heading"><h3>样本 {{ (samples.page - 1) * samples.page_size + index + 1 }}</h3><span>{{ sample.dataset.toUpperCase() }} · {{ sample.split }}</span></div>
              <p lang="zh-CN" class="competition-sample-text">{{ sample.text }}</p>
              <template v-if="sample.relations.length"><h4>关系标注</h4><ul class="competition-relations"><li v-for="(relation, relationIndex) in sample.relations" :key="relationIndex"><span>{{ relation.subject }}<small v-if="relation.subject_type">（{{ relation.subject_type }}）</small></span><span class="competition-predicate">→ {{ relation.predicate }} →</span><span>{{ relation.object }}<small v-if="relation.object_type">（{{ relation.object_type }}）</small></span></li></ul></template>
              <template v-if="sample.entities.length"><h4>实体标注</h4><ul class="competition-entities"><li v-for="(entity, entityIndex) in sample.entities" :key="entityIndex"><strong>{{ entity.text }}</strong><span>{{ entity.type }}</span><small>位置 {{ entity.start }}–{{ entity.end }}</small></li></ul></template>
              <p v-if="!sample.relations.length && !sample.entities.length" class="competition-caption">{{ sample.split === 'test' ? '此评测样本未提供标注。' : '此样本未提供关系或实体标注。' }}</p>
            </article>
          </div>
          <nav v-if="samples.total" class="competition-pagination" aria-label="参赛数据分页"><span>第 {{ samples.page }} / {{ pageCount }} 页</span><div><button class="button secondary small" :disabled="samples.page <= 1" @click="loadSamples(samples.page - 1)">上一页</button><button class="button secondary small" :disabled="samples.page >= pageCount" @click="loadSamples(samples.page + 1)">下一页</button></div></nav>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.competition-data { min-width: 0; overflow-wrap: anywhere; }
.competition-notice { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 22px; padding: 16px 20px; background: var(--primary-tint); border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 13px; line-height: 1.9; color: var(--ink-soft); }
.competition-notice svg { flex-shrink: 0; margin-top: 4px; color: var(--primary); }
.competition-notice p { margin: 0; }
.competition-status, .competition-browser { padding: 22px 24px; }
.competition-status > summary { cursor: pointer; font-weight: 600; }
.competition-status > .competition-caption, .competition-status > .competition-error { margin-top: 16px; }
.competition-caption { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.8; }
.competition-datasets { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 18px; }
.competition-dataset { min-width: 0; padding: 17px; border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 13px; }
.competition-dataset h3 { margin: 0 0 8px; font-size: 15px; }
.competition-dataset p { margin: 9px 0 0; line-height: 1.8; }
.competition-counts { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--ink-soft); }
.competition-hash { margin-top: 12px; font-size: 12px; color: var(--muted); }
.competition-hash summary { cursor: pointer; }
.competition-hash code { display: block; margin-top: 8px; white-space: normal; word-break: break-all; line-height: 1.8; }
.competition-browser { margin-top: 22px; }
.competition-browser h2 { margin: 0 0 20px; font-size: 19px; }
.competition-filters { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, .8fr) minmax(0, 1.5fr) auto; align-items: end; gap: 12px; }
.competition-filters .field { min-width: 0; margin: 0; }
.competition-filters input, .competition-filters select { min-width: 0; width: 100%; }
.competition-filters .button { min-height: 44px; }
.competition-filters + .competition-caption { margin-top: 12px; }
.competition-evaluation { margin: 18px 0; padding: 12px 16px; border: 1px solid var(--amber-soft); border-radius: var(--radius-sm); background: var(--amber-tint); font-size: 13px; line-height: 1.8; }
.competition-split-note { margin-top: 14px; }
.competition-result-count { color: var(--muted); font-size: 13px; margin: 20px 0 14px; line-height: 1.8; }
.competition-empty { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 32px 8px; text-align: center; font-size: 13px; color: var(--muted); line-height: 1.8; }
.competition-empty p { margin: 0; }
.competition-error { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 20px; }
.competition-samples { display: grid; gap: 16px; }
.competition-sample { min-width: 0; padding: 20px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface-soft); }
.competition-sample-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; align-items: center; }
.competition-sample-heading h3 { margin: 0; font-size: 14px; }
.competition-sample-heading > span { color: var(--muted); font-size: 11px; }
.competition-sample-text { white-space: pre-wrap; font-size: 14px; line-height: 1.9; margin: 14px 0; }
.competition-sample h4 { margin: 18px 0 10px; font-size: 12px; color: var(--muted); }
.competition-relations, .competition-entities { list-style: none; padding: 0; margin: 0; font-size: 13px; }
.competition-relations { display: grid; gap: 9px; }
.competition-relations li { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; line-height: 1.8; }
.competition-relations small { color: var(--muted); font-size: 11px; }
.competition-predicate { color: var(--primary-deep); }
.competition-entities { display: flex; flex-wrap: wrap; gap: 8px; }
.competition-entities li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 5px 8px; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius-xs); background: var(--surface); }
.competition-entities li > span { color: var(--primary-deep); }
.competition-entities small { font-size: 11px; color: var(--muted); }
.competition-pagination { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px; padding-top: 22px; color: var(--muted); font-size: 12px; }
.competition-pagination > div { display: flex; gap: 8px; flex-wrap: wrap; }
.competition-data a { color: var(--primary-deep); text-decoration: underline; text-underline-offset: 3px; }
.competition-data button:focus-visible, .competition-data a:focus-visible, .competition-data summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; }
@media (max-width: 800px) { .competition-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 540px) {
  .competition-datasets, .competition-filters { grid-template-columns: minmax(0, 1fr); }
  .competition-status, .competition-browser { padding: 18px 14px; }
  .competition-notice { padding: 14px; font-size: 12px; }
  .competition-sample, .competition-dataset { padding: 14px; }
  .competition-filters .button { width: 100%; }
}
</style>
