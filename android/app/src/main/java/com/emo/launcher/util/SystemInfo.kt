package com.emo.launcher.util

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.RandomAccessFile

/**
 * System information queries — pure data, no side effects.
 * Every method returns a JSONObject (or primitive) that the bridge
 * passes straight to JavaScript.
 */
object SystemInfo {

    // =====================================================================
    // BATTERY
    // =====================================================================

    fun getBattery(context: Context): JSONObject {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))

        val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val charging = bm.isCharging
        val temp = (intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0) / 10
        val voltage = intent?.getIntExtra(BatteryManager.EXTRA_VOLTAGE, 0) ?: 0
        val healthInt = intent?.getIntExtra(BatteryManager.EXTRA_HEALTH, 0) ?: 0
        val health = when (healthInt) {
            BatteryManager.BATTERY_HEALTH_GOOD -> "good"
            BatteryManager.BATTERY_HEALTH_OVERHEAT -> "overheat"
            BatteryManager.BATTERY_HEALTH_DEAD -> "dead"
            BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE -> "over_voltage"
            BatteryManager.BATTERY_HEALTH_COLD -> "cold"
            else -> "unknown"
        }

        return JSONObject().apply {
            put("level", level)
            put("charging", charging)
            put("temp", temp)
            put("voltage", voltage)
            put("health", health)
        }
    }

    // =====================================================================
    // RAM
    // =====================================================================

    fun getRAM(context: Context): JSONObject {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val memInfo = ActivityManager.MemoryInfo()
        am.getMemoryInfo(memInfo)

        val totalMB = memInfo.totalMem / (1024 * 1024)
        val freeMB = memInfo.availMem / (1024 * 1024)
        val usedMB = totalMB - freeMB
        val percent = if (totalMB > 0) ((usedMB * 100) / totalMB).toInt() else 0

        return JSONObject().apply {
            put("used", usedMB)
            put("total", totalMB)
            put("free", freeMB)
            put("percent", percent)
        }
    }

    // =====================================================================
    // CPU
    // =====================================================================

    private var lastCpuTotal: Long = 0
    private var lastCpuIdle: Long = 0

    fun getCPU(): JSONObject {
        var usage = 0
        val cores = Runtime.getRuntime().availableProcessors()

        try {
            val reader = RandomAccessFile("/proc/stat", "r")
            val line = reader.readLine()
            reader.close()

            val parts = line.split("\\s+".toRegex())
            // parts: cpu user nice system idle iowait irq softirq ...
            if (parts.size >= 5) {
                val idle = parts[4].toLongOrNull() ?: 0L
                var total = 0L
                for (i in 1 until parts.size) {
                    total += parts[i].toLongOrNull() ?: 0L
                }

                val diffTotal = total - lastCpuTotal
                val diffIdle = idle - lastCpuIdle
                if (diffTotal > 0) {
                    usage = (100 * (diffTotal - diffIdle) / diffTotal).toInt()
                }
                lastCpuTotal = total
                lastCpuIdle = idle
            }
        } catch (_: Exception) { }

        // Read per-core frequencies
        val freqs = JSONArray()
        for (i in 0 until cores) {
            try {
                val path = "/sys/devices/system/cpu/cpu$i/cpufreq/scaling_cur_freq"
                val freq = RandomAccessFile(path, "r").use { it.readLine().trim().toLong() / 1000 }
                freqs.put(freq) // MHz
            } catch (_: Exception) {
                freqs.put(0)
            }
        }

        return JSONObject().apply {
            put("usage", usage)
            put("cores", cores)
            put("freq", freqs)
        }
    }

    // =====================================================================
    // STORAGE
    // =====================================================================

    fun getStorage(): JSONObject {
        val stat = StatFs(Environment.getDataDirectory().path)
        val totalMB = (stat.blockSizeLong * stat.blockCountLong) / (1024 * 1024)
        val freeMB = (stat.blockSizeLong * stat.availableBlocksLong) / (1024 * 1024)
        val usedMB = totalMB - freeMB

        return JSONObject().apply {
            put("used", usedMB)
            put("total", totalMB)
            put("free", freeMB)
        }
    }

    // =====================================================================
    // NETWORK
    // =====================================================================

    fun getNetwork(context: Context): JSONObject {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork
        val caps = cm.getNetworkCapabilities(network)

        val type = when {
            caps == null -> "none"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "other"
        }

        val result = JSONObject().apply {
            put("type", type)
        }

        // WiFi details
        if (type == "wifi") {
            try {
                val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                val info = wm.connectionInfo
                result.put("ssid", info.ssid?.removeSurrounding("\"") ?: "")
                result.put("strength", info.rssi)
                val ip = info.ipAddress
                val ipStr = "${ip and 0xFF}.${(ip shr 8) and 0xFF}.${(ip shr 16) and 0xFF}.${(ip shr 24) and 0xFF}"
                result.put("ip", ipStr)
            } catch (_: Exception) { }
        }

        return result
    }

    // =====================================================================
    // DEVICE INFO
    // =====================================================================

    fun getDeviceInfo(): JSONObject {
        return JSONObject().apply {
            put("model", Build.MODEL)
            put("brand", Build.BRAND)
            put("manufacturer", Build.MANUFACTURER)
            put("android", Build.VERSION.RELEASE)
            put("sdk", Build.VERSION.SDK_INT)
            put("product", Build.PRODUCT)
            put("hardware", Build.HARDWARE)
        }
    }

    // =====================================================================
    // SCREEN
    // =====================================================================

    fun getScreenInfo(context: Context): JSONObject {
        val dm = context.resources.displayMetrics
        return JSONObject().apply {
            put("width", dm.widthPixels)
            put("height", dm.heightPixels)
            put("density", dm.density.toDouble())
            put("dpi", dm.densityDpi)
        }
    }

    // =====================================================================
    // UPTIME
    // =====================================================================

    fun getUptime(): Long {
        return SystemClock.elapsedRealtime() / 1000  // seconds
    }

    // =====================================================================
    // INSTALLED APPS
    // =====================================================================

    fun getInstalledApps(context: Context): JSONArray {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val apps = pm.queryIntentActivities(intent, 0)

        val result = JSONArray()
        for (app in apps) {
            val info = app.activityInfo
            val appObj = JSONObject().apply {
                put("name", info.loadLabel(pm).toString())
                put("package", info.packageName)
            }
            result.put(appObj)
        }
        return result
    }
}
