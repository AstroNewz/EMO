package com.emo.launcher.services

import android.util.Log

/**
 * WhatsAppAutomation — shared state between EmoBridge and EmoAccessibilityService.
 *
 * When EmoBridge fires a WhatsApp intent, it sets [pendingMessage] so the
 * Accessibility Service knows to auto-tap the Send button once WhatsApp loads.
 */
object WhatsAppAutomation {

    private const val TAG = "EMO-WA"

    /** The message waiting to be auto-sent. Null when no automation is pending. */
    @Volatile
    var pendingMessage: String? = null
        private set

    /** The target contact name for UI feedback. */
    @Volatile
    var pendingContact: String? = null
        private set

    /** Timestamp when the pending send was registered (for timeout safety). */
    @Volatile
    private var pendingAt: Long = 0L

    /** Max time (ms) we'll wait for WhatsApp to appear before giving up. */
    private const val TIMEOUT_MS = 15_000L

    /**
     * Register a pending WhatsApp auto-send.
     * Called by EmoBridge just before firing the WhatsApp intent.
     */
    fun register(message: String, contact: String) {
        pendingMessage = message
        pendingContact = contact
        pendingAt = System.currentTimeMillis()
        Log.i(TAG, "Pending send registered for '$contact': $message")
    }

    /**
     * Called by EmoAccessibilityService after it successfully taps Send,
     * or if the operation times out / fails.
     */
    fun clear() {
        val contact = pendingContact
        pendingMessage = null
        pendingContact = null
        pendingAt = 0L
        Log.i(TAG, "Pending send cleared (contact=$contact)")
    }

    /** Returns true if a pending send exists and hasn't timed out. */
    fun isActive(): Boolean {
        val msg = pendingMessage ?: return false
        if (System.currentTimeMillis() - pendingAt > TIMEOUT_MS) {
            Log.w(TAG, "Pending send timed out — clearing.")
            clear()
            return false
        }
        return true
    }
}
