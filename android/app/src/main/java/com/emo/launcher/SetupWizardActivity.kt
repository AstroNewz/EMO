package com.emo.launcher

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import com.emo.launcher.services.EmoAccessibilityService

/**
 * SetupWizardActivity — walks the user through granting permissions.
 *
 * Five steps:
 *   1. Set EMO as default home screen
 *   2. Grant overlay permission (draw over other apps)
 *   3. Enable EMO Accessibility Service
 *   4. Disable battery optimization for EMO + Termux
 *   5. Grant notification access (optional)
 *
 * Each step: explains WHY, shows granted/not-granted status, and
 * deep-links to the relevant Android Settings page.
 */
class SetupWizardActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "EMO-Setup"
        private const val PREFS = "emo_setup"
        private const val KEY_COMPLETED = "setup_completed"

        fun isSetupCompleted(context: Context): Boolean {
            return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(KEY_COMPLETED, false)
        }
    }

    private var currentStep = 0
    private val totalSteps = 5

    private lateinit var stepIndicator: TextView
    private lateinit var stepTitle: TextView
    private lateinit var stepDescription: TextView
    private lateinit var stepStatus: TextView
    private lateinit var btnGrant: Button
    private lateinit var btnSkip: Button
    private val dots = mutableListOf<View>()

    data class Step(
        val title: String,
        val description: String,
        val checkGranted: () -> Boolean,
        val grantAction: () -> Unit
    )

    private val steps by lazy {
        listOf(
            Step(
                "Set EMO as Home Screen",
                "EMO needs to be your default launcher so pressing Home always returns to the terminal.",
                ::isDefaultHome,
                ::requestDefaultHome
            ),
            Step(
                "Overlay Permission",
                "Allow EMO to draw over other apps. This enables the floating Termux terminal popup.",
                { Settings.canDrawOverlays(this) },
                {
                    startActivity(Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:$packageName")
                    ))
                }
            ),
            Step(
                "Enable Accessibility",
                "EMO intercepts Back and Recents buttons so the phone stays in terminal mode. This is the core of full device control.",
                { EmoAccessibilityService.isActive },
                {
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                }
            ),
            Step(
                "Disable Battery Optimization",
                "Prevent Android from killing EMO and Termux in the background. Critical on Vivo/MIUI/ColorOS devices.",
                ::isBatteryOptimizationDisabled,
                ::requestBatteryOptimization
            ),
            Step(
                "Notification Access",
                "Let EMO read your notifications and display them in the HUD. You'll see calls, messages, and alerts inside the terminal.",
                ::isNotificationListenerEnabled,
                {
                    startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                }
            )
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_setup)

        stepIndicator = findViewById(R.id.stepIndicator)
        stepTitle = findViewById(R.id.stepTitle)
        stepDescription = findViewById(R.id.stepDescription)
        stepStatus = findViewById(R.id.stepStatus)
        btnGrant = findViewById(R.id.btnGrant)
        btnSkip = findViewById(R.id.btnSkip)

        dots.add(findViewById(R.id.dot1))
        dots.add(findViewById(R.id.dot2))
        dots.add(findViewById(R.id.dot3))
        dots.add(findViewById(R.id.dot4))
        dots.add(findViewById(R.id.dot5))

        btnGrant.setOnClickListener {
            if (currentStep < totalSteps) {
                steps[currentStep].grantAction()
            }
        }

        btnSkip.setOnClickListener {
            nextStep()
        }

        updateUI()
    }

    override fun onResume() {
        super.onResume()
        // Refresh status after returning from Settings
        updateUI()
    }

    private fun nextStep() {
        currentStep++
        if (currentStep >= totalSteps) {
            completeSetup()
        } else {
            updateUI()
        }
    }

    private fun updateUI() {
        if (currentStep >= totalSteps) {
            completeSetup()
            return
        }

        val step = steps[currentStep]
        val granted = step.checkGranted()

        stepIndicator.text = "STEP ${currentStep + 1} / $totalSteps"
        stepTitle.text = step.title
        stepDescription.text = step.description

        if (granted) {
            stepStatus.text = "● GRANTED"
            stepStatus.setTextColor(0xFF00FFD1.toInt())
            btnGrant.text = "NEXT"
            btnGrant.setOnClickListener { nextStep() }
        } else {
            stepStatus.text = "● NOT GRANTED"
            stepStatus.setTextColor(0xFFFF4444.toInt())
            btnGrant.text = "GRANT"
            btnGrant.setOnClickListener { step.grantAction() }
        }

        // Update progress dots
        for (i in dots.indices) {
            dots[i].setBackgroundColor(
                if (i <= currentStep) 0xFF00FFD1.toInt() else 0xFF333333.toInt()
            )
        }
    }

    private fun completeSetup() {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_COMPLETED, true)
            .apply()

        Log.i(TAG, "Setup wizard completed.")

        // Return to the launcher
        val intent = Intent(this, LauncherActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        startActivity(intent)
        finish()
    }

    // =====================================================================
    // Permission checks
    // =====================================================================

    private fun isDefaultHome(): Boolean {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_HOME)
        val resolveInfo = packageManager.resolveActivity(intent, 0)
        return resolveInfo?.activityInfo?.packageName == packageName
    }

    private fun requestDefaultHome() {
        // Android's "choose default home" dialog
        val intent = Intent(Intent.ACTION_MAIN).apply {
            addCategory(Intent.CATEGORY_HOME)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        startActivity(intent)
    }

    private fun isBatteryOptimizationDisabled(): Boolean {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    @android.annotation.SuppressLint("BatteryLife")
    private fun requestBatteryOptimization() {
        try {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:$packageName")
            }
            startActivity(intent)
        } catch (_: Exception) {
            // Fallback: open the full battery optimization list
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
    }

    private fun isNotificationListenerEnabled(): Boolean {
        val cn = ComponentName(this, "com.emo.launcher.services.EmoNotificationListener")
        val enabledListeners = Settings.Secure.getString(
            contentResolver,
            "enabled_notification_listeners"
        ) ?: ""
        return enabledListeners.contains(cn.flattenToString())
    }
}
