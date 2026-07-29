/**
 * globe.js — Wireframe Earth globe rendered on canvas.
 * Zero dependencies. Uses procedural wireframe sphere with depth shading.
 */
(() => {
  const canvas = document.getElementById('globe-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, cx, cy, radius;
  let rotation = 0;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.parentElement.getBoundingClientRect();
    W = rect.width; H = rect.height;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx = W / 2; cy = H / 2;
    radius = Math.min(W, H) * 0.34;
  }
  resize();
  window.addEventListener('resize', resize);

  // Convert spherical to 2D with simple perspective
  function project(latDeg, lonDeg) {
    const lat = latDeg * Math.PI / 180;
    const lon = (lonDeg + rotation) * Math.PI / 180;
    const x = radius * Math.cos(lat) * Math.cos(lon);
    const z = radius * Math.cos(lat) * Math.sin(lon);
    const y = radius * Math.sin(lat);
    const perspScale = 1 + z / (radius * 3.5);
    return {
      x: cx + x * perspScale,
      y: cy - y * perspScale,
      z: z,
      depth: (z + radius) / (2 * radius) // 0 = back, 1 = front
    };
  }

  function getAccentRgb() {
    return getComputedStyle(document.body).getPropertyValue('--accent-rgb').trim() || '0, 255, 209';
  }

  function drawGlobe() {
    ctx.clearRect(0, 0, W, H);
    const rgb = getAccentRgb();

    // Atmosphere glow
    const glow = ctx.createRadialGradient(cx, cy, radius * 0.8, cx, cy, radius * 1.3);
    glow.addColorStop(0, `rgba(${rgb}, 0.03)`);
    glow.addColorStop(1, 'transparent');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 1.3, 0, Math.PI * 2);
    ctx.fill();

    // --- LATITUDE LINES ---
    for (let lat = -75; lat <= 75; lat += 15) {
      const pts = [];
      for (let lon = 0; lon <= 360; lon += 3) {
        pts.push(project(lat, lon));
      }
      ctx.beginPath();
      for (let i = 0; i < pts.length; i++) {
        const alpha = 0.04 + pts[i].depth * 0.18;
        ctx.strokeStyle = `rgba(${rgb}, ${alpha})`;
        if (i === 0) ctx.moveTo(pts[i].x, pts[i].y);
        else ctx.lineTo(pts[i].x, pts[i].y);
      }
      ctx.lineWidth = lat === 0 ? 1.2 : 0.6;
      ctx.stroke();
    }

    // --- LONGITUDE LINES ---
    for (let lon = 0; lon < 360; lon += 15) {
      const pts = [];
      for (let lat = -90; lat <= 90; lat += 3) {
        pts.push(project(lat, lon));
      }
      for (let i = 1; i < pts.length; i++) {
        const alpha = 0.04 + pts[i].depth * 0.2;
        ctx.strokeStyle = `rgba(${rgb}, ${alpha})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        ctx.moveTo(pts[i - 1].x, pts[i - 1].y);
        ctx.lineTo(pts[i].x, pts[i].y);
        ctx.stroke();
      }
    }

    // --- EQUATOR HIGHLIGHT ---
    ctx.strokeStyle = `rgba(${rgb}, 0.35)`;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    const eqPts = [];
    for (let lon = 0; lon <= 360; lon += 2) {
      eqPts.push(project(0, lon));
    }
    for (let i = 0; i < eqPts.length; i++) {
      if (i === 0) ctx.moveTo(eqPts[i].x, eqPts[i].y);
      else ctx.lineTo(eqPts[i].x, eqPts[i].y);
    }
    ctx.stroke();

    // --- POLAR DOTS ---
    const north = project(90, 0);
    const south = project(-90, 0);
    ctx.fillStyle = `rgba(${rgb}, 0.5)`;
    ctx.beginPath();
    ctx.arc(north.x, north.y, 2.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(south.x, south.y, 2.5, 0, Math.PI * 2);
    ctx.fill();

    // --- ORBIT RING ---
    ctx.strokeStyle = `rgba(${rgb}, 0.08)`;
    ctx.lineWidth = 0.8;
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.ellipse(cx, cy, radius * 1.4, radius * 0.15, -0.2, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    // Orbiting dot
    const orbitAngle = rotation * 0.008;
    const ox = cx + radius * 1.4 * Math.cos(orbitAngle);
    const oy = cy + radius * 0.15 * Math.sin(orbitAngle) * Math.cos(-0.2);
    ctx.fillStyle = `rgba(${rgb}, 0.6)`;
    ctx.beginPath();
    ctx.arc(ox, oy, 2, 0, Math.PI * 2);
    ctx.fill();
  }

  function animate() {
    rotation += 0.12;
    drawGlobe();
    requestAnimationFrame(animate);
  }
  animate();
})();
