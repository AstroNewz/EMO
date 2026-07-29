/**
 * hud-core.js — Master HUD Controller.
 * Initializes gestures, termux swipe triggers, and global status coordination.
 */
(() => {
  console.log("[EMO HUD] Core system initialized.");

  // ---- SWIPE UP FOR TERMINAL (Gesture Listener) ----
  let startY = 0;
  const terminalHint = document.getElementById('terminal-hint');

  window.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
  }, { passive: true });

  window.addEventListener('touchend', (e) => {
    const endY = e.changedTouches[0].clientY;
    const deltaY = startY - endY;

    // Swipe up threshold > 120px near the bottom
    if (deltaY > 120 && startY > window.innerHeight * 0.7) {
      if (typeof Bridge !== 'undefined' && Bridge.available) {
        Bridge.vibrate(50);
        Bridge.toggleTermuxPopup();
      }
    }
  }, { passive: true });

  if (terminalHint) {
    terminalHint.addEventListener('click', () => {
      if (typeof Bridge !== 'undefined' && Bridge.available) {
        Bridge.vibrate(30);
        Bridge.toggleTermuxPopup();
      }
    });
  }
})();
