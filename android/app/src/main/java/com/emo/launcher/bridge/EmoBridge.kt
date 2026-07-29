package com.emo.launcher.bridge

import android.app.ActivityManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.util.Log
import android.webkit.JavascriptInterface
import android.widget.Toast
import com.emo.launcher.LauncherActivity
import com.emo.launcher.overlay.TermuxPopupManager
import com.emo.launcher.util.SystemInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * EmoBridge — the Kotlin ↔ JavaScript interface.
 *
 * Every public method annotated with @JavascriptInterface is callable
 * from the Web HUD as `window.Android.methodName(args)`.
 *
 * Methods run on the WebView's internal JS thread. Heavy operations
 * (like scanning installed apps) are kept lightweight by caching.
 *
 * Categories:
 *   1. System Diagnostics (battery, RAM, CPU, storage, network, uptime)
 *   2. Device Control (vibrate, brightness, volume, screen)
 *   3. App Management (list, launch, recent)
 *   4. Termux Control (run commands, restart)
 *   5. EMO-Specific (server status, clipboard, toast, speak)
 */
class EmoBridge(private val activity: LauncherActivity) {

    companion object {
        private const val TAG = "EmoBridge"
    }

    private val context: Context get() = activity.applicationContext
    private val popupManager by lazy { TermuxPopupManager(activity) }

    // Cache installed apps — refreshed on demand, not every call
    private var cachedApps: String? = null
    private var appsCacheTime: Long = 0
    private val APP_CACHE_TTL = 60_000L  // 1 minute

    // =====================================================================
    // 1. SYSTEM DIAGNOSTICS
    // =====================================================================

    @JavascriptInterface
    fun getBattery(): String {
        return try {
            SystemInfo.getBattery(context).toString()
        } catch (e: Exception) {
            Log.e(TAG, "getBattery failed", e)
            JSONObject().put("level", -1).put("error", e.message).toString()
        }
    }

    @JavascriptInterface
    fun getBatteryLevel(): Int {
        return try {
            SystemInfo.getBattery(context).getInt("level")
        } catch (_: Exception) { -1 }
    }

    @JavascriptInterface
    fun getBatteryCharging(): Boolean {
        return try {
            SystemInfo.getBattery(context).getBoolean("charging")
        } catch (_: Exception) { false }
    }

    @JavascriptInterface
    fun getRAM(): String {
        return try {
            SystemInfo.getRAM(context).toString()
        } catch (e: Exception) {
            Log.e(TAG, "getRAM failed", e)
            "{\"error\":\"${e.message}\"}"
        }
    }

    @JavascriptInterface
    fun getCPU(): String {
        return try {
            SystemInfo.getCPU().toString()
        } catch (e: Exception) {
            Log.e(TAG, "getCPU failed", e)
            "{\"error\":\"${e.message}\"}"
        }
    }

    @JavascriptInterface
    fun getStorage(): String {
        return try {
            SystemInfo.getStorage().toString()
        } catch (e: Exception) {
            Log.e(TAG, "getStorage failed", e)
            "{\"error\":\"${e.message}\"}"
        }
    }

    @JavascriptInterface
    fun getNetwork(): String {
        return try {
            SystemInfo.getNetwork(context).toString()
        } catch (e: Exception) {
            Log.e(TAG, "getNetwork failed", e)
            "{\"type\":\"unknown\",\"error\":\"${e.message}\"}"
        }
    }

    @JavascriptInterface
    fun getUptime(): Long {
        return SystemInfo.getUptime()
    }

    @JavascriptInterface
    fun getDeviceInfo(): String {
        return try {
            SystemInfo.getDeviceInfo().toString()
        } catch (e: Exception) {
            "{\"error\":\"${e.message}\"}"
        }
    }

    @JavascriptInterface
    fun getScreenInfo(): String {
        return try {
            SystemInfo.getScreenInfo(context).toString()
        } catch (e: Exception) {
            "{\"error\":\"${e.message}\"}"
        }
    }

    /**
     * Returns a full telemetry snapshot — all diagnostics in one call.
     * The HUD calls this once per refresh cycle instead of 6 separate calls.
     */
    @JavascriptInterface
    fun getTelemetry(): String {
        return try {
            JSONObject().apply {
                put("battery", SystemInfo.getBattery(context))
                put("ram", SystemInfo.getRAM(context))
                put("cpu", SystemInfo.getCPU())
                put("storage", SystemInfo.getStorage())
                put("network", SystemInfo.getNetwork(context))
                put("uptime", SystemInfo.getUptime())
                put("device", SystemInfo.getDeviceInfo())
                put("screen", SystemInfo.getScreenInfo(context))
                put("timestamp", System.currentTimeMillis())
            }.toString()
        } catch (e: Exception) {
            Log.e(TAG, "getTelemetry failed", e)
            "{\"error\":\"${e.message}\"}"
        }
    }

    // =====================================================================
    // 2. DEVICE CONTROL
    // =====================================================================

    @JavascriptInterface
    fun vibrate(durationMs: Long) {
        try {
            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                vm.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(
                    VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE)
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(durationMs)
            }
        } catch (e: Exception) {
            Log.e(TAG, "vibrate failed", e)
        }
    }

    @JavascriptInterface
    fun vibratePattern(patternJson: String) {
        try {
            val arr = JSONArray(patternJson)
            val pattern = LongArray(arr.length()) { arr.getLong(it) }

            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
                vm.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createWaveform(pattern, -1))
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(pattern, -1)
            }
        } catch (e: Exception) {
            Log.e(TAG, "vibratePattern failed", e)
        }
    }

    @JavascriptInterface
    fun setBrightness(value: Int) {
        try {
            val clamped = value.coerceIn(0, 255)
            Settings.System.putInt(
                context.contentResolver,
                Settings.System.SCREEN_BRIGHTNESS,
                clamped
            )
        } catch (e: Exception) {
            Log.e(TAG, "setBrightness failed (needs WRITE_SETTINGS)", e)
        }
    }

    @JavascriptInterface
    fun getScreenBrightness(): Int {
        return try {
            Settings.System.getInt(
                context.contentResolver,
                Settings.System.SCREEN_BRIGHTNESS,
                128
            )
        } catch (_: Exception) { 128 }
    }

    @JavascriptInterface
    fun setVolume(stream: Int, level: Int) {
        try {
            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val maxVol = am.getStreamMaxVolume(stream)
            val clamped = level.coerceIn(0, maxVol)
            am.setStreamVolume(stream, clamped, 0)
        } catch (e: Exception) {
            Log.e(TAG, "setVolume failed", e)
        }
    }

    @JavascriptInterface
    fun getVolume(stream: Int): Int {
        return try {
            val am = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            am.getStreamVolume(stream)
        } catch (_: Exception) { 0 }
    }

    @JavascriptInterface
    fun keepScreenOn(on: Boolean) {
        activity.runOnUiThread {
            if (on) {
                activity.window.addFlags(
                    android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                )
            } else {
                activity.window.clearFlags(
                    android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
                )
            }
        }
    }

    // =====================================================================
    // 3. APP MANAGEMENT
    // =====================================================================

    @JavascriptInterface
    fun getInstalledApps(): String {
        val now = System.currentTimeMillis()
        if (cachedApps != null && (now - appsCacheTime) < APP_CACHE_TTL) {
            return cachedApps!!
        }
        return try {
            val apps = SystemInfo.getInstalledApps(context).toString()
            cachedApps = apps
            appsCacheTime = now
            apps
        } catch (e: Exception) {
            Log.e(TAG, "getInstalledApps failed", e)
            "[]"
        }
    }

    @JavascriptInterface
    fun launchApp(packageName: String): Boolean {
        return try {
            val intent = context.packageManager.getLaunchIntentForPackage(packageName)
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(intent)
                true
            } else {
                Log.w(TAG, "No launch intent for: $packageName")
                false
            }
        } catch (e: Exception) {
            Log.e(TAG, "launchApp failed: $packageName", e)
            false
        }
    }

    @JavascriptInterface
    fun isAppInstalled(packageName: String): Boolean {
        return try {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (_: Exception) {
            false
        }
    }

    @JavascriptInterface
    fun refreshAppCache() {
        cachedApps = null
        appsCacheTime = 0
    }

    // =====================================================================
    // 4. TERMUX CONTROL
    // =====================================================================

    @JavascriptInterface
    fun termuxRun(command: String): Boolean {
        return try {
            val intent = Intent("com.termux.RUN_COMMAND").apply {
                setClassName("com.termux", "com.termux.app.RunCommandService")
                putExtra("com.termux.RUN_COMMAND_PATH", "/data/data/com.termux/files/usr/bin/bash")
                putExtra("com.termux.RUN_COMMAND_ARGUMENTS", arrayOf("-c", command))
                putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
            }
            context.startService(intent)
            true
        } catch (e: Exception) {
            Log.e(TAG, "termuxRun failed", e)
            false
        }
    }

    @JavascriptInterface
    fun termuxIsRunning(): Boolean {
        return try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            @Suppress("DEPRECATION")
            val running = am.getRunningAppProcesses() ?: return false
            running.any { it.processName == "com.termux" }
        } catch (_: Exception) {
            false
        }
    }

    @JavascriptInterface
    fun termuxRestart(): Boolean {
        return try {
            // Start Termux app
            val launchIntent = context.packageManager.getLaunchIntentForPackage("com.termux")
            if (launchIntent != null) {
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(launchIntent)
            }
            // Then run EMO's startup script
            Thread.sleep(2000) // Give Termux a moment to boot
            termuxRun("cd ~/storage/shared/EMO && bash run.sh")
        } catch (e: Exception) {
            Log.e(TAG, "termuxRestart failed", e)
            false
        }
    }

    @JavascriptInterface
    fun showTermuxPopup() {
        activity.runOnUiThread {
            popupManager.show()
        }
    }

    @JavascriptInterface
    fun hideTermuxPopup() {
        activity.runOnUiThread {
            popupManager.hide()
        }
    }

    @JavascriptInterface
    fun toggleTermuxPopup() {
        activity.runOnUiThread {
            popupManager.toggle()
        }
    }

    // =====================================================================
    // 5. EMO-SPECIFIC
    // =====================================================================

    @JavascriptInterface
    fun getServerStatus(): String {
        val launcher = LauncherActivity.instance
        return JSONObject().apply {
            put("live", launcher?.isLiveMode ?: false)
            put("mode", if (launcher?.isLiveMode == true) "live" else "offline")
        }.toString()
    }

    @JavascriptInterface
    fun toast(message: String) {
        activity.runOnUiThread {
            Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
        }
    }

    @JavascriptInterface
    fun copyToClipboard(text: String) {
        activity.runOnUiThread {
            val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.setPrimaryClip(ClipData.newPlainText("EMO", text))
        }
    }

    @JavascriptInterface
    fun readClipboard(): String {
        return try {
            val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            cm.primaryClip?.getItemAt(0)?.text?.toString() ?: ""
        } catch (_: Exception) { "" }
    }

    @JavascriptInterface
    fun reloadHud() {
        activity.runOnUiThread { activity.recreate() }
    }

    @JavascriptInterface
    fun getEmoVersion(): String {
        return try {
            val pInfo = context.packageManager.getPackageInfo(context.packageName, 0)
            pInfo.versionName ?: "1.0.0"
        } catch (_: Exception) { "1.0.0" }
    }

    /**
     * Open Android Settings directly — useful for the setup wizard
     * and for quick system access from the HUD.
     */
    @JavascriptInterface
    fun openSettings(page: String) {
        try {
            val action = when (page) {
                "wifi" -> Settings.ACTION_WIFI_SETTINGS
                "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
                "display" -> Settings.ACTION_DISPLAY_SETTINGS
                "battery" -> Settings.ACTION_BATTERY_SAVER_SETTINGS
                "apps" -> Settings.ACTION_APPLICATION_SETTINGS
                "sound" -> Settings.ACTION_SOUND_SETTINGS
                "accessibility" -> Settings.ACTION_ACCESSIBILITY_SETTINGS
                else -> Settings.ACTION_SETTINGS
            }
            val intent = Intent(action).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "openSettings failed: $page", e)
        }
    }
}
