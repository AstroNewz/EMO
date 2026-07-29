package com.emo.launcher.services

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import com.emo.launcher.LauncherActivity

/**
 * EmoAccessibilityService — intercepts system navigation to keep the user in EMO.
 *
 * When enabled, this service:
 *   1. Captures the BACK button → returns to EMO instead of exiting
 *   2. Captures the RECENTS button → returns to EMO (stays in terminal mode)
 *   3. (Optional) Can block status bar pull-down
 *
 * The user must manually enable this in Settings → Accessibility → EMO.
 * The SetupWizardActivity walks them through it.
 *
 * This is the "hard lock" that makes the phone feel like a dedicated terminal.
 * It can be toggled off in config.yaml (launcher.intercept_back / intercept_recents).
 */
class EmoAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "EMO-Accessibility"

        /** Whether the service is currently running — checked by the setup wizard. */
        @Volatile
        var isActive: Boolean = false
            private set
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        isActive = true

        serviceInfo = serviceInfo.apply {
            // We want to detect window state changes (app switches, recents panel)
            eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                         AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
            notificationTimeout = 100
        }

        Log.i(TAG, "Accessibility service connected — EMO has full control.")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null) return

        when (event.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                val pkg = event.packageName?.toString() ?: return
                val cls = event.className?.toString() ?: ""

                // Detect the Recents screen (system UI launcher panel)
                if (pkg == "com.android.systemui" &&
                    (cls.contains("RecentsActivity") || cls.contains("Recents"))
                ) {
                    Log.d(TAG, "Recents detected — returning to EMO.")
                    returnToEmo()
                }

                // Detect other launchers trying to take over
                if (cls.contains("Launcher") && pkg != "com.emo.launcher") {
                    Log.d(TAG, "External launcher detected ($pkg) — returning to EMO.")
                    returnToEmo()
                }
            }
        }
    }

    override fun onInterrupt() {
        Log.w(TAG, "Accessibility service interrupted.")
    }

    override fun onDestroy() {
        isActive = false
        Log.i(TAG, "Accessibility service destroyed.")
        super.onDestroy()
    }

    /**
     * Intercept the global BACK action. Return true to consume it (stay in EMO).
     */
    override fun onKeyEvent(event: android.view.KeyEvent?): Boolean {
        if (event?.keyCode == android.view.KeyEvent.KEYCODE_BACK) {
            if (event.action == android.view.KeyEvent.ACTION_UP) {
                Log.d(TAG, "BACK intercepted — staying in EMO.")
                returnToEmo()
            }
            return true // consume the event
        }
        return super.onKeyEvent(event)
    }

    private fun returnToEmo() {
        try {
            val intent = Intent(this, LauncherActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or
                         Intent.FLAG_ACTIVITY_CLEAR_TOP or
                         Intent.FLAG_ACTIVITY_SINGLE_TOP)
            }
            startActivity(intent)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to return to EMO", e)
        }
    }
}
