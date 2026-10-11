<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, exportRecords, isNative } from '../api'
import type { User } from '../types'
import Icon from './Icon.vue'

const props = defineProps<{ user: User; signingOut: boolean; initialSection?: 'profile' | 'security' | 'data'; profileOnly?: boolean }>()
const emit = defineEmits<{ updated: [user: User]; logout: []; remove: []; notify: [message: string] }>()
const section = ref<'profile' | 'security' | 'data'>(props.initialSection ?? 'security')
const sections = computed(() => props.profileOnly ? { profile: '个人资料' } : { security: '账号安全', data: '数据与隐私' })
const nickname = ref(props.user.display_name)
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const profileBusy = ref(false)
const passwordBusy = ref(false)
const exporting = ref(false)
const profileError = ref('')
const passwordError = ref('')
const exportError = ref('')
watch(() => props.user.display_name, value => { nickname.value = value })
function canLeave() {
  if (profileBusy.value || passwordBusy.value || exporting.value) return false
  return (nickname.value.trim() === props.user.display_name && !currentPassword.value && !newPassword.value && !confirmPassword.value) || window.confirm('还有尚未保存的修改，确定离开吗？')
}
defineExpose({ canLeave })
async function saveProfile() {
  if (profileBusy.value || !nickname.value.trim()) return
  profileBusy.value = true; profileError.value = ''
  try { emit('updated', await api.updateProfile(nickname.value.trim())); emit('notify', '称呼已更新') }
  catch (e) { profileError.value = e instanceof Error ? e.message : '保存失败，请重试。' }
  finally { profileBusy.value = false }
}
async function changePassword() {
  if (passwordBusy.value) return
  passwordError.value = ''
  if (newPassword.value !== confirmPassword.value) { passwordError.value = '两次输入的新密码不一致。'; return }
  if (currentPassword.value === newPassword.value) { passwordError.value = '新密码需要与当前密码不同。'; return }
  passwordBusy.value = true
  try {
    await api.changePassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''; newPassword.value = ''; confirmPassword.value = ''
    emit('notify', '密码已更新，其他设备需重新登录')
  } catch (e) { passwordError.value = e instanceof Error ? e.message : '修改失败，请重试。' }
  finally { passwordBusy.value = false }
}
async function exportData() {
  if (exporting.value) return
  exporting.value = true; exportError.value = ''
  try { await exportRecords(); emit('notify', isNative ? '导出文件已交给系统分享面板' : '导出文件已生成，请查看浏览器下载') }
  catch (e) { exportError.value = e instanceof Error ? e.message : '导出失败，请重试。' }
  finally { exporting.value = false }
}
</script>

<template>
  <section v-if="!initialSection" class="page-heading"><div><span class="eyebrow">个人账户管理</span><h1>账户设置</h1><p>管理个人账号，以及保存在知己中的健康数据。</p></div></section>
  <div class="account-settings-layout">
    <section class="panel account-identity"><span class="avatar large">{{ user.display_name.slice(0, 1) }}</span><div><h2>{{ user.display_name }}</h2><p>@{{ user.username }} · {{ user.created_at.slice(0, 10) }} 加入知己</p></div><button v-if="!profileOnly" class="button secondary" :disabled="signingOut || profileBusy || passwordBusy || exporting" @click="canLeave() && emit('logout')"><Icon name="logout" :size="17" />{{ signingOut ? '正在退出…' : '退出登录' }}</button></section>
    <div class="account-settings-body" :class="{ 'profile-only': profileOnly }"><div v-if="!profileOnly" class="account-settings-nav" role="group" aria-label="账户设置分组"><button v-for="(label, key) in sections" :key="key" :class="{ active: section === key }" :aria-pressed="section === key" @click="section = key">{{ label }}<Icon name="chevron" :size="15" /></button></div><div class="account-sections">
      <section v-show="section === 'profile'" class="panel data-panel"><h2>个人资料</h2><form class="account-form" @submit.prevent="saveProfile"><label class="field">怎么称呼你<input v-model="nickname" autocomplete="nickname" required maxlength="40" :disabled="profileBusy || signingOut" /></label><div v-if="profileError" class="notice error" role="alert">{{ profileError }}</div><button class="button secondary small" :disabled="profileBusy || signingOut || !nickname.trim() || nickname.trim() === user.display_name">{{ profileBusy ? '正在保存…' : '保存称呼' }}</button></form></section>
      <section v-show="section === 'security'" class="panel data-panel"><h2>账号安全</h2><p class="small-note account-security-note">修改密码后，当前设备保持登录，其他设备的会话将退出。</p><form class="account-form" @submit.prevent="changePassword"><input class="sr-only" :value="user.username" name="username" autocomplete="username" tabindex="-1" readonly aria-label="当前用户名" /><div class="form-grid"><label class="field">当前密码<input v-model="currentPassword" type="password" autocomplete="current-password" required minlength="10" maxlength="128" :disabled="passwordBusy || signingOut" /></label><label class="field">新密码<input v-model="newPassword" type="password" autocomplete="new-password" required minlength="10" maxlength="128" placeholder="10–128 个字符" :disabled="passwordBusy || signingOut" /></label><label class="field">再次输入新密码<input v-model="confirmPassword" type="password" autocomplete="new-password" required minlength="10" maxlength="128" :disabled="passwordBusy || signingOut" /></label></div><div v-if="passwordError" class="notice error" role="alert">{{ passwordError }}</div><button class="button secondary small" :disabled="passwordBusy || signingOut">{{ passwordBusy ? '正在更新…' : '更新密码' }}</button></form></section>
      <section v-show="section === 'data'" class="panel data-panel"><h2>数据与隐私</h2><div class="setting-row"><span class="setting-icon"><Icon name="download" :size="22" /></span><div><h3>导出健康记录</h3><p>获取完整的 JSON 数据，留存一份属于自己的备份。导出文件包含健康信息，请妥善保存。</p></div><button class="button secondary small" :disabled="exporting || signingOut" @click="exportData">{{ exporting ? '正在导出…' : '导出 JSON' }}</button></div><p v-if="exportError" class="notice error" role="alert">{{ exportError }}</p><div class="setting-row"><span class="setting-icon"><Icon name="shield" :size="22" /></span><div><h3>同一账号，多端访问</h3><p>电脑网页、Android 和 iOS 连接同一服务后，共享账号下的记录。可在页面右上角刷新最新记录。</p></div></div><div class="setting-row danger-zone"><span class="setting-icon"><Icon name="trash" :size="22" /></span><div><h3>删除账号</h3><p>永久删除账号及全部健康记录，此操作无法撤销。</p></div><button class="text-button danger-text" :disabled="profileBusy || passwordBusy || exporting || signingOut" @click="emit('remove')">删除账号</button></div></section>
      <section v-show="section === 'data'" class="panel about-panel"><span class="small-leaf"><Icon name="leaf" :size="22" /></span><div><h3>知己 · 认识身体，也关照自己</h3><p>病程、健康档案及设备读数在同一账号下保存。测量保留实际来源，区域汇总由你自愿选择参与。</p></div></section>
    </div>
  </div></div>
</template>

<style scoped>
.account-settings-layout { display: grid; gap: 20px; min-width: 0; max-width: 960px; margin: 0 auto; }.account-settings-body.profile-only{grid-template-columns:minmax(0,1fr)}.account-settings-layout>.page-heading{display:none}.account-identity{border-radius:20px}.account-sections{min-width:0}.data-panel{border-radius:20px}
.account-identity { display: flex; align-items: center; gap: 20px; padding: 24px 28px; }
.account-identity > div { flex: 1; min-width: 0; }.account-identity h2 { margin: 0 0 8px; font-size: 20px; overflow-wrap: anywhere; }.account-identity p { color: var(--muted); font-size: 12px; line-height: 1.8; margin: 0; overflow-wrap: anywhere; }
.account-identity .avatar { width: 56px; height: 56px; font-size: 23px; flex-shrink: 0; }
.account-settings-body { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 24px; align-items: start; }
.account-settings-nav { display: grid; gap: 6px; }.account-settings-nav button { display: flex; align-items: center; justify-content: space-between; padding: 13px 14px; text-align: left; border-radius: 8px; font-size: 14px; color: var(--muted); }.account-settings-nav button.active { color: var(--primary-deep); font-weight: 650; background: var(--primary-soft); }
.data-panel { padding: 28px; }.data-panel > h2 { font-size: 18px; margin-bottom: 24px; }.account-form { max-width: 720px; }.account-form > .field { max-width: 420px; }.account-form .form-grid { grid-template-columns: minmax(0, 1fr); max-width: 420px; }
.setting-row { align-items: flex-start; gap: 16px; padding: 20px 0; }.setting-row > div { min-width: 0; }.setting-row .button { flex-shrink: 0; }.danger-zone { margin-top: 10px; border-top: 1px solid var(--border); background: transparent; }.danger-zone .text-button { font-size: 12px; }
@media (max-width: 760px) { .account-settings-body { grid-template-columns: minmax(0, 1fr); gap: 18px; }.account-settings-nav { display: flex; justify-content: space-between; border-bottom: 1px solid var(--border); gap: 0; }.account-settings-nav button { padding: 12px 10px; border-radius: 6px 6px 0 0; font-size: 13px; }.account-settings-nav svg { display: none; }.account-identity { padding: 20px; gap: 14px; flex-wrap: wrap; }.account-identity .avatar { width: 44px; height: 44px; font-size: 18px; }.account-identity .button { width: 100%; }.data-panel { padding: 22px 18px; }.setting-row { flex-wrap: wrap; }.setting-row .button { margin-left: 0; } }
</style>
