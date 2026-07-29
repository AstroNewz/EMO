/**
 * telemetry.js — Real-time system telemetry updates.
 * Pulls data from both the native bridge AND the backend API,
 * merging the best of both sources.
 */
(() => {
  const BRIDGE_INTERVAL = 2000;   // Native bridge refresh (battery, RAM, CPU)
  const BACKEND_INTERVAL = 4000;  // Backend API refresh (weather, AI status)

  // ---- CLOCK ----
  function updateClock() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const el = document.getElementById('clock');
    if (el) el.textContent = `${h}:${m}`;
  }
  updateClock();
  setInterval(updateClock, 1000);

  // ---- BRIDGE TELEMETRY (works offline too) ----
  function updateFromBridge() {
    // Battery
    const bat = Bridge.getBattery();
    if (bat.level >= 0) {
      const batBadge = document.getElementById('bat-badge');
      if (batBadge) batBadge.textContent = `${bat.charging ? '⚡' : '🔋'} ${bat.level}%`;
    }

    // RAM
    const ram = Bridge.getRAM();
    if (ram.total > 0) {
      const usedGB = (ram.used / 1024).toFixed(1);
      const totalGB = (ram.total / 1024).toFixed(0);
      const ramVal = document.getElementById('ram-val');
      if (ramVal) ramVal.innerHTML = `${usedGB}<span class="unit">/${totalGB}G</span>`;
      const ramFill = document.getElementById('ram-fill');
      if (ramFill) ramFill.style.width = `${ram.percent}%`;
    }

    // CPU
    const cpu = Bridge.getCPU();
    if (cpu.cores > 0) {
      const cpuVal = document.getElementById('cpu-val');
      if (cpuVal) cpuVal.innerHTML = `${cpu.usage}<span class="unit">%</span>`;
      const cpuFill = document.getElementById('cpu-fill');
      if (cpuFill) cpuFill.style.width = `${cpu.usage}%`;
    }

    // Storage
    const stor = Bridge.getStorage();
    if (stor.total > 0) {
      const usedGB = (stor.used / 1024).toFixed(0);
      const totalGB = (stor.total / 1024).toFixed(0);
      const pct = Math.round((stor.used / stor.total) * 100);
      const storVal = document.getElementById('stor-val');
      if (storVal) storVal.innerHTML = `${usedGB}<span class="unit">/${totalGB}G</span>`;
      const storFill = document.getElementById('stor-fill');
      if (storFill) storFill.style.width = `${pct}%`;
    }

    // Uptime
    const secs = Bridge.getUptime();
    if (secs > 0) {
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const upVal = document.getElementById('up-val');
      if (upVal) upVal.innerHTML = `${h}<span class="unit">h</span>${m}<span class="unit">m</span>`;
    }

    // Network badge
    const net = Bridge.getNetwork();
    const netBadge = document.getElementById('net-badge');
    if (netBadge) {
      const icon = net.type === 'wifi' ? '📶' : net.type === 'mobile' ? '📱' : '—';
      netBadge.textContent = icon;
    }
  }

  // ---- BACKEND TELEMETRY (live mode only) ----
  function updateFromBackend() {
    // AI tier
    fetch('/api/ai/status')
      .then(r => r.json())
      .then(data => {
        const el = document.getElementById('ai-tier');
        if (el) {
          const model = (data.model || '').split('/').pop().split(':')[0];
          el.textContent = `${(data.tier || '?').toUpperCase()} · ${model || '?'}`;
        }
      })
      .catch(() => {});

    // Backend telemetry (weather, state, emotion sync)
    let lastState = '';
    fetch('/api/telemetry')
      .then(r => r.json())
      .then(data => {
        const dot = document.getElementById('status-dot');
        if (dot) {
          dot.classList.remove('offline');
          dot.title = `Backend up ${data.uptime || 0}s`;
        }

        // Dynamically update background glow & character mood class
        if (data.state && data.state !== lastState) {
          lastState = data.state;
          document.body.className = `mood-${data.state}`;

          // Trigger native haptic feedback for emotional reactions
          if (typeof Bridge !== 'undefined' && Bridge.available) {
            if (data.state === 'happy' || data.state === 'excited') {
              Bridge.vibratePattern([0, 40, 60, 40]);
            } else if (data.state === 'surprised') {
              Bridge.vibratePattern([0, 120]);
            } else if (data.state === 'angry') {
              Bridge.vibratePattern([0, 200]);
            } else if (data.state === 'confused' || data.state === 'curious') {
              Bridge.vibratePattern([0, 80]);
            }
          }
        }
      })
      .catch(() => {
        const dot = document.getElementById('status-dot');
        if (dot) dot.classList.add('offline');
      });
  }

  // Initial + periodic
  setTimeout(updateFromBridge, 300);
  setInterval(updateFromBridge, BRIDGE_INTERVAL);

  setTimeout(updateFromBackend, 1000);
  setInterval(updateFromBackend, BACKEND_INTERVAL);
})();
