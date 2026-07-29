/**
 * app-drawer.js — Interactive App Drawer for the Web HUD.
 * Fetches installed apps from the native bridge and renders an interactive app launcher grid.
 */
(() => {
  const toggleBtn = document.getElementById('drawer-toggle');
  const appGrid = document.getElementById('app-grid');

  if (!toggleBtn || !appGrid) return;

  let isOpen = false;
  let appsLoaded = false;

  toggleBtn.addEventListener('click', () => {
    isOpen = !isOpen;
    toggleBtn.classList.toggle('open', isOpen);
    appGrid.classList.toggle('open', isOpen);

    if (isOpen && !appsLoaded) {
      loadApps();
    }
  });

  function loadApps() {
    if (typeof Bridge === 'undefined' || !Bridge.available) {
      renderDefaultApps();
      return;
    }

    const apps = Bridge.getInstalledApps();
    if (apps && apps.length > 0) {
      renderApps(apps);
      appsLoaded = true;
    } else {
      renderDefaultApps();
    }
  }

  function renderApps(apps) {
    appGrid.innerHTML = '';
    // Show top 8-12 apps or all when expanded
    apps.slice(0, 12).forEach(app => {
      const tile = document.createElement('div');
      tile.className = 'app-tile';
      
      // Default icon placeholder (can be enhanced with base64 icons)
      const iconChar = app.name ? app.name.charAt(0).toUpperCase() : '📱';
      
      tile.innerHTML = `
        <div class="app-icon">${iconChar}</div>
        <div class="app-name">${app.name}</div>
      `;

      tile.addEventListener('click', () => {
        Bridge.vibrate(40);
        Bridge.launchApp(app.package);
      });

      appGrid.appendChild(tile);
    });
  }

  function renderDefaultApps() {
    const defaults = [
      { name: 'Chrome', pkg: 'com.android.chrome', icon: '🌐' },
      { name: 'YouTube', pkg: 'com.google.android.youtube', icon: '📺' },
      { name: 'Camera', pkg: 'com.android.camera', icon: '📷' },
      { name: 'Settings', pkg: 'com.android.settings', icon: '⚙' },
      { name: 'Termux', pkg: 'com.termux', icon: '💻' },
      { name: 'Files', pkg: 'com.google.android.documentsui', icon: '📁' }
    ];

    appGrid.innerHTML = '';
    defaults.forEach(app => {
      const tile = document.createElement('div');
      tile.className = 'app-tile';
      tile.innerHTML = `
        <div class="app-icon">${app.icon}</div>
        <div class="app-name">${app.name}</div>
      `;

      tile.addEventListener('click', () => {
        if (typeof Bridge !== 'undefined') {
          Bridge.vibrate(40);
          if (app.pkg === 'com.android.settings') {
            Bridge.openSettings('settings');
          } else {
            Bridge.launchApp(app.pkg);
          }
        }
      });

      appGrid.appendChild(tile);
    });
  }
})();
