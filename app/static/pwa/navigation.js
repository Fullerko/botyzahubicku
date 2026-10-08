/* Live, same-origin navigation. No HTML, accounts, cart or QR data are cached. */
(() => {
  'use strict';
  const routes = new Set(['/', '/produkty', '/kalendar', '/cart', '/odmeny']);
  let active = null;
  let turn = 0;
  const supported = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true || matchMedia('(max-width: 767px)').matches;
  const clearBusy = () => {
    document.documentElement.classList.remove('bzh-navigating');
    document.querySelector('main')?.removeAttribute('aria-busy');
    document.querySelectorAll('[data-bzh-nav-link]').forEach(link => link.classList.remove('bzh-nav-pressed'));
  };
  const navigate = async (url, push = true) => {
    active?.abort();
    active = new AbortController();
    const controller = active;
    const signal = controller.signal;
    const ticket = ++turn;
    document.documentElement.classList.add('bzh-navigating');
    document.querySelector('main')?.setAttribute('aria-busy', 'true');
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url.href, {credentials: 'same-origin', cache: 'no-store', signal, headers: {'X-BZH-Navigation': '1'}});
      if (!response.ok || response.redirected || !response.headers.get('Content-Type')?.includes('text/html')) throw Error('full-navigation');
      const html = await response.text();
      if (ticket !== turn) return;
      const page = new DOMParser().parseFromString(html, 'text/html');
      const main = page.querySelector('main');
      const navbar = page.querySelector('body > nav.navbar');
      const bottom = page.querySelector('[data-bzh-nav]');
      if (!main || !navbar || !bottom) throw Error('full-navigation');
      // The allowlist has no scanner/admin/checkout or document-specific executable content.
      // Tracking scripts are executed only after the user has committed this navigation.
      const scripts = [...page.querySelectorAll('body script')].filter(s => !s.src && (!s.type || s.type === 'text/javascript'));
      document.dispatchEvent(new Event('bzh:before-navigate'));
      document.querySelector('main').replaceWith(main);
      document.querySelector('body > nav.navbar').replaceWith(navbar);
      document.querySelector('[data-bzh-nav]').replaceWith(bottom);
      const promo = page.querySelector('.topbar');
      if (promo) document.querySelector('.topbar')?.replaceWith(promo);
      document.title = page.title;
      for (const selector of ['meta[name="description"]','meta[name="robots"]','link[rel="canonical"]']) {
        const fresh = page.querySelector(selector);
        if (fresh) document.head.querySelector(selector)?.replaceWith(fresh);
      }
      if (push) history.pushState({bzhNavigation: true}, '', url.href);
      scrollTo({top:0,left:0,behavior:'instant'});
      document.dispatchEvent(new Event('bzh:page'));
      for (const original of scripts) {
        const script = document.createElement('script');
        script.textContent = original.textContent;
        document.body.appendChild(script);
        script.remove();
      }
    } catch (error) {
      if (ticket === turn) location.assign(url.href);
    } finally {
      clearTimeout(timeout);
      if (ticket === turn) clearBusy();
    }
  };
  document.addEventListener('click', event => {
    const link = event.target.closest?.('[data-bzh-nav-link]');
    if (!link || !supported() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || !routes.has(url.pathname) || !routes.has(location.pathname)) return;
    event.preventDefault();
    if (url.href === location.href) {scrollTo({top:0,behavior:'instant'});clearBusy();return;}
    document.querySelectorAll('[data-bzh-nav-link]').forEach(item => item.classList.toggle('bzh-nav-pressed', item === link));
    navigate(url);
  });
  addEventListener('popstate', () => {
    if (supported() && routes.has(location.pathname)) navigate(new URL(location.href), false);
    else location.reload();
  });
  addEventListener('pageshow', clearBusy);
})();
