(() => {
  'use strict';
  const panels = [...document.querySelectorAll('[data-push-panel]')];
  const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const setStatus = text => panels.forEach(panel => { panel.querySelector('[data-push-status]').textContent = text; });
  const showEnabled = enabled => panels.forEach(panel => {
    panel.querySelector('[data-push-enable]').hidden = enabled;
    panel.querySelector('[data-push-disable]').hidden = !enabled;
  });
  const setBusy = busy => panels.forEach(panel => panel.querySelectorAll('button').forEach(button => { button.disabled = busy; }));
  const decodeKey = key => Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/') + '='.repeat((4-key.length%4)%4)), char => char.charCodeAt(0));
  let config, registration;
  const post = async (url, payload) => {
    const response = await fetch(url, {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf}, body:JSON.stringify(payload || {})});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw Error(data.error || 'Obnovte stránku a zkuste to znovu.'); }
    return response.json();
  };
  if (panels.length) {
    if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      setStatus(isIOS ? 'Na iPhonu otevřete aplikaci z plochy; oznámení vyžadují iOS 16.4 nebo novější.' : 'Tento prohlížeč oznámení nepodporuje. Použijte aktuální Chrome, Firefox nebo Safari.');
    } else if (isIOS && !isStandalone()) {
      setStatus('Na iPhonu nejdřív přidejte aplikaci na plochu přes Safari a otevřete její ikonu.');
    } else {
      Promise.all([fetch('/api/mobile/push-config', {cache:'no-store',credentials:'same-origin'}).then(response => { if (!response.ok) throw Error(); return response.json(); }), navigator.serviceWorker.ready]).then(async ([data, reg]) => {
        config=data; registration=reg;
        const version=await new Promise(resolve=>{
          const channel=new MessageChannel();
          const timer=setTimeout(()=>resolve(null),1500);
          channel.port1.onmessage=event=>{clearTimeout(timer);resolve(event.data);};
          reg.active?.postMessage({type:'MOBILE_VERSION'},[channel.port2]);
        });
        if(version !== 'bzh-mobile-v6') {setStatus('Nejdřív aktualizujte aplikaci tlačítkem „Aktualizovat“ v oznámení nové verze a znovu otevřete tuto stránku.'); return;}

        const existing=await registration.pushManager.getSubscription();
        if (existing && Notification.permission === 'granted' && !config.optedOut) {
          await post('/api/mobile/push-subscribe', existing.toJSON());
          showEnabled(true); setStatus('Oznámení jsou zapnutá pro toto zařízení.');
        } else {
          showEnabled(false);
          setStatus(Notification.permission === 'denied' ? 'Oznámení jsou blokovaná. Povolte je v nastavení telefonu nebo prohlížeče a obnovte stránku.' : 'Oznámení zapnete tlačítkem výše.');
        }
        setBusy(false);
      }).catch(() => setStatus('Nastavení se nepodařilo načíst. Připojte se k internetu a obnovte stránku.'));
      panels.forEach(panel => {
        panel.querySelector('[data-push-enable]').addEventListener('click', () => {
          if (!config || !registration) return;
          if (Notification.permission === 'denied') { setStatus('Povolte oznámení v nastavení telefonu nebo prohlížeče a obnovte stránku.'); return; }
          // Call subscribe immediately in the click handler; Safari requires a user gesture.
          const subscribing=registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:decodeKey(config.publicKey)});
          setBusy(true);
          subscribing.then(subscription => post('/api/mobile/push-subscribe',subscription.toJSON())).then(() => { showEnabled(true); setStatus('Hotovo. Oznámení jsou zapnutá pro toto zařízení.'); }).catch(error => { setStatus(error.name === 'NotAllowedError' ? 'Oznámení nebyla povolena. Můžete je později zapnout v nastavení.' : (error.message || 'Povolení oznámení se nepodařilo uložit.')); }).finally(() => setBusy(false));
        });
        panel.querySelector('[data-push-disable]').addEventListener('click', async () => {
          if (!config || !registration) return;
          setBusy(true);
          try {
            // Remove server-side consent first, so a browser failure cannot keep sending.
            await post('/api/mobile/push-unsubscribe');
            const subscription=await registration.pushManager.getSubscription();
            if (subscription) await subscription.unsubscribe();
            showEnabled(false); setStatus('Oznámení jsou vypnutá pro toto zařízení.');
          } catch (error) { setStatus(error.message || 'Odhlášení se nepodařilo. Zkuste znovu.'); }
          finally { setBusy(false); }
        });
      });
    }
  }
  const campaign=document.getElementById('bzh-campaign');
  if (campaign) {
    let running=false;
    const start=document.getElementById('bzh-send-campaign'), stop=document.getElementById('bzh-stop-campaign'), status=document.getElementById('bzh-campaign-status');
    stop.addEventListener('click',()=>{running=false; status.textContent='Pozastavuji po dokončení aktuální dávky…';});
    start.addEventListener('click',async()=>{
      if (running) return;
      running=true; start.disabled=true; stop.hidden=false;
      let finished=false;
      try {
        while (running) {
          status.textContent='Odesílám oznámení. Nechte stránku otevřenou…';
          const response=await fetch(campaign.dataset.batchUrl,{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':campaign.dataset.csrf}});
          if (!response.ok) throw Error('Odesílání se přerušilo. Obnovte stránku a pokračujte.');
          const counts=await response.json();
          for (const [key,value] of Object.entries(counts)) { const el=campaign.querySelector('[data-count="'+key+'"]'); if(el) el.textContent=value; }
          if (!counts.pending && !counts.sending) {finished=true;break;}
          await new Promise(resolve=>setTimeout(resolve,counts.sending && !counts.pending ? 3000 : 150));
        }
        status.textContent=finished ? 'Zpracování dokončeno. Výsledky jsou uvedené výše.' : 'Odesílání je pozastavené. Můžete pokračovat.';
      } catch(error) {status.textContent=error.message;}
      finally {running=false;start.disabled=finished;stop.hidden=true;}
    });
  }
})();