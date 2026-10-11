package com.zhiji.healthdevice

import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.activity.result.ActivityResult
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.*
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import kotlinx.coroutines.*
import java.time.Instant
import java.time.temporal.ChronoUnit
import kotlin.reflect.KClass

@CapacitorPlugin(name = "ZhijiHealth")
class ZhijiHealthPlugin : Plugin() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val recordTypes = listOf(HeartRateRecord::class, RestingHeartRateRecord::class,
        OxygenSaturationRecord::class, BodyTemperatureRecord::class, StepsRecord::class, SleepSessionRecord::class,
        NutritionRecord::class, HydrationRecord::class, ActiveCaloriesBurnedRecord::class,
        BasalMetabolicRateRecord::class, HeartRateVariabilityRmssdRecord::class, Vo2MaxRecord::class,
        ExerciseSessionRecord::class, DistanceRecord::class)
    private val permissions = recordTypes.map { HealthPermission.getReadPermission(it) }.toSet()
    private val permissionContract = PermissionController.createRequestPermissionResultContract()
    private var reading = false
    private val pageLimit = 20
    private val rowLimit = 4000

    private fun available(): Boolean = Build.VERSION.SDK_INT >= 28 &&
        HealthConnectClient.getSdkStatus(context) == HealthConnectClient.SDK_AVAILABLE
    private fun client() = HealthConnectClient.getOrCreate(context)
    private fun status(state: String, permission: String, message: String) = JSObject().apply {
        put("state", state); put("source", "health_connect"); put("read_permission", permission); put("message", message)
    }
    private suspend fun currentStatus(): JSObject {
        if (!available()) return status("unavailable", "unknown", "需要 Android 9 或更新版本及可用的 Health Connect；Android 13 及以前通常需安装或更新 Health Connect。")
        val granted = client().permissionController.getGrantedPermissions()
        val count = permissions.count { it in granted }
        return if (count > 0) status("ready", if (count == permissions.size) "granted" else "unknown",
            "已允许读取 $count/${permissions.size} 项健康资料，仅同步实际获准的类型；手表资料需先同步到 Health Connect。")
        else status("permission", "not_requested", "请按需允许读取 Health Connect 中的健康资料。")
    }

    @PluginMethod fun getStatus(call: PluginCall) {
        scope.launch {
            try { call.resolve(currentStatus()) }
            catch (_: Exception) { call.resolve(status("unavailable", "unknown", "暂时无法访问 Health Connect，请检查系统服务。")) }
        }
    }
    @PluginMethod fun requestAccess(call: PluginCall) {
        if (!available()) { getStatus(call); return }
        Handler(Looper.getMainLooper()).post {
            val intent = permissionContract.createIntent(context, permissions)
            startActivityForResult(call, intent, "permissionResult")
        }
    }
    @ActivityCallback
    private fun permissionResult(call: PluginCall?, result: ActivityResult) {
        if (call == null) return
        scope.launch {
            try {
                val granted = permissionContract.parseResult(result.resultCode, result.data)
                if (granted.none { it in permissions }) call.resolve(status("permission", "denied", "尚未允许读取健康资料，可在 Health Connect 设置中授权。"))
                else call.resolve(currentStatus())
            } catch (_: Exception) { call.reject("健康授权申请未完成，请重试。", "PERMISSION") }
        }
    }

    @PluginMethod fun read(call: PluginCall) {
        val days = call.getInt("days")
        if (days != 7 && days != 30) { call.reject("仅支持最近 7 天或 30 天。", "INVALID_DAYS"); return }
        if (!available()) { call.reject("Health Connect 不可用。", "UNAVAILABLE"); return }
        synchronized(this) {
            if (reading) { call.reject("健康资料正在读取，请稍后重试。", "BUSY"); return }
            reading = true
        }
        scope.launch {
            try {
                val health = client()
                val granted = health.permissionController.getGrantedPermissions()
                val until = Instant.now()
                val since = until.minus(days.toLong(), ChronoUnit.DAYS)
                val output = JSArray()
                var truncated = false
                for (type in recordTypes) {
                    if (HealthPermission.getReadPermission(type) !in granted) continue
                    var token: String? = null
                    var pages = 0
                    var rows = 0
                    do {
                        val response = health.readRecords(ReadRecordsRequest(
                            recordType = type, timeRangeFilter = TimeRangeFilter.between(since, until),
                            ascendingOrder = false, pageSize = 200, pageToken = token))
                        for (record in response.records) {
                            if (record.metadata.recordingMethod == Metadata.RECORDING_METHOD_MANUAL_ENTRY) continue
                            for (item in mapRecord(record, since, until)) {
                                if (rows >= rowLimit) { truncated = true; break }
                                output.put(item); rows++
                            }
                        }
                        token = response.pageToken
                        pages++
                        if (token != null && (pages >= pageLimit || rows >= rowLimit)) { truncated = true; break }
                    } while (token != null)
                }
                call.resolve(JSObject().apply {
                    put("readings", output); put("truncated", truncated)
                    put("message", "已排除系统中明确标记为手动输入的记录。设备未提供或未同步的指标不补造；普通心率不视为静息心率。")
                })
            } catch (_: SecurityException) { call.reject("读取权限已变化，请重新检查健康授权。", "PERMISSION") }
            catch (_: Exception) { call.reject("健康资料读取失败，请检查系统服务并重试。", "READ_FAILED") }
            finally { synchronized(this@ZhijiHealthPlugin) { reading = false } }
        }
    }

    private fun mapRecord(record: Record, since: Instant, until: Instant): List<JSObject> {
        val metadata = record.metadata
        val device = metadata.device
        val name = listOfNotNull(device?.manufacturer, device?.model).filter { it.isNotBlank() }.joinToString(" ")
            .ifBlank { "Health Connect（设备型号未提供）" }
        fun item(kind: String, value: Double, unit: String, start: Instant, end: Instant = start, suffix: String = "") = JSObject().apply {
            put("id", metadata.id + suffix); put("kind", kind); put("value", value); put("unit", unit)
            put("startDate", start.toString()); put("endDate", end.toString())
            put("deviceName", name); put("origin", metadata.dataOrigin.packageName); put("manual", false)
        }
        return when (record) {
            is HeartRateRecord -> record.samples.filter { it.time >= since && it.time <= until }.map {
                item("heart_rate", it.beatsPerMinute.toDouble(), "bpm", it.time, suffix = ":${it.time}") }
            is RestingHeartRateRecord -> listOf(item("resting_heart_rate", record.beatsPerMinute.toDouble(), "bpm", record.time))
            is OxygenSaturationRecord -> listOf(item("oxygen_saturation", record.percentage.value, "percent", record.time))
            is BodyTemperatureRecord -> listOf(item("body_temperature", record.temperature.inCelsius, "celsius", record.time))
            is StepsRecord -> listOf(item("steps", record.count.toDouble(), "count", record.startTime, record.endTime))
            is SleepSessionRecord -> {
                val asleep = setOf(SleepSessionRecord.STAGE_TYPE_SLEEPING, SleepSessionRecord.STAGE_TYPE_LIGHT,
                    SleepSessionRecord.STAGE_TYPE_DEEP, SleepSessionRecord.STAGE_TYPE_REM)
                // A bare session is time in bed, not proven sleep. Import only
                // known asleep stages, never add a main session to its stages.
                record.stages.filter { it.stage in asleep }.mapNotNull {
                    val start = maxOf(it.startTime, since)
                    val end = minOf(it.endTime, until)
                    if (end <= start) null else item("sleep", (end.epochSecond - start.epochSecond) / 60.0,
                        "minutes", start, end, ":sleep:$start:$end")
                }
            }
            // Only platform-provided values are passed through; the plugin never derives them.
            is NutritionRecord -> record.energy?.let {
                listOf(item("dietary_energy", it.inKilocalories, "kilocalorie", record.startTime, record.endTime))
            } ?: emptyList()
            is HydrationRecord -> listOf(item("hydration", record.volume.inLiters, "liter", record.startTime, record.endTime))
            is ActiveCaloriesBurnedRecord -> listOf(item("active_energy", record.energy.inKilocalories, "kilocalorie", record.startTime, record.endTime))
            is BasalMetabolicRateRecord -> listOf(item("basal_energy", record.basalMetabolicRate.inKilocaloriesPerDay, "kilocalorie", record.time))
            // Health Connect exposes RMSSD only; there is no SDNN record type.
            is HeartRateVariabilityRmssdRecord -> listOf(item("hrv_rmssd", record.heartRateVariabilityMillis, "millisecond", record.time))
            is Vo2MaxRecord -> listOf(item("vo2max", record.vo2MillilitersPerMinuteKilogram, "ml/kg/min", record.time))
            // Duration only: Health Connect has no per-activity distance on the session,
            // so the plugin never guesses run/cycle distance from Android data.
            is ExerciseSessionRecord -> listOf(item("exercise_minutes",
                (record.endTime.epochSecond - record.startTime.epochSecond) / 60.0, "minute",
                record.startTime, record.endTime))
            // Distance is keyed by the platform's own exercise type; only running and
            // cycling are attributed, other activity types are not guessed into either.
            is DistanceRecord -> when (record.exerciseType) {
                ExerciseSessionRecord.EXERCISE_TYPE_RUNNING, ExerciseSessionRecord.EXERCISE_TYPE_RUNNING_TREADMILL ->
                    listOf(item("distance_run", record.distance.inMeters, "meter", record.startTime, record.endTime))
                ExerciseSessionRecord.EXERCISE_TYPE_BIKING, ExerciseSessionRecord.EXERCISE_TYPE_BIKING_STATIONARY ->
                    listOf(item("distance_cycle", record.distance.inMeters, "meter", record.startTime, record.endTime))
                else -> emptyList()
            }
            else -> emptyList()
        }
    }
    override fun handleOnDestroy() { scope.cancel(); super.handleOnDestroy() }
}
