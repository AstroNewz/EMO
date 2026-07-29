# EMO Launcher ProGuard rules
-keepattributes JavascriptInterface
-keepclassmembers class com.emo.launcher.bridge.EmoBridge {
    @android.webkit.JavascriptInterface <methods>;
}
# Keep accessibility service metadata
-keep class com.emo.launcher.services.EmoAccessibilityService
