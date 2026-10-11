import { Capacitor } from '@capacitor/core'
import { ZhijiHealth } from '@zhiji/health-device'

export type HealthDeviceSource = 'health_connect' | 'healthkit' | 'bluetooth'
export type HealthDeviceMetric = 'heart_rate' | 'spo2' | 'temperature' | 'steps' | 'sleep_minutes'
  | 'dietary_energy' | 'hydration' | 'active_energy' | 'basal_energy' | 'hrv_sdnn' | 'hrv_rmssd' | 'vo2max'
  | 'distance_run' | 'distance_cycle' | 'exercise_minutes'
export type HealthDeviceUnit = 'bpm' | '%' | 'C' | 'count' | 'min' | 'kcal' | 'ml' | 'ms' | 'mL/kg/min' | 'm'
export interface HealthDeviceItem {
  source: HealthDeviceSource
  source_id: string
  metric: HealthDeviceMetric
  value: number
  unit: HealthDeviceUnit
  measured_at: string
  context: 'resting' | 'active' | 'unknown'
  device_name: string
}
export interface HealthDeviceStatus {
  state: 'unavailable' | 'permission' | 'ready'
  source: HealthDeviceSource | null
  read_permission: 'granted' | 'unknown' | 'not_requested' | 'denied'
  message: string
}
export interface HealthDeviceResult extends HealthDeviceStatus {
  items: HealthDeviceItem[]
  truncated: boolean
}
interface NativeReading {
  id: string
  kind: string
  value: number
  unit: string
  startDate: string
  endDate?: string
  deviceName?: string
  origin?: string
  manual?: boolean
}
type Interval = { start: number; end: number }
const MAX_ITEMS = 5000
const DAY = 86_400_000

function isNativeReading(value: unknown): value is NativeReading {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  return typeof v.id === 'string' && !!v.id && typeof v.kind === 'string'
    && typeof v.value === 'number' && Number.isFinite(v.value) && typeof v.unit === 'string'
    && typeof v.startDate === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(v.startDate)
    && Number.isFinite(Date.parse(v.startDate))
}

/** Union intervals, rather than adding main sleep sessions to overlapping stages. */
export function unionSleepMinutes(intervals: Interval[]): number {
  const sorted = intervals.filter(x => x.end > x.start).sort((a, b) => a.start - b.start)
  let total = 0, end = -Infinity
  for (const item of sorted) {
    total += Math.max(0, item.end - Math.max(end, item.start))
    end = Math.max(end, item.end)
  }
  return Math.round(total / 60_000 * 100) / 100
}

/** Native UUIDs and series timestamps are retained. Health-platform manual entries are excluded. */
export function normalizeNativeReadings(raw: unknown[], source: 'health_connect' | 'healthkit'): HealthDeviceItem[] {
  const items: HealthDeviceItem[] = []
  const seen = new Set<string>()
  const sleep = new Map<string, Interval[]>()
  const steps = new Map<string, Map<string, { total: number; name: string; last: number }>>()
  for (const reading of raw) {
    if (!isNativeReading(reading) || reading.manual === true) continue
    if (seen.has(reading.id)) continue
    seen.add(reading.id)
    const measured_at = new Date(reading.startDate).toISOString()
    const device_name = reading.deviceName?.slice(0, 100) || '系统健康资料（设备型号未提供）'
    const base = { source, source_id: reading.id.slice(0, 160), measured_at, device_name, context: 'unknown' as const }
    if (reading.kind === 'sleep') {
      const end = Date.parse(reading.endDate || '')
      let start = Date.parse(measured_at)
      if (!Number.isFinite(end) || end <= start || end - start > 2 * DAY) continue
      while (start < end) {
        const dayEnd = (Math.floor(start / DAY) + 1) * DAY
        const key = new Date(start).toISOString().slice(0, 10)
        const intervals = sleep.get(key) || []
        intervals.push({ start, end: Math.min(end, dayEnd) })
        sleep.set(key, intervals)
        start = dayEnd
      }
    } else if (reading.kind === 'steps' && reading.unit === 'count' && Number.isInteger(reading.value) && reading.value >= 0 && reading.value <= 200_000) {
      // Android raw records can overlap phone/watch sources. Choose one source
      // per UTC day; never invent proportional counts or sum duplicate devices.
      const day = measured_at.slice(0, 10)
      const origins = steps.get(day) || new Map<string, { total: number; name: string; last: number }>()
      const origin = `${reading.origin || ''}:${device_name}`
      const current = origins.get(origin) || { total: 0, name: device_name, last: Date.parse(measured_at) }
      current.total += reading.value
      const end = Date.parse(reading.endDate || measured_at)
      current.last = Math.max(current.last, Number.isFinite(end) ? end : Date.parse(measured_at))
      origins.set(origin, current)
      steps.set(day, origins)
    } else if (reading.kind === 'heart_rate' || reading.kind === 'resting_heart_rate') {
      if (reading.unit === 'bpm' && reading.value >= 20 && reading.value <= 250)
        items.push({ ...base, metric: 'heart_rate', unit: 'bpm', value: reading.value,
          context: reading.kind === 'resting_heart_rate' ? 'resting' : 'unknown' })
    } else if (reading.kind === 'oxygen_saturation') {
      const value = reading.unit === 'fraction' ? reading.value * 100 : reading.unit === 'percent' ? reading.value : NaN
      if (value >= 50 && value <= 100) items.push({ ...base, metric: 'spo2', unit: '%', value: Math.round(value * 100) / 100 })
    } else if (reading.kind === 'body_temperature') {
      const value = reading.unit === 'celsius' ? reading.value : reading.unit === 'fahrenheit' ? (reading.value - 32) * 5 / 9 : NaN
      if (value >= 30 && value <= 45) items.push({ ...base, metric: 'temperature', unit: 'C', value: Math.round(value * 100) / 100 })
    } else if (reading.kind === 'dietary_energy' && reading.unit === 'kilocalorie') {
      if (reading.value >= 0 && reading.value <= 10000) items.push({ ...base, metric: 'dietary_energy', unit: 'kcal', value: Math.round(reading.value * 100) / 100 })
    } else if (reading.kind === 'hydration' && reading.unit === 'liter') {
      const value = reading.value * 1000
      if (value >= 0 && value <= 20000) items.push({ ...base, metric: 'hydration', unit: 'ml', value: Math.round(value * 100) / 100 })
    } else if (reading.kind === 'active_energy' && reading.unit === 'kilocalorie') {
      if (reading.value >= 0 && reading.value <= 20000) items.push({ ...base, metric: 'active_energy', unit: 'kcal', value: Math.round(reading.value * 100) / 100 })
    } else if (reading.kind === 'basal_energy' && reading.unit === 'kilocalorie') {
      if (reading.value >= 0 && reading.value <= 20000) items.push({ ...base, metric: 'basal_energy', unit: 'kcal', value: Math.round(reading.value * 100) / 100 })
    } else if (reading.kind === 'hrv_sdnn' && reading.unit === 'millisecond') {
      if (reading.value >= 1 && reading.value <= 500) items.push({ ...base, metric: 'hrv_sdnn', unit: 'ms', value: Math.round(reading.value * 100) / 100 })
    } else if (reading.kind === 'hrv_rmssd' && reading.unit === 'millisecond') {
      if (reading.value >= 1 && reading.value <= 500) items.push({ ...base, metric: 'hrv_rmssd', unit: 'ms', value: Math.round(reading.value * 100) / 100 })
    } else if (reading.kind === 'vo2max' && reading.unit === 'ml/kg/min') {
      if (reading.value >= 5 && reading.value <= 100) items.push({ ...base, metric: 'vo2max', unit: 'mL/kg/min', value: Math.round(reading.value * 100) / 100 })
    } else if (reading.kind === 'distance_run' && reading.unit === 'meter') {
      if (reading.value >= 0 && reading.value <= 200000) items.push({ ...base, metric: 'distance_run', unit: 'm', value: Math.round(reading.value) })
    } else if (reading.kind === 'distance_cycle' && reading.unit === 'meter') {
      if (reading.value >= 0 && reading.value <= 500000) items.push({ ...base, metric: 'distance_cycle', unit: 'm', value: Math.round(reading.value) })
    } else if (reading.kind === 'exercise_minutes' && reading.unit === 'minute') {
      const value = reading.endDate ? (Date.parse(reading.endDate) - Date.parse(measured_at)) / 60000 : NaN
      if (Number.isFinite(value) && value > 0 && value <= 1440) items.push({ ...base, metric: 'exercise_minutes', unit: 'min', value: Math.round(value * 100) / 100 })
    }
  }
  for (const [day, intervals] of sleep) {
    const value = unionSleepMinutes(intervals)
    const measured_at = new Date(Math.max(...intervals.map(x => x.end))).toISOString()
    items.push({ source, source_id: `sleep-utc-day-${day}:${value}:${measured_at}`, metric: 'sleep_minutes', value,
      unit: 'min', measured_at, context: 'unknown', device_name: '系统睡眠资料（重叠时间已合并）' })
  }
  for (const [day, origins] of steps) {
    const selected = [...origins.entries()].sort((a, b) => b[1].total - a[1].total || a[0].localeCompare(b[0]))[0]
    if (selected && selected[1].total <= 200_000) {
      const value = Math.round(selected[1].total)
      const measured_at = new Date(selected[1].last).toISOString()
      let tag = 2166136261
      for (const char of selected[0]) tag = Math.imul(tag ^ char.charCodeAt(0), 16777619)
      items.push({ source, source_id: `steps-utc-day-${day}:${value}:${measured_at}:${(tag >>> 0).toString(16)}`,
        metric: 'steps', value, unit: 'count', measured_at, context: 'unknown', device_name: selected[1].name })
    }
  }
  // Preserve summaries, resting HR and sparse metrics before dense HR series.
  const priority = (item: HealthDeviceItem) => ['steps', 'sleep_minutes', 'distance_run', 'distance_cycle', 'exercise_minutes'].includes(item.metric) ? 2
    : item.metric !== 'heart_rate' || item.context === 'resting' ? 1 : 0
  return items.sort((a, b) => priority(b) - priority(a)
    || b.measured_at.localeCompare(a.measured_at) || a.source_id.localeCompare(b.source_id))
}

function bluetoothAvailable(): boolean {
  return typeof navigator !== 'undefined' && 'bluetooth' in navigator && globalThis.isSecureContext === true
}

export async function getHealthDeviceStatus(): Promise<HealthDeviceStatus> {
  if (Capacitor.isNativePlatform()) {
    if (!Capacitor.isPluginAvailable('ZhijiHealth')) return { state: 'unavailable', source: null, read_permission: 'unknown', message: '当前安装包未包含健康读取插件，请安装更新后的原生应用。' }
    return ZhijiHealth.getStatus()
  }
  return bluetoothAvailable()
    ? { state: 'permission', source: 'bluetooth', read_permission: 'not_requested', message: '此浏览器可连接支持标准蓝牙心率服务的设备；7/30天历史同步请使用 Android 或 iOS 原生应用。' }
    : { state: 'unavailable', source: null, read_permission: 'unknown', message: '网页无法直接读取 Health Connect 或 Apple 健康；请使用原生应用。标准蓝牙心率仅在支持 Web Bluetooth 的安全浏览器中可用。' }
}

export async function requestHealthDevicePermissions(): Promise<HealthDeviceStatus> {
  if (Capacitor.isNativePlatform()) return ZhijiHealth.requestAccess()
  return getHealthDeviceStatus()
}

export async function readHealthDeviceData(days: 7 | 30): Promise<HealthDeviceResult> {
  if (days !== 7 && days !== 30) throw new Error('仅支持最近 7 天或 30 天。')
  const status = await getHealthDeviceStatus()
  if (!Capacitor.isNativePlatform() || status.state !== 'ready') return { ...status, items: [], truncated: false }
  const raw = await ZhijiHealth.read({ days })
  const source = status.source as 'health_connect' | 'healthkit'
  const items = normalizeNativeReadings(raw.readings, source)
  const truncated = raw.truncated || items.length > MAX_ITEMS
  const message = [status.message, raw.message,
    items.length ? '读取到的资料需由你确认导入；不支持或未产生的指标不会补造。' : '未读取到资料：可能没有记录、尚未同步或未允许相应读取权限；这不能用于判断健康状况。',
    truncated ? '记录较多，本次仅返回有限的最近记录。' : '',
    '睡眠按 UTC 日期合并重叠时间；步数按 UTC 日期选择单一来源，避免手机与手表重复叠加。超出档案允许范围的异常读数会被跳过。日总量更新会形成新的修订记录，应查看当日最新值，不能把多个修订相加。'].filter(Boolean).join(' ')
  return { ...status, source, items: items.slice(0, MAX_ITEMS), truncated, message }
}

/** Bluetooth SIG Heart Rate Measurement: flags bit 0 selects 8/16-bit bpm. */
export function parseBluetoothHeartRate(value: DataView): number {
  if (value.byteLength < 2) throw new Error('蓝牙心率数据长度不足。')
  if ((value.getUint8(0) & 6) === 4) throw new Error('设备未检测到有效皮肤接触。')
  const wide = (value.getUint8(0) & 1) !== 0
  if (wide && value.byteLength < 3) throw new Error('蓝牙心率数据长度不足。')
  const bpm = wide ? value.getUint16(1, true) : value.getUint8(1)
  if (bpm < 20 || bpm > 250) throw new Error('蓝牙设备返回了超出档案记录范围的心率。')
  return bpm
}

interface BluetoothCharacteristic extends EventTarget { value?: DataView; startNotifications(): Promise<unknown>; stopNotifications(): Promise<unknown> }
interface BluetoothDevice extends EventTarget { id: string; name?: string; gatt?: { connected: boolean; connect(): Promise<{ getPrimaryService(name: string): Promise<{ getCharacteristic(name: string): Promise<BluetoothCharacteristic> }> }>; disconnect(): void } }
interface BluetoothApi { requestDevice(options: { filters: { services: string[] }[] }): Promise<BluetoothDevice> }

export async function connectBluetoothHeartRate(onItem: (item: HealthDeviceItem) => void): Promise<{ deviceName: string; disconnect: () => void; isConnected: () => boolean }> {
  if (!bluetoothAvailable()) throw new Error('当前浏览器不支持安全的 Web Bluetooth 连接。')
  const bluetooth = (navigator as unknown as { bluetooth: BluetoothApi }).bluetooth
  const device = await bluetooth.requestDevice({ filters: [{ services: ['heart_rate'] }] })
  if (!device.gatt) throw new Error('该设备没有可用的蓝牙 GATT 服务。')
  let characteristic: BluetoothCharacteristic | undefined
  let stopped = false
  let sequence = 0
  const session = globalThis.crypto.randomUUID()
  const onValue = () => {
    if (stopped || !characteristic?.value) return
    try {
      const value = parseBluetoothHeartRate(characteristic.value)
      const measured_at = new Date().toISOString()
      onItem({ source: 'bluetooth', source_id: `${device.id.slice(0, 80)}:${session}:${sequence++}`, metric: 'heart_rate', value,
        unit: 'bpm', measured_at, context: 'unknown', device_name: device.name?.slice(0, 100) || '标准蓝牙心率设备' })
    } catch { /* Drop malformed sensor packets; never invent readings. */ }
  }
  const disconnect = () => {
    if (stopped) return
    stopped = true
    characteristic?.removeEventListener('characteristicvaluechanged', onValue)
    void characteristic?.stopNotifications().catch(() => undefined)
    device.removeEventListener('gattserverdisconnected', disconnect)
    device.gatt?.disconnect()
  }
  try {
    const server = await device.gatt.connect()
    characteristic = await (await server.getPrimaryService('heart_rate')).getCharacteristic('heart_rate_measurement')
    characteristic.addEventListener('characteristicvaluechanged', onValue)
    device.addEventListener('gattserverdisconnected', disconnect)
    await characteristic.startNotifications()
    return { deviceName: device.name?.slice(0, 100) || '标准蓝牙心率设备', disconnect,
      isConnected: () => !stopped && device.gatt?.connected === true }
  } catch (error) { disconnect(); throw error }
}
