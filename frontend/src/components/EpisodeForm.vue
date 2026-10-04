<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ApiError, api } from '../api'
import { today, severityLabels } from '../format'
import type { Episode, EpisodeInput } from '../types'
import Icon from './Icon.vue'

const props = defineProps<{ episode?: Episode }>()
const emit = defineEmits<{ saved: [episode: Episode]; dirty: []; busy: [value: boolean] }>()
const initial = props.episode
const form = reactive<EpisodeInput>({
  chief_complaint: initial?.chief_complaint ?? '', symptoms: [...(initial?.symptoms ?? [])],
  severity: initial?.severity ?? 2, started_at: initial?.started_at ?? today(), ended_at: initial?.ended_at ?? null,
  status: initial?.status ?? 'ongoing', outcome: initial?.outcome ?? 'ongoing',
  vitals: { temperature: initial?.vitals.temperature ?? null, heart_rate: initial?.vitals.heart_rate ?? null, spo2: initial?.vitals.spo2 ?? null },
  medications: initial?.medications.map(m => ({ ...m })) ?? [], notes: initial?.notes ?? '',
})
const version = ref(initial?.version)
const loading = ref(false)
const error = ref('')
const conflict = ref(false)
const customSymptom = ref('')
const commonSymptoms = ['发热', '咳嗽', '咽痛', '流鼻涕', '头痛', '头晕', '乏力', '恶心', '腹痛', '腹泻', '胸痛', '呼吸困难', '意识不清', '抽搐', '大出血', '口角歪斜', '言语不清']
const extraSymptoms = computed(() => form.symptoms.filter(s => !commonSymptoms.includes(s)))
watch(form, () => emit('dirty'), { deep: true })
watch(() => form.status, value => {
  if (value === 'ended') { form.ended_at = form.ended_at || today() }
  else form.ended_at = null
})
function toggleSymptom(symptom: string) {
  const i = form.symptoms.indexOf(symptom)
  if (i >= 0) form.symptoms.splice(i, 1)
  else if (form.symptoms.length < 20) form.symptoms.push(symptom)
  else error.value = '每条记录最多添加 20 个症状。'
}
function addSymptom() {
  const value = customSymptom.value.trim()
  if (!value) return
  if (!form.symptoms.includes(value)) toggleSymptom(value)
  customSymptom.value = ''
}
function numberOrNull(value: unknown) { return value === '' || value === null ? null : Number(value) }
async function save() {
  if (loading.value || conflict.value) return
  if (form.ended_at && form.ended_at < form.started_at) { error.value = '结束日期不能早于开始日期。'; return }
  const input: EpisodeInput = {
    ...form, chief_complaint: form.chief_complaint.trim(), symptoms: [...form.symptoms],
    ended_at: form.status === 'ongoing' ? null : form.ended_at,
    vitals: { temperature: numberOrNull(form.vitals.temperature), heart_rate: numberOrNull(form.vitals.heart_rate), spo2: numberOrNull(form.vitals.spo2) },
    medications: form.medications.map(m => ({ name: m.name.trim(), dose: m.dose.trim(), frequency: m.frequency.trim() })),
  }
  loading.value = true; emit('busy', true); error.value = ''
  try {
    const saved = initial ? await api.update(initial.id, input, version.value!) : await api.create(input)
    emit('saved', saved)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败，请重试。'
    conflict.value = e instanceof ApiError && e.status === 409
  } finally { loading.value = false; emit('busy', false) }
}
async function reload() {
  if (!initial || !window.confirm('重新载入会替换你在此页面尚未保存的修改，继续吗？')) return
  loading.value = true; emit('busy', true)
  try {
    const latest = await api.episode(initial.id)
    Object.assign(form, latest, { symptoms: [...latest.symptoms], medications: latest.medications.map(m => ({ ...m })), vitals: { ...latest.vitals } })
    version.value = latest.version; conflict.value = false; error.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : '载入失败，请重试。' }
  finally { loading.value = false; emit('busy', false) }
}
</script>

<template>
  <form class="episode-form" @submit.prevent="save">
    <fieldset :disabled="loading">
      <div class="form-section"><div class="section-number">01</div><div><h3>这次感觉怎么样？</h3><p>用自己的话，记录身体的变化。</p></div></div>
      <label class="field">主要不适 <span class="required">*</span><input v-model="form.chief_complaint" required maxlength="200" placeholder="例如：从昨晚开始头痛，还有些乏力" /></label>
      <div class="field"><span id="symptoms-label">症状标签 <span class="field-hint">可多选</span></span><div class="symptom-options" role="group" aria-labelledby="symptoms-label"><button v-for="symptom in [...commonSymptoms, ...extraSymptoms]" :key="symptom" type="button" class="symptom-chip" :class="{ selected: form.symptoms.includes(symptom) }" :aria-pressed="form.symptoms.includes(symptom)" @click="toggleSymptom(symptom)">{{ symptom }}<Icon v-if="form.symptoms.includes(symptom)" name="check" :size="13" /></button></div></div>
      <div class="inline-field"><input v-model="customSymptom" maxlength="50" aria-label="自定义症状" placeholder="其他症状，自己添加" @keydown.enter.prevent="addSymptom" /><button class="button secondary small" type="button" :disabled="!customSymptom.trim()" @click="addSymptom"><Icon name="plus" :size="15" />添加</button></div>
      <div class="field severity-field"><span id="severity-label">不适程度 <span class="field-hint">主观感受，不代表医学分级</span></span><div class="severity-options" role="group" aria-labelledby="severity-label"><button v-for="(label, index) in severityLabels" :key="label" type="button" :class="{ selected: form.severity === index + 1 }" :aria-pressed="form.severity === index + 1" @click="form.severity = index + 1"><span>{{ index + 1 }}</span>{{ label }}</button></div></div>
      <div class="form-grid"><label class="field">开始日期 <span class="required">*</span><input v-model="form.started_at" type="date" :max="today()" required /></label><label class="field">记录状态<select v-model="form.status"><option value="ongoing">仍在持续</option><option value="ended">已经结束</option></select></label><label v-if="form.status === 'ended'" class="field">结束日期 <span class="required">*</span><input v-model="form.ended_at" type="date" :min="form.started_at" :max="today()" required /></label><label class="field">目前变化<select v-model="form.outcome"><option value="ongoing">仍在观察</option><option value="improving">有所好转</option><option value="resolved">症状已消失</option><option value="worsened">有所加重</option></select></label></div>
      <div class="form-divider"></div>
      <div class="form-section"><div class="section-number">02</div><div><h3>补充一些细节 <span class="field-hint">选填</span></h3><p>填入实际测量的数据，没有测量可以留空。</p></div></div>
      <div class="form-grid vitals-grid"><label class="field">体温 <span class="field-hint">°C</span><input v-model="form.vitals.temperature" type="number" inputmode="decimal" min="30" max="45" step="0.1" placeholder="未填写" /></label><label class="field">心率 <span class="field-hint">次 / 分</span><input v-model="form.vitals.heart_rate" type="number" inputmode="numeric" min="20" max="250" step="1" placeholder="未填写" /></label><label class="field">血氧 <span class="field-hint">%</span><input v-model="form.vitals.spo2" type="number" inputmode="numeric" min="50" max="100" step="1" placeholder="未填写" /></label></div>
      <div class="field"><span>用药记录 <span class="field-hint">仅记录实际用药，不提供用药建议</span></span><div v-for="(medication, index) in form.medications" :key="index" class="medication-row"><label><span class="sr-only">药品名称 {{ index + 1 }}</span><input v-model="medication.name" required maxlength="100" placeholder="药品名称" /></label><label><span class="sr-only">用量 {{ index + 1 }}</span><input v-model="medication.dose" maxlength="100" placeholder="每次用量" /></label><label><span class="sr-only">频率 {{ index + 1 }}</span><input v-model="medication.frequency" maxlength="100" placeholder="使用频率" /></label><button class="icon-button" type="button" :aria-label="`移除第 ${index + 1} 条用药记录`" @click="form.medications.splice(index, 1)"><Icon name="close" :size="16" /></button></div><button v-if="form.medications.length < 20" class="add-medication" type="button" @click="form.medications.push({ name: '', dose: '', frequency: '' })"><Icon name="plus" :size="16" />添加用药</button></div>
      <label class="field">其他想记下的事<textarea v-model="form.notes" rows="3" maxlength="3000" placeholder="例如：当天饮食、作息、就诊经过，或医生的嘱咐"></textarea><span class="character-count">{{ form.notes.length }} / 3000</span></label>
    </fieldset>
    <div v-if="error" class="notice error" role="alert">{{ error }}<button v-if="conflict" type="button" class="text-button" :disabled="loading" @click="reload">重新载入最新记录</button></div>
    <div class="form-footer"><p><Icon name="shield" :size="15" /> 保存后仅你登录的账号可见</p><button class="button primary" :disabled="loading || conflict"><Icon name="check" :size="18" />{{ loading ? '正在保存…' : initial ? '保存修改' : '保存这次记录' }}</button></div>
  </form>
</template>
