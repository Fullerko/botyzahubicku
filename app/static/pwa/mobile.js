(() => {
  'use strict';
  const standalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const button = document.getElementById('bzh-install-button');
  const installed = document.getElementById('bzh-installed');
  const status = document.getElementById('bzh-install-status');
  let promptEvent = null;
  const renderInstall = () => {
    if (button) button.hidden = standalone() || !promptEvent;
    if (installed) installed.hidden = !standalone();
  };
  renderInstall();
  addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); promptEvent = event; renderInstall();
  });
  button?.addEventListener('click', async () => {
    if (!promptEvent) return;
    const event = promptEvent; promptEvent = null; button.disabled = true;
    try {
      await event.prompt();
      const result = await event.userChoice;
      if (status) status.textContent = result.outcome === 'accepted' ? 'Instalace byla potvrzena. Ikonu najdete na ploše telefonu.' : 'Instalaci můžete spustit později z nabídky prohlížeče.';
    } catch { if (status) status.textContent = 'Použijte postup instalace přes nabídku prohlížeče níže.'; }
    finally { button.disabled = false; renderInstall(); }
  });
  addEventListener('appinstalled', () => { promptEvent = null; renderInstall(); });

  // Show the animated splash only on the first launch in this app session.
  // Ordinary account/admin page loads and in-app navigation never add this class.
  const bootSplashStarted = performance.now();
  const finishBootSplash = () => {
    if (!document.documentElement.classList.contains('bzh-boot')) return;
    const minimumVisible = Math.max(0, 700 - (performance.now() - bootSplashStarted));
    setTimeout(() => document.documentElement.classList.remove('bzh-boot'), minimumVisible);
  };
  if (document.readyState === 'complete') finishBootSplash();
  else addEventListener('load', finishBootSplash, {once:true});
  setTimeout(finishBootSplash, 4500);
  let focusLifecycle;
  const initializePage = () => {
    focusLifecycle?.abort();
    focusLifecycle = new AbortController();
  // BZH V7: never let restored browser focus flash the software keyboard.
  // Text controls start readonly and are unlocked synchronously only by a real user tap.
  if (standalone() && /^\/(cart|odmeny|muj-ucet)(?:\/|$)/.test(location.pathname)) {
    const lockable = 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit]):not([type=file]):not([type=range]):not([type=color]), textarea';
    const locked = new Map();
    document.querySelectorAll(lockable).forEach(el => {
      if (el.readOnly || el.disabled) return;
      locked.set(el, {readOnly: el.readOnly, inputMode: el.getAttribute('inputmode')});
      el.readOnly = true;
      el.setAttribute('data-bzh-focus-lock', '1');
      el.setAttribute('inputmode', 'none');
    });
    const unlock = el => {
      const state = locked.get(el);
      if (!state) return;
      el.readOnly = state.readOnly;
      if (state.inputMode === null) el.removeAttribute('inputmode'); else el.setAttribute('inputmode', state.inputMode);
      el.removeAttribute('data-bzh-focus-lock');
      locked.delete(el);
    };
    document.addEventListener('pointerdown', event => {
      const el = event.target.closest?.('[data-bzh-focus-lock]');
      if (el) unlock(el);
    }, {capture:true,signal:focusLifecycle.signal});
    document.addEventListener('keydown', event => {
      const el = event.target.closest?.('[data-bzh-focus-lock]');
      if (el && (event.key === 'Enter' || event.key === ' ')) unlock(el);
    }, {capture:true,signal:focusLifecycle.signal});
  }

  };
  initializePage();
  document.addEventListener('bzh:page', initializePage);
  // BZH V7: bottom navigation feels immediate and always opens sections at the top.
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  const resetKey = 'bzh-nav-reset-scroll';
  const resetScroll = () => {
    try {if (sessionStorage.getItem(resetKey) !== location.pathname) return; sessionStorage.removeItem(resetKey);}catch{return;}
    scrollTo({top: 0, left: 0, behavior: 'instant'});
  };
  resetScroll();
  requestAnimationFrame(resetScroll);
  addEventListener('pageshow', resetScroll);
  document.addEventListener('pointerdown', event => {
    const link=event.target.closest?.('[data-bzh-nav-link]');
    if(!link)return;
    document.querySelectorAll('[data-bzh-nav-link].bzh-nav-pressed').forEach(item=>item.classList.remove('bzh-nav-pressed'));
    link.classList.add('bzh-nav-pressed');
  }, {passive:true});
  document.addEventListener('click', event => {
    const link=event.target.closest?.('[data-bzh-nav-link]');
    if(!link)return;
    try{sessionStorage.setItem(resetKey,new URL(link.href,location.href).pathname);}catch{}
  });

  const connection = document.getElementById('bzh-connection');
  const connectionState = () => { if (connection) connection.hidden = navigator.onLine; };
  addEventListener('online', connectionState); addEventListener('offline', connectionState); connectionState();
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'}).then(registration => {
    const updateBox = document.getElementById('bzh-update');
    const offerUpdate = () => { if (registration.waiting && navigator.serviceWorker.controller && updateBox) updateBox.hidden = false; };
    offerUpdate();
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      worker?.addEventListener('statechange', () => { if (worker.state === 'installed') offerUpdate(); });
    });
    let acceptedUpdate = false;
    document.getElementById('bzh-update-button')?.addEventListener('click', () => {
      if (registration.waiting && confirm('Aktualizace znovu načte stránku. Neuložený formulář bude ztracen. Pokračovat?')) {
        acceptedUpdate = true; registration.waiting.postMessage({type:'ACTIVATE_UPDATE'});
      }
    });
    document.getElementById('bzh-update-dismiss')?.addEventListener('click', () => { updateBox.hidden = true; });
    navigator.serviceWorker.addEventListener('controllerchange', () => { if (acceptedUpdate) location.reload(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) registration.update().catch(() => {}); });
  }).catch(() => { if (status) status.textContent = 'Automatická instalace není dostupná. Zkontrolujte HTTPS a postup níže.'; });
})();
