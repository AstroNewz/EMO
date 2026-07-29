package com.emo.launcher

import android.annotation.SuppressLint
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.emo.launcher.overlay.TermuxPopupManager
import com.emo.launcher.services.WatchdogService
import com.emo.launcher.util.NetworkUtils
import com.emo.launcher.util.SystemInfo
import com.emo.launcher.view.EmoPixelFaceView
import org.json.JSONObject

/**
 * LauncherActivity — Pure Native Kotlin Taskmagotchi Companion.
 *
 * 100% Native Android UI — zero WebView or Chrome dependency!
 * Renders EMO's pixelated LED face directly on native Canvas via EmoPixelFaceView.
 */
class LauncherActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "EMO"
        const val BACKEND_URL = "http://127.0.0.1:3000"

        @Volatile
        var instance: LauncherActivity? = null
            private set
    }

    private lateinit var pixelFaceView: EmoPixelFaceView
    private lateinit var tvHappyMeter: TextView
    private lateinit var tvEnergyMeter: TextView
    private lateinit var tvTasksMeter: TextView
    private lateinit var tvSpeechText: TextView
    private lateinit var tvStatusSub: TextView
    private lateinit var etChatInput: EditText
    private lateinit var btnSend: Button
    private lateinit var tvSwipeHint: TextView

    private val popupManager by lazy { TermuxPopupManager(this) }

    @Volatile
    var isLiveMode: Boolean = false
        private set

    private var isPolling = true

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        setContentView(R.layout.activity_launcher)
        instance = this

        pixelFaceView = findViewById(R.id.pixelFaceView)
        tvHappyMeter = findViewById(R.id.tvHappyMeter)
        tvEnergyMeter = findViewById(R.id.tvEnergyMeter)
        tvTasksMeter = findViewById(R.id.tvTasksMeter)
        tvSpeechText = findViewById(R.id.tvSpeechText)
        tvStatusSub = findViewById(R.id.tvStatusSub)
        etChatInput = findViewById(R.id.etChatInput)
        btnSend = findViewById(R.id.btnSend)
        tvSwipeHint = findViewById(R.id.tvSwipeHint)

        enterImmersiveMode()

        // Start Watchdog Foreground Service
        val serviceIntent = Intent(this, WatchdogService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(serviceIntent)
        } else {
            startService(serviceIntent)
        }

        // Tap on stage to trigger voice listen wish
        pixelFaceView.setOnClickListener {
            triggerWish("listen")
        }

        btnSend.setOnClickListener {
            val text = etChatInput.text.toString().trim()
            if (text.isNotEmpty()) {
                tvSpeechText.text = "You: $text"
                etChatInput.setText("")
                triggerWish("listen")
            }
        }

        tvSwipeHint.setOnClickListener {
            popupManager.toggle()
        }

        // Start background telemetry polling loop
        startNativeTelemetryLoop()

        Log.i(TAG, "LauncherActivity created — Pure Native EMO Taskmagotchi Active.")
    }

    override fun onResume() {
        super.onResume()
        enterImmersiveMode()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) enterImmersiveMode()
    }

    override fun onDestroy() {
        isPolling = false
        instance = null
        super.onDestroy()
    }

    private fun triggerWish(wish: String) {
        Thread {
            try {
                val data = "{\"wish\":\"$wish\"}".toByteArray()
                val conn = java.net.URL("$BACKEND_URL/wish").openConnection() as java.net.HttpURLConnection
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json")
                conn.doOutput = true
                conn.outputStream.write(data)
                conn.responseCode
                conn.disconnect()
            } catch (_: Exception) {}
        }.start()
    }

    private fun startNativeTelemetryLoop() {
        Thread {
            while (isPolling) {
                try {
                    val battery = SystemInfo.getBattery(this)
                    val batLevel = battery.optInt("level", 95)
                    val batCharging = battery.optBoolean("charging", false)

                    // Hit backend telemetry
                    val jsonStr = NetworkUtils.get("$BACKEND_URL/api/telemetry", 2000)
                    if (jsonStr != null) {
                        val json = JSONObject(jsonStr)
                        val stateStr = json.optString("state", "idle").uppercase()
                        val uptime = json.optInt("uptime", 0)

                        isLiveMode = true
                        runOnUiThread {
                            tvEnergyMeter.text = "ENERGY ${if (batCharging) "⚡" else "🔋"} $batLevel%"
                            tvStatusSub.text = "EMO ONLINE · STATE: $stateStr · UPTIME: ${uptime}s"
                            
                            try {
                                pixelFaceView.currentState = EmoPixelFaceView.State.valueOf(stateStr)
                            } catch (_: Exception) {
                                pixelFaceView.currentState = EmoPixelFaceView.State.IDLE
                            }
                        }
                    } else {
                        isLiveMode = false
                        runOnUiThread {
                            tvEnergyMeter.text = "ENERGY ${if (batCharging) "⚡" else "🔋"} $batLevel%"
                            tvStatusSub.text = "EMO OFFLINE · WAITING FOR 127.0.0.1:3000..."
                            pixelFaceView.currentState = EmoPixelFaceView.State.IDLE
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Telemetry poll exception", e)
                }

                try {
                    Thread.sleep(1500)
                } catch (_: InterruptedException) {}
            }
        }.start()
    }

    fun loadLiveHud() {
        isLiveMode = true
    }

    fun loadOfflineHud() {
        isLiveMode = false
    }

    private fun enterImmersiveMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.systemBars())
                controller.systemBarsBehavior =
                    WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                    or View.SYSTEM_UI_FLAG_FULLSCREEN
                )
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        // Swallow back button — stay in EMO
    }
}
