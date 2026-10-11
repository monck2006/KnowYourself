# 手机与手表真实健康资料接入

项目包含本地 Capacitor 插件 `@zhiji/health-device`，Android 实现调用 Health Connect，iOS 实现调用 HealthKit。网页可选连接标准蓝牙心率服务。应用只读取最近 7 或 30 天、用户允许的实际记录，不写回系统健康库，也不生成模拟读数。

## 支持范围

| 运行环境 | 实际资料通道 | 前提 |
| --- | --- | --- |
| Android 手机及已同步的手表 | Health Connect：普通/静息心率、心率变异性(RMSSD)、血氧、体温、步数、睡眠、饮食能量、饮水、活动消耗、基础代谢、最大摄氧量、运动时长、跑步/骑行距离 | Android 9+，系统服务可用并允许相应读取；Android 13 及以前通常需安装 Health Connect；手表厂商须把资料同步到该健康库 |
| iPhone 及 Apple Watch | HealthKit：上述指标（心率变异性为 SDNN） | 支持健康资料的设备，Apple 健康内已有记录，并按需完成读取授权；Apple Watch 先同步至 iPhone |
| 支持 Web Bluetooth 的安全浏览器 | 标准 GATT Heart Rate Service 的实时心率 | HTTPS 或 localhost，用户点击选择支持该协议的设备；不能读取系统健康库或手表的 7/30 天历史 |

### 指标口径与不可读取的派生值

- **心率变异性（HRV）**：iOS 存 SDNN、Android Health Connect 存 RMSSD，两者口径不同，字段分别为 `hrv_sdnn` 与 `hrv_rmssd`，**不合并、不互相比较**。
- **最大摄氧量 `vo2max`**：可能是系统或厂商估算，仅原样保留读数，不据此推断体能或健康结论。
- **平台不提供的派生值**：睡眠 HRV、压力、乳酸阈心率、最大心率，以及跑步能力、运动状态、肌肉能力、热量缺口、运动周报等“运动表现”，健康库均不存储。本应用**不计算、不推断**这些结论；仅在用户主动导入厂商导出时按“厂商估算，非本应用计算”强标注，否则界面明确“暂不可用”。
- **运动距离**：Android 依据 Health Connect `DistanceRecord` 自带的 `exerciseType`、iOS 依据 `HKWorkout` 的活动类型，只把跑步与骑行分别归入 `distance_run`、`distance_cycle`；其他运动类型不猜测。运动时长取会话真实起止；平台不提供距离的会话不会补造。

能连接手机系统健康库不代表所有品牌手表都已同步；指标是否存在取决于硬件、厂商和用户设置。网页和原生功能分别检测可用性。手动录入独立标记为 `manual`，系统中明确标记为手动输入的记录也排除出设备导入。

## 调用契约

`src/lib/healthDevice.ts` 导出 `HealthDeviceItem`、`HealthDeviceStatus`、`HealthDeviceResult` 和以下函数：

```ts
getHealthDeviceStatus(): Promise<HealthDeviceStatus>
requestHealthDevicePermissions(): Promise<HealthDeviceStatus>
readHealthDeviceData(days: 7 | 30): Promise<HealthDeviceResult>
connectBluetoothHeartRate(onItem): Promise<{
  deviceName: string
  disconnect(): void
  isConnected(): boolean
}>
```

状态为 `unavailable`、`permission` 或 `ready`，同时提供 `read_permission`。Android 根据实际授权类型读取；部分获准也可读取已获准类型。Apple 为保护隐私不披露读取权限是否遭拒绝，因此授权流程完成后的 `ready / unknown` 只表示可以尝试读取，不能宣称已获得读权限；空结果也不能证明用户拒绝或身体异常。页面先申请授权、读取预览，再由用户确认导入服务器。

统一记录使用 `source: health_connect | healthkit | bluetooth`，包含稳定 `source_id`、指标/单位、带时区 `measured_at`、真实来源设备名称以及 `context`。原生 UUID 保留；Android 心率序列用 UUID 加实际样本时间区分。普通心率和蓝牙心率均为 `unknown`，只有平台明确提供的静息心率类别标记 `resting`。Apple 血氧比例乘以 100，体温统一摄氏度。

导入范围与档案接口一致：心率 20–250 bpm、血氧 50–100%、体温 30–45°C、整数步数 0–200000、睡眠 0–1440 分钟、饮食/活动/基础代谢能量 0–20000 kcal、饮水 0–20000 ml、HRV 1–500 ms、最大摄氧量 5–100 mL/kg/min、跑步距离 0–200000 m、骑行距离 0–500000 m、运动时长 0–1440 分钟。异常读数跳过并提示，不能以零值或猜测补齐。每次原生读取按类型最多 4000 条，Android 另限每类型 20 页；界面最多返回 5000 个规范化记录，达到上限明确提示。

## 日总量与去重语义

睡眠只导入明确的睡着区间，排除卧床、清醒阶段；把相交区间取并集，不把睡眠主会话与阶段再次相加。没有明确睡着阶段的 Android 会话暂不导入。区间按 UTC 日期切分，日总量不等同本地日历中的一晚睡眠。

步数按 UTC 日期、来源应用和设备分组，同日选择总量最高的一组，避免把手机和手表叠加。此保守策略可能少于系统综合显示值；不伪称平台官方去重总量，不按时长猜测跨日步数。跨日原始步数记录归其开始日期，应用尚未执行按当地时区的精确日汇总。

原始读数不可变。每日汇总的 `source_id` 含 UTC 日期、总量、最新实际记录结束时间（步数另含来源标识）；相同内容重复同步 ID 不变，来源数据变化后形成新的日汇总修订。`measured_at` 使用实际记录时间，不用同步按钮点击时间。界面查看同日最新修订，不能把多次同步的日总量相加。

蓝牙包没有平台历史 UUID，ID 使用浏览器设备标识、连接会话 UUID 和递增包序号，导入同一预览记录时保持该 ID；再次采集是新的测量。时间是浏览器收到实时通知的时间。连接断开会移除通知监听，`isConnected()` 立即反映断开状态。

## 原生配置与构建

Android 插件在 `native-plugins/health-device/android`，`@CapacitorPlugin(name = "ZhijiHealth")` 注册真实桥。清单声明六类只读健康权限、Health Connect 包可见性及权限用途说明页面/Android 14 权限用途入口。主工程最低 SDK 为 26，健康功能在 28+ 检测；使用 SDK 36、JDK 21。仓库中文目录通过 `android.overridePathCheck=true` 处理 Android Gradle Plugin 的路径检查。

iOS 插件在 `native-plugins/health-device/ios`，实现 `CAPBridgedPlugin`。`Package.swift` 链接 HealthKit，Capacitor SPM 已包含插件产品；`Info.plist` 配有 `NSHealthShareUsageDescription`，`App.entitlements` 有 HealthKit 权限，Debug/Release 均指定该 entitlements 文件。只读接入不申请写入健康资料的权限。

```sh
cd frontend
pnpm install
pnpm test:devices
pnpm build
pnpm exec cap sync
# 已配置 JDK 21 / Android SDK 后
cd android
./gradlew :app:assembleDebug
```

本地 `file:` 插件源码变更后，若 pnpm 仍使用旧打包副本，运行 `pnpm install --force` 再执行 `cap sync`。两平台生成的插件注册文件由 Capacitor 管理，不应手写空桥替代注册。

iOS 必须在 macOS/Xcode 打开 `frontend/ios/App/App.xcodeproj`，选择开发团队，确认 Signing & Capabilities 的 HealthKit、Bundle ID 和签名描述文件一致，再在真实 iPhone 上编译安装。当前 Windows 环境不能编译/运行 HealthKit，也未验证 Apple Watch 实机读数。原生编译、TS 映射测试和 `cap sync` 不能替代两平台真机授权/读数验证。

### Android 本轮实际构建证据（2026-10-11）

本机系统 Java 仍为 JDK 17。本次从 [Adoptium 官方 API](https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jdk&os=windows&vendor=eclipse) 下载 Temurin 21.0.12.1 Windows x64 ZIP，核验官方 SHA256 `f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e` 后解压至 `%TEMP%/zhiji-android-jdk21-20261011`。只在构建进程设置 `JAVA_HOME`，未安装 Android Studio、未更改全局 Java。Gradle 在线获取正规 Maven 依赖并按现有许可证补齐 Android SDK Build-Tools 35。

首次真实编译发现插件通过 `activity.runOnUiThread` 访问未透传的 AppCompat 类型，已在插件源码修正为 Android 主线程 `Handler.post`，并刷新 pnpm 本地副本。随后 `:zhiji-health-device:compileDebugKotlin` 与 `:app:assembleDebug` 均通过，日志为 `BUILD SUCCESSFUL in 1m 1s`。APK 已经 `apksigner verify` 验证调试签名（v2）通过。

- APK：`frontend/android/app/build/outputs/apk/debug/app-debug.apk`，6336482 字节。
- APK SHA256：`8fe203c3b40c6f1067ae7c29500ba0bae3444e159a479c72bc6b0d06c974cc2e`。
- 构建日志：`%TEMP%/zhiji-android-jdk21-20261011/assemble-debug-fixed.log`。
- 构建包包含真实健康插件及健康读取权限；尚未在 Android 手机/手表上完成授权和测量对照。

本轮 APK 未设置 `VITE_API_BASE_URL`，属于构建验收包。手机需要连接实际服务时，先在前端配置真实 **HTTPS** 后端地址，再执行 `pnpm build`、`pnpm exec cap sync android` 和 Gradle 调试构建；不要把手机的 localhost 当成电脑后端地址。工程不为此放宽 HTTP/TLS 安全配置。

## 真机验收

1. 在官方健康应用确认真实心率、步数等资料及来源；手表先完成同步。
2. 安装原生包，仅授予部分类型并读取，检查其余类型不补造；撤销权限后重试。
3. 对照实际样本的时间、单位、设备，普通心率应为 `unknown`；Apple 未授权时不能显示“已授权”。
4. 同一批资料导入两次应计为重复；增加当日步数后重读应产生新日修订，页面展示最新值。
5. 睡眠阶段重叠时分钟数不重复增加；手动写入系统健康库的记录不进入设备导入。
6. Web Bluetooth 选实际标准心率设备，接收有效通知后才出现读数；断连后状态更新，不能把旧值显示为持续采集。

## 官方依据

- [Capacitor 原生插件开发与注册](https://capacitorjs.com/docs/plugins/creating-plugins)
- [Android Health Connect 接入、兼容性和授权清单](https://developer.android.com/health-and-fitness/health-connect/get-started)
- [Health Connect 读取资料](https://developer.android.com/health-and-fitness/health-connect/read-data)
- [Health Connect 1.1.0 官方发布记录](https://developer.android.com/jetpack/androidx/releases/health-connect)
- [Android 睡眠阶段类型](https://developer.android.com/reference/androidx/health/connect/client/records/SleepSessionRecord)
- [Apple HealthKit 授权](https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data)
- [Apple 健康资料隐私与读取权限限制](https://developer.apple.com/documentation/healthkit/protecting-user-privacy)
- [Xcode 配置 HealthKit](https://developer.apple.com/documentation/xcode/configuring-healthkit-access)
- [Web Bluetooth 实际连接与通知](https://developer.chrome.com/docs/capabilities/bluetooth)
