package com.zhiji.healthdevice

import android.app.Activity
import android.os.Bundle
import android.widget.ScrollView
import android.widget.TextView

class HealthPermissionRationaleActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = TextView(this).apply {
            textSize = 18f
            setPadding(32, 48, 32, 48)
            text = "知己 · 健康资料读取说明\n\n我们仅在你主动同步时读取最近 7 天或 30 天的心率、静息心率、血氧、体温、步数和睡眠。资料来自手机健康平台及已同步的手表，不会向 Health Connect 写入或删除记录。\n\n读取后由你确认导入个人健康档案；确认导入的数据将通过应用配置的健康档案服务保存。你可以在 Health Connect 撤回任一权限，也可在知己删除已导入的档案资料。\n\n未授权、未同步或设备不支持的指标可能没有数据。健康记录仅用于辅助观察，不能代替医疗诊断。"
        }
        setContentView(ScrollView(this).apply { addView(text) })
    }
}
