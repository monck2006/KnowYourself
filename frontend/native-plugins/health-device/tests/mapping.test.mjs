import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeNativeReadings, unionSleepMinutes, parseBluetoothHeartRate } from '../../../src/lib/healthDevice.ts'

const base = { id: 'native-uuid', kind: 'heart_rate', value: 75, unit: 'bpm', startDate: '2026-10-10T10:00:00+08:00', deviceName: 'Actual watch', origin: 'actual.vendor', manual: false }

test('ordinary HR remains unknown; only explicit resting HR becomes resting', () => {
  const items = normalizeNativeReadings([base, { ...base, id: 'resting', kind: 'resting_heart_rate' }], 'healthkit')
  assert.equal(items.find(x => x.source_id === 'native-uuid').context, 'unknown')
  assert.equal(items.find(x => x.source_id === 'resting').context, 'resting')
  assert.equal(items[0].measured_at, '2026-10-10T02:00:00.000Z')
})

test('Apple oxygen fraction and Fahrenheit map to percent and Celsius', () => {
  const items = normalizeNativeReadings([
    { ...base, id: 'oxygen', kind: 'oxygen_saturation', unit: 'fraction', value: 0.97 },
    { ...base, id: 'temperature', kind: 'body_temperature', unit: 'fahrenheit', value: 98.6 },
  ], 'healthkit')
  assert.equal(items.find(x => x.metric === 'spo2').value, 97)
  assert.equal(items.find(x => x.metric === 'temperature').value, 37)
  assert.equal(items.find(x => x.metric === 'temperature').unit, 'C')
})

test('Android oxygen is already percent and body temperature Celsius', () => {
  const items = normalizeNativeReadings([
    { ...base, id: 'oxygen', kind: 'oxygen_saturation', unit: 'percent', value: 96 },
    { ...base, id: 'temperature', kind: 'body_temperature', unit: 'celsius', value: 36.5 },
  ], 'health_connect')
  assert.deepEqual(items.map(x => x.value).sort(), [36.5, 96])
})

test('manual records, duplicate UUIDs, unsupported units and timezone-less timestamps are excluded', () => {
  const items = normalizeNativeReadings([
    base, base, { ...base, id: 'manual', manual: true },
    { ...base, id: 'unit', unit: 'beats' }, { ...base, id: 'timezone', startDate: '2026-10-10T10:00:00' },
  ], 'healthkit')
  assert.equal(items.length, 1)
  assert.equal(items[0].source_id, 'native-uuid')
})

test('sleep overlap union avoids double counting main and staged intervals', () => {
  assert.equal(unionSleepMinutes([{ start: 0, end: 120_000 }, { start: 60_000, end: 180_000 }]), 3)
  const items = normalizeNativeReadings([
    { ...base, id: 'sleep-main', kind: 'sleep', unit: 'minutes', startDate: '2026-10-10T01:00:00Z', endDate: '2026-10-10T03:00:00Z' },
    { ...base, id: 'sleep-stage', kind: 'sleep', unit: 'minutes', startDate: '2026-10-10T01:30:00Z', endDate: '2026-10-10T02:30:00Z' },
  ], 'healthkit')
  assert.equal(items.length, 1)
  assert.equal(items[0].value, 120)
  assert.equal(items[0].source_id, 'sleep-utc-day-2026-10-10:120:2026-10-10T03:00:00.000Z')
  assert.equal(items[0].measured_at, '2026-10-10T03:00:00.000Z')
})

test('sleep crossing UTC midnight is split into stable dated totals', () => {
  const items = normalizeNativeReadings([{ ...base, id: 'sleep', kind: 'sleep', unit: 'minutes',
    startDate: '2026-10-10T23:30:00Z', endDate: '2026-10-11T00:45:00Z' }], 'health_connect')
  assert.deepEqual(items.map(x => x.value).sort(), [30, 45])
})

test('phone and watch steps are not added together even with one vendor origin', () => {
  const items = normalizeNativeReadings([
    { ...base, id: 'phone', kind: 'steps', unit: 'count', value: 1000, deviceName: 'Phone' },
    { ...base, id: 'watch', kind: 'steps', unit: 'count', value: 1200, deviceName: 'Watch' },
  ], 'health_connect')
  assert.equal(items.length, 1)
  assert.equal(items[0].value, 1200)
  assert.equal(items[0].device_name, 'Watch')
})

test('Bluetooth flags support 8-bit and little-endian 16-bit heart rate', () => {
  assert.equal(parseBluetoothHeartRate(new DataView(Uint8Array.from([0, 75]).buffer)), 75)
  assert.equal(parseBluetoothHeartRate(new DataView(Uint8Array.from([1, 240, 0]).buffer)), 240)
  assert.throws(() => parseBluetoothHeartRate(new DataView(Uint8Array.from([1, 4, 1]).buffer)))
  assert.throws(() => parseBluetoothHeartRate(new DataView(Uint8Array.from([1, 75]).buffer)))
  assert.throws(() => parseBluetoothHeartRate(new DataView(Uint8Array.from([4, 75]).buffer)))
  assert.throws(() => parseBluetoothHeartRate(new DataView(Uint8Array.from([0, 0]).buffer)))
})

test('device strings match backend input length bounds', () => {
  const item = normalizeNativeReadings([{ ...base, id: 'i'.repeat(170), deviceName: 'n'.repeat(120) }], 'healthkit')[0]
  assert.equal(item.source_id.length, 160)
  assert.equal(item.device_name.length, 100)
})

test('daily aggregate revisions use real record end and change only when data changes', () => {
  const reading = { ...base, id: 'step', kind: 'steps', unit: 'count', value: 10, endDate: '2026-10-10T11:00:00+08:00' }
  const first = normalizeNativeReadings([reading], 'health_connect')[0]
  assert.deepEqual(normalizeNativeReadings([reading], 'health_connect')[0], first)
  assert.equal(first.measured_at, '2026-10-10T03:00:00.000Z')
  assert.notEqual(normalizeNativeReadings([{ ...reading, value: 20 }], 'health_connect')[0].source_id, first.source_id)
})

test('out-of-contract outliers cannot reject a whole otherwise valid import', () => {
  assert.equal(normalizeNativeReadings([base,
    { ...base, id: 'hr', value: 260 },
    { ...base, id: 'spo2', kind: 'oxygen_saturation', unit: 'percent', value: 40 },
    { ...base, id: 'temperature', kind: 'body_temperature', unit: 'celsius', value: 20 },
    { ...base, id: 'steps', kind: 'steps', unit: 'count', value: 200001 },
  ], 'healthkit').length, 1)
})

test('dense ordinary HR cannot displace older resting HR and sparse metrics', () => {
  const dense = Array.from({ length: 5000 }, (_, index) => ({ ...base, id: `hr-${index}` }))
  const items = normalizeNativeReadings([...dense,
    { ...base, id: 'rest', kind: 'resting_heart_rate', startDate: '2026-09-20T00:00:00Z' },
    { ...base, id: 'oxygen-old', kind: 'oxygen_saturation', unit: 'fraction', value: 0.98, startDate: '2026-09-20T00:00:00Z' },
    { ...base, id: 'temperature-old', kind: 'body_temperature', unit: 'celsius', value: 36.5, startDate: '2026-09-20T00:00:00Z' },
  ], 'healthkit').slice(0, 5000)
  assert.ok(items.some(x => x.source_id === 'rest'))
  assert.ok(items.some(x => x.source_id === 'oxygen-old'))
  assert.ok(items.some(x => x.source_id === 'temperature-old'))
})

test('new platform metrics map with cross-platform unit conversion', () => {
  const items = normalizeNativeReadings([
    { ...base, id: 'diet', kind: 'dietary_energy', unit: 'kilocalorie', value: 520 },
    { ...base, id: 'water', kind: 'hydration', unit: 'liter', value: 1.5 },
    { ...base, id: 'active', kind: 'active_energy', unit: 'kilocalorie', value: 300 },
    { ...base, id: 'basal', kind: 'basal_energy', unit: 'kilocalorie', value: 1500 },
    { ...base, id: 'sdnn', kind: 'hrv_sdnn', unit: 'millisecond', value: 42 },
    { ...base, id: 'rmssd', kind: 'hrv_rmssd', unit: 'millisecond', value: 38 },
    { ...base, id: 'vo2', kind: 'vo2max', unit: 'ml/kg/min', value: 47.5 },
  ], 'healthkit')
  const byId = id => items.find(x => x.source_id === id)
  assert.equal(byId('water').value, 1500)
  assert.equal(byId('water').unit, 'ml')
  assert.equal(byId('vo2').unit, 'mL/kg/min')
  // SDNN and RMSSD stay distinct metrics; they must never be merged.
  assert.equal(byId('sdnn').metric, 'hrv_sdnn')
  assert.equal(byId('rmssd').metric, 'hrv_rmssd')
  assert.equal(items.filter(x => ['dietary_energy', 'hydration', 'active_energy', 'basal_energy', 'hrv_sdnn', 'hrv_rmssd', 'vo2max'].includes(x.metric)).length, 7)
})

test('new metrics outside contract ranges are dropped, not clamped', () => {
  const items = normalizeNativeReadings([
    { ...base, id: 'bad-diet', kind: 'dietary_energy', unit: 'kilocalorie', value: 99999 },
    { ...base, id: 'bad-hrv', kind: 'hrv_sdnn', unit: 'millisecond', value: 900 },
    { ...base, id: 'bad-vo2', kind: 'vo2max', unit: 'ml/kg/min', value: 2 },
    { ...base, id: 'ok-water', kind: 'hydration', unit: 'liter', value: 0.25 },
  ], 'health_connect')
  assert.deepEqual(items.map(x => x.source_id), ['ok-water'])
})

test('exercise distance and duration carry no invented values', () => {
  const items = normalizeNativeReadings([
    { ...base, id: 'run', kind: 'distance_run', unit: 'meter', value: 5120.4, endDate: '2026-10-10T10:30:00+08:00' },
    { ...base, id: 'cycle', kind: 'distance_cycle', unit: 'meter', value: 20300 },
    { ...base, id: 'session', kind: 'exercise_minutes', unit: 'minute', startDate: '2026-10-10T10:00:00+08:00', endDate: '2026-10-10T10:30:00Z' },
    { ...base, id: 'bad-run', kind: 'distance_run', unit: 'meter', value: 400000 },
  ], 'healthkit')
  const byId = id => items.find(x => x.source_id === id)
  assert.equal(byId('run').value, 5120)          // distance is a whole number of metres
  assert.equal(byId('cycle').metric, 'distance_cycle')
  assert.equal(byId('bad-run'), undefined)       // over the 200 km run ceiling
  // Duration comes from the real interval, not a stored value.
  assert.equal(byId('session').metric, 'exercise_minutes')
  assert.ok(Math.abs(byId('session').value - 510) < 0.01)
})
