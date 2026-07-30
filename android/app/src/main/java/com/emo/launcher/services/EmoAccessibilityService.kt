package com.emo.launcher.services

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.emo.launcher.LauncherActivity

/**
 * EmoAccessibilityService — intercepts system navigation to keep the user in EMO
 * AND auto-sends WhatsApp messages on Boss's behalf.
 *
 * When enabled, this service:
 *   1. Captures the BACK button → returns to EMO instead of exiting
 *   2. Captures the RECENTS button → returns to EMO (stays in terminal mode)
 *   3. When WhatsAppAutomation is active, auto-taps the WhatsApp Send button
 *
 * The user must manually enable this in Settings → Accessibility → EMO.
 */
class EmoAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "EMO-Accessibility"

        /** Whether the service is currently running — checked by the setup wizard. */
        @Volatile
        var isActive: Boolean = false
            private set
    }

    private val handler = Handler(Looper.getMainLooper())

    override fun onServiceConnected() {
        super.onServiceConnected()
        isActive = true

        serviceInfo = serviceInfo.apply {
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
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED,
            AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED -> {
                val pkg = event.packageName?.toString() ?: return

                // ── WhatsApp auto-send ────────────────────────────────────
                if (pkg == "com.whatsapp" && WhatsAppAutomation.isActive()) {
                    // Delay slightly to let the send button fully render
                    handler.postDelayed({ tryTapWhatsAppSend() }, 800)
                }

                // ── Recents screen intercept ──────────────────────────────
                val cls = event.className?.toString() ?: ""
                if (pkg == "com.android.systemui" &&
                    (cls.contains("RecentsActivity") || cls.contains("Recents"))
                ) {
                    Log.d(TAG, "Recents detected — returning to EMO.")
                    returnToEmo()
                }

                // ── External launcher intercept ───────────────────────────
                if (cls.contains("Launcher") && pkg != "com.emo.launcher") {
                    Log.d(TAG, "External launcher detected ($pkg) — returning to EMO.")
                    returnToEmo()
                }
            }
        }
    }

    /**
     * Traverse the WhatsApp window tree and tap the Send button.
     * WhatsApp's send button has content-desc "Send" or class ImageButton
     * in the input toolbar.
     */
    private fun tryTapWhatsAppSend() {
        if (!WhatsAppAutomation.isActive()) return

        val root = rootInActiveWindow ?: run {
            Log.w(TAG, "tryTapWhatsAppSend: rootInActiveWindow is null")
            return
        }

        val sendButton = findSendButton(root)
        if (sendButton != null) {
            val clicked = sendButton.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            Log.i(TAG, "WhatsApp Send tapped (success=$clicked) for '${WhatsAppAutomation.pendingContact}'")
            WhatsAppAutomation.clear()

            // Return to EMO after a short pause so the send completes
            handler.postDelayed({ returnToEmo() }, 600)
        } else {
            Log.w(TAG, "Send button not found yet — will retry on next event.")
        }

        root.recycle()
    }

    /**
     * Recursively search the accessibility node tree for WhatsApp's send button.
     * Tries multiple identification strategies for resilience across WA versions.
     */
    private fun findSendButton(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        // Strategy 1: content-description == "Send"
        val byDesc = node.findAccessibilityNodeInfosByText("Send")
        for (n in byDesc) {
            if (n.isClickable && n.isEnabled) {
                Log.d(TAG, "Found send button by text 'Send'")
                return n
            }
        }

        // Strategy 2: recurse looking for ImageButton that's clickable in WA's entry bar
        return findClickableImageButton(node, depth = 0)
    }

    private fun findClickableImageButton(node: AccessibilityNodeInfo, depth: Int): AccessibilityNodeInfo? {
        if (depth > 12) return null
        val cls = node.className?.toString() ?: ""
        val desc = node.contentDescription?.toString()?.lowercase() ?: ""
        if (node.isClickable && node.isEnabled &&
            (cls == "android.widget.ImageButton" || desc == "send")
        ) {
            return node
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findClickableImageButton(child, depth + 1)
            if (found != null) return found
            child.recycle()
        }
        return null
    }

    override fun onInterrupt() {
        Log.w(TAG, "Accessibility service interrupted.")
    }

    override fun onDestroy() {
        isActive = false
        WhatsAppAutomation.clear()
        Log.i(TAG, "Accessibility service destroyed.")
        super.onDestroy()
    }

    /**
     * Intercept the global BACK action. Return true to consume it (stay in EMO).
     */
    override fun onKeyEvent(event: android.view.KeyEvent?): Boolean {
        if (event?.keyCode == android.view.KeyEvent.KEYCODE_BACK) {
            if (event.action == android.view.KeyEvent.ACTION_UP) {
                // Don't intercept Back while WhatsApp auto-send is in progress
                if (!WhatsAppAutomation.isActive()) {
                    Log.d(TAG, "BACK intercepted — staying in EMO.")
                    returnToEmo()
                }
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
