<script setup lang="ts">
import { ref } from 'vue'
import type { Episode } from '../types'
import ConversationIntake from './ConversationIntake.vue'

const props = defineProps<{ userId: number | string; active?: boolean }>()
const emit = defineEmits<{ saved: [episode: Episode, silent?: boolean]; dirty: [value: boolean]; busy: [value: boolean] }>()
const intakeKey = ref(0)
const intake = ref<InstanceType<typeof ConversationIntake>>()
const dirty = ref(false)
function newConsultation() {
  if (dirty.value && !window.confirm('开始新问诊会清空当前对话，确定继续吗？')) return
  try { localStorage.removeItem(`zhiji.intake.session.${props.userId}`) } catch { /* local storage may be unavailable */ }
  intakeKey.value += 1; dirty.value = false; emit('dirty', false)
}
function prefill(text: string) { intake.value?.prefill(text) }
defineExpose({ newConsultation, prefill })
</script>

<template>
  <section class="consultation-home">
    <ConversationIntake ref="intake" :key="`${props.userId}-${intakeKey}`" :user-id="props.userId" :active="props.active" @saved="(episode, silent) => emit('saved', episode, silent)" @dirty="dirty = $event; emit('dirty', $event)" @busy="$emit('busy', $event)" />
  </section>
</template>

<style scoped>
.consultation-home { max-width: 800px; margin: 0 auto; }
.consultation-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin:0 0 20px; }
.consultation-caption { color:var(--faint); font-size:12px; letter-spacing:.04em; }
.new-conversation { display:flex; align-items:center; gap:5px; min-height:38px; padding:7px 12px; border:1px solid var(--border); border-radius:10px; color:var(--ink-soft); background:var(--surface); font-size:12px; }
.new-conversation:hover { color:var(--primary); border-color:var(--primary); }
@media(min-width:901px) {
  .consultation-home { display:flex; flex-direction:column; height:100%; min-height:420px; }
}
@media(max-width:640px) { .consultation-heading { margin-bottom:6px; }.consultation-caption { font-size:11px; } }
</style>
