import Foundation
import Capacitor
import HealthKit

@objc(ZhijiHealthPlugin)
public class ZhijiHealthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ZhijiHealthPlugin"
    public let jsName = "ZhijiHealth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestAccess", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "read", returnType: CAPPluginReturnPromise)
    ]
    private let store = HKHealthStore()
    private let sampleLimit = 4000
    private var reading = false

    private var quantities: [(HKQuantityTypeIdentifier, String, HKUnit, String)] {
        [(.heartRate, "heart_rate", HKUnit.count().unitDivided(by: HKUnit.minute()), "bpm"),
         (.restingHeartRate, "resting_heart_rate", HKUnit.count().unitDivided(by: HKUnit.minute()), "bpm"),
         (.oxygenSaturation, "oxygen_saturation", HKUnit.percent(), "fraction"),
         (.bodyTemperature, "body_temperature", HKUnit.degreeCelsius(), "celsius"),
         (.stepCount, "steps", HKUnit.count(), "count"),
         (.dietaryEnergyConsumed, "dietary_energy", HKUnit.kilocalorie(), "kilocalorie"),
         (.dietaryWater, "hydration", HKUnit.liter(), "liter"),
         (.activeEnergyBurned, "active_energy", HKUnit.kilocalorie(), "kilocalorie"),
         (.basalEnergyBurned, "basal_energy", HKUnit.kilocalorie(), "kilocalorie"),
         // HealthKit reports SDNN; the RMSSD form is a separate identifier used by Health Connect.
         (.heartRateVariabilitySDNN, "hrv_sdnn", HKUnit.secondUnit(with: .milli), "millisecond"),
         (.vo2Max, "vo2max", HKUnit.literUnit(with: .milli).unitDivided(by: HKUnit.gramUnit(with: .kilo).unitMultiplied(by: HKUnit.minute())), "ml/kg/min")]
    }
    private var readTypes: Set<HKObjectType> {
        var types = Set<HKObjectType>(quantities.compactMap { HKObjectType.quantityType(forIdentifier: $0.0) })
        if let sleep = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) { types.insert(sleep) }
        types.insert(HKObjectType.workoutType())
        return types
    }
    private var available: Bool {
        HKHealthStore.isHealthDataAvailable()
            && !(Bundle.main.object(forInfoDictionaryKey: "NSHealthShareUsageDescription") as? String ?? "").isEmpty
    }
    private func status(_ state: String, _ permission: String, _ message: String) -> JSObject {
        ["state": state, "source": "healthkit", "read_permission": permission, "message": message]
    }

    @objc public func getStatus(_ call: CAPPluginCall) {
        guard available else {
            call.resolve(status("unavailable", "unknown", "此设备不支持 HealthKit 或安装包未配置健康读取用途。"))
            return
        }
        store.getRequestStatusForAuthorization(toShare: [], read: readTypes) { requestStatus, error in
            if error != nil {
                call.resolve(self.status("permission", "unknown", "暂时无法确认授权申请状态，请解锁设备后重试。"))
            } else if requestStatus == .shouldRequest || requestStatus == .unknown {
                call.resolve(self.status("permission", "not_requested", "请按需允许读取 Apple 健康中已同步的手机和 Apple Watch 资料。"))
            } else {
                call.resolve(self.status("ready", "unknown", "已完成 HealthKit 授权申请；系统为保护隐私，不向应用披露各项读权限是否被拒绝。"))
            }
        }
    }

    @objc public func requestAccess(_ call: CAPPluginCall) {
        guard available else { getStatus(call); return }
        DispatchQueue.main.async {
            self.store.requestAuthorization(toShare: [], read: self.readTypes) { completed, error in
                if error != nil || !completed {
                    call.resolve(self.status("permission", "unknown", "健康授权申请未完成，请在 Apple 健康或系统设置中检查读取权限。"))
                } else {
                    // The callback means the authorization flow finished. It
                    // does NOT prove that any read permission was granted.
                    call.resolve(self.status("ready", "unknown", "已完成授权申请，读权限仍不可由应用判定；可尝试读取实际资料。"))
                }
            }
        }
    }

    @objc public func read(_ call: CAPPluginCall) {
        guard available else { call.reject("此设备无法读取 HealthKit。", "UNAVAILABLE"); return }
        guard let days = call.getInt("days"), days == 7 || days == 30 else {
            call.reject("仅支持最近 7 天或 30 天。", "INVALID_DAYS"); return
        }
        DispatchQueue.main.async {
            guard !self.reading else { call.reject("健康资料正在读取，请稍后重试。", "BUSY"); return }
            self.reading = true
            self.readSamples(call, days: days)
        }
    }

    private func readSamples(_ call: CAPPluginCall, days: Int) {
        let until = Date()
        let since = until.addingTimeInterval(-Double(days) * 86400)
        let datePredicate = HKQuery.predicateForSamples(withStart: since, end: until, options: [])
        let manuallyEntered = HKQuery.predicateForObjects(withMetadataKey: HKMetadataKeyWasUserEntered, operatorType: .equalTo, value: true)
        let predicate = NSCompoundPredicate(andPredicateWithSubpredicates: [datePredicate, NSCompoundPredicate(notPredicateWithSubpredicate: manuallyEntered)])
        let group = DispatchGroup()
        let lock = NSLock()
        var readings: [JSObject] = []
        var truncated = false
        var failed = false
        let specs: [(HKSampleType, String, HKUnit?, String)] = quantities.compactMap { spec in
            guard let type = HKObjectType.quantityType(forIdentifier: spec.0) else { return nil }
            return (type, spec.1, spec.2, spec.3)
        } + [(HKObjectType.categoryType(forIdentifier: .sleepAnalysis)!, "sleep", nil, "minutes")]

        for (type, kind, unit, unitName) in specs {
            group.enter()
            let query = HKSampleQuery(sampleType: type, predicate: predicate, limit: sampleLimit + 1,
                sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)]) { _, samples, error in
                var mapped: [JSObject] = []
                let formatter = ISO8601DateFormatter()
                for sample in (samples ?? []).prefix(self.sampleLimit) {
                    if (sample.metadata?[HKMetadataKeyWasUserEntered] as? NSNumber)?.boolValue == true { continue }
                    var value: Double
                    if let quantity = sample as? HKQuantitySample, let unit = unit {
                        value = quantity.quantity.doubleValue(for: unit)
                    } else if let category = sample as? HKCategorySample {
                        // 0=in bed and 2=awake are excluded. 1 is the legacy
                        // unspecified asleep value; 3/4/5 are core/deep/REM.
                        guard [1, 3, 4, 5].contains(category.value) else { continue }
                        value = max(0, min(category.endDate, until).timeIntervalSince(max(category.startDate, since))) / 60
                    } else { continue }
                    guard value.isFinite && value >= 0 else { continue }
                    let deviceName = sample.device?.name ?? sample.device?.model ?? sample.sourceRevision.source.name
                    mapped.append([
                        "id": sample.uuid.uuidString,
                        "kind": kind, "value": value, "unit": unitName,
                        "startDate": formatter.string(from: kind == "sleep" ? max(sample.startDate, since) : sample.startDate),
                        "endDate": formatter.string(from: min(sample.endDate, until)),
                        "deviceName": deviceName,
                        "origin": sample.sourceRevision.source.bundleIdentifier,
                        "manual": false
                    ])
                }
                lock.lock()
                readings.append(contentsOf: mapped)
                truncated = truncated || (samples?.count ?? 0) > self.sampleLimit
                failed = failed || error != nil
                lock.unlock()
                group.leave()
            }
            store.execute(query)
        }
        // Workouts carry the activity type and distance; running and cycling are the
        // only ones attributed to a distance metric, others are never guessed.
        group.enter()
        let workoutQuery = HKSampleQuery(sampleType: HKObjectType.workoutType(), predicate: predicate,
            limit: sampleLimit + 1, sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)]) { _, samples, error in
            var mapped: [JSObject] = []
            let formatter = ISO8601DateFormatter()
            for sample in (samples ?? []).prefix(self.sampleLimit) {
                guard let workout = sample as? HKWorkout else { continue }
                if (workout.metadata?[HKMetadataKeyWasUserEntered] as? NSNumber)?.boolValue == true { continue }
                let minutes = min(workout.endDate, until).timeIntervalSince(max(workout.startDate, since)) / 60
                let deviceName = workout.device?.name ?? workout.device?.model ?? workout.sourceRevision.source.name
                func emit(_ kind: String, _ value: Double, _ unitName: String, _ suffix: String) {
                    mapped.append(["id": workout.uuid.uuidString + suffix, "kind": kind, "value": value, "unit": unitName,
                        "startDate": formatter.string(from: max(workout.startDate, since)),
                        "endDate": formatter.string(from: min(workout.endDate, until)),
                        "deviceName": deviceName, "origin": workout.sourceRevision.source.bundleIdentifier, "manual": false])
                }
                if minutes > 0 && minutes <= 1440 { emit("exercise_minutes", minutes, "minute", ":duration") }
                if let distance = workout.totalDistance?.doubleValue(for: HKUnit.meter()) {
                    if workout.workoutActivityType == .running && distance >= 0 && distance <= 200000 {
                        emit("distance_run", distance, "meter", ":distance")
                    } else if workout.workoutActivityType == .cycling && distance >= 0 && distance <= 500000 {
                        emit("distance_cycle", distance, "meter", ":distance")
                    }
                }
            }
            lock.lock()
            readings.append(contentsOf: mapped)
            truncated = truncated || (samples?.count ?? 0) > self.sampleLimit
            failed = failed || error != nil
            lock.unlock()
            group.leave()
        }
        store.execute(workoutQuery)
        group.notify(queue: .main) {
            self.reading = false
            call.resolve(["readings": readings, "truncated": truncated,
                "message": failed ? "部分类型未能读取，请解锁设备并检查 Apple 健康的权限与同步情况。" : "仅返回系统健康库中的真实记录，已排除明确标记为手动输入的记录。"])
        }
    }
}
