package com.emo.launcher.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.emo.launcher.LauncherActivity
import com.emo.launcher.R
import com.emo.launcher.util.NetworkUtils

/**
 * WatchdogService — self-healing foreground service.
 *
 * Runs permanently in the foreground (unkillable by the OS battery manager).
 * Polls the EMO backend at localhost:3000/api/health every 2 seconds and
 * controls the LauncherActivity's WebView:
 *
 *   - Server UP   → load live HUD from localhost:3000
 *   - Server DOWN → load offline HUD from embedded assets
 *   - Server BACK → seamlessly hot-reload the live HUD
 *
 * If the backend goes down, the watchdog also attempts to restart Termux
 * and re-run the EMO startup script.
 */
class WatchdogService : Service() {

    companion object {
        private const val TAG = "EMO-Watchdog"
        private const val CHANNEL_ID = "emo_watchdog"
        private const val NOTIFICATION_ID = 1001
        private const val POLL_INTERVAL_MS = 2000L    // 2 seconds
        private const val FAILURE_THRESHOLD = 2        // consecutive fails before offline switch
        private const val RESTART_COOLDOWN_MS = 30_000L // don't retry Termux restart more than once per 30s
    }

    private lateinit var handlerThread: HandlerThread
    private lateinit var handler: Handler
    private var consecutiveFailures = 0
    private var isRunning = false
    private var lastRestartAttempt = 0L

    // Current known state
    enum class BackendState { UNKNOWN, LIVE, OFFLINE, RECOVERING }
    @Volatile
    var backendState: BackendState = BackendState.UNKNOWN
        private set

    // =====================================================================
    // SERVICE LIFECYCLE
    // =====================================================================

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Initializing..."))
        
        handlerThread = HandlerThread("emo-watchdog").also { it.start() }
        handler = Handler(handlerThread.looper)
        
        Log.i(TAG, "Watchdog service created.")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!isRunning) {
            isRunning = true
            handler.post(pollRunnable)
            Log.i(TAG, "Watchdog polling started (every ${POLL_INTERVAL_MS}ms).")
        }
        // If the system kills this service, restart it automatically
        return START_STICKY
    }

    override fun onDestroy() {
        isRunning = false
        handler.removeCallbacksAndMessages(null)
        handlerThread.quitSafely()
        Log.i(TAG, "Watchdog service destroyed.")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // =====================================================================
    // POLL LOOP
    // =====================================================================

    private val pollRunnable = object : Runnable {
        override fun run() {
            if (!isRunning) return

            val alive = NetworkUtils.isBackendAlive()

            if (alive) {
                onBackendAlive()
            } else {
                onBackendDead()
            }

            // Schedule the next poll
            handler.postDelayed(this, POLL_INTERVAL_MS)
        }
    }

    private fun onBackendAlive() {
        if (consecutiveFailures > 0) {
            Log.i(TAG, "Backend recovered after $consecutiveFailures failures.")
        }
        consecutiveFailures = 0

        val launcher = LauncherActivity.instance

        when (backendState) {
            BackendState.UNKNOWN, BackendState.OFFLINE -> {
                // Server just came up — switch to live HUD
                backendState = BackendState.RECOVERING
                Log.i(TAG, "→ Backend detected. Switching to LIVE mode.")
                updateNotification("EMO online — live HUD active")
                launcher?.loadLiveHud()
                backendState = BackendState.LIVE
            }
            BackendState.RECOVERING -> {
                // Already switching, just confirm we're live
                backendState = BackendState.LIVE
            }
            BackendState.LIVE -> {
                // All good, nothing to do
            }
        }
    }

    private fun onBackendDead() {
        consecutiveFailures++

        if (consecutiveFailures >= FAILURE_THRESHOLD && backendState != BackendState.OFFLINE) {
            Log.w(TAG, "→ Backend DOWN ($consecutiveFailures consecutive failures). Switching to OFFLINE mode.")
            backendState = BackendState.OFFLINE
            updateNotification("EMO offline — waiting for backend...")

            val launcher = LauncherActivity.instance
            launcher?.loadOfflineHud()

            // Attempt to restart Termux (throttled)
            attemptTermuxRestart()
        }
    }

    // =====================================================================
    // TERMUX RESTART
    // =====================================================================

    private fun attemptTermuxRestart() {
        val now = System.currentTimeMillis()
        if (now - lastRestartAttempt < RESTART_COOLDOWN_MS) {
            Log.d(TAG, "Termux restart on cooldown, skipping.")
            return
        }
        lastRestartAttempt = now

        Log.i(TAG, "Attempting to restart Termux + EMO backend...")

        try {
            // First, try to launch the Termux app itself
            val launchIntent = packageManager.getLaunchIntentForPackage("com.termux")
            if (launchIntent != null) {
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                startActivity(launchIntent)
            }

            // Then send the RUN_COMMAND to start run.sh
            handler.postDelayed({
                try {
                    val runIntent = Intent("com.termux.RUN_COMMAND").apply {
                        setClassName("com.termux", "com.termux.app.RunCommandService")
                        putExtra(
                            "com.termux.RUN_COMMAND_PATH",
                            "/data/data/com.termux/files/usr/bin/bash"
                        )
                        putExtra(
                            "com.termux.RUN_COMMAND_ARGUMENTS",
                            arrayOf("-c", "cd ~/storage/shared/EMO && bash run.sh &")
                        )
                        putExtra("com.termux.RUN_COMMAND_BACKGROUND", true)
                    }
                    startService(runIntent)
                    Log.i(TAG, "Termux RUN_COMMAND sent (run.sh).")
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to send RUN_COMMAND to Termux", e)
                }
            }, 3000) // Wait 3s for Termux to boot before sending command
        } catch (e: Exception) {
            Log.e(TAG, "Failed to restart Termux", e)
        }
    }

    // =====================================================================
    // NOTIFICATIONS
    // =====================================================================

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.watchdog_channel_name),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = getString(R.string.watchdog_channel_desc)
                setShowBadge(false)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, LauncherActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.watchdog_notification_title))
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_info_details) // TODO: custom EMO icon
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIFICATION_ID, buildNotification(text))
    }
}
