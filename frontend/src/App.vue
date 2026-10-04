<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, api, connectionError, exportRecords, isNative } from './api'
import { dateLabel, outcomeLabels } from './format'
import type { Episode, Overview, User } from './types'
import AuthScreen from './components/AuthScreen.vue'
import EpisodeForm from './components/EpisodeForm.vue'
import EpisodeDetail from './components/EpisodeDetail.vue'
import Icon from './components/Icon.vue'

type Page = 'overview' | 'history' | 'account'
const user = ref<User | null>(null)
const booting = ref(true)
const page = ref<Page>(['history', 'account'].includes(location.hash.slice(1)) ? location.hash.slice(1) as Page : 'overview')
const loading = ref(false)
const overview = ref<Overview | null>(null)
const episodes = ref<Episode[]>([])
const search = ref('')
const filter = ref('all')
const error = ref('')
const toast = ref('')
const modal = ref<'create' | 'detail' | 'edit' | 'delete-account' | null>(null)
const selected = ref<Episode | undefined>()
const formDirty = ref(false)
const formBusy = ref(false)
const deleting = ref(false)
const exporting = ref(false)
const signingOut = ref(false)
const deletionPassword = ref('')
const deletionConsent = ref(false)
const modalError = ref('')
const modalElement = ref<HTMLElement>()
let restoreFocus: HTMLElement | null = null
let toastTimer: ReturnType<typeof setTimeout>
const names = { overview: '健康概览', history: '我的记录', account: '账号与数据' }
const date = new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })
const filtered = computed(() => episodes.value.filter(episode => {
  const q = search.value.trim().toLocaleLowerCase()
  return (filter.value === 'all' || episode.status === filter.value) && (!q || [episode.chief_complaint, episode.notes, ...episode.symptoms].join(' ').toLocaleLowerCase().includes(q))
}).sort((a, b) => b.started_at.localeCompare(a.started_at) || b.created_at.localeCompare(a.created_at)))
const completed = computed(() => overview.value ? Math.max(0, overview.value.episode_count - overview.value.ongoing_count) : 0)
const modalTitle = computed(() => modal.value === 'create' ? '记录一次身体变化' : modal.value === 'edit' ? '编辑这次记录' : modal.value === 'delete-account' ? '删除账号与所有数据' : '记录详情')
function notify(message: string) { toast.value = message; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 4500) }
function describe(e: unknown) { return e instanceof Error ? e.message : '操作未完成，请重试。' }
function navigate(next: Page) { page.value = next; location.hash = next; error.value = '' }
function hashChanged() { const next = location.hash.slice(1); if (next === 'overview' || next === 'history' || next === 'account') page.value = next }
async function load() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try { const [summary, records] = await Promise.all([api.overview(), api.episodes()]); overview.value = summary; episodes.value = records }
  catch (e) { error.value = describe(e) }
  finally { loading.value = false }
}
async function authenticated(current: User) { user.value = current; await load() }
function openCreate() { selected.value = undefined; formDirty.value = false; modalError.value = ''; modal.value = 'create' }
async function openDetail(episode: Episode) {
  selected.value = episode; modal.value = 'detail'; modalError.value = ''
  try { const latest = await api.episode(episode.id); if (selected.value?.id === episode.id && modal.value === 'detail') selected.value = latest }
  catch (e) { modalError.value = describe(e) }
}
function edit() { formDirty.value = false; modalError.value = ''; modal.value = 'edit' }
function closeModal() {
  if (formBusy.value || deleting.value) return
  if (formDirty.value && (modal.value === 'create' || modal.value === 'edit') && !window.confirm('这次修改还没有保存。确定离开吗？')) return
  modal.value = null; formDirty.value = false; modalError.value = ''; deletionPassword.value = ''; deletionConsent.value = false
}
async function saved(episode: Episode) {
  const wasEdit = modal.value === 'edit'
  formDirty.value = false; selected.value = episode; modal.value = 'detail'; modalError.value = ''
  notify(wasEdit ? '修改已保存' : '这次身体变化，已经好好记下了')
  await load()
}
async function removeEpisode() {
  if (!selected.value || !window.confirm('确定删除这条健康记录？删除后无法恢复。')) return
  deleting.value = true; modalError.value = ''
  try { await api.delete(selected.value.id, selected.value.version); modal.value = null; notify('记录已删除'); await load() }
  catch (e) { modalError.value = describe(e) }
  finally { deleting.value = false }
}
async function reloadDetail() {
  if (!selected.value) return
  try { selected.value = await api.episode(selected.value.id); modalError.value = '' }
  catch (e) { modalError.value = describe(e) }
}
function clearAccount() { user.value = null; episodes.value = []; overview.value = null; modal.value = null; error.value = ''; deletionPassword.value = ''; deletionConsent.value = false; navigate('overview') }
async function logout() {
  signingOut.value = true; error.value = ''
  try { await api.logout(); clearAccount() }
  catch (e) { if (e instanceof ApiError && e.status === 401) clearAccount(); else error.value = describe(e) }
  finally { signingOut.value = false }
}
async function exportData() {
  exporting.value = true; error.value = ''
  try { await exportRecords(); notify(isNative ? '导出文件已交给系统分享面板' : '导出文件已生成，请查看浏览器下载') }
  catch (e) { error.value = describe(e) }
  finally { exporting.value = false }
}
async function deleteAccount() {
  if (!deletionConsent.value || !deletionPassword.value || deleting.value) return
  deleting.value = true; modalError.value = ''
  try { await api.deleteAccount(deletionPassword.value); clearAccount(); notify('账号和全部健康记录已删除') }
  catch (e) { modalError.value = describe(e) }
  finally { deleting.value = false }
}
function beforeUnload(event: BeforeUnloadEvent) { if (formDirty.value && (modal.value === 'create' || modal.value === 'edit')) { event.preventDefault(); event.returnValue = '' } }
function handleKeys(event: KeyboardEvent) {
  if (!modal.value) return
  if (event.key === 'Escape') { event.preventDefault(); closeModal(); return }
  if (event.key !== 'Tab') return
  const focusables = [...(modalElement.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]') ?? [])].filter(el => el.offsetParent !== null)
  const first = focusables[0], last = focusables[focusables.length - 1]
  if (!first) { event.preventDefault(); return }
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
watch(modal, async (value, old) => {
  if (value && !old) restoreFocus = document.activeElement as HTMLElement
  document.body.style.overflow = value ? 'hidden' : ''
  await nextTick()
  if (value) modalElement.value?.focus()
  else restoreFocus?.focus()
})
onMounted(async () => {
  window.addEventListener('hashchange', hashChanged); window.addEventListener('beforeunload', beforeUnload); document.addEventListener('keydown', handleKeys)
  if (!isNative && !connectionError) {
    try { user.value = await api.me(); await load() }
    catch (e) { if (!(e instanceof ApiError && e.status === 401)) error.value = describe(e) }
  }
  booting.value = false
})
onBeforeUnmount(() => {
  window.removeEventListener('hashchange', hashChanged); window.removeEventListener('beforeunload', beforeUnload); document.removeEventListener('keydown', handleKeys)
  clearTimeout(toastTimer); document.body.style.overflow = ''
})
</script>

<template>
  <div v-if="booting" class="boot-screen"><span class="brand-mark"><Icon name="leaf" :size="30" /></span><p>正在打开你的知己…</p></div>
  <AuthScreen v-else-if="!user" @authenticated="authenticated" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <a href="#overview" class="brand"><span class="brand-mark"><Icon name="leaf" :size="27" /></span><span>知己<small>KnowYourself</small></span></a>
      <div class="nav-label">我的健康空间</div>
      <nav class="main-nav" aria-label="主导航"><button v-for="(label, key) in names" :key="key" :class="{ active: page === key }" :aria-current="page === key ? 'page' : undefined" @click="navigate(key)"><Icon :name="key === 'overview' ? 'grid' : key === 'history' ? 'book' : 'user'" /><span>{{ label }}</span><span v-if="key === 'history' && overview?.episode_count" class="nav-count">{{ overview.episode_count }}</span></button></nav>
      <div class="sidebar-bottom"><div class="sidebar-note"><span class="small-leaf"><Icon name="leaf" :size="23" /></span><p>多了解自己一点，<br />多照顾自己一些。</p></div><button class="profile-button" @click="navigate('account')"><span class="avatar">{{ user.display_name.slice(0, 1) }}</span><span><strong>{{ user.display_name }}</strong><small>我的个人空间</small></span><Icon name="chevron" :size="16" /></button></div>
    </aside>
    <div class="workspace">
      <header class="topbar"><div class="breadcrumb"><span class="mobile-brand"><Icon name="leaf" :size="21" />知己</span><span class="desktop-only">我的空间</span><span class="breadcrumb-separator">/</span><strong>{{ names[page] }}</strong></div><div class="topbar-actions"><span class="today-label">{{ date }}</span><button class="icon-button refresh-button" :disabled="loading" aria-label="刷新健康记录" title="刷新，获取其他设备上的最新记录" @click="load"><Icon name="refresh" :size="18" :class="{ spinning: loading }" /></button><button class="button primary small" @click="openCreate"><Icon name="plus" :size="17" /><span>记一笔</span></button></div></header>
      <main class="main-content">
        <div v-if="error" class="notice error page-error" role="alert">{{ error }}<button class="text-button" @click="load">重试</button></div>
        <template v-if="page === 'overview'">
          <section class="page-heading"><div><span class="eyebrow">A MOMENT FOR YOURSELF</span><h1>{{ user.display_name }}，今天感觉怎么样？</h1><p>从一次小小的记录开始，更了解自己的身体。</p></div><span class="heading-decoration" aria-hidden="true">✳</span></section>
          <section class="welcome-card"><div class="welcome-copy"><span class="welcome-kicker"><span></span>给身体留一份记忆</span><h2>每一次变化，<br />都值得认真记下。</h2><p>症状、感受、用药和好转的时刻，<br class="desktop-only" />让下次回顾时，少一点模糊，多一点了解。</p><button class="button light" @click="openCreate">记录此刻的感受<Icon name="arrow" :size="18" /></button></div><div class="botanical-art" aria-hidden="true"><div class="art-orbit orbit-one"></div><div class="art-orbit orbit-two"></div><div class="art-line"></div><div class="art-leaf leaf-one"></div><div class="art-leaf leaf-two"></div><div class="art-leaf leaf-three"></div><div class="art-leaf leaf-four"></div><div class="art-dot dot-one"></div><div class="art-dot dot-two"></div><div class="art-caption">GROW AT YOUR OWN PACE</div></div></section>
          <section class="stats-grid" aria-label="记录统计"><div class="stat-card"><span class="stat-icon"><Icon name="book" :size="21" /></span><div><span>累计健康记录</span><strong>{{ overview?.episode_count ?? '—' }}<small>次</small></strong></div><span class="stat-note">一点一滴，了解自己</span></div><div class="stat-card"><span class="stat-icon amber"><Icon name="pulse" :size="21" /></span><div><span>正在持续</span><strong>{{ overview?.ongoing_count ?? '—' }}<small>次</small></strong></div><span class="stat-note">留意身体的变化</span></div><div class="stat-card"><span class="stat-icon sage"><Icon name="check" :size="21" /></span><div><span>已结束记录</span><strong>{{ overview ? completed : '—' }}<small>次</small></strong></div><span class="stat-note">留存每一段经历</span></div></section>
          <div class="overview-columns"><section class="panel recent-panel"><div class="panel-heading"><div><span class="eyebrow">YOUR HEALTH JOURNAL</span><h2>最近的记录</h2></div><button class="text-button" @click="navigate('history')">查看全部<Icon name="arrow" :size="15" /></button></div><div v-if="loading && !overview" class="empty-state compact"><span class="loading-dot"></span><p>正在读取记录…</p></div><div v-else-if="!overview?.recent_episodes.length" class="empty-state"><span class="empty-icon"><Icon name="book" :size="29" /></span><h3>你的健康故事，从这里开始</h3><p>还没有健康记录。身体有变化时，<br />花一分钟记下来，留给未来的自己。</p><button class="button secondary small" @click="openCreate"><Icon name="plus" :size="16" />写下第一条记录</button></div><div v-else class="record-list"><button v-for="episode in overview.recent_episodes" :key="episode.id" class="record-row" @click="openDetail(episode)"><span class="record-date"><strong>{{ episode.started_at.slice(8, 10) }}</strong><small>{{ Number(episode.started_at.slice(5, 7)) }} 月</small></span><span class="record-body"><strong>{{ episode.chief_complaint }}</strong><span>{{ episode.symptoms.slice(0, 3).join(' · ') || '未添加症状标签' }}</span></span><span class="badge" :class="episode.status">{{ episode.status === 'ongoing' ? '持续中' : '已结束' }}</span><Icon name="chevron" :size="16" /></button></div></section>
          <aside class="insight-column"><section class="panel pattern-panel"><div class="panel-heading"><div><span class="eyebrow">LITTLE OBSERVATIONS</span><h2>记录中的线索</h2></div><span class="insight-icon"><Icon name="leaf" :size="23" /></span></div><template v-if="overview?.patterns.length"><div v-for="(pattern, index) in overview.patterns.slice(0, 3)" :key="index" class="pattern-item"><div><strong>{{ pattern.symptoms.join(' · ') }}</strong><span>曾共同出现 {{ pattern.occurrences }} 次</span></div><small>最近 {{ dateLabel(pattern.last_seen) }}</small></div><p class="small-note">重复出现的症状仅供回顾，不代表相同病因，也不表示可以沿用过去的用药。</p></template><div v-else class="pattern-empty"><p>每一条记录，<br />都是认识身体的一条线索。</p><span>积累记录后，这里会展示重复出现的症状组合，帮你回顾。</span></div></section><div class="gentle-note"><Icon name="info" :size="20" /><div><strong>记录是了解的开始</strong><p>知己提供信息提示，不替代专业诊断。遇到紧急不适，请及时就医。</p></div></div></aside></div>
        </template>
        <template v-else-if="page === 'history'">
          <section class="page-heading"><div><span class="eyebrow">YOUR HEALTH JOURNAL</span><h1>每一次记录，都有意义。</h1><p>回顾身体的变化，把你的健康经历串联起来。</p></div></section>
          <section class="panel history-panel"><div class="history-toolbar"><div class="filter-tabs" role="group" aria-label="按记录状态筛选"><button :class="{ active: filter === 'all' }" :aria-pressed="filter === 'all'" @click="filter = 'all'">全部记录<span>{{ episodes.length }}</span></button><button :class="{ active: filter === 'ongoing' }" :aria-pressed="filter === 'ongoing'" @click="filter = 'ongoing'">持续中</button><button :class="{ active: filter === 'ended' }" :aria-pressed="filter === 'ended'" @click="filter = 'ended'">已结束</button></div><label class="search-field"><Icon name="search" :size="17" /><input v-model="search" type="search" aria-label="搜索健康记录" placeholder="搜索症状、感受或笔记" /></label></div><div v-if="loading && !episodes.length" class="empty-state"><p>正在读取你的记录…</p></div><div v-else-if="!filtered.length" class="empty-state"><span class="empty-icon"><Icon :name="episodes.length ? 'search' : 'book'" :size="29" /></span><h3>{{ episodes.length ? '没有找到符合条件的记录' : '给身体的变化，留一个位置' }}</h3><p>{{ episodes.length ? '试试其他关键词，或切换记录状态。' : '从第一次记录开始，让每一段经历都清晰可回顾。' }}</p><button v-if="!episodes.length" class="button secondary small" @click="openCreate"><Icon name="plus" :size="16" />新增一条记录</button><button v-else class="text-button" @click="search = ''; filter = 'all'">清除筛选条件</button></div><div v-else class="history-list"><button v-for="episode in filtered" :key="episode.id" class="history-row" @click="openDetail(episode)"><div class="history-date"><span>{{ episode.started_at.slice(0, 4) }}</span><strong>{{ dateLabel(episode.started_at) }}</strong></div><div class="history-body"><div class="history-title"><h3>{{ episode.chief_complaint }}</h3><span v-if="episode.analysis.level === 'emergency'" class="urgent-dot" title="有紧急风险提示">需及时关注</span></div><div class="tag-list"><span v-for="symptom in episode.symptoms.slice(0, 4)" :key="symptom" class="tag">{{ symptom }}</span><span v-if="episode.symptoms.length > 4" class="tag">+{{ episode.symptoms.length - 4 }}</span><span v-if="!episode.symptoms.length" class="muted">未添加症状标签</span></div></div><div class="history-state"><span class="badge" :class="episode.status">{{ episode.status === 'ongoing' ? '持续中' : '已结束' }}</span><small>{{ outcomeLabels[episode.outcome] }}</small></div><Icon name="chevron" :size="17" /></button></div><div v-if="filtered.length" class="history-total">共 {{ filtered.length }} 条记录 · 按开始日期排序</div></section>
        </template>
        <template v-else>
          <section class="page-heading"><div><span class="eyebrow">YOUR SPACE, YOUR CHOICE</span><h1>你的记录，由你掌握。</h1><p>管理个人账号，以及保存在知己中的健康数据。</p></div></section>
          <div class="account-layout"><section class="panel account-profile"><span class="avatar large">{{ user.display_name.slice(0, 1) }}</span><h2>{{ user.display_name }}</h2><p>@{{ user.username }}</p><span class="account-since">{{ user.created_at.slice(0, 10) }} 加入知己</span><button class="button secondary" :disabled="signingOut" @click="logout"><Icon name="logout" :size="17" />{{ signingOut ? '正在退出…' : '退出登录' }}</button></section><div class="account-sections"><section class="panel data-panel"><h2>数据与隐私</h2><div class="setting-row"><span class="setting-icon"><Icon name="download" :size="22" /></span><div><h3>导出健康记录</h3><p>获取完整的 JSON 数据，留存一份属于自己的备份。导出文件包含健康信息，请妥善保存。</p></div><button class="button secondary small" :disabled="exporting" @click="exportData">{{ exporting ? '正在导出…' : '导出数据' }}</button></div><div class="setting-row"><span class="setting-icon"><Icon name="shield" :size="22" /></span><div><h3>同一账号，多端访问</h3><p>电脑网页、Android 和 iOS 连接同一服务后，共享账号下的记录。点击页面右上角刷新，可读取最新数据。</p></div></div><div class="setting-row danger-zone"><span class="setting-icon"><Icon name="trash" :size="22" /></span><div><h3>删除账号</h3><p>永久删除账号及全部健康记录，此操作无法撤销。</p></div><button class="text-button danger-text" @click="modalError = ''; modal = 'delete-account'">删除账号</button></div></section><section class="panel about-panel"><span class="small-leaf"><Icon name="leaf" :size="22" /></span><div><h3>知己 · 认识身体，也关照自己</h3><p>当前记录通过手动填写。健康提示基于已填写信息与规则，不代表医学诊断、疗效评价或治疗建议。</p></div></section></div></div>
        </template>
        <footer class="page-footer"><span>知己 · 好好记录，好好照顾自己</span><span>个人健康记录空间</span></footer>
      </main>
    </div>
    <nav class="mobile-nav" aria-label="移动端主导航"><button v-for="(label, key) in names" :key="key" :class="{ active: page === key }" :aria-current="page === key ? 'page' : undefined" @click="navigate(key)"><Icon :name="key === 'overview' ? 'grid' : key === 'history' ? 'book' : 'user'" :size="21" /><span>{{ key === 'account' ? '我的' : label }}</span></button></nav>
  </div>
  <Transition name="toast"><div v-if="toast" class="toast-message" role="status"><Icon name="check" :size="18" />{{ toast }}</div></Transition>
  <Teleport to="body"><div v-if="modal" class="modal-backdrop" @click.self="closeModal"><section ref="modalElement" class="modal" :class="{ 'small-modal': modal === 'delete-account' }" role="dialog" aria-modal="true" aria-labelledby="modal-heading" tabindex="-1"><header class="modal-header"><div><span class="eyebrow">{{ modal === 'delete-account' ? 'ACCOUNT & PRIVACY' : 'YOUR HEALTH JOURNAL' }}</span><h2 id="modal-heading">{{ modalTitle }}</h2></div><button class="icon-button" :disabled="formBusy || deleting" aria-label="关闭弹窗" @click="closeModal"><Icon name="close" :size="22" /></button></header><div class="modal-content"><div v-if="modalError" class="notice error" role="alert">{{ modalError }}<button v-if="modal === 'detail'" class="text-button" @click="reloadDetail">重新载入记录</button></div><EpisodeForm v-if="modal === 'create' || modal === 'edit'" :key="`${modal}-${selected?.id || 'new'}`" :episode="modal === 'edit' ? selected : undefined" @saved="saved" @dirty="formDirty = true" @busy="formBusy = $event" /><EpisodeDetail v-else-if="modal === 'detail' && selected" :episode="selected" :deleting="deleting" @edit="edit" @remove="removeEpisode" /><form v-else-if="modal === 'delete-account'" class="delete-account-form" @submit.prevent="deleteAccount"><div class="notice error"><Icon name="alert" :size="21" /><span>账号及所有健康记录将永久删除，无法恢复。你可以先返回账号页面导出备份。</span></div><label class="field">输入当前密码以确认<input v-model="deletionPassword" type="password" autocomplete="current-password" required :disabled="deleting" /></label><label class="consent"><input v-model="deletionConsent" type="checkbox" required :disabled="deleting" /><span>我理解此操作无法撤销，确认删除账号和全部记录。</span></label><div class="detail-actions"><button class="button secondary" type="button" :disabled="deleting" @click="closeModal">保留账号</button><button class="button danger" :disabled="deleting || !deletionConsent || !deletionPassword">{{ deleting ? '正在删除…' : '永久删除账号' }}</button></div></form></div></section></div></Teleport>
</template>
