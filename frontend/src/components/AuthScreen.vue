<script setup lang="ts">
import { ref } from 'vue'
import { api, connectionError } from '../api'
import type { User } from '../types'
import Icon from './Icon.vue'

defineProps<{ initialError?: string }>()
const emit = defineEmits<{ authenticated: [user: User] }>()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const displayName = ref('')
const password = ref('')
const consent = ref(false)
const loading = ref(false)
const error = ref('')
function switchMode() { mode.value = mode.value === 'login' ? 'register' : 'login'; error.value = ''; password.value = '' }
async function submit() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    const user = mode.value === 'login' ? await api.login(username.value.trim(), password.value) : await api.register(username.value.trim(), displayName.value.trim(), password.value)
    emit('authenticated', user)
  } catch (e) { error.value = e instanceof Error ? e.message : '登录失败，请重试。' }
  finally { loading.value = false }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-story">
      <a href="#" class="brand"><span class="brand-mark"><Icon name="leaf" :size="27" /></span><span>知己<small>KnowYourself</small></span></a>
      <div class="auth-story-content">
        <span class="eyebrow">你的个人健康工作台</span>
        <h1>了解这次不适，<br />也看见身体的变化。</h1>
        <p>从症状梳理到病程回顾，把实际用药、设备测量与个人健康背景放在一起。</p>
        <ul class="auth-service-list"><li><Icon name="pulse" :size="20" /><span><strong>有步骤地梳理症状</strong><small>补充关键信息，整理下一步与就诊准备</small></span></li><li><Icon name="book" :size="20" /><span><strong>连续记录病程和用药</strong><small>结合历史与真实测量，回顾身体变化</small></span></li><li><Icon name="shield" :size="20" /><span><strong>由你管理个人数据</strong><small>跨设备查看，可导出记录或删除账户</small></span></li></ul>
      </div>
      <div class="auth-story-footer"><Icon name="shield" :size="18" /> 为自己记录，由自己掌握</div>
    </section>
    <section class="auth-panel">
      <div class="auth-form-wrap">
        <span class="eyebrow">知己 · 个人健康管理</span>
        <h2>{{ mode === 'login' ? '欢迎回到知己' : '从认识自己开始' }}</h2>
        <p class="muted auth-intro">{{ mode === 'login' ? '登录账号，接着记录你的健康故事。' : '创建账号，在电脑和手机上查看同一份记录。' }}</p>
        <div v-if="connectionError" class="notice error" role="alert">{{ connectionError }}</div>
        <div v-else-if="initialError" class="notice error" role="alert">{{ initialError }}</div>
        <form @submit.prevent="submit">
          <label class="field">用户名<input v-model="username" name="username" autocomplete="username" required minlength="3" maxlength="32" placeholder="输入用户名" :disabled="loading" /></label>
          <label v-if="mode === 'register'" class="field">怎么称呼你<input v-model="displayName" name="display_name" autocomplete="nickname" required maxlength="40" placeholder="你的称呼" :disabled="loading" /></label>
          <label class="field">密码<input v-model="password" name="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required :minlength="mode === 'register' ? 10 : undefined" maxlength="128" :placeholder="mode === 'register' ? '至少 10 个字符' : '输入密码'" :disabled="loading" /></label>
          <label v-if="mode === 'register'" class="consent"><input v-model="consent" type="checkbox" required /><span>我同意将主动填写的健康信息保存到此服务，用于个人记录和规则提示。我了解可以导出数据或删除账号。</span></label>
          <div v-if="error" class="notice error" role="alert">{{ error }}</div>
          <button class="button primary auth-submit" :disabled="loading || !!connectionError">{{ loading ? '正在处理…' : mode === 'login' ? '登录知己' : '创建账号' }}<Icon v-if="!loading" name="arrow" :size="18" /></button>
        </form>
        <p class="auth-switch">{{ mode === 'login' ? '第一次来到这里？' : '已经有账号了？' }}<button class="text-button" :disabled="loading" @click="switchMode">{{ mode === 'login' ? '创建账号' : '去登录' }}</button></p>
        <div class="auth-note"><Icon name="info" :size="17" /><p>知己提供健康记录与信息提示，不作诊断，也不能替代医生。紧急不适请及时就医。</p></div>
      </div>
      <span class="auth-copyright">知己 · 好好记录，好好照顾自己</span>
    </section>
  </main>
</template>

<style scoped>
.auth-story { background: #153e52; color: white; }
.auth-story .brand, .auth-story .brand small { color: white; }.auth-story .brand small { opacity: .7; }
.auth-story-content h1 { font-family: var(--font); font-size: clamp(32px, 3vw, 44px); font-weight: 650; line-height: 1.45; letter-spacing: 0; color: white; }.auth-story-content > p { color: #c9dce5; max-width: 430px; line-height: 1.9; }.auth-story-content > .eyebrow { color: #a6cdd6; }
.auth-service-list { list-style: none; display: grid; gap: 24px; padding: 0; margin-top: 40px; }.auth-service-list li { display: flex; align-items: flex-start; gap: 14px; }.auth-service-list svg { color: #9ac8d1; flex-shrink: 0; margin-top: 3px; }.auth-service-list span { display: grid; gap: 7px; }.auth-service-list strong { font-size: 14px; font-weight: 550; }.auth-service-list small { font-size: 12px; color: #a9c4d0; line-height: 1.8; }.auth-story-footer { color: #b4cdd6; }
.auth-panel { background: var(--surface); }.auth-form-wrap h2 { font-family: var(--font); font-weight: 650; }.auth-note { border-radius: 8px; }
@media (max-width: 900px) { .auth-story { min-height: auto; padding: 24px; }.auth-story-content, .auth-story-footer { display: none; }.auth-panel { padding-top: 32px; } }
</style>
