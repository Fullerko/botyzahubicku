(() => {
 'use strict';
 const standalone=matchMedia('(display-mode: standalone)').matches || navigator.standalone===true || !!window.BZH_NATIVE_APP;
 const activation=document.querySelector('[data-reward-activation]');
 if(activation){activation.hidden=!standalone;const hint=document.querySelector('[data-reward-install]');if(hint)hint.hidden=standalone;}
 const qr=document.querySelector('[data-reward-qr]');
 const refreshQR=()=>{if(qr && !document.hidden){const url=new URL(qr.src,location.href);url.searchParams.set('v',Date.now());qr.src=url.href;}};
 document.querySelector('[data-refresh-qr]')?.addEventListener('click',refreshQR);
 if(qr){setInterval(refreshQR,60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshQR();});}
 const amount=document.querySelector('[data-reward-amount]');
 if(amount)amount.addEventListener('input',()=>{
  const raw=amount.value.trim().replace(/ /g,'').replace(',','.');let text='Odměna: 5 %';
  if(/^\d{1,7}(\.\d{1,2})?$/.test(raw)){const [whole,fraction='']=raw.split('.');const cents=Number(whole)*100+Number(fraction.padEnd(2,'0'));const credit=Math.floor((cents*5+50)/100);text='Odměna: '+(credit/100).toLocaleString('cs-CZ',{minimumFractionDigits:2,maximumFractionDigits:2})+' Kč';}
  document.querySelector('[data-reward-preview]').textContent=text;
 });
 const scanner=document.querySelector('[data-reward-scanner]');
 if(!scanner)return;
 const video=scanner.querySelector('[data-scan-video]'),canvas=scanner.querySelector('[data-scan-canvas]'),start=scanner.querySelector('[data-scan-start]'),stop=scanner.querySelector('[data-scan-stop]'),status=scanner.querySelector('[data-scan-status]'),form=scanner.querySelector('[data-scan-form]'),input=scanner.querySelector('[data-scan-code]');
 let stream=null,timer=null,generation=0;
 const stopCamera=()=>{generation++;clearTimeout(timer);if(stream)stream.getTracks().forEach(track=>track.stop());stream=null;video.srcObject=null;video.hidden=true;start.disabled=false;start.hidden=false;stop.hidden=true;};
 const accept=text=>{
  let valid=false;
  try{const url=new URL(text);valid=url.origin===location.origin && url.pathname==='/admin/odmeny/nacist' && url.searchParams.has('t');}catch{valid=/^[0-9A-F]{10}$/i.test(text) || text.startsWith('reward:');}
  if(!valid){status.textContent='Tento QR není zákaznický kód našeho programu.';return false;}
  input.value=text;stopCamera();status.textContent='Kód načten. Otevírám zákazníka…';form.requestSubmit();return true;
 };
 const detect=async()=>{
  if(!stream)return;
  try{
   if(video.readyState>=2 && video.videoWidth){
    const scale=Math.min(1,640/video.videoWidth);canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);
    const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(video,0,0,canvas.width,canvas.height);
    const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);
    const result=window.jsQR(pixels.data,pixels.width,pixels.height,{inversionAttempts:'attemptBoth'});
    if(result && accept(result.data))return;
   }
  }catch{status.textContent='Čtení kamery se nepodařilo. Zadejte zákaznický kód ručně.';stopCamera();return;}
  if(stream)timer=setTimeout(detect,180);
 };
 start.addEventListener('click',async()=>{
  if(!navigator.mediaDevices?.getUserMedia || !window.jsQR){status.textContent='Kamera zde není dostupná. Zadejte zákaznický kód ručně nebo použijte běžnou kameru telefonu.';return;}
  const turn=++generation;start.disabled=true;
  try{
   const next=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'},width:{ideal:1280}},audio:false});
   if(turn!==generation){next.getTracks().forEach(track=>track.stop());return;}
   stream=next;video.srcObject=stream;video.hidden=false;await video.play();
   if(turn!==generation)return;
   start.hidden=true;stop.hidden=false;status.textContent='Namiřte kameru na QR kód v aplikaci zákazníka.';detect();
  }catch(error){stopCamera();status.textContent=error.name==='NotAllowedError'?'Přístup ke kameře nebyl povolen. Povolte jej v nastavení nebo zadejte kód ručně.':'Kameru nelze otevřít. Zadejte zákaznický kód ručně.';}
 });
 stop.addEventListener('click',()=>{stopCamera();status.textContent='Kamera byla zastavena.';});
 addEventListener('pagehide',stopCamera);document.addEventListener('visibilitychange',()=>{if(document.hidden)stopCamera();});
})();
