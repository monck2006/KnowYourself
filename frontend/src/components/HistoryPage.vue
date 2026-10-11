<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { exportEpisodeCsv } from '../api'
import { dateLabel, outcomeLabels } from '../format'
import { selectEpisodes, type JournalFilters } from '../journal'
import type { Episode } from '../types'
import Icon from './Icon.vue'

const props = defineProps<{ episodes: Episode[]; loading: boolean }>()
const emit = defineEmits<{ open: [episode: Episode]; create: []; notify: [message: string]; report: [episodes: Episode[]] }>()
const defaults: JournalFilters = { search: '', status: 'all', from: '', to: '', sort: 'newest' }
const filters = reactive({ ...defaults })
const currentPage = ref(1)
const pageSize = 12
const exporting = ref(false)
const exportError = ref('')
const filtered = computed(() => selectEpisodes(props.episodes, filters))
const invalidDates = computed(() => !!filters.from && !!filters.to && filters.from > filters.to)
const hasFilters = computed(() => !!(filters.search || filters.from || filters.to || filters.status !== 'all'))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visible = computed(() => filtered.value.slice((currentPage.value - 1) * pageSize, currentPage.value * pageSize))
watch(filters, () => { currentPage.value = 1 })
watch(pageCount, count => { currentPage.value = Math.min(currentPage.value, count) })
function reset() { Object.assign(filters, defaults); exportError.value = '' }
async function exportCsv() {
  if (exporting.value || !filtered.value.length) return
  exporting.value = true; exportError.value = ''
  try { await exportEpisodeCsv(filtered.value); emit('notify', '所选记录的 CSV 文件已生成') }
  catch (e) { exportError.value = e instanceof Error ? e.message : '导出失败，请重试。' }
  finally { exporting.value = false }
}
</script>

<template>
  <section class="page-heading"><div><span class="eyebrow">YOUR HEALTH JOURNAL</span><h1>每一次记录，都有意义。</h1><p>回顾身体的变化，把你的健康经历串联起来。</p></div></section>
  <section class="panel history-panel" :aria-busy="loading">
    <div class="history-toolbar">
      <div class="filter-tabs" role="group" aria-label="按记录状态筛选">
        <button v-for="(label, status) in { all: '全部记录', ongoing: '持续中', ended: '已结束' }" :key="status" :class="{ active: filters.status === status }" :aria-pressed="filters.status === status" @click="filters.status = status">{{ label }}<span v-if="status === 'all'">{{ episodes.length }}</span></button>
      </div>
      <label class="search-field"><Icon name="search" :size="17" /><input v-model="filters.search" type="search" aria-label="搜索健康记录" placeholder="搜索症状、用药或笔记" /></label>
    </div>
    <div class="journal-filters">
      <label class="field">开始日期从<input v-model="filters.from" type="date" :max="filters.to || undefined" /></label>
      <label class="field">开始日期至<input v-model="filters.to" type="date" :min="filters.from || undefined" /></label>
      <label class="field">排序方式<select v-model="filters.sort" aria-label="排序方式"><option value="newest">开始日期：最新在前</option><option value="oldest">开始日期：最早在前</option><option value="updated">最近修改在前</option><option value="severity">不适程度：从高到低</option></select></label>
      <div class="journal-filter-actions"><button class="button secondary small" :disabled="loading || !filtered.length" @click="emit('report', filtered)"><Icon name="print" :size="16" />就诊摘要</button><button v-if="hasFilters" class="text-button" @click="reset">清除筛选</button><button class="button secondary small" :disabled="exporting || loading || !filtered.length" @click="exportCsv"><Icon name="download" :size="16" />{{ exporting ? '正在导出…' : '导出所选 CSV' }}</button></div>
    </div>
    <p v-if="invalidDates" class="notice error" role="alert">开始日期范围有误，“从”不能晚于“至”。</p>
    <p v-if="exportError" class="notice error" role="alert">{{ exportError }}</p>
    <div v-if="loading && !episodes.length" class="empty-state"><p>正在读取你的记录…</p></div>
    <div v-else-if="!filtered.length" class="empty-state"><span class="empty-icon"><Icon :name="episodes.length ? 'search' : 'book'" :size="29" /></span><h3>{{ episodes.length ? '没有找到符合条件的记录' : '给身体的变化，留一个位置' }}</h3><p>{{ episodes.length ? '试试其他关键词、日期范围或记录状态。' : '从第一次记录开始，让每一段经历都清晰可回顾。' }}</p><button v-if="!episodes.length" class="button secondary small" @click="emit('create')"><Icon name="plus" :size="16" />新增一条记录</button><button v-else class="text-button" @click="reset">清除筛选条件</button></div>
    <div v-else class="history-list">
      <button v-for="episode in visible" :key="episode.id" class="history-row" @click="emit('open', episode)"><div class="history-date"><span>{{ episode.started_at.slice(0, 4) }}</span><strong>{{ dateLabel(episode.started_at) }}</strong></div><div class="history-body"><div class="history-title"><h3>{{ episode.chief_complaint }}</h3><span v-if="episode.analysis.level === 'emergency'" class="urgent-dot" title="有紧急风险提示">需及时关注</span></div><div class="tag-list"><span v-for="symptom in episode.symptoms.slice(0, 4)" :key="symptom" class="tag">{{ symptom }}</span><span v-if="episode.symptoms.length > 4" class="tag">+{{ episode.symptoms.length - 4 }}</span><span v-if="!episode.symptoms.length" class="muted">未添加症状标签</span></div></div><div class="history-state"><span class="badge" :class="episode.status">{{ episode.status === 'ongoing' ? '持续中' : '已结束' }}</span><small>{{ outcomeLabels[episode.outcome] }}</small></div><Icon name="chevron" :size="17" /></button>
    </div>
    <div v-if="filtered.length" class="history-total journal-pagination"><span role="status">共 {{ filtered.length }} 条 · 第 {{ currentPage }} / {{ pageCount }} 页</span><nav v-if="pageCount > 1" aria-label="健康记录分页"><button class="button secondary small" :disabled="currentPage === 1" @click="currentPage--">上一页</button><button class="button secondary small" :disabled="currentPage === pageCount" @click="currentPage++">下一页</button></nav></div>
    <p class="small-note journal-export-note">CSV 导出当前筛选的所有记录，包含健康信息。完整备份可在「账号与数据」导出 JSON。</p>
  </section>
</template>
