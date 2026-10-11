<script setup lang="ts">
import { computed } from 'vue'
import type { Episode, User } from '../types'
import Icon from './Icon.vue'

const props = defineProps<{ user: User; episodes: Episode[]; loading: boolean }>()
const emit = defineEmits<{ open: [section: 'profile' | 'records' | 'health' | 'archive' | 'devices' | 'account'] }>()
const ongoing = computed(() => props.episodes.filter(item => item.status === 'ongoing').length)
const groups = [
  [{ key: 'records', label: '问诊记录', note: '近期与持续中的病程', icon: 'book' },
   { key: 'health', label: '健康数据', note: '查看测量与身体变化', icon: 'heart' },
   { key: 'archive', label: '健康档案', note: '让每次问诊更了解你', icon: 'user' }],
  [{ key: 'devices', label: '设备与同步', note: '连接你的健康设备', icon: 'pulse' },
   { key: 'account', label: '账号与设置', note: '安全、隐私与数据管理', icon: 'shield' }],
] as const
</script>

<template>
  <div class="mine-home">
    <section class="mine-welcome">
      <button class="mine-identity" @click="emit('open', 'profile')" aria-label="查看个人资料">
        <span class="mine-avatar">{{ user.display_name.slice(0, 1) }}</span>
        <span class="mine-identity-text"><span class="mine-kicker">我的知己</span><strong>{{ user.display_name }}</strong><small>@{{ user.username }}</small></span>
        <Icon name="chevron" :size="19" />
      </button>
      <div class="mine-overview" aria-label="已保存的问诊概况">
        <button @click="emit('open', 'records')"><strong>{{ loading && !episodes.length ? '—' : episodes.length }}</strong><span>问诊记录</span></button>
        <span class="mine-stat-divider" aria-hidden="true"></span>
        <button @click="emit('open', 'records')"><strong>{{ loading && !episodes.length ? '—' : ongoing }}</strong><span>持续中的病程</span></button>
      </div>
    </section>
    <div class="mine-group-label">我的健康</div>
    <section v-for="(group, index) in groups" :key="index" class="mine-group" :aria-label="index === 0 ? '我的健康' : '管理与设置'">
      <button v-for="item in group" :key="item.key" class="mine-entry" @click="emit('open', item.key)">
        <span class="mine-entry-icon"><Icon :name="item.icon" :size="21" /></span>
        <span class="mine-entry-copy"><strong>{{ item.label }}</strong><small>{{ item.note }}</small></span>
        <span v-if="item.key === 'records' && ongoing" class="mine-entry-count">{{ ongoing }} 条持续中</span>
        <Icon name="chevron" :size="17" />
      </button>
    </section>
    <p class="mine-footnote"><Icon name="leaf" :size="15" />认识身体，也关照自己</p>
  </div>
</template>

<style scoped>
.mine-home{width:100%;max-width:760px;margin:10px auto 0}.mine-welcome{border:1px solid #e1ecea;border-radius:24px;background:linear-gradient(115deg,#edf7f4 0%,#f9fcfb 72%);padding:30px 30px 0;overflow:hidden}.mine-identity{display:flex;align-items:center;width:100%;text-align:left;gap:18px}.mine-avatar{display:grid;place-items:center;flex-shrink:0;width:66px;height:66px;border-radius:23px;background:#fff;border:1px solid #dbeae5;color:#236b62;font-size:28px;box-shadow:0 4px 12px #2b6f5e08}.mine-identity-text{display:grid;gap:4px;flex:1;min-width:0}.mine-kicker{font-size:11px;letter-spacing:.07em;color:#688b82}.mine-identity-text strong{font-size:23px;letter-spacing:-.02em;overflow-wrap:anywhere;color:var(--ink)}.mine-identity-text small{font-size:12px;color:var(--muted)}.mine-identity>svg{color:#8da59e}.mine-overview{display:flex;align-items:center;margin-top:25px;padding:20px 0 22px;border-top:1px solid #dceae5}.mine-overview button{flex:1;display:flex;align-items:baseline;justify-content:center;gap:10px}.mine-overview strong{font-size:25px;font-weight:600;letter-spacing:-.04em;color:#205e54;font-variant-numeric:tabular-nums}.mine-overview span{font-size:12px;color:#607c73}.mine-stat-divider{height:26px;width:1px;background:#d6e5de}.mine-group-label{margin:28px 5px 11px;color:var(--muted);font-size:12px}.mine-group{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:0 23px;margin-bottom:16px}.mine-entry{display:flex;width:100%;align-items:center;gap:15px;text-align:left;padding:20px 0;border-bottom:1px solid var(--border-faint);min-height:82px}.mine-entry:last-child{border-bottom:0}.mine-entry-icon{display:grid;place-items:center;width:40px;height:40px;flex-shrink:0;border-radius:13px;color:#33796d;background:#f0f7f4}.mine-entry-copy{display:grid;gap:5px;flex:1;min-width:0}.mine-entry-copy strong{font-size:14px;font-weight:600}.mine-entry-copy small{font-size:12px;color:var(--muted)}.mine-entry>svg{color:var(--faint);flex-shrink:0}.mine-entry-count{font-size:11px;color:#3b7e6f;white-space:nowrap}.mine-footnote{display:flex;align-items:center;justify-content:center;gap:7px;color:var(--faint);font-size:11px;padding:15px 0 8px}.mine-entry:hover .mine-entry-copy strong,.mine-identity:hover strong{color:var(--primary-deep)}
@media(max-width:640px){.mine-home{margin-top:0}.mine-welcome{padding:23px 20px 0;border-radius:21px}.mine-avatar{width:58px;height:58px;border-radius:20px;font-size:25px}.mine-identity-text strong{font-size:21px}.mine-group{padding:0 18px;border-radius:18px}.mine-entry{padding:18px 0;gap:12px}.mine-overview{margin-top:22px}.mine-overview button{display:grid;gap:4px;justify-items:center}.mine-entry-count{display:none}}
</style>
