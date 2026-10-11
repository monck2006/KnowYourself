<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, api } from '../api'
import { emptyIntakeDraft, intakeDraftToEpisodeInput } from '../episodeInput'
import type { Analysis, Assessment, Episode, IntakeContext, IntakeDraft } from '../types'
import Icon from './Icon.vue'
import ConsultationAction from './ConsultationAction.vue'

type Task = 'chief_complaint' | 'severity' | 'symptoms' | 'started_at' | string
interface CardDef { key: string; label: string; title: string; help?: string; options: string[]; multi?: boolean }
type ChatMessage = { role: 'assistant' | 'user'; text: string }
type Attachment = { name: string; kind: 'image' | 'camera' }
type ActionRow = { priority: 'now' | 'today' | 'observe'; title: string; detail: string }
type ActionView = {
  level: 'emergency' | 'attention' | 'recorded'
  label: string; summary: string; reasons: string[]
  actions: ActionRow[]
  sources: { title: string; url: string }[]
  knowledge: { id?: string; title: string; excerpt: string; source_url: string; source?: string }[]
  monitoring: { next_check_in: string; escalation_signs: string[] } | null
  facts: { complaint: string; startedAt: string }
}
type CardValue = string | string[]
interface Working { complaintValue: string; severityIndex: number | null; symptomOptions: string[]; symptomPresent: string[]; symptomAbsent: string[]; dateValue: string; cardAnswers: Record<string, CardValue> }

const props = defineProps<{ userId: number | string; active?: boolean }>()
const emit = defineEmits<{ saved: [episode: Episode, silent?: boolean]; dirty: [value: boolean]; busy: [value: boolean] }>()
const storageKey = computed(() => `zhiji.intake.session.${props.userId}`)
const TASK_ORDER: Task[] = ['chief_complaint', 'severity', 'symptoms', 'started_at']
/** Choice cards the model may open; each has a fixed set of options the user taps. */
const CARDS: Record<string, CardDef> = {
  location: { key: 'location', label: '不适部位', title: '主要哪个部位不舒服？', options: ['头/面部', '咽喉/颈部', '胸部', '腹部', '腰背', '四肢/关节', '全身', '不好说'] },
  character: { key: 'character', label: '不适性质', title: '更接近哪种感觉？', options: ['胀/闷', '刺痛', '钝痛', '灼热', '酸胀', '痒', '麻木', '说不清'] },
  duration: { key: 'duration', label: '变化趋势', title: '这几天在怎么变化？', options: ['一直持续', '时好时坏', '逐渐加重', '逐渐减轻', '已经好转'] },
  sleep: { key: 'sleep', label: '睡眠', title: '这几天睡得怎么样？', options: ['基本正常', '入睡困难', '容易醒', '明显睡不够', '说不清'] },
  appetite: { key: 'appetite', label: '食欲', title: '食欲和进食有变化吗？', options: ['正常', '吃得少', '完全不想吃', '恶心想吐', '说不清'] },
  hydration: { key: 'hydration', label: '饮水', title: '喝水和排尿正常吗？', options: ['正常', '喝得比平时少', '喝不下', '尿量明显减少', '说不清'] },
  triggers: { key: 'triggers', label: '可能诱因', title: '起病前后有没有这些情况？', options: ['受凉/淋雨', '劳累/熬夜', '饮食刺激', '身体接触/外伤', '没有明显诱因', '说不清'] },
  exposure: { key: 'exposure', label: '接触史', title: '近期接触过有相似症状的人吗？', options: ['有', '没有', '不确定'] },
  history: { key: 'history', label: '既往类似', title: '以前出现过类似情况吗？', options: ['第一次', '偶尔有过', '经常反复', '说不清'] },
  medications: { key: 'medications', label: '用药', title: '这几天有没有用药？', options: ['没用药', '用了常用药', '用了新药', '自行加量', '记不清'] },
  measures: { key: 'measures', label: '体征', title: '有没有量过体温、血氧或心率？', options: ['量过体温', '量过血氧', '量过心率', '没量过'] },
  impact: { key: 'impact', label: '生活影响', title: '对日常生活有影响吗？', options: ['基本不影响', '有些影响', '影响挺大', '说不清'] },
  other: { key: 'other', label: '其他补充', title: '还有想补充的吗？', options: ['暂时没有了'] },
}
/** Tools that open an interactive box on the client: the 4 core questions, all choice cards, and the action box. */
const DIALOG_TOOLS: string[] = [...TASK_ORDER, ...Object.keys(CARDS), 'next_step', 'none']
const levels = [
  { title: '几乎没感觉', help: '现在几乎感觉不到不舒服。' },
  { title: '略微不适', help: '能感觉到，但目前还应付得来。' },
  { title: '有些难受', help: '不舒服的感觉比较明显。' },
  { title: '明显难受', help: '不适感很强，较难忽略。' },
  { title: '很难受', help: '感觉比较难忍受。' },
]

const messages = ref<ChatMessage[]>([])
const draft = ref<IntakeDraft>(emptyIntakeDraft())
const input = ref('')
const attachments = ref<Attachment[]>([])
const task = ref<Task | null>(null)
const resumeTask = ref<Task | null>(null)
const editing = ref(false)
const stash = ref<Working | null>(null)
const missing = ref<string[]>([])
const complaintValue = ref('')
const severityIndex = ref<number | null>(null)
const symptomOptions = ref<string[]>([])
const symptomPresent = ref<string[]>([])
const symptomAbsent = ref<string[]>([])
const dateValue = ref('')
const cardAnswers = ref<Record<string, CardValue>>({})
const turns = ref(0)
const consent = ref(true) // 云端发送范围已在注册时的隐私协议中说明并同意，此处不再单独勾选。
const busy = ref(false)
const saving = ref(false)
const recordSaved = ref(false)
const episodeId = ref('')
const episodeVersion = ref(1)
const error = ref('')
const notice = ref('')
const conflict = ref(false)
const modelReady = ref<boolean | null>(null)
const cloud = ref(false)
const capabilities = ref<{ text: boolean; images: boolean; audio: boolean } | null>(null)
const modelNotice = ref('')
const action = ref<ActionView | null>(null)
const lastContext = ref<IntakeContext | null>(null)
const lastMessage = ref('')
const voiceSupported = ref(false)
const listening = ref(false)
const voiceError = ref('')
const attachOpen = ref(false)
const thread = ref<HTMLElement>()
const imageInput = ref<HTMLInputElement>()
const cameraInput = ref<HTMLInputElement>()
let recognition: any = null
let active = true
let persistTimer: ReturnType<typeof setTimeout> | undefined
let typeTimer: ReturnType<typeof setTimeout> | undefined

// Random empty-state invitation, revealed with a typewriter effect.
const INVITES = [
  '哪里不舒服？我们慢慢说。',
  '慢慢讲，我在听。',
  '今天身体怎么样？',
  '哪儿难受，说说看。',
  '别急，一件一件说清楚。',
  '把感觉讲给我，我帮你理一理。',
  '身体哪里不对劲？',
  '说说看，是哪里不舒服。',
]
const inviteText = ref('')
function reducedMotion() { return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches }
function typeInvite() {
  clearTimeout(typeTimer)
  const phrase = INVITES[Math.floor(Math.random() * INVITES.length)]
  if (reducedMotion()) { inviteText.value = phrase; return }
  inviteText.value = ''
  let index = 0
  const step = () => {
    if (!active) return
    inviteText.value = phrase.slice(0, ++index)
    if (index < phrase.length) typeTimer = setTimeout(step, 55)
  }
  typeTimer = setTimeout(step, 300)
}

const severityLabel = computed(() => draft.value.severity == null ? '' : levels[draft.value.severity - 1]?.title || '')
const extraCards = computed(() => Object.entries(cardAnswers.value)
  .filter(([key, value]) => CARDS[key] && (Array.isArray(value) ? value.length : !!value))
  .map(([key, value]) => ({ key, label: CARDS[key].label, value: Array.isArray(value) ? value.join('、') : value as string })))
const results = computed(() => [
  ...(draft.value.chief_complaint ? [{ key: 'chief_complaint', label: '主要不适', value: draft.value.chief_complaint }] : []),
  ...(draft.value.symptoms.length ? [{ key: 'symptoms', label: '症状', value: draft.value.symptoms.join('、') }] : []),
  ...(draft.value.started_at ? [{ key: 'started_at', label: '开始时间', value: humanDate(draft.value.started_at) }] : []),
  ...(draft.value.severity != null ? [{ key: 'severity', label: '不适程度', value: severityLabel.value }] : []),
  ...extraCards.value,
])
const complete = computed(() => !!draft.value.chief_complaint && draft.value.symptoms.length > 0 && !!draft.value.started_at && draft.value.severity != null)
const severityHint = computed(() => severityIndex.value == null ? '滑到接近你感受的位置' : levels[severityIndex.value]?.help || '')
const showEmpty = computed(() => !messages.value.length && !results.value.length && !task.value && !action.value)
const showTask = computed(() => !!task.value && !action.value)
const card = computed<CardDef | undefined>(() => (task.value ? CARDS[task.value] : undefined))
const taskTitle = computed(() => {
  if (task.value === 'chief_complaint') return '这次主要哪里不舒服？'
  if (task.value === 'severity') return '现在感觉怎么样？'
  if (task.value === 'symptoms') return '这些感觉符合吗？'
  if (task.value === 'started_at') return '从什么时候开始的？'
  return card.value?.title ?? ''
})
const taskReady = computed(() => {
  if (task.value === 'chief_complaint') return !!complaintValue.value.trim()
  if (task.value === 'severity') return severityIndex.value != null
  if (task.value === 'started_at') return !!dateValue.value
  if (card.value) { const answer = cardAnswers.value[card.value.key]; return Array.isArray(answer) ? answer.length > 0 : !!answer }
  return true
})
const imagesSupported = computed(() => capabilities.value?.images === true)

function humanDate(value: string) {
  const date = new Date(`${value}T12:00:00`)
  const today = new Date(); today.setHours(12, 0, 0, 0)
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return key(date) === key(today) ? '今天开始' : key(date) === key(yesterday) ? '昨天开始' : `${date.getMonth() + 1}月${date.getDate()}日开始`
}
function isoDay(offset: number) { const date = new Date(); date.setHours(12, 0, 0, 0); date.setDate(date.getDate() + offset); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` }
function describe(reason: unknown) { return reason instanceof Error ? reason.message : '暂时没有完成，请重试。' }
async function scrollThread() { await nextTick(); thread.value?.scrollTo({ top: thread.value.scrollHeight, behavior: 'smooth' }) }
function setDirty() { emit('dirty', !recordSaved.value && (!!input.value.trim() || messages.value.length > 0 || results.value.length > 0 || !!action.value)) }

function currentWorking(): Working {
  return { complaintValue: complaintValue.value, severityIndex: severityIndex.value, symptomOptions: [...symptomOptions.value], symptomPresent: [...symptomPresent.value], symptomAbsent: [...symptomAbsent.value], dateValue: dateValue.value, cardAnswers: { ...cardAnswers.value } }
}
function applyWorking(value: Working) {
  complaintValue.value = value.complaintValue; severityIndex.value = value.severityIndex
  symptomOptions.value = [...value.symptomOptions]; symptomPresent.value = [...value.symptomPresent]
  symptomAbsent.value = [...value.symptomAbsent]; dateValue.value = value.dateValue; cardAnswers.value = { ...(value.cardAnswers ?? {}) }
}
/** Load the active task's working values from the server draft, without touching a paused task. */
function loadWorking(key: Task) {
  if (key === 'chief_complaint') complaintValue.value = draft.value.chief_complaint
  else if (key === 'severity') severityIndex.value = draft.value.severity == null ? null : draft.value.severity - 1
  else if (key === 'symptoms') {
    symptomOptions.value = [...new Set([...symptomOptions.value, ...draft.value.symptoms])]
    symptomPresent.value = [...draft.value.symptoms]; symptomAbsent.value = []
  } else if (key === 'started_at') dateValue.value = draft.value.started_at
}
function localMissing() {
  const list: string[] = []
  if (!draft.value.chief_complaint.trim()) list.push('chief_complaint')
  if (draft.value.severity == null) list.push('severity')
  if (!draft.value.symptoms.length) list.push('symptoms')
  if (!draft.value.started_at) list.push('started_at')
  return list
}
function nextTask() {
  if (editing.value) return
  const list = missing.value.length ? missing.value : localMissing()
  const key = TASK_ORDER.find(item => list.includes(item)) ?? null
  task.value = key
  if (key) loadWorking(key)
}

function localSnapshot() {
  try {
    localStorage.setItem(storageKey.value, JSON.stringify({
      messages: messages.value, draft: draft.value, missing: missing.value, task: task.value,
      recordSaved: recordSaved.value, turns: turns.value, symptomOptions: symptomOptions.value,
      cardAnswers: cardAnswers.value, action: action.value,
    }))
  } catch { /* local storage may be unavailable */ }
}
function persistSoon() { clearTimeout(persistTimer); persistTimer = setTimeout(localSnapshot, 120) }
function restoreSession() {
  try {
    const raw = localStorage.getItem(storageKey.value)
    if (!raw) return
    const value = JSON.parse(raw) as {
      messages?: ChatMessage[]; draft?: IntakeDraft; missing?: string[]; task?: Task | null
      recordSaved?: boolean; turns?: number; symptomOptions?: string[]; action?: ActionView | null
      cardAnswers?: Record<string, CardValue>
    }
    if (Array.isArray(value.messages) && value.messages.length && value.messages.every(m => ['assistant', 'user'].includes(m.role) && typeof m.text === 'string')) messages.value = value.messages.slice(-80)
    if (value.draft && typeof value.draft === 'object') draft.value = { ...emptyIntakeDraft(), ...value.draft, symptoms: Array.isArray(value.draft.symptoms) ? value.draft.symptoms.filter((x): x is string => typeof x === 'string').slice(0, 20) : [] }
    if (Array.isArray(value.missing)) missing.value = value.missing.filter((x): x is string => typeof x === 'string')
    if (value.task && DIALOG_TOOLS.includes(value.task)) { task.value = value.task; loadWorking(value.task) }
    recordSaved.value = value.recordSaved === true
    if (Number.isSafeInteger(value.turns) && value.turns! >= 0) turns.value = value.turns!
    if (Array.isArray(value.symptomOptions)) symptomOptions.value = value.symptomOptions.filter((x): x is string => typeof x === 'string').slice(0, 20)
    if (value.cardAnswers && typeof value.cardAnswers === 'object') cardAnswers.value = { ...value.cardAnswers }
    if (value.action && typeof value.action === 'object') action.value = value.action
    setDirty()
  } catch { /* ignore corrupt or unavailable local drafts */ }
}
async function checkModel(): Promise<boolean> {
  modelReady.value = null; modelNotice.value = ''
  try {
    const status = await api.modelStatus()
    if (!active) return false
    modelReady.value = status.status === 'ready'; cloud.value = status.cloud; capabilities.value = status.capabilities ?? null
    if (!modelReady.value) modelNotice.value = '问诊服务暂时不可用，输入内容已保留在本机。' + (status.notice ? `（${status.notice}）` : '')
    return modelReady.value
  } catch { if (active) { modelReady.value = false; modelNotice.value = '暂时无法连接问诊服务，输入内容已保留在本机。' } return false }
}

function showAction(source: Analysis | Assessment) {
  const triage = 'triage' in source ? source.triage : source
  const monitoring = 'monitoring' in source ? source.monitoring : null
  const knowledge = 'knowledge' in source ? source.knowledge : []
  action.value = {
    level: triage.level, label: triage.label, summary: triage.summary, reasons: triage.reasons ?? [],
    actions: triage.action_plan ?? [], sources: ('sources' in source ? source.sources : []) ?? [],
    knowledge: knowledge ?? [], monitoring,
    facts: { complaint: draft.value.chief_complaint, startedAt: draft.value.started_at ? humanDate(draft.value.started_at) : '' },
  }
}
/** Open the dialog tool the model chose. `next_step` shows the action box; a task tool opens one box. */
function openTool(tool: string, source?: Analysis | Assessment) {
  const level = source ? ('triage' in source ? source.triage.level : source.level) : null
  if (level === 'emergency') { showAction(source!); task.value = null; return }
  if (tool === 'next_step') { if (source) showAction(source); task.value = null; return }
  if (DIALOG_TOOLS.includes(tool as Task)) { action.value = null; task.value = tool as Task; loadWorking(tool as Task); return }
  action.value = null; task.value = null
}

async function performTurn(message: string, appendMessage: boolean) {
  const text = message.trim()
  if (!text || busy.value || saving.value) return
  if (appendMessage) messages.value.push({ role: 'user', text })
  lastMessage.value = text
  busy.value = true; error.value = ''; notice.value = ''; emit('busy', true); emit('dirty', true)
  persistSoon(); void scrollThread()
  try {
    // Pre-model danger precheck: rules only, no model, no invented fields.
    try {
      const precheck = await api.intakeTriage({ ...draft.value, notes: [draft.value.notes, text].filter(Boolean).join(' ') })
      if (active && precheck.level === 'emergency') { showAction(precheck); task.value = null }
    } catch { /* precheck failure must not block or fabricate a result */ }
    const context = lastContext.value ?? api.intakeContext()
    lastContext.value = context
    // Always ask the server: it returns a rule-based tool even when no model is configured,
    // so the fixed dialog boxes stay usable offline (they collect values directly).
    const turn = await api.intakeTurn(draft.value, text, turns.value, consent.value, context)
    if (!active) return
    if (turn.status === 'not_configured') {
      modelReady.value = false
      modelNotice.value = '问诊整理服务暂时不可用，输入内容已保留在本机。'
      openTool(turn.tool, turn.triage)
      notice.value = '整理服务暂时不可用，无法解析自由文字；先用下面的对话框逐项确认也可以继续。'
      return
    }
    turns.value += 1; modelReady.value = true
    draft.value = turn.draft; missing.value = turn.missing_fields
    symptomOptions.value = [...new Set([...symptomOptions.value, ...turn.draft.symptoms])]
    lastContext.value = null
    // The model chose which dialog tool to open (or none); emergency always shows the action box.
    openTool(turn.tool, turn.triage)
    const reply = [turn.reply, (task.value || action.value) ? '' : turn.question].filter(Boolean).join('\n')
    if (reply) messages.value.push({ role: 'assistant', text: reply })
    if (turn.status === 'unavailable') { error.value = '这次没有完成整理，输入内容已保留，可以重试。'; input.value = text }
    persistSoon(); setDirty(); void scrollThread()
  } catch (reason) {
    if (active) { error.value = '这次没有发送成功，输入内容已保留，可以重试。'; input.value = text; persistSoon(); setDirty() }
  } finally { if (active) { busy.value = false; emit('busy', false) } }
}
async function send() {
  const message = input.value.trim()
  if (!message || busy.value || saving.value) return
  // When a dialog box is open, the composer fills that box directly instead of calling the model.
  if (task.value && !action.value) {
    if (task.value === 'chief_complaint') complaintValue.value = message.slice(0, 200)
    else if (task.value === 'symptoms') {
      if (!symptomOptions.value.includes(message)) symptomOptions.value.push(message)
      if (!symptomPresent.value.includes(message)) symptomPresent.value.push(message)
      symptomAbsent.value = symptomAbsent.value.filter(item => item !== message)
    }
    else if (CARDS[task.value]) cardAnswers.value = { ...cardAnswers.value, [task.value]: message }
    else return  // severity / started_at use their own controls; ignore stray text.
    input.value = ''
    persistSoon(); setDirty()
    return
  }
  input.value = ''
  await performTurn(message, true)
  if (error.value && !input.value) input.value = message
}
async function retry() {
  if (busy.value) return
  if (modelReady.value === false) await checkModel()
  const message = lastMessage.value || input.value.trim()
  if (!message) return
  const last = messages.value.at(-1)
  const append = !(last?.role === 'user' && last.text === message)
  await performTurn(message, append)
}
function startEdit(key: Task) {
  if (editing.value || !DIALOG_TOOLS.includes(key) || key === 'next_step' || key === 'none') return
  stash.value = currentWorking(); resumeTask.value = task.value; editing.value = true; task.value = key; loadWorking(key)
  void scrollThread()
}
function cancelEdit() {
  if (!editing.value) return
  if (stash.value) applyWorking(stash.value)
  task.value = resumeTask.value; resumeTask.value = null; editing.value = false; stash.value = null
}
function commitTask(): boolean {
  if (!task.value) return false
  const done = task.value
  if (done === 'chief_complaint') {
    const value = complaintValue.value.trim(); if (!value) return false
    draft.value.chief_complaint = value.slice(0, 200)
  } else if (done === 'severity') {
    if (severityIndex.value == null || severityIndex.value < 0 || severityIndex.value > 4) return false
    draft.value.severity = severityIndex.value + 1
  } else if (done === 'symptoms') {
    draft.value.symptoms = symptomPresent.value.slice(0, 20)
  } else if (done === 'started_at') {
    if (!dateValue.value) return false
    draft.value.started_at = dateValue.value
  } else if (CARDS[done]) {
    const answer = cardAnswers.value[done]
    if (Array.isArray(answer) ? !answer.length : !answer) return false
    const text = Array.isArray(answer) ? answer.join('、') : answer
    // No dedicated schema field: keep each answered card as a labelled line in notes.
    const label = CARDS[done].label
    const rest = draft.value.notes.split('\n').filter(line => !line.startsWith(`${label}：`)).join('\n').trim()
    draft.value.notes = [rest, `${label}：${text}`].filter(Boolean).join('\n')
  } else return false
  missing.value = localMissing()
  return true
}
function completeTask() {
  if (!task.value || busy.value || saving.value) return
  const done = task.value
  if (!commitTask()) return
  notice.value = (done === 'symptoms' && !draft.value.symptoms.length)
    ? '记录至少需要一项当前症状。如果现在确实没有这些不适，可以在下面补充其他感受；未点亮不代表没有。'
    : ''
  if (editing.value) {
    if (stash.value) applyWorking(stash.value)
    task.value = resumeTask.value; resumeTask.value = null; editing.value = false; stash.value = null
  } else if (CARDS[done]) {
    // Extra cards are optional: after one, let the model decide the next tool, else close.
    task.value = null
  } else nextTask()
  persistSoon(); setDirty(); void scrollThread()
}
function chooseStart(value: string) { if (value) dateValue.value = value }
function toggleCardOption(card: CardDef, option: string) {
  const current = cardAnswers.value[card.key]
  if (card.multi) {
    const list = Array.isArray(current) ? [...current] : []
    cardAnswers.value = { ...cardAnswers.value, [card.key]: list.includes(option) ? list.filter(x => x !== option) : [...list, option] }
    return
  }
  // Single choice: tapping an option records it and closes the card immediately, no confirm button.
  cardAnswers.value = { ...cardAnswers.value, [card.key]: option }
  if (!editing.value && task.value === card.key) completeTask()
}
function cardSelected(card: CardDef, option: string): boolean {
  const current = cardAnswers.value[card.key]
  return Array.isArray(current) ? current.includes(option) : current === option
}
function toggleSymptom(value: string) {
  if (symptomPresent.value.includes(value)) {
    symptomPresent.value = symptomPresent.value.filter(item => item !== value)
    if (!symptomAbsent.value.includes(value)) symptomAbsent.value.push(value)
  } else {
    symptomPresent.value = [...symptomPresent.value, value]
    symptomAbsent.value = symptomAbsent.value.filter(item => item !== value)
  }
}

function clearVoice() { try { recognition?.abort() } catch { /* ignore */ } recognition = null; listening.value = false }
async function toggleVoice() {
  if (listening.value) { clearVoice(); return }
  if (!voiceSupported.value) { voiceError.value = '当前浏览器不支持语音识别，可以改用文字输入。'; return }
  voiceError.value = ''
  try { const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); stream.getTracks().forEach(track => track.stop()) }
  catch { voiceError.value = '无法获得麦克风权限，请在浏览器设置中允许后重试。'; return }
  const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  try {
    const instance = new Ctor(); instance.lang = 'zh-CN'; instance.interimResults = false; instance.continuous = false
    instance.onresult = (event: any) => { const text = event.results?.[0]?.[0]?.transcript ?? ''; if (text) { input.value = (input.value ? input.value + ' ' : '') + text; setDirty() } }
    instance.onerror = (event: any) => { voiceError.value = event?.error === 'not-allowed' ? '麦克风权限被拒绝，可以改用文字输入。' : '语音识别没有完成，请重试或改用文字输入。'; listening.value = false }
    instance.onend = () => { listening.value = false }
    recognition = instance; instance.start(); listening.value = true
  } catch { voiceError.value = '语音识别启动失败，可以改用文字输入。' }
}
function addAttachments(event: Event, kind: Attachment['kind']) {
  const files = Array.from((event.target as HTMLInputElement).files ?? [])
  for (const file of files) attachments.value.push({ name: file.name, kind })
  if (files.length) notice.value = imagesSupported.value
    ? '已添加图片。识别能力以服务端实际状态为准。'
    : '当前服务只支持文字，图片和拍照不会被识别或上传，也不会被当成已看懂。请用文字描述你的感觉。'
  ;(event.target as HTMLInputElement).value = ''
}
function removeAttachment(index: number) { attachments.value.splice(index, 1) }
function openImagePicker() { attachOpen.value = false; imageInput.value?.click() }
function openCamera() { attachOpen.value = false; cameraInput.value?.click() }

function restart() { reset() }
function reset() {
  clearTimeout(persistTimer); clearTimeout(recordTimer); clearVoice()
  messages.value = []; draft.value = emptyIntakeDraft(); input.value = ''; attachments.value = []
  task.value = null; resumeTask.value = null; editing.value = false; stash.value = null; missing.value = []
  turns.value = 0; error.value = ''; notice.value = ''; conflict.value = false; recordSaved.value = false
  episodeId.value = ''; episodeVersion.value = 1
  complaintValue.value = ''; severityIndex.value = null; symptomOptions.value = []; symptomPresent.value = []
  symptomAbsent.value = []; dateValue.value = ''; cardAnswers.value = {}; lastContext.value = null; lastMessage.value = ''
  action.value = null
  try { localStorage.removeItem(storageKey.value) } catch { /* local storage may be unavailable */ }
  typeInvite()
  emit('dirty', false); void scrollThread()
}
async function autoRecord() {
  if (!complete.value || saving.value || busy.value) return
  saving.value = true; error.value = ''; conflict.value = false
  try {
    const input = intakeDraftToEpisodeInput(draft.value)
    const episode = episodeId.value
      ? await api.update(episodeId.value, input, episodeVersion.value)
      : await api.create(input)
    if (!active) return
    episodeId.value = episode.id; episodeVersion.value = episode.version
    recordSaved.value = true
    try { localStorage.removeItem(storageKey.value) } catch { /* storage may be unavailable */ }
    emit('dirty', false); emit('saved', episode, true)  // auto-record: refresh lists silently, no toast
  } catch (reason) {
    if (active) { error.value = describe(reason); conflict.value = reason instanceof ApiError && reason.status === 409 }
  } finally { if (active) saving.value = false }
}
function buildSavedAction(assessment: Assessment): ActionView {
  return {
    level: assessment.triage.level, label: assessment.triage.label, summary: assessment.triage.summary, reasons: assessment.triage.reasons ?? [],
    actions: assessment.triage.action_plan ?? [], sources: [], knowledge: assessment.knowledge ?? [],
    monitoring: assessment.monitoring, facts: { complaint: draft.value.chief_complaint, startedAt: draft.value.started_at ? humanDate(draft.value.started_at) : '' },
  }
}

function prefill(text: string) { if (busy.value || saving.value) return; input.value = text.slice(0, 500); setDirty() }
defineExpose({ prefill })

// Auto-record: whenever the draft is complete, save silently (create once, then update on changes).
let recordTimer: ReturnType<typeof setTimeout> | undefined
function scheduleRecord() {
  if (!complete.value || busy.value || saving.value || missing.value.length) return
  clearTimeout(recordTimer); recordTimer = setTimeout(() => { if (active) void autoRecord() }, 600)
}
watch(complete, value => { if (value) scheduleRecord() })
watch(() => ({ ...draft.value }), () => scheduleRecord(), { deep: true })
watch([messages, draft, input, missing, task, turns, symptomOptions, cardAnswers, action], persistSoon, { deep: true })
watch(() => props.active, value => { if (value === false) clearVoice() })
onMounted(() => {
  active = true
  voiceSupported.value = typeof window !== 'undefined' && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
  restoreSession(); typeInvite(); void checkModel()
})
onBeforeUnmount(() => { active = false; clearVoice(); clearTimeout(persistTimer); clearTimeout(typeTimer); clearTimeout(recordTimer) })
</script>

<template>
  <div class="chat-intake">
    <div v-if="modelReady === false" class="model-status" role="status"><span>{{ modelNotice || '问诊服务暂时不可用，你写下的内容已保留在本机。' }}</span><button class="text-button" :disabled="busy" @click="retry">重试连接</button></div>
    <div v-else-if="modelReady === null" class="model-status" role="status">正在连接问诊服务…</div>
    <div ref="thread" class="chat-thread" role="log" aria-live="polite" aria-label="问诊对话">
      <p v-if="showEmpty" class="empty-invite"><span>{{ inviteText }}</span><span class="caret" aria-hidden="true"></span></p>
      <div v-for="(message, index) in messages" :key="index" class="bubble" :class="message.role">
        <span v-if="message.role === 'assistant'" class="bubble-avatar"><Icon name="leaf" :size="16" /></span><p>{{ message.text }}</p>
      </div>
      <div v-if="busy" class="bubble assistant"><span class="bubble-avatar"><Icon name="leaf" :size="16" /></span><p class="chat-typing">正在整理…</p></div>
      <ConsultationAction v-if="action" v-bind="action" class="thread-action" />
      <button v-for="item in results" :key="item.key" class="result-row" :aria-label="`修改${item.label}：${item.value}`" @click="startEdit(item.key)">
        <span><small>{{ item.label }}</small>{{ item.value }}</span><em>修改</em>
      </button>
      <section v-if="showTask" class="task-box" aria-label="当前问诊任务">
        <h2>{{ taskTitle }}</h2>
        <template v-if="task === 'chief_complaint'">
          <p class="task-help">{{ complaintValue ? '已记下：' + complaintValue : '用最下面的输入框说说这次主要哪里不舒服。' }}</p>
        </template>
        <template v-else-if="task === 'severity'">
          <div class="severity-view">
            <strong>{{ severityIndex == null ? '接近哪种感受？' : levels[severityIndex].title }}</strong>
            <p>{{ severityHint }}</p>
            <label class="sr-only" for="severity-range">选择接近你的不适感受</label>
            <input id="severity-range" type="range" min="0" max="4" step="1" :value="severityIndex == null ? 2 : severityIndex" :aria-valuetext="severityIndex == null ? '尚未选择' : levels[severityIndex].title + '，' + levels[severityIndex].help" @input="severityIndex = Number(($event.target as HTMLInputElement).value)" />
            <div class="range-labels"><span>轻些</span><span>难受些</span></div>
            <p class="task-hint">拖动只描述强弱；未拖动时保持未知，不会自动记成某个程度。</p>
          </div>
        </template>
        <template v-else-if="task === 'symptoms'">
          <p class="task-help">已提到的感觉会点亮；点一下可撤回，没有点亮不代表没有。要用自己的话说，就用最下面的输入框补充。</p>
          <div v-if="symptomOptions.length" class="symptom-tags">
            <button v-for="symptom in symptomOptions" :key="symptom" :aria-pressed="symptomPresent.includes(symptom)" :class="{ off: symptomAbsent.includes(symptom) }" @click="toggleSymptom(symptom)">{{ symptom }}<span v-if="symptomAbsent.includes(symptom)"> 现无</span></button>
          </div>
          <p v-else class="task-help">还没有识别到具体症状，在最下面的输入框里说说你的感觉。</p>
        </template>
        <template v-else-if="card">
          <p v-if="card.help" class="task-help">{{ card.help }}</p>
          <div class="card-options">
            <button v-for="option in card.options" :key="option" :aria-pressed="cardSelected(card, option)" @click="toggleCardOption(card, option)">{{ option }}</button>
          </div>
          <p class="task-hint">也可以直接用最下面的输入框补充一句话。</p>
        </template>
        <template v-else>
          <div class="time-options">
            <button :aria-pressed="dateValue === isoDay(0)" @click="chooseStart(isoDay(0))">今天开始</button>
            <button :aria-pressed="dateValue === isoDay(-1)" @click="chooseStart(isoDay(-1))">昨天开始</button>
            <button :aria-pressed="dateValue === isoDay(-2)" @click="chooseStart(isoDay(-2))">前几天开始</button>
          </div>
          <label class="field">选择其他日期<input type="date" :max="isoDay(0)" :value="dateValue" @change="chooseStart(($event.target as HTMLInputElement).value)" /></label>
          <p class="task-hint">只记录日期，不虚构具体时刻；「昨晚」等模糊说法不改成精确时间。记不清可以先跳过，稍后再补。</p>
        </template>
        <div v-if="!card" class="task-actions">
          <button v-if="editing" class="text-button" @click="cancelEdit">取消修改</button>
          <button class="button primary small" :disabled="busy || saving || !taskReady" @click="completeTask">{{ task === 'severity' ? '继续' : '记下了' }}</button>
        </div>
        <div v-else class="task-actions">
          <button v-if="editing" class="text-button" @click="cancelEdit">取消修改</button>
          <button class="text-button" @click="task = null">先跳过</button>
        </div>
      </section>
      <p v-if="notice && !busy" class="followup-hint" role="status">{{ notice }}</p>
    </div>

    <div v-if="attachments.length" class="attachments" aria-label="未识别的附件">
      <span v-for="(item, index) in attachments" :key="index" class="attachment"><Icon :name="item.kind === 'camera' ? 'camera' : 'image'" :size="15" />{{ item.name }}<button aria-label="移除附件" @click="removeAttachment(index)">×</button></span>
    </div>
    <p v-if="voiceError" class="voice-error" role="alert">{{ voiceError }}</p>

    <div v-if="error" class="notice error chat-error" role="alert"><span>{{ error }}</span><button class="text-button" :disabled="busy" @click="retry">重试</button></div>
    <div v-if="conflict" class="chat-hint">记录已在别处更新，请重新载入后再试。</div>

    <form class="chat-composer" @submit.prevent="send">
      <div class="composer-row">
        <button type="button" class="tool" :class="{ active: attachOpen }" :aria-expanded="attachOpen" aria-label="添加图片或拍照" @click="attachOpen = !attachOpen"><Icon name="plus" :size="20" /></button>
        <input ref="imageInput" class="file-hidden" type="file" accept="image/*" multiple @change="addAttachments($event, 'image')" />
        <input ref="cameraInput" class="file-hidden" type="file" accept="image/*" capture="environment" @change="addAttachments($event, 'camera')" />
        <label class="sr-only" for="intake-input">继续描述你的感觉</label>
        <textarea id="intake-input" v-model="input" rows="1" maxlength="500" :disabled="busy || saving" placeholder="说说你的感觉…" @input="setDirty" @keydown.enter.exact.prevent="send"></textarea>
        <button v-if="voiceSupported" type="button" class="tool" :class="{ listening }" :aria-label="listening ? '停止语音输入' : '语音输入'" :aria-pressed="listening" @click="toggleVoice"><Icon :name="listening ? 'stop' : 'mic'" :size="20" /></button>
        <button class="button primary" :disabled="!input.trim() || busy || saving"><span>{{ busy ? '整理中…' : '发送' }}</span><Icon name="arrow" :size="17" /></button>
      </div>
      <div v-if="attachOpen" class="attach-row">
        <button type="button" class="attach-option" @click="openCamera"><Icon name="camera" :size="18" />拍照</button>
        <button type="button" class="attach-option" @click="openImagePicker"><Icon name="image" :size="18" />选图片</button>
        <span v-if="!imagesSupported" class="attach-note">当前服务只支持文字，图片不会被识别或上传。</span>
      </div>
      <p v-if="voiceSupported" class="composer-hint">语音识别由浏览器的语音服务完成，可能有隐私与网络限制；识别结果会先填进输入框，由你确认后再发送。</p>
    </form>
  </div>
</template>

<style scoped>
.chat-intake { display:flex; flex-direction:column; gap:16px; min-width:0; }
.model-status { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:9px 12px; color:var(--muted); font-size:12px; line-height:1.6; border-bottom:1px solid var(--border-faint); }
.model-status > span { flex:1; min-width:0; }
.model-status .text-button { flex:none; white-space:nowrap; }
.chat-thread { display:flex; flex-direction:column; gap:16px; min-height:0; overflow-y:auto; padding:6px 2px; }
/* On desktop the chat column fills the workspace; the thread scrolls and the composer stays at the bottom. */
@media (min-width:901px) {
  .chat-intake { flex:1 1 auto; min-height:0; }
  .chat-thread { flex:1 1 auto; }
  .chat-composer { flex:none; }
}
.empty-invite { margin:auto; padding:52px 0 44px; color:var(--ink-soft); font-size:17px; text-align:center; }
.empty-invite .caret { display:inline-block; width:2px; height:1.05em; margin-left:2px; vertical-align:-0.16em; background:var(--primary); animation:caret-blink 0.9s step-end infinite; }
@keyframes caret-blink { 50% { opacity:0; } }
@media (prefers-reduced-motion: reduce) { .empty-invite .caret { animation:none; } }
.bubble { display:flex; align-items:flex-start; gap:9px; max-width:min(90%,680px); }
.bubble.user { margin-left:auto; flex-direction:row-reverse; }
.bubble p { margin:0; padding:3px 0; font-size:15px; line-height:1.8; white-space:pre-line; overflow-wrap:anywhere; }
.bubble.user p { padding:10px 14px; border-radius:15px 15px 4px 15px; color:var(--ink); background:var(--surface-sunken); }
.bubble-avatar { display:grid; place-items:center; width:26px; height:26px; flex:none; margin-top:2px; border-radius:50%; color:var(--primary-deep); background:var(--primary-soft); }
.chat-typing { color:var(--muted); }
.thread-action { justify-self:center; width:100%; max-width:560px; margin:2px 0; }
.result-row { display:flex; align-items:center; justify-content:space-between; gap:16px; justify-self:center; width:min(100%,500px); padding:9px 4px; border-bottom:1px solid var(--border-faint); color:var(--ink); text-align:left; }
.result-row span { display:grid; gap:2px; font-size:13px; line-height:1.6; }
.result-row small { color:var(--muted); font-size:11px; }
.result-row em { flex:none; color:var(--muted); font-size:11px; font-style:normal; }
.result-row:hover em { color:var(--primary); }
.task-box { display:grid; gap:14px; width:min(100%,520px); justify-self:center; padding:20px; border:1px solid var(--border); border-radius:16px; background:var(--surface); }
.task-box h2 { margin:0; font-size:16px; font-weight:550; line-height:1.5; }
.task-box > input { width:100%; }
.severity-view { display:grid; gap:7px; text-align:center; }
.severity-view strong { font-size:19px; color:var(--primary-deep); }
.severity-view > p { margin:0; min-height:20px; font-size:12px; color:var(--muted); line-height:1.7; }
.severity-view input[type=range] { width:100%; margin:6px 0 0; min-height:28px; accent-color:var(--primary); }
.range-labels { display:flex; justify-content:space-between; font-size:11px; color:var(--faint); }
.task-help,.task-hint { margin:0; font-size:12px; color:var(--muted); line-height:1.75; }
.symptom-tags,.time-options,.card-options { display:flex; flex-wrap:wrap; gap:9px; }
.card-options { display:grid; grid-template-columns:1fr 1fr; }
.symptom-tags button,.time-options > button,.card-options > button { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:38px; padding:8px 12px; border:1px solid var(--border); border-radius:11px; color:var(--muted); background:var(--surface); font-size:13px; }
.symptom-tags button[aria-pressed="true"],.time-options > button[aria-pressed="true"],.card-options > button[aria-pressed="true"] { color:var(--primary-deep); background:var(--primary-tint); border-color:var(--primary-soft); }
.symptom-tags button.off { text-decoration:line-through; text-decoration-color:var(--faint); }
.time-options .field { flex:1 1 190px; margin:0; font-size:12px; }
.time-options input { margin-top:5px; }
.task-actions { display:flex; justify-content:flex-end; align-items:center; gap:14px; }
.followup-hint { justify-self:center; margin:0; max-width:520px; text-align:center; font-size:12px; color:var(--muted); line-height:1.7; }
.attachments { display:flex; flex-wrap:wrap; gap:8px; }
.attachment { display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border:1px dashed var(--border-strong); border-radius:10px; font-size:12px; color:var(--muted); }
.attachment button { color:var(--muted); font-size:14px; }
.voice-error { margin:0; font-size:12px; color:var(--danger); }
.chat-composer { display:grid; gap:8px; padding:11px; border:1px solid var(--border); border-radius:16px; background:var(--surface-soft); }
.composer-row { display:flex; align-items:flex-end; gap:8px; }
.composer-row textarea { flex:1; min-width:0; min-height:40px; max-height:150px; resize:none; background:none; border:0; padding:9px 2px; }
.tool { display:grid; place-items:center; padding:8px; color:var(--muted); border-radius:9px; }
.tool:hover { color:var(--primary); background:var(--primary-tint); }
.tool.active { color:var(--primary); background:var(--primary-tint); }
.tool.listening { color:var(--emergency); background:var(--emergency-soft); }
.attach-row { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:2px; }
.attach-option { display:inline-flex; align-items:center; gap:6px; padding:9px 13px; border:1px solid var(--border); border-radius:10px; color:var(--ink-soft); background:var(--surface); font-size:13px; }
.attach-option:hover { color:var(--primary); border-color:var(--primary-soft); background:var(--primary-tint); }
.attach-note { font-size:11px; color:var(--muted); line-height:1.6; }
.file-hidden { position:absolute; width:1px; height:1px; opacity:0; pointer-events:none; }
.composer-hint { margin:0; font-size:11px; color:var(--muted); line-height:1.7; }
.chat-error { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:0; }
.chat-hint { font-size:12px; color:var(--muted); line-height:1.7; }
.save-row { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; font-size:13px; color:var(--muted); }
.save-row.saved { display:flex; align-items:center; gap:9px; color:var(--primary-deep); }
.save-row .button { flex:none; }
@media(max-width:640px){
  .chat-intake { display:flex; flex-direction:column; gap:14px; min-height:calc(100dvh - 158px - env(safe-area-inset-bottom)); }
  /* Mobile: let the page scroll naturally instead of trapping a short inner scroller. */
  .chat-thread { display:flex; flex-direction:column; flex:1 1 auto; max-height:none; overflow:visible; padding:2px 2px 4px; }
  .empty-invite { flex:1; display:flex; align-items:center; justify-content:center; padding:24px 0; font-size:16px; }
  .bubble { max-width:92%; }
  .bubble p { font-size:15px; }
  .task-box { padding:18px 15px; }
  .severity-view strong { font-size:18px; }
  .result-row { padding:11px 2px; }
  /* Sticky composer sits just above the fixed bottom nav and grows with its own content. */
  .chat-composer { position:sticky; bottom:calc(73px + env(safe-area-inset-bottom)); z-index:40; margin:0 -16px; padding:9px 16px; border:0; border-top:1px solid var(--border); border-radius:0; background:var(--surface); }
  .composer-row { align-items:center; gap:6px; }
  .composer-row textarea { min-height:38px; padding:7px 2px; font-size:16px; }
  .composer-row .button.primary { padding:9px 14px; }
  .composer-hint { display:none; }
  .followup-hint { text-align:left; }
  .save-row { flex-direction:column; align-items:flex-start; gap:10px; }
  .save-row .button { width:100%; justify-content:center; }
}
</style>
