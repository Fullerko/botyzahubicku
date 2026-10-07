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
