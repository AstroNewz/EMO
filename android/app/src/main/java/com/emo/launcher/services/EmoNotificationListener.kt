package com.emo.launcher.services

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

/**
 * EmoNotificationListener — mirrors phone notifications into the HUD.
 *
 * Reads incoming notifications from all apps and stores them so the
 * Web HUD can display them (via the EmoBridge or a backend API).
 * The user must grant notification access in Settings.
 */
class EmoNotificationListener : NotificationListenerService() {

    companion object {
        private const val TAG = "EMO-Notifications"
        private const val MAX_STORED = 50

        /** Current notifications, readable by the bridge. */
        val notifications = mutableListOf<JSONObject>()
        private val lock = Any()

        fun getNotificationsJson(): String {
            synchronized(lock) {
                return JSONArray(notifications).toString()
            }
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        sbn ?: return
        try {
            val notification = sbn.notification
            val extras = notification.extras
            val entry = JSONObject().apply {
                put("id", sbn.id)
                put("key", sbn.key)
                put("package", sbn.packageName)
                put("title", extras.getCharSequence("android.title")?.toString() ?: "")
                put("text", extras.getCharSequence("android.text")?.toString() ?: "")
                put("time", sbn.postTime)
                put("ongoing", sbn.isOngoing)
            }

            synchronized(lock) {
                // Remove duplicate by key
                notifications.removeAll { it.optString("key") == sbn.key }
                notifications.add(0, entry)
                // Trim old notifications
                while (notifications.size > MAX_STORED) {
                    notifications.removeAt(notifications.lastIndex)
                }
            }

            Log.d(TAG, "Notification: ${sbn.packageName} — ${entry.optString("title")}")
        } catch (e: Exception) {
            Log.e(TAG, "Error processing notification", e)
        }
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        sbn ?: return
        synchronized(lock) {
            notifications.removeAll { it.optString("key") == sbn.key }
        }
    }
}
