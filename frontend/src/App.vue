<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, api, connectionError, isNative } from './api'
import type { Episode, Overview, User } from './types'
import AuthScreen from './components/AuthScreen.vue'
import Icon from './components/Icon.vue'
import ConsultationHome from './components/ConsultationHome.vue'
import MineHome from './components/MineHome.vue'

const HistoryPage = defineAsyncComponent(() => import('./components/HistoryPage.vue'))
const AccountPage = defineAsyncComponent(() => import('./components/AccountPage.vue'))
const KnowledgePage = defineAsyncComponent(() => import('./components/KnowledgePage.vue'))
const HealthPage = defineAsyncComponent(() => import('./components/HealthPage.vue'))
const EpisodeDetail = defineAsyncComponent(() => import('./components/EpisodeDetail.vue'))
const EpisodeForm = defineAsyncComponent(() => import('./components/EpisodeForm.vue'))
const VisitReport = defineAsyncComponent(() => import('./components/VisitReport.vue'))

type Page = 'consultation' | 'knowledge' | 'mine'
type MineSection = 'home' | 'records' | 'record-detail' | 'health' | 'archive' | 'devices' | 'profile' | 'account'
const pages: Page[] = ['consultation', 'knowledge', 'mine']
const pageNames: Record<Page, string> = { consultation: '问诊', knowledge: '科普', mine: '我的' }
const pageIcons: Record<Page, string> = { consultation: 'pulse', knowledge: 'search', mine: 'user' }
const mineNames: Record<MineSection, string> = { home: '我的', records: '问诊记录', 'record-detail': '病程详情', health: '健康数据', archive: '健康档案', devices: '设备与同步', profile: '个人资料', account: '账号与设置' }

const user = ref<User | null>(null)
const booting = ref(true)
const page = ref<Page>(pages.includes(location.hash.slice(1) as Page) ? location.hash.slice(1) as Page : 'consultation')
const mineSection = ref<MineSection>('home')
const detailId = ref('')
const detailLoading = ref(false)
const consultationHome = ref<InstanceType<typeof ConsultationHome>>()
const healthPage = ref<InstanceType<typeof HealthPage>>()
const accountPage = ref<InstanceType<typeof AccountPage>>()
const intakeDirty = ref(false)
const routeKey = computed(() => page.value === 'mine' ? `mine/${mineSection.value}/${mineSection.value === 'record-detail' ? detailId.value : ''}` : page.value)
const scrollPositions = new Map<string, number>()
const loading = ref(false)
const overview = ref<Overview | null>(null)
const episodes = ref<Episode[]>([])
const error = ref('')
const toast = ref('')
const modal = ref<'edit' | 'delete-account' | 'report' | null>(null)
const selected = ref<Episode>()
const reportEpisodes = ref<Episode[]>([])
const reportUser = ref<User | null>(null)
const reportScope = ref('')
const formDirty = ref(false)
const formBusy = ref(false)
const deleting = ref(false)
const signingOut = ref(false)
const deletionPassword = ref('')
const deletionConsent = ref(false)
const modalError = ref('')
let toastTimer: ReturnType<typeof setTimeout>
let accountGeneration = 0
let reloadQueued = false
const isDirty = computed(() => intakeDirty.value || (formDirty.value && modal.value === 'edit'))

function describe(e: unknown) { return e instanceof Error ? e.message : '操作未完成，请重试。' }
function notify(message: string) { toast.value = message; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 4500) }
function canLeaveSubpage() { return (healthPage.value?.canLeave() ?? true) && (accountPage.value?.canLeave() ?? true) }
function currentHash() { return page.value === 'mine' ? `mine/${mineSection.value}${mineSection.value === 'record-detail' ? `/${encodeURIComponent(detailId.value)}` : ''}` : page.value }
function navigate(next: Page) { if ((next !== page.value || mineSection.value !== 'home') && !canLeaveSubpage()) return; page.value = next; if (next === 'mine') mineSection.value = 'home'; location.hash = next; error.value = '' }
function goMine(section: MineSection) { if ((page.value !== 'mine' || mineSection.value !== section) && !canLeaveSubpage()) return; page.value = 'mine'; mineSection.value = section; location.hash = `mine/${section}`; error.value = '' }
async function consultTopic(title: string) { navigate('consultation'); await nextTick(); consultationHome.value?.prefill(`我想了解「${title}」，结合我的情况聊一聊。`) }
function hashChanged() {
  if (user.value && location.hash.slice(1) !== currentHash() && !canLeaveSubpage()) { history.replaceState(null, '', `#${currentHash()}`); return }
  const path = location.hash.slice(1).split('/')
  const legacy: Record<string, MineSection | Page> = { overview: 'consultation', consultation: 'consultation', history: 'records', health: 'devices', account: 'account' }
  if (pages.includes(path[0] as Page)) { page.value = path[0] as Page; mineSection.value = path[0] === 'mine' && path[1] && path[1] in mineNames ? path[1] as MineSection : 'home' }
  else if (legacy[path[0]]) { const target = legacy[path[0]]; page.value = target === 'consultation' ? 'consultation' : target === 'records' || target === 'devices' || target === 'account' ? 'mine' : 'consultation'; mineSection.value = target === 'consultation' ? 'home' : target === 'records' || target === 'devices' || target === 'account' ? target : 'home'; location.hash = page.value === 'mine' ? `mine/${mineSection.value}` : 'consultation' }
  else { page.value = 'consultation'; mineSection.value = 'home'; location.hash = 'consultation' }
  if (page.value === 'mine' && mineSection.value === 'record-detail') {
    let id = ''
    try { id = decodeURIComponent(path[2] ?? '') } catch { /* malformed bookmark */ }
    detailId.value = id
    if (!id) goMine('records')
    else if (user.value && selected.value?.id !== id) void loadDetail(id)
  }
}
async function loadDetail(id: string) {
  const generation = accountGeneration
  selected.value = episodes.value.find(item => item.id === id); modalError.value = ''; detailLoading.value = true
  try { const latest = await api.episode(id); if (generation === accountGeneration && detailId.value === id) selected.value = latest }
  catch (e) { if (generation === accountGeneration && detailId.value === id) modalError.value = describe(e) }
  finally { if (generation === accountGeneration && detailId.value === id) detailLoading.value = false }
}
async function load() {
  if (!user.value) return
  if (loading.value) { reloadQueued = true; return }
  const generation = accountGeneration; loading.value = true; error.value = ''
  try { const workspace = await api.workspace(); if (generation !== accountGeneration) return; overview.value = workspace; episodes.value = workspace.episodes }
  catch (e) { if (generation !== accountGeneration) return; if (e instanceof ApiError && e.status === 401) { clearAccount(); notify('登录已过期，请重新登录。') } else error.value = describe(e) }
  finally { if (generation === accountGeneration) { loading.value = false; if (reloadQueued) { reloadQueued = false; void load() } } }
}
async function authenticated(current: User) { if (user.value?.id !== current.id) { episodes.value = []; overview.value = null; selected.value = undefined; intakeDirty.value = false; scrollPositions.clear() }; accountGeneration++; user.value = current; await load(); if (mineSection.value === 'record-detail' && detailId.value) await loadDetail(detailId.value) }
function profileUpdated(current: User) { if (current.id === user.value?.id) user.value = current }
function openReport(records: Episode[], scope = '我的记录：当前筛选结果') { if (!user.value || !records.length) return; reportEpisodes.value = JSON.parse(JSON.stringify(records)) as Episode[]; reportUser.value = { ...user.value }; reportScope.value = scope; modalError.value = ''; formDirty.value = false; modal.value = 'report' }
async function openDetail(episode: Episode) {
  if (!canLeaveSubpage()) return
  selected.value = episode; detailId.value = episode.id; page.value = 'mine'; mineSection.value = 'record-detail'; location.hash = `mine/record-detail/${encodeURIComponent(episode.id)}`; await loadDetail(episode.id)
}
function edit() { formDirty.value = false; modalError.value = ''; modal.value = 'edit' }
function closeModal() {
  if (formBusy.value || deleting.value) return
  if (formDirty.value && modal.value === 'edit' && !window.confirm('这次修改还没有保存。确定离开吗？')) return
  modal.value = null; formDirty.value = false; modalError.value = ''; deletionPassword.value = ''; deletionConsent.value = false; reportEpisodes.value = []; reportUser.value = null
}
async function saved(episode: Episode, silent = false) { const wasEdit = modal.value === 'edit'; formDirty.value = false; if (!wasEdit) intakeDirty.value = false; selected.value = episode; modal.value = null; modalError.value = ''; if (!silent) notify(wasEdit ? '修改已保存' : '这次身体变化，已经好好记下了'); await load() }
async function removeEpisode() {
  if (!selected.value || !window.confirm('确定删除这条健康记录？删除后无法恢复。')) return
  deleting.value = true; modalError.value = ''
  try { await api.delete(selected.value.id, selected.value.version); selected.value = undefined; mineSection.value = 'records'; location.hash = 'mine/records'; notify('记录已删除'); await load() }
  catch (e) { modalError.value = describe(e) } finally { deleting.value = false }
}
async function reloadDetail() { if (detailId.value) await loadDetail(detailId.value) }
function clearAccount() { accountGeneration++; reloadQueued = false; loading.value = false; detailLoading.value = false; detailId.value = ''; intakeDirty.value = false; scrollPositions.clear(); user.value = null; episodes.value = []; overview.value = null; selected.value = undefined; modal.value = null; error.value = ''; modalError.value = ''; formDirty.value = false; reportEpisodes.value = []; reportUser.value = null; deletionPassword.value = ''; deletionConsent.value = false; clearTimeout(toastTimer); toast.value = ''; page.value = 'consultation'; mineSection.value = 'home'; location.hash = 'consultation' }
async function logout() { signingOut.value = true; error.value = ''; try { await api.logout(); clearAccount() } catch (e) { if (e instanceof ApiError && e.status === 401) clearAccount(); else error.value = describe(e) } finally { signingOut.value = false } }
async function deleteAccount() { if (!deletionConsent.value || !deletionPassword.value || deleting.value) return; deleting.value = true; modalError.value = ''; try { await api.deleteAccount(deletionPassword.value); clearAccount(); notify('账号和全部健康记录已删除') } catch (e) { modalError.value = describe(e) } finally { deleting.value = false } }
function beforeUnload(event: BeforeUnloadEvent) { if (isDirty.value || (formDirty.value && modal.value === 'edit')) { event.preventDefault(); event.returnValue = '' } }
function focusMain() { document.getElementById('main-workspace')?.focus() }
function modalKeys(event: KeyboardEvent) {
  if (!modal.value) return
  if (event.key === 'Escape') { event.preventDefault(); closeModal(); return }
  if (event.key !== 'Tab') return
  const root = document.querySelector<HTMLElement>('.modal')
  const items = [...(root?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]') ?? [])].filter(el => el.offsetParent !== null)
  const first = items[0], last = items.at(-1)
  if (!first || !last) { event.preventDefault(); return }
  if (!items.includes(document.activeElement as HTMLElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus() }
  else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
watch(modal, async value => {
  if (value) { await nextTick(); document.querySelector<HTMLElement>('.modal')?.focus() }
})

watch(modal, value => { document.body.style.overflow = value ? 'hidden' : '' })
watch(routeKey, async (next, previous) => { scrollPositions.set(previous, window.scrollY); await nextTick(); window.scrollTo({ top: scrollPositions.get(next) ?? 0, behavior: 'instant' }) })
onMounted(async () => {
  window.addEventListener('hashchange', hashChanged); window.addEventListener('beforeunload', beforeUnload); document.addEventListener('keydown', modalKeys)
  hashChanged()
  if (!isNative && !connectionError) { try { user.value = await api.me(); await load(); if (mineSection.value === 'record-detail' && detailId.value) await loadDetail(detailId.value) } catch (e) { if (!(e instanceof ApiError && e.status === 401)) error.value = describe(e) } }
  booting.value = false
})
onBeforeUnmount(() => { window.removeEventListener('hashchange', hashChanged); window.removeEventListener('beforeunload', beforeUnload); document.removeEventListener('keydown', modalKeys); clearTimeout(toastTimer); document.body.style.overflow = '' })
</script>

<template>
  <div v-if="booting" class="boot-screen"><span class="brand-mark"><Icon name="leaf" :size="30" /></span><p>正在打开你的知己…</p></div>
  <AuthScreen v-else-if="!user" :initial-error="error" @authenticated="authenticated" />
  <div v-else class="app-shell" :class="{ 'chat-shell': page === 'consultation' }">
    <a href="#main-workspace" class="skip-workspace" @click.prevent="focusMain">跳转到主要内容</a>
    <aside class="sidebar"><a href="#consultation" class="brand" @click.prevent="navigate('consultation')"><span class="brand-mark"><Icon name="leaf" :size="27" /></span><span>知己<small>认识身体，也关照自己</small></span></a>
      <nav class="main-nav" aria-label="主导航"><button v-for="key in pages" :key="key" :class="{ active: page === key }" :aria-current="page === key ? 'page' : undefined" @click="navigate(key)"><Icon :name="pageIcons[key]" /><span>{{ pageNames[key] }}</span></button></nav>
      <div class="sidebar-bottom"><button class="profile-button" @click="goMine('home')"><span class="avatar">{{ user.display_name.slice(0, 1) }}</span><span><strong>{{ user.display_name }}</strong><small>我的</small></span><Icon name="chevron" :size="16" /></button></div>
    </aside>
    <div class="workspace"><header class="topbar"><div class="breadcrumb"><span class="mobile-brand"><Icon name="leaf" :size="21" />知己</span><span class="desktop-only">知己</span><span class="breadcrumb-separator">/</span><strong>{{ page === 'mine' ? mineNames[mineSection] : pageNames[page] }}</strong></div><div class="topbar-actions"><button v-if="page === 'consultation'" class="new-conversation" @click="consultationHome?.newConsultation()"><span aria-hidden="true">＋</span> 新问诊</button><button v-if="page !== 'consultation'" class="icon-button refresh-button" :disabled="loading" aria-label="刷新数据" @click="load"><Icon name="refresh" :size="18" :class="{ spinning: loading }" /></button></div></header>
      <main id="main-workspace" class="main-content" tabindex="-1"><div v-if="error" class="notice error page-error" role="alert">{{ error }}<button class="text-button" @click="load">重试</button></div>
        <ConsultationHome ref="consultationHome" :key="user.id" v-show="page === 'consultation'" :user-id="user.id" :active="page === 'consultation'" @saved="saved" @dirty="intakeDirty = $event" @busy="formBusy = $event" />
        <KnowledgePage v-if="page === 'knowledge'" :episodes="episodes" @consult="consultTopic" />
        <MineHome v-if="page === 'mine' && mineSection === 'home'" :user="user" :episodes="episodes" :loading="loading" @open="goMine" />
        <template v-if="page === 'mine' && mineSection === 'record-detail'"><div class="subpage-heading"><button class="text-button" @click="goMine('records')">‹ 返回问诊记录</button><h1>{{ mineNames[mineSection] }}</h1></div><div v-if="modalError" class="notice error" role="alert">{{ modalError }}<button class="text-button" @click="reloadDetail">重新载入</button></div><p v-if="detailLoading && !selected" class="detail-loading" role="status">正在打开这次记录…</p><EpisodeDetail v-if="selected" :episode="selected" :deleting="deleting" @edit="edit" @remove="removeEpisode" @report="openReport([selected!], '单条病程记录')" /></template>
        <template v-if="page === 'mine' && mineSection !== 'home' && mineSection !== 'record-detail'"><div class="subpage-heading"><button class="text-button" @click="goMine('home')">‹ 返回我的</button><h1>{{ mineNames[mineSection] }}</h1></div>
          <HistoryPage v-if="mineSection === 'records'" :episodes="episodes" :loading="loading" @open="openDetail" @create="navigate('consultation')" @notify="notify" @report="openReport" />
          <HealthPage ref="healthPage" v-else-if="['health','archive','devices'].includes(mineSection)" :key="mineSection" :embedded="true" :initial-section="mineSection === 'archive' ? 'profile' : mineSection === 'health' ? 'measurements' : 'devices'" @changed="load" @notify="notify" />
          <AccountPage ref="accountPage" v-else :key="`${user.id}-${mineSection}`" :initial-section="mineSection === 'profile' ? 'profile' : 'security'" :profile-only="mineSection === 'profile'" :user="user" :signing-out="signingOut" @updated="profileUpdated" @logout="logout" @remove="modalError = ''; modal = 'delete-account'" @notify="notify" />
        </template>
      </main>
    </div>
    <nav class="mobile-nav" aria-label="主导航"><button v-for="key in pages" :key="key" :class="{ active: page === key }" :aria-label="pageNames[key]" :aria-current="page === key ? 'page' : undefined" @click="navigate(key)"><Icon :name="pageIcons[key]" :size="21" /><span>{{ pageNames[key] }}</span></button></nav>
  </div>
  <Transition name="toast"><div v-if="toast" class="toast-message" role="status"><Icon name="check" :size="18" />{{ toast }}</div></Transition>
  <Teleport to="body"><div v-if="modal" class="modal-backdrop" @click.self="closeModal"><section class="modal" :class="{ 'small-modal': modal === 'delete-account', 'report-modal': modal === 'report' }" role="dialog" aria-modal="true" aria-labelledby="modal-heading" tabindex="-1"><header class="modal-header"><div><span class="eyebrow">知己</span><h2 id="modal-heading">{{ modal === 'edit' ? '编辑这次记录' : modal === 'delete-account' ? '删除账号与所有数据' : '就诊摘要' }}</h2></div><button class="icon-button" :disabled="formBusy || deleting" aria-label="关闭弹窗" @click="closeModal"><Icon name="close" :size="22" /></button></header><div class="modal-content"><div v-if="modalError" class="notice error" role="alert">{{ modalError }}</div><EpisodeForm v-if="modal === 'edit' && selected" :key="`edit-${selected.id}`" :episode="selected" @saved="saved" @dirty="formDirty = true" @busy="formBusy = $event" /><VisitReport v-else-if="modal === 'report' && reportUser" :episodes="reportEpisodes" :user="reportUser" :scope="reportScope" @busy="formBusy = $event" @notify="notify" /><form v-else-if="modal === 'delete-account'" class="delete-account-form" @submit.prevent="deleteAccount"><div class="notice error"><Icon name="alert" :size="21" /><span>账号及所有健康记录将永久删除，无法恢复。请先导出备份。</span></div><label class="field">输入当前密码<input v-model="deletionPassword" type="password" autocomplete="current-password" required :disabled="deleting" /></label><label class="consent"><input v-model="deletionConsent" type="checkbox" required :disabled="deleting" /><span>我确认删除账号和全部记录。</span></label><div class="detail-actions"><button class="button secondary" type="button" :disabled="deleting" @click="closeModal">保留账号</button><button class="button danger" :disabled="deleting || !deletionConsent || !deletionPassword">{{ deleting ? '正在删除…' : '永久删除账号' }}</button></div></form></div></section></div></Teleport>
</template>

<style scoped>
.skip-workspace { position: fixed; z-index: 200; top: 8px; left: 16px; transform: translateY(-160%); background: var(--primary-deep); color: white; padding: 12px 18px; border-radius: 8px; }.skip-workspace:focus { transform: translateY(0); }
.subpage-heading { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }.subpage-heading h1 { margin: 0; font-size: 24px; }.subpage-heading + :deep(.page-heading) { display: none; }
.topbar-avatar { display: none; }
.new-conversation { display:flex; align-items:center; gap:5px; min-height:34px; padding:6px 12px; border:1px solid var(--border); border-radius:10px; color:var(--ink-soft); background:var(--surface); font-size:12px; }
.new-conversation:hover { color:var(--primary); border-color:var(--primary); }
.subpage-heading{max-width:960px;margin:4px auto 24px}.subpage-heading .text-button{font-size:13px}.subpage-heading h1{font-size:22px;letter-spacing:-.025em}.detail-loading{padding:35px 0;color:var(--muted);font-size:14px}.chat-shell .topbar{background:var(--surface);border-bottom-color:transparent}.chat-shell .main-content{padding-top:12px}.topbar-actions:empty{display:none}@media(min-width:901px){.chat-shell .workspace{height:100dvh;overflow:hidden}.chat-shell .main-content{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;overflow:hidden}.chat-shell .main-content>.consultation-home{flex:1 1 auto;min-height:0;width:100%}}@media(max-width:640px){.subpage-heading{gap:16px;align-items:center;margin-bottom:22px}.subpage-heading h1{font-size:20px}.chat-shell .main-content{padding-top:4px;padding-bottom:0}}
</style>
