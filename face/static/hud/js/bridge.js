/**
 * bridge.js — Wrapper around window.Android.* native bridge calls.
 * Provides safe fallbacks when the bridge is unavailable (browser testing).
 */
const Bridge = (() => {
  const hasNative = typeof Android !== 'undefined';

  function safeCall(fn, fallback) {
    if (!hasNative) return fallback;
    try { return fn(); } catch (_) { return fallback; }
  }

  function safeJsonCall(fn, fallback) {
    if (!hasNative) return fallback;
    try { return JSON.parse(fn()); } catch (_) { return fallback; }
  }

  return {
    available: hasNative,

    // --- System diagnostics ---
    getBattery: () => safeJsonCall(() => Android.getBattery(),
      { level: -1, charging: false, temp: 0, health: 'unknown' }),

    getRAM: () => safeJsonCall(() => Android.getRAM(),
      { used: 0, total: 0, free: 0, percent: 0 }),

    getCPU: () => safeJsonCall(() => Android.getCPU(),
      { usage: 0, cores: 0, freq: [] }),

    getStorage: () => safeJsonCall(() => Android.getStorage(),
      { used: 0, total: 0, free: 0 }),

    getNetwork: () => safeJsonCall(() => Android.getNetwork(),
      { type: 'unknown' }),

    getUptime: () => safeCall(() => Android.getUptime(), 0),

    getDeviceInfo: () => safeJsonCall(() => Android.getDeviceInfo(),
      { model: 'Unknown', brand: 'Unknown' }),

    getTelemetry: () => safeJsonCall(() => Android.getTelemetry(),
      null),

    // --- Device control ---
    vibrate: (ms) => safeCall(() => Android.vibrate(ms)),
    vibratePattern: (pattern) => safeCall(() => Android.vibratePattern(JSON.stringify(pattern))),
    setBrightness: (v) => safeCall(() => Android.setBrightness(v)),
    keepScreenOn: (on) => safeCall(() => Android.keepScreenOn(on)),

    // --- App management ---
    getInstalledApps: () => safeJsonCall(() => Android.getInstalledApps(), []),
    launchApp: (pkg) => safeCall(() => Android.launchApp(pkg), false),

    // --- Termux ---
    termuxRun: (cmd) => safeCall(() => Android.termuxRun(cmd), false),
    termuxIsRunning: () => safeCall(() => Android.termuxIsRunning(), false),
    showTermuxPopup: () => safeCall(() => Android.showTermuxPopup()),
    hideTermuxPopup: () => safeCall(() => Android.hideTermuxPopup()),
    toggleTermuxPopup: () => safeCall(() => Android.toggleTermuxPopup()),

    // --- EMO-specific ---
    getServerStatus: () => safeJsonCall(() => Android.getServerStatus(),
      { live: false, mode: 'unknown' }),
    toast: (msg) => safeCall(() => Android.toast(msg)),
    copyToClipboard: (text) => safeCall(() => Android.copyToClipboard(text)),
    readClipboard: () => safeCall(() => Android.readClipboard(), ''),
    openSettings: (page) => safeCall(() => Android.openSettings(page)),
    getEmoVersion: () => safeCall(() => Android.getEmoVersion(), '1.0.0'),
  };
})();
