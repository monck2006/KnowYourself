<script setup lang="ts">
import { ref } from 'vue'
import { api, connectionError } from '../api'
import type { User } from '../types'
import Icon from './Icon.vue'

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
        <span class="eyebrow">A LITTLE MORE IN TUNE WITH YOU</span>
        <h1>身体的每个信号，<br />都值得被听见。</h1>
        <p>记下不舒服的时刻，也记下好转的日子。<br />让零散的感受，成为有迹可循的健康记录。</p>
        <div class="auth-leaves" aria-hidden="true"><span></span><span></span><span></span><i></i></div>
      </div>
      <div class="auth-story-footer"><Icon name="shield" :size="18" /> 为自己记录，由自己掌握</div>
    </section>
    <section class="auth-panel">
      <div class="auth-form-wrap">
        <span class="eyebrow">YOUR HEALTH, YOUR STORY</span>
        <h2>{{ mode === 'login' ? '欢迎回到知己' : '从认识自己开始' }}</h2>
        <p class="muted auth-intro">{{ mode === 'login' ? '登录账号，接着记录你的健康故事。' : '创建账号，在电脑和手机上查看同一份记录。' }}</p>
        <div v-if="connectionError" class="notice error" role="alert">{{ connectionError }}</div>
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
