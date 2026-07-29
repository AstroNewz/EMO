package com.emo.launcher.overlay

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.PixelFormat
import android.os.Build
import android.util.Log
import android.view.Gravity
import android.view.LayoutInflater
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import com.emo.launcher.R

/**
 * TermuxPopupManager — manages the floating Termux terminal overlay window.
 *
 * Uses TYPE_APPLICATION_OVERLAY to display a translucent, semi-transparent terminal
 * over the EMO HUD (via ttyd running on port 7681 or direct web terminal).
 */
class TermuxPopupManager(private val context: Context) {

    companion object {
        private const val TAG = "TermuxPopupManager"
        private const val TTYD_URL = "http://127.0.0.1:7681"
    }

    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var popupView: View? = null
    private var webView: WebView? = null
    var isShowing = false
        private set

    @SuppressLint("ClickableViewAccessibility", "SetJavaScriptEnabled")
    fun show() {
        if (isShowing) return

        try {
            val params = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                (context.resources.displayMetrics.heightPixels * 0.45).toInt(),
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                } else {
                    @Suppress("DEPRECATION")
                    WindowManager.LayoutParams.TYPE_PHONE
                },
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                        WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT
            ).apply {
                gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
                x = 0
                y = 0
            }

            popupView = View.inflate(context, R.layout.overlay_termux_popup, null)
            webView = popupView?.findViewById(R.id.termuxWebView)

            webView?.apply {
                setBackgroundColor(0x00000000)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.cacheMode = WebSettings.LOAD_NO_CACHE
                webViewClient = WebViewClient()
                loadUrl(TTYD_URL)
            }

            // Drag handle to slide/dismiss overlay
            val dragHandle = popupView?.findViewById<View>(R.id.dragHandle)
            var initialY = 0f
            var initialTouchY = 0f

            dragHandle?.setOnTouchListener { _, event ->
                when (event.action) {
                    MotionEvent.ACTION_DOWN -> {
                        initialY = params.y.toFloat()
                        initialTouchY = event.rawY
                        true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        params.y = (initialY - (event.rawY - initialTouchY)).toInt()
                        windowManager.updateViewLayout(popupView, params)
                        true
                    }
                    MotionEvent.ACTION_UP -> {
                        if (event.rawY - initialTouchY > 150) {
                            hide()
                        }
                        true
                    }
                    else -> false
                }
            }

            windowManager.addView(popupView, params)
            isShowing = true
            Log.i(TAG, "Termux popup overlay shown.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to show Termux popup overlay", e)
        }
    }

    fun hide() {
        if (!isShowing || popupView == null) return
        try {
            windowManager.removeView(popupView)
            popupView = null
            webView = null
            isShowing = false
            Log.i(TAG, "Termux popup overlay hidden.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to hide Termux popup overlay", e)
        }
    }

    fun toggle() {
        if (isShowing) hide() else show()
    }
}
