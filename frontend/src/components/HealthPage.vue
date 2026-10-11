<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { ApiError, api } from '../api'
import { coarseGrid, contextLabels, metrics, sourceLabels, vendorDerivedMetrics } from '../healthLabels'
import type { HealthContext, HealthProfile, ObservationInput, ObservationMetric } from '../types'
import { connectBluetoothHeartRate, getHealthDeviceStatus, readHealthDeviceData, requestHealthDevicePermissions } from '../lib/healthDevice'
import type { HealthDeviceItem, HealthDeviceResult, HealthDeviceStatus } from '../lib/healthDevice'
import Icon from './Icon.vue'

const props = defineProps<{ initialSection?: 'profile' | 'devices' | 'measurements' | 'region'; embedded?: boolean }>()
const emit = defineEmits<{ changed: []; notify: [message: string] }>()
const section = ref<'profile' | 'devices' | 'measurements' | 'region'>(props.initialSection ?? 'devices')
const sections = { profile: '健康档案', measurements: '健康数据', devices: '设备与同步', region: '区域动态' }
const editingProfile = ref(false)
const context = ref<HealthContext | null>(null)
const loading = ref(false), error = ref(''), profileError = ref(''), profileBusy = ref(false), conflict = ref(false)
const profileLoaded = ref(false), profileDirty = ref(false)
const profile = reactive({ version: 0, birth_year: null as number | null, chronic: '', family: '', province: '', city: '', district: '', code: '', regional_consent: false })
const locating = ref(false), locationNotice = ref('')
const deviceStatus = ref<HealthDeviceStatus | null>(null), deviceBusy = ref(false), deviceError = ref('')
const deviceResult = shallowRef<HealthDeviceResult | null>(null)
const importBusy = ref(false), importNotice = ref('')
const deviceDays = ref<7 | 30>(7)
const authorizationRequested = ref(false)
const bluetooth = shallowRef<{ deviceName: string; disconnect: () => void; isConnected?: () => boolean } | null>(null)
const bluetoothReading = shallowRef<HealthDeviceItem | null>(null)
function localDateTime() { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
const manual = reactive({ metric: 'heart_rate' as ObservationMetric, value: null as number | null, measured_at: localDateTime(), context: 'unknown', device_name: '' })
const manualBusy = ref(false), manualError = ref('')
let manualId = crypto.randomUUID()
let active = true, contextRequest = 0
let bluetoothTimer: ReturnType<typeof setInterval> | undefined
const currentMetric = computed(() => metrics[manual.metric])
const recentReadings = computed(() => context.value?.observations.items.slice(0, 20) ?? [])
const availableBaselines = computed(() => Object.fromEntries(Object.entries(context.value?.observations.baseline ?? {}).filter(([, item]) => item.reading_count > 0)))
const permissionLabels = { granted: '已获得读取权限', unknown: '读取权限状态无法确认', not_requested: '尚未请求读取权限', denied: '读取权限未获允许' }
const stateLabels = { ready: '可尝试读取', permission: '需要系统授权', unavailable: '当前不可用' }
function describe(reason: unknown) { return reason instanceof Error ? reason.message : '操作未完成，请重试。' }
function time(value: string) { return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }
function applyProfile(value: HealthProfile) {
  Object.assign(profile, { version: value.version, birth_year: value.birth_year, chronic: value.chronic_conditions.join('\n'), family: value.family_history.join('\n'), ...value.region, regional_consent: value.regional_consent })
  profileLoaded.value = true; profileDirty.value = false; conflict.value = false
}
async function loadContext(replaceProfile = false) {
  const request = ++contextRequest
  loading.value = true; error.value = ''
  try {
    const result = await api.healthContext()
    if (!active || request !== contextRequest) return
    context.value = result
    if (replaceProfile || !profileLoaded.value) applyProfile(result.profile)
  } catch (reason) { if (active && request === contextRequest) error.value = describe(reason) }
  finally { if (active && request === contextRequest) loading.value = false }
}
function conditions(text: string) {
  const values = [...new Set(text.split(/[\n,，、;；]+/).map(item => item.trim()).filter(Boolean))]
  if (values.length > 30 || values.some(item => item.length > 100)) throw new Error('每类病史最多 30 项，每项不超过 100 字。')
  return values
}
async function saveProfile() {
  if (profileBusy.value || loading.value || !profileLoaded.value || conflict.value) return
  profileBusy.value = true; profileError.value = ''; contextRequest++
  try {
    const saved = await api.saveHealthProfile({ version: profile.version, birth_year: profile.birth_year === null || String(profile.birth_year) === '' ? null : Number(profile.birth_year), chronic_conditions: conditions(profile.chronic), family_history: conditions(profile.family), region: { province: profile.province.trim(), city: profile.city.trim(), district: profile.district.trim(), code: profile.code, label: '' }, regional_consent: profile.regional_consent })
    if (!active) return
    applyProfile(saved); editingProfile.value = false; emit('notify', '健康档案已保存'); emit('changed'); await loadContext()
  } catch (reason) { if (active) { profileError.value = describe(reason); conflict.value = reason instanceof ApiError && reason.status === 409 } }
  finally { if (active) profileBusy.value = false }
}
async function reloadProfile() {
  if (profileDirty.value && !window.confirm('重新载入会替换本页尚未保存的档案修改，继续吗？')) return
  await loadContext(true)
  if (active && !error.value) profileError.value = ''
}
function manualRegion() { profile.code = ''; locationNotice.value = ''; profileDirty.value = true }
function locate() {
  locationNotice.value = ''
  if (!navigator.geolocation) { locationNotice.value = '当前环境不支持定位，请手动填写省市区。'; return }
  locating.value = true
  navigator.geolocation.getCurrentPosition(position => {
    if (!active) return
    try { profile.code = coarseGrid(position.coords.latitude, position.coords.longitude); profile.province = ''; profile.city = ''; profile.district = ''; profileDirty.value = true; locationNotice.value = '已选约 10 公里位置网格，保存档案后生效。原始经纬度不会发送或保存。' }
    catch (reason) { locationNotice.value = describe(reason) }
    locating.value = false
  }, () => { if (active) { locating.value = false; locationNotice.value = '定位未完成，请手动填写省市区。' } }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 3600000 })
}
async function checkDevice() {
  try { const result = await getHealthDeviceStatus(); if (active) { deviceStatus.value = result; authorizationRequested.value = result.read_permission === 'granted' } }
  catch (reason) { if (active) deviceError.value = describe(reason) }
}
async function authorize() {
  deviceBusy.value = true; deviceError.value = ''
  try { const result = await requestHealthDevicePermissions(); if (active) { deviceStatus.value = result; authorizationRequested.value = result.state === 'ready' && result.read_permission !== 'denied' } }
  catch (reason) { if (active) deviceError.value = describe(reason) }
  finally { if (active) deviceBusy.value = false }
}
async function readDevice() {
  if (!authorizationRequested.value || deviceStatus.value?.state !== 'ready') return
  deviceBusy.value = true; deviceError.value = ''; deviceResult.value = null; importNotice.value = ''
  try { const result = await readHealthDeviceData(deviceDays.value); if (active) { deviceStatus.value = result; deviceResult.value = result } }
  catch (reason) { if (active) deviceError.value = describe(reason) }
  finally { if (active) deviceBusy.value = false }
}
async function importReadings(items: ObservationInput[]) {
  if (importBusy.value || !items.length) return
  importBusy.value = true; deviceError.value = ''; importNotice.value = ''
  let inserted = 0, duplicates = 0
  try {
    for (let index = 0; index < items.length; index += 200) {
      if (!active) return
      const result = await api.importObservations(items.slice(index, index + 200))
      inserted += result.inserted; duplicates += result.duplicates
    }
    if (!active) return
    importNotice.value = `已新增 ${inserted} 条，跳过 ${duplicates} 条重复读数。`
    deviceResult.value = null; emit('changed'); await loadContext()
  } catch (reason) { if (active) deviceError.value = `${describe(reason)}${inserted ? ` 已成功导入 ${inserted} 条，可重试剩余数据；重复读数会跳过。` : ''}` }
  finally { if (active) importBusy.value = false }
}
async function connectBluetooth() {
  deviceBusy.value = true; deviceError.value = ''
  try {
    const connected = await connectBluetoothHeartRate(item => { if (active) bluetoothReading.value = item })
    if (active) {
      bluetooth.value = connected
      bluetoothTimer = setInterval(() => {
        if (bluetooth.value?.isConnected && !bluetooth.value.isConnected()) { disconnectBluetooth(); deviceError.value = '蓝牙设备连接已断开，请重新连接后读取。' }
      }, 1000)
    }
    else connected.disconnect()
  } catch (reason) { if (active) deviceError.value = describe(reason) }
  finally { if (active) deviceBusy.value = false }
}
function disconnectBluetooth() { clearInterval(bluetoothTimer); bluetooth.value?.disconnect(); bluetooth.value = null; bluetoothReading.value = null }
async function saveManual() {
  if (manualBusy.value || manual.value === null) return
  manualBusy.value = true; manualError.value = ''
  try {
    const result = await api.importObservations([{ source: 'manual', source_id: `manual-${manualId}`, metric: manual.metric, value: Number(manual.value), unit: currentMetric.value.unit, measured_at: new Date(manual.measured_at).toISOString(), context: manual.context, device_name: manual.device_name.trim() }])
    if (!active) return
    manualId = crypto.randomUUID(); manual.value = null; emit('notify', `手动测量已保存${result.duplicates ? '（已跳过重复条目）' : ''}`); emit('changed'); await loadContext()
  } catch (reason) { if (active) manualError.value = describe(reason) }
  finally { if (active) manualBusy.value = false }
}
function manualChanged() { manualId = crypto.randomUUID() }
function cancelProfileEdit() { if (context.value) applyProfile(context.value.profile); editingProfile.value = false }
function canLeave() { if (profileBusy.value || manualBusy.value || importBusy.value) return false; return (!profileDirty.value && manual.value === null) || window.confirm('还有尚未保存的健康信息，确定离开吗？') }
defineExpose({ canLeave })
watch(section, value => { if (value === 'devices' && !deviceStatus.value) void checkDevice() })
onMounted(() => { void loadContext(); if (section.value === 'devices') void checkDevice() })
onBeforeUnmount(() => { active = false; contextRequest++; disconnectBluetooth() })
</script>

<template>
  <div class="health-page">
    <section v-if="!embedded" class="page-heading"><div><span class="eyebrow">个人健康背景</span><h1>健康档案与设备</h1><p>管理既往情况与真实测量，为每次病程建立个人比较依据。</p></div><button class="button secondary small" :disabled="loading || profileBusy" @click="loadContext()"><Icon name="refresh" :size="16" />刷新数据</button></section>
    <div v-if="error" class="notice error" role="alert">{{ error }}<button class="text-button" @click="loadContext()">重试</button></div>
    <p v-if="loading && !context" class="health-empty" role="status">正在读取健康档案…</p>
    <div v-if="!embedded" class="health-section-nav" role="group" aria-label="健康管理分区"><button v-for="(label, key) in sections" :key="key" :class="{ active: section === key }" :aria-pressed="section === key" @click="section = key">{{ label }}</button></div><div class="health-layout" :class="{ 'single-section': section !== 'devices' }">
      <section v-show="section === 'profile'" class="panel health-panel profile-panel"><h2>个人健康档案</h2><p class="health-caption">用于结合既往情况理解本次记录。出生年份、慢性病及家族病史均可留空。</p>
        <div v-if="context && !editingProfile && context.profile.version" class="saved-profile"><dl><div><dt>出生年份</dt><dd>{{ context.profile.birth_year || '未填写' }}</dd></div><div><dt>既往慢性病</dt><dd>{{ context.profile.chronic_conditions.join('、') || '未填写' }}</dd></div><div><dt>家族病史</dt><dd>{{ context.profile.family_history.join('、') || '未填写' }}</dd></div><div><dt>所在区域</dt><dd>{{ context.profile.region.label || '未选择' }}</dd></div><div><dt>区域汇总</dt><dd>{{ context.profile.regional_consent ? '自愿参与' : '未参与' }}</dd></div></dl><button class="button secondary small" @click="editingProfile = true">编辑健康档案</button></div><form v-show="editingProfile || !context?.profile.version" @submit.prevent="saveProfile" @input="profileDirty = true" @change="profileDirty = true"><fieldset :disabled="!profileLoaded || profileBusy || loading"><label class="field">出生年份<input v-model="profile.birth_year" type="number" min="1900" :max="new Date().getFullYear()" placeholder="选填" /></label><div class="form-grid"><label class="field">既往慢性病<textarea v-model="profile.chronic" rows="3" maxlength="3030" placeholder="如：高血压，每行一项"></textarea></label><label class="field">家族病史<textarea v-model="profile.family" rows="3" maxlength="3030" placeholder="每行一项，按实际了解填写"></textarea></label></div>
          <h3>所在区域与自愿汇总</h3><div class="region-fields"><label class="field">省份<input v-model="profile.province" maxlength="60" placeholder="如：浙江省" @input="manualRegion" /></label><label class="field">城市<input v-model="profile.city" maxlength="60" placeholder="如：杭州市" @input="manualRegion" /></label><label class="field">区县<input v-model="profile.district" maxlength="60" placeholder="选填" @input="manualRegion" /></label></div><button class="button secondary small" type="button" :disabled="locating" @click="locate">{{ locating ? '正在选择位置…' : '使用约 10 公里位置网格' }}</button><p v-if="profile.code.startsWith('grid:')" class="health-caption">当前选择：粗略位置网格（不含原始 GPS）</p><p v-if="locationNotice" class="health-caption" role="status">{{ locationNotice }}</p>
          <label class="health-consent"><input v-model="profile.regional_consent" type="checkbox" /><span>自愿将我的症状记录纳入所在区域匿名汇总。每组至少 5 位不同参与者才显示人数档位，可随时取消并保存撤回。</span></label>
        </fieldset><div v-if="profileError" class="notice error" role="alert">{{ profileError }}<button v-if="conflict" type="button" class="text-button" @click="reloadProfile">重新载入档案</button></div><button class="button primary small" :disabled="!profileLoaded || profileBusy || loading || conflict || !profileDirty">{{ profileBusy ? '正在保存…' : '保存健康档案' }}</button><button v-if="editingProfile" class="text-button cancel-profile" type="button" :disabled="profileBusy" @click="cancelProfileEdit">取消编辑</button></form>
      </section>

      <section v-show="section === 'devices'" class="panel health-panel device-panel"><div class="health-panel-heading"><h2>健康设备与系统数据</h2><span class="source-status-label">保留实际来源</span></div><p class="health-caption">Android 读取 Health Connect，iOS 读取 Apple 健康中你允许的记录。实际可读指标取决于设备和系统已有数据。</p>
        <template v-if="deviceStatus"><div class="device-state"><strong>{{ deviceStatus.source ? sourceLabels[deviceStatus.source] : '当前环境' }} · {{ stateLabels[deviceStatus.state] }}</strong><span>{{ permissionLabels[deviceStatus.read_permission] }}</span></div><p class="health-caption">{{ deviceStatus.message }}</p></template><p v-else class="health-caption" role="status">正在检查设备读取能力…</p>
        <div v-if="deviceStatus && deviceStatus.source !== 'bluetooth' && deviceStatus.state !== 'unavailable'" class="device-controls"><button class="button secondary small" :disabled="deviceBusy || importBusy" @click="authorize">{{ deviceBusy ? '正在处理…' : '请求系统读取权限' }}</button><label class="field">读取范围<select v-model="deviceDays" :disabled="deviceBusy || importBusy"><option :value="7">最近 7 天</option><option :value="30">最近 30 天</option></select></label><button class="button primary small" :disabled="deviceBusy || importBusy || !authorizationRequested || deviceStatus.state !== 'ready'" @click="readDevice">读取健康数据</button></div>
        <div v-if="deviceStatus?.source === 'bluetooth'" class="device-controls"><button v-if="!bluetooth" class="button secondary small" :disabled="deviceBusy" @click="connectBluetooth">连接蓝牙心率设备</button><template v-else><span>{{ bluetooth.deviceName }}</span><button class="text-button" @click="disconnectBluetooth">断开</button><p v-if="bluetoothReading">最新心率：<strong>{{ bluetoothReading.value }} 次/分</strong><br /><small>{{ time(bluetoothReading.measured_at) }} · 状态未知</small></p><button v-if="bluetoothReading" class="button primary small" :disabled="importBusy" @click="importReadings([bluetoothReading])">保存当前设备读数</button><p v-else class="health-caption">已建立连接，正在等待设备真实读数…</p></template></div>
        <div v-if="deviceResult" class="device-preview"><p class="health-caption">{{ deviceResult.message }}</p><p v-if="deviceResult.truncated" class="health-caption">记录较多，本次只读取了有限的最近记录。</p><p>读取到 {{ deviceResult.items.length }} 条真实记录。</p><button v-if="deviceResult.items.length" class="button primary small" :disabled="importBusy" @click="importReadings(deviceResult.items)">{{ importBusy ? '正在导入…' : `导入这 ${deviceResult.items.length} 条记录` }}</button></div><p v-if="importNotice" class="health-caption" role="status">{{ importNotice }}</p><p v-if="deviceError" class="notice error" role="alert">{{ deviceError }}<button v-if="!deviceStatus" class="text-button" @click="checkDevice">重新检查</button></p>
        <p class="health-caption device-note">Apple 健康不会公开是否拒绝读取；没有返回数据不等于没有健康记录。设备来源和手动来源分开保存，未知测量状态不会当作静息基线。</p>
        <details class="health-panel performance-panel"><summary>运动表现（厂商派生，本应用不提供）</summary><p class="health-caption">下列“运动表现”由手表厂商自行计算，健康平台并不存储，本应用<b>不计算、不推断</b>，因此这里始终显示“暂不可用”。若你从厂商 App 导出，请附上来源标明为“厂商估算”，不要作为本应用结论。</p><ul class="performance-list"><li v-for="name in vendorDerivedMetrics" :key="name"><span>{{ name }}</span><small>暂不可用</small></li></ul></details>
      </section>

      <details v-show="section === 'measurements'" class="panel health-panel manual-measurement"><summary>手动添加一次测量</summary><p class="health-caption">没有连接设备也可以记录实测值；这些数据始终标记为「手动录入」。</p><form @submit.prevent="saveManual" @input="manualChanged"><fieldset :disabled="manualBusy"><div class="form-grid"><label class="field">指标<select v-model="manual.metric" @change="manual.value = null"><option v-for="(item, key) in metrics" :key="key" :value="key">{{ item.label }}</option></select></label><label class="field">数值 · {{ currentMetric.displayUnit }}<input v-model="manual.value" required type="number" inputmode="decimal" :min="currentMetric.min" :max="currentMetric.max" :step="currentMetric.step" /></label><label class="field">实际测量时间<input v-model="manual.measured_at" required type="datetime-local" :max="localDateTime()" /></label><label class="field">测量时状态<select v-model="manual.context"><option value="unknown">不确定</option><option value="resting">静息</option><option value="active">活动中</option></select></label></div><label class="field">测量工具名称<input v-model="manual.device_name" maxlength="100" placeholder="选填，如：家用体温计" /></label></fieldset><p v-if="manualError" class="notice error" role="alert">{{ manualError }}</p><button class="button secondary small" :disabled="manualBusy">{{ manualBusy ? '正在保存…' : '保存手动测量' }}</button></form></details>

      <section v-if="context" v-show="section === 'region'" class="panel health-panel region-panel"><h2>所在区域 · 近 {{ context.region.window_days }} 天</h2><p v-if="context.region.region_label">{{ context.region.region_label }}</p><p v-if="context.region.status === 'disabled'" class="health-caption">保存所在区域并自愿开启汇总后，可查看达到展示条件的匿名信号。</p><p v-else-if="context.region.status === 'insufficient'" class="health-caption">当前尚未达到每组至少 5 位不同参与者的展示条件。这不能用于排除感染。</p><article v-for="signal in context.region.signals" :key="signal.cluster" class="regional-signal"><h3>{{ signal.label }} · {{ signal.people_band }} 人</h3><p>{{ signal.description }}</p><span>{{ signal.trend === 'increased' ? '较前一时段增加' : signal.trend === 'stable' ? '与前一时段相近' : '暂无可比趋势' }}</span></article><p class="health-caption">{{ context.region.notice }}</p><button class="button secondary small" @click="section = 'profile'; editingProfile = true">设置地区与参与选项</button></section>
    </div>

    <section v-if="context" v-show="section === 'measurements'" class="panel health-panel readings-panel"><h2>最近测量与个人静息基线</h2><p class="health-caption">{{ context.observations.notice || '基线根据最近 30 天至少 3 个不同日期的静息记录计算，仅描述个人变化。' }}</p><div class="baseline-grid"><div v-for="(baseline, key) in availableBaselines" :key="key" class="baseline-card"><strong>{{ metrics[key as ObservationMetric]?.label || key }}</strong><p v-if="baseline.median != null">{{ baseline.median }} <small>{{ metrics[key as ObservationMetric]?.displayUnit || baseline.unit }}</small></p><p v-else class="health-caption">静息记录不足 3 个日期</p><span>来自 {{ baseline.sample_count }} 个日期 · {{ baseline.reading_count }} 条测量</span><small v-if="baseline.p10 != null && baseline.p90 != null">个人分布 {{ baseline.p10 }}–{{ baseline.p90 }}</small></div></div><p v-if="!recentReadings.length" class="health-empty">还没有测量记录。先连接设备，或手动记下一次实测值。</p><div v-else class="reading-list"><div v-for="item in recentReadings" :key="item.id" class="reading-item"><div><strong>{{ metrics[item.metric as ObservationMetric]?.label || item.metric }} · {{ item.value }} {{ metrics[item.metric as ObservationMetric]?.displayUnit || item.unit }}</strong><span>{{ time(item.measured_at) }} · {{ contextLabels[item.context] || item.context }}</span></div><div><span class="reading-source">{{ sourceLabels[item.source] || item.source }}</span><small v-if="item.device_name">{{ item.device_name }}</small></div></div><p class="health-caption">近 30 天共 {{ context.observations.total }} 条，此处展示最近 {{ recentReadings.length }} 条。</p></div></section>
  </div>
</template>

<style scoped>
.health-page { min-width: 0; overflow-wrap: anywhere; max-width:960px; margin:0 auto; }.health-page .health-panel{border-radius:20px}.health-page .health-layout{grid-template-columns:minmax(0,1fr)}
.health-section-nav { display: flex; gap: 28px; border-bottom: 1px solid var(--border-strong); margin-bottom: 24px; }
.health-section-nav button { padding: 12px 2px; font-size: 14px; border-bottom: 3px solid transparent; color: var(--muted); }
.health-section-nav button.active { color: var(--primary-deep); font-weight: 650; border-color: var(--primary); }
.health-layout { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: 22px; align-items: start; }
.health-layout.single-section { grid-template-columns: minmax(0, 1fr); }
.profile-panel, .region-panel { max-width: 960px; }
.saved-profile dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 32px; margin: 22px 0; }
.saved-profile dl > div { padding: 17px 0; border-bottom: 1px solid var(--border); font-size: 14px; line-height: 1.8; }
.saved-profile dt { color: var(--muted); font-size: 12px; margin-bottom: 6px; }.saved-profile dd { margin: 0; }
.cancel-profile { margin-left: 20px; }.health-panel-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }.health-panel-heading h2 { margin: 0; }
.source-status-label { font-size: 11px; color: var(--primary-deep); background: var(--primary-tint); padding: 4px 8px; border-radius: 5px; }
.manual-measurement summary { font-weight: 650; font-size: 16px; cursor: pointer; line-height: 1.8; }.manual-measurement[open] summary { margin-bottom: 18px; }
.health-panel { padding: 24px; min-width: 0; }
.health-panel h2 { font-size: 19px; margin: 0 0 12px; }
.health-panel h3 { font-size: 14px; margin: 20px 0 12px; }
.health-caption { color: var(--muted); line-height: 1.8; font-size: 12px; margin: 8px 0 16px; }
.health-panel fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.health-panel input, .health-panel select, .health-panel textarea { min-width: 0; width: 100%; }
.region-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.health-consent { display: flex; align-items: flex-start; gap: 10px; margin: 20px 0; font-size: 12px; line-height: 1.8; color: var(--ink-soft); }
.health-consent input { width: 16px; flex-shrink: 0; margin-top: 4px; }
.device-state { display: grid; gap: 8px; font-size: 13px; margin: 20px 0 12px; }
.device-state span { color: var(--muted); font-size: 12px; }
.device-controls { display: flex; align-items: end; flex-wrap: wrap; gap: 12px; margin: 20px 0; }
.device-controls .field { margin: 0; flex-basis: 140px; }
.device-preview { padding: 14px; border-radius: var(--radius-sm); background: var(--primary-tint); font-size: 13px; }
.device-note { padding-top: 16px; border-top: 1px solid var(--border); margin-top: 22px; }
.performance-panel { margin-top: 18px; }
.performance-panel summary { font-weight: 650; font-size: 14px; cursor: pointer; line-height: 1.8; }
.performance-panel[open] summary { margin-bottom: 12px; }
.performance-list { list-style: none; padding: 0; margin: 8px 0 0; display: grid; gap: 8px; }
.performance-list li { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; padding: 9px 0; border-bottom: 1px solid var(--border-faint); }
.performance-list small { color: var(--muted); font-size: 12px; }
.regional-signal { border-bottom: 1px solid var(--border); padding-bottom: 16px; font-size: 13px; line-height: 1.8; }
.regional-signal span { font-size: 12px; color: var(--primary); }
.readings-panel { margin-top: 22px; }
.baseline-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 20px 0; }
.baseline-card { display: flex; flex-direction: column; gap: 7px; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 13px; }
.baseline-card p { margin: 5px 0; }
.baseline-card span, .baseline-card small { color: var(--muted); font-size: 11px; line-height: 1.6; }
.reading-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; border-top: 1px solid var(--border); padding: 14px 0; font-size: 13px; }
.reading-item > div { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.reading-item > div:last-child { align-items: flex-end; text-align: right; }
.reading-item span, .reading-item small { color: var(--muted); font-size: 11px; }
.reading-source { padding: 3px 7px; background: var(--primary-tint); border-radius: 5px; }
.health-empty { padding: 32px 12px; text-align: center; color: var(--muted); font-size: 13px; }
@media (max-width: 1100px) { .health-layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 540px) { .health-panel { padding: 20px 16px; } .health-section-nav { gap: 0; justify-content: space-between; }.health-section-nav button { font-size: 13px; }.saved-profile dl, .region-fields { grid-template-columns: minmax(0, 1fr); } .reading-item { align-items: flex-start; flex-direction: column; } .reading-item > div:last-child { align-items: flex-start; text-align: left; } }
</style>
