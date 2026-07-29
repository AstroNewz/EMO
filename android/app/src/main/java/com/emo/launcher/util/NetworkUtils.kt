package com.emo.launcher.util

import java.net.HttpURLConnection
import java.net.URL

/**
 * Localhost connectivity helpers for the watchdog.
 */
object NetworkUtils {

    /**
     * Check if the EMO backend is alive by hitting the health endpoint.
     * Returns true if it responds with HTTP 200 within [timeoutMs].
     * Runs on the caller's thread — always call from a background thread.
     */
    fun isBackendAlive(
        baseUrl: String = "http://127.0.0.1:3000",
        healthPath: String = "/api/health",
        timeoutMs: Int = 2000
    ): Boolean {
        return try {
            val url = URL("$baseUrl$healthPath")
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.requestMethod = "GET"
            conn.instanceFollowRedirects = false
            val code = conn.responseCode
            conn.disconnect()
            code == 200
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Simple GET request that returns the response body as a String,
     * or null on any failure. For fetching JSON from the local backend.
     */
    fun get(url: String, timeoutMs: Int = 3000): String? {
        return try {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.requestMethod = "GET"
            val body = conn.inputStream.bufferedReader().readText()
            conn.disconnect()
            body
        } catch (_: Exception) {
            null
        }
    }
}
