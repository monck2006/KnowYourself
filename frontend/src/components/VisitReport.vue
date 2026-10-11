<script setup lang="ts">
import { computed, ref } from 'vue'
import { isNative, saveTextFile } from '../api'
import { outcomeLabels, severityLabels, today } from '../format'
import { buildVisitSummary, visitReportDocument } from '../visitReport'
import type { Episode, User } from '../types'
import reportStyles from '../visitReport.css?raw'
import '../visitReport.css'
import Icon from './Icon.vue'

const props = defineProps<{ episodes: Episode[]; user: User; scope: string }>()
const emit = defineEmits<{ busy: [value: boolean]; notify: [message: string] }>()
const summary = computed(() => buildVisitSummary(props.episodes))
const questions = ref('')
const reportElement = ref<HTMLElement>()
const exporting = ref(false)
const error = ref('')
const generatedAt = new Date().toLocaleString('zh-CN')
function measured(value: number | null, unit: string): string { return value == null ? '未填写' : `${value} ${unit}` }
function printReport() {
  error.value = ''
  try { window.print() }
  catch { error.value = '当前环境无法打开打印，请下载 HTML 后使用浏览器打开。' }
}
async function download() {
  if (exporting.value || !reportElement.value) return
  exporting.value = true; emit('busy', true); error.value = ''
  try {
    // The body is serialized from Vue's escaped text bindings; it contains no scripts or external resources.
    const html = visitReportDocument(reportElement.value.outerHTML, reportStyles, props.user.display_name)
    await saveTextFile(`知己就诊摘要-${today()}.html`, html, 'text/html')
    emit('notify', isNative ? '摘要已交给系统分享面板' : '就诊摘要已下载，可离线打开和打印')
  } catch (e) { error.value = e instanceof Error ? e.message : '导出失败，请重试。' }
  finally { exporting.value = false; emit('busy', false) }
}
</script>

<template>
  <div class="report-preview">
    <div class="report-toolbar">
      <p>摘要包含 {{ summary.count }} 条记录。报告包含健康信息，请妥善保存。</p>
      <div class="report-buttons">
        <button v-if="!isNative" class="button primary small" :disabled="exporting" @click="printReport"><Icon name="print" :size="17" />打印 / 保存 PDF</button>
        <button class="button secondary small" :disabled="exporting" @click="download"><Icon name="download" :size="17" />{{ exporting ? '正在导出…' : '下载 HTML' }}</button>
      </div>
      <label class="field report-questions-input">就诊时想问的问题（选填）<textarea v-model="questions" rows="2" maxlength="2000" :disabled="exporting" placeholder="例如：希望向医生补充或确认的事情。只加入本次摘要，不写入健康记录。"></textarea></label>
      <p v-if="!isNative" class="small-note">点击打印后，可在浏览器打印窗口中选择“另存为 PDF”。</p>
      <p v-else class="small-note">下载后可在系统浏览器中打开 HTML，再使用系统打印功能。</p>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    </div>
    <article ref="reportElement" class="visit-report" aria-label="就诊摘要正文">
      <header class="visit-report-header">
        <p class="visit-report-brand">知己 · KNOW YOURSELF</p>
        <h1>个人健康记录 · 就诊摘要</h1>
        <p><strong>{{ user.display_name }}</strong><span>生成时间：{{ generatedAt }}</span></p>
      </header>
      <p class="visit-report-notice">来源：本人手动填写的健康记录。本摘要用于说明个人经历，不是医疗机构出具的病历或诊断。未填写的数据不表示正常；状态反映最后一次保存的内容。</p>
      <section class="visit-report-summary">
        <h2>记录范围</h2>
        <p>{{ scope }} · 共 {{ summary.count }} 条，持续中 {{ summary.ongoingCount }} 条，已结束 {{ summary.endedCount }} 条。</p>
        <p v-if="summary.firstDate">所选记录的开始日期：{{ summary.firstDate }} 至 {{ summary.lastDate }}。</p>
        <div class="visit-report-overview">
          <div><h3>填写过的症状</h3><p>{{ summary.symptoms.map(item => `${item.name}（${item.count} 条）`).join('、') || '未填写症状标签' }}</p></div>
          <div><h3>填写过的用药</h3><p>{{ summary.medications.map(item => `${item.name}（${item.count} 条）`).join('、') || '未填写用药信息' }}</p></div>
        </div>
        <p class="visit-report-muted">次数按包含该项的记录条数统计；用药内容为本人填写，不能据此判断疗效或调整用药。</p>
      </section>
      <section v-if="questions.trim()" class="visit-report-questions"><h2>就诊时想问的问题</h2><p>{{ questions.trim() }}</p></section>
      <section class="visit-report-records">
        <h2>病程明细 · 按开始日期排列</h2>
        <article v-for="(episode, index) in summary.records" :key="episode.id" class="visit-report-episode">
          <h3>{{ index + 1 }}. {{ episode.chief_complaint }}</h3>
          <dl class="visit-report-facts">
            <div><dt>开始 / 结束</dt><dd>{{ episode.started_at }} / {{ episode.ended_at || '尚未结束' }}</dd></div>
            <div><dt>记录状态 / 变化</dt><dd>{{ episode.status === 'ongoing' ? '持续中' : '已结束' }} / {{ outcomeLabels[episode.outcome] }}</dd></div>
            <div><dt>症状标签</dt><dd>{{ episode.symptoms.join('、') || '未填写' }}</dd></div>
            <div><dt>主观不适程度</dt><dd>{{ episode.severity }} / 5 · {{ severityLabels[episode.severity - 1] }}</dd></div>
          </dl>
          <p class="visit-report-measurements"><strong>手动测量：</strong>体温 {{ measured(episode.vitals.temperature, '°C') }}；心率 {{ measured(episode.vitals.heart_rate, '次/分') }}；血氧 {{ measured(episode.vitals.spo2, '%') }}。测量的具体时刻未记录。</p>
          <div class="visit-report-medications">
            <h4>用药记录</h4>
            <table v-if="episode.medications.length"><thead><tr><th scope="col">名称</th><th scope="col">每次用量</th><th scope="col">使用频率</th></tr></thead><tbody><tr v-for="(medication, medicationIndex) in episode.medications" :key="medicationIndex"><td>{{ medication.name }}</td><td>{{ medication.dose || '未填写' }}</td><td>{{ medication.frequency || '未填写' }}</td></tr></tbody></table>
            <p v-else>未填写用药信息。</p>
          </div>
          <div v-if="episode.notes" class="visit-report-notes"><h4>补充笔记</h4><p>{{ episode.notes }}</p></div>
          <p class="visit-report-muted">最近保存：{{ new Date(episode.updated_at).toLocaleString('zh-CN') }}</p>
        </article>
      </section>
      <footer class="visit-report-footer">此摘要仅包含本次选择的记录。健康记录以本人实际填写为准，请在就诊时补充最新情况。</footer>
    </article>
  </div>
</template>
