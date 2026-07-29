package com.emo.launcher.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.emo.launcher.LauncherActivity
import com.emo.launcher.services.WatchdogService

/**
 * BootReceiver — auto-starts EMO and Termux when the phone powers on.
 *
 * Sequence:
 *   1. Phone boots → Android fires BOOT_COMPLETED
 *   2. BootReceiver starts the WatchdogService (foreground)
 *   3. BootReceiver launches LauncherActivity (since EMO is the HOME app,
 *      this is redundant but ensures it's up even if the HOME intent is delayed)
 *   4. BootReceiver fires a RUN_COMMAND intent to Termux to start run.sh
 *
 * The watchdog will initially load the offline HUD (instant), then
 * switch to the live HUD once the Termux backend comes up.
 */
class BootReceiver : BroadcastReceiver() {

    companion object {
        private const val TAG = "EMO-Boot"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action != Intent.ACTION_BOOT_COMPLETED &&
            action != "android.intent.action.QUICKBOOT_POWERON" &&
            action != "com.htc.intent.action.QUICKBOOT_POWERON"
        ) return

        Log.i(TAG, "Boot completed — starting EMO.")

        // 1. Start the watchdog foreground service
        try {
            val serviceIntent = Intent(context, WatchdogService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent)
            } else {
                context.startService(serviceIntent)
            }
            Log.i(TAG, "Watchdog service started.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start watchdog", e)
        }

        // 2. Launch EMO (in case HOME intent is slow)
        try {
            val launcherIntent = Intent(context, LauncherActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            }
            context.startActivity(launcherIntent)
            Log.i(TAG, "Launcher activity started.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start launcher", e)
        }

        // 3. Start Termux and run EMO backend (with a delay)
        try {
            // Launch Termux app first
            val termuxIntent = context.packageManager.getLaunchIntentForPackage("com.termux")
            if (termuxIntent != null) {
                termuxIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                context.startActivity(termuxIntent)
                Log.i(TAG, "Termux app launched.")
            }

            // Send the RUN_COMMAND after a delay (Termux needs time to initialize)
            Thread {
                Thread.sleep(5000) // Wait 5s for Termux to fully boot
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
                    context.startService(runIntent)
                    Log.i(TAG, "EMO backend (run.sh) started in Termux.")
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to start run.sh in Termux", e)
                }
            }.start()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to launch Termux", e)
        }
    }
}
