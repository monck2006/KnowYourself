import type { ObservationMetric } from './types'
export const metrics: Record<ObservationMetric, { label: string; unit: string; displayUnit: string; min: number; max: number; step: string }> = {
  heart_rate: { label: '心率', unit: 'bpm', displayUnit: '次/分', min: 20, max: 250, step: '1' },
  spo2: { label: '血氧', unit: '%', displayUnit: '%', min: 50, max: 100, step: '.1' },
  temperature: { label: '体温', unit: 'C', displayUnit: '°C', min: 30, max: 45, step: '.1' },
  steps: { label: '步数', unit: 'count', displayUnit: '步', min: 0, max: 200000, step: '1' },
  sleep_minutes: { label: '睡眠时长', unit: 'min', displayUnit: '分钟', min: 0, max: 1440, step: '1' },
  dietary_energy: { label: '饮食摄入', unit: 'kcal', displayUnit: '千卡', min: 0, max: 10000, step: '1' },
  hydration: { label: '饮水', unit: 'ml', displayUnit: '毫升', min: 0, max: 20000, step: '1' },
  active_energy: { label: '活动消耗', unit: 'kcal', displayUnit: '千卡', min: 0, max: 20000, step: '1' },
  basal_energy: { label: '静息消耗', unit: 'kcal', displayUnit: '千卡', min: 0, max: 20000, step: '1' },
  hrv_sdnn: { label: '心率变异性 SDNN', unit: 'ms', displayUnit: '毫秒', min: 1, max: 500, step: '.1' },
  hrv_rmssd: { label: '心率变异性 RMSSD', unit: 'ms', displayUnit: '毫秒', min: 1, max: 500, step: '.1' },
  vo2max: { label: '最大摄氧量', unit: 'mL/kg/min', displayUnit: 'mL/kg/min', min: 5, max: 100, step: '.1' },
  distance_run: { label: '跑步距离', unit: 'm', displayUnit: '米', min: 0, max: 200000, step: '1' },
  distance_cycle: { label: '骑行距离', unit: 'm', displayUnit: '米', min: 0, max: 500000, step: '1' },
  exercise_minutes: { label: '运动时长', unit: 'min', displayUnit: '分钟', min: 0, max: 1440, step: '1' },
}
export const sourceLabels: Record<string, string> = { manual: '手动录入', health_connect: 'Android Health Connect', healthkit: 'Apple 健康', bluetooth: '蓝牙心率设备' }
export const contextLabels: Record<string, string> = { resting: '静息', active: '活动中', unknown: '状态未知' }
/** Vendor-derived "运动表现". Health platforms do not store these, so the app never computes them. */
export const vendorDerivedMetrics = ['跑步能力', '运动状态', '肌肉能力', '本周热量缺口', '户外跑步最快', '运动周报', '运动趋势']
export function coarseGrid(latitude: number, longitude: number) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) throw new Error('定位结果无效，请手动选择地区。')
  return `grid:${Math.floor(latitude * 10)}:${Math.floor(longitude * 10)}`
}
