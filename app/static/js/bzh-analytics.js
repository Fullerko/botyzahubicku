(function () {
  const endpoint = '/api/analytics/event';
  const heatmapEndpoint = '/api/analytics/heatmap';

  function isBotLike() {
    const ua = (navigator.userAgent || '').toLowerCase();
    const patterns = ['bot', 'crawl', 'spider', 'headless', 'lighthouse', 'pagespeed', 'python', 'curl', 'wget'];
    return !ua || patterns.some((pattern) => ua.includes(pattern));
  }

  function shouldTrack() {
    const path = window.location.pathname || '';
    if (isBotLike()) return false;
    if (path.startsWith('/admin')) return false;
    if (path.startsWith('/api/')) return false;
    if (path.startsWith('/static/')) return false;
    if (path.startsWith('/uploads/')) return false;
    return true;
  }

  if (!shouldTrack()) return;

  function post(url, payload) {
    try {
      const body = JSON.stringify(payload);
      if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        navigator.sendBeacon(url, blob);
        return;
      }

      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        keepalive: true,
        body: body
      }).catch(() => {});
    } catch (error) {
      // Analytics must never break the shop.
    }
  }

  function textOf(element) {
    return (element && element.innerText ? element.innerText : '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 180);
  }

  function selectorOf(element) {
    if (!element) return '';
    if (element.id) return `#${element.id}`;
    if (element.getAttribute('data-track')) return `[data-track="${element.getAttribute('data-track')}"]`;
    const cls = String(element.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    return `${element.tagName.toLowerCase()}${cls ? '.' + cls : ''}`.slice(0, 280);
  }

  function productIdFromPath(path) {
    if (!path || !path.startsWith('/produkt/')) return null;
    return null;
  }

  function track(event, data) {
    post(endpoint, Object.assign({
      event: event,
      path: window.location.pathname,
      referrer: document.referrer || '',
      ts: Date.now()
    }, data || {}));
  }

  track('page_ready', {
    title: document.title || '',
    product_id: productIdFromPath(window.location.pathname)
  });

  let maxDepthSent = 0;
  function trackScrollDepth() {
    const doc = document.documentElement;
    const body = document.body;
    const scrollTop = window.scrollY || doc.scrollTop || body.scrollTop || 0;
    const height = Math.max(body.scrollHeight, doc.scrollHeight) - window.innerHeight;
    if (height <= 0) return;

    const depth = Math.round((scrollTop / height) * 100);
    const milestones = [25, 50, 75, 90];
    milestones.forEach((milestone) => {
      if (depth >= milestone && maxDepthSent < milestone) {
        maxDepthSent = milestone;
        track('scroll_depth', { value: milestone });
      }
    });
  }

  window.addEventListener('scroll', () => {
    window.clearTimeout(window.__bzhScrollTimer);
    window.__bzhScrollTimer = window.setTimeout(trackScrollDepth, 250);
  }, { passive: true });

  document.addEventListener('click', (event) => {
    const target = event.target.closest('a, button, input[type="submit"], .btn, [data-track]');
    if (!target) return;

    const href = target.getAttribute('href') || '';
    let eventName = 'click';

    if (href.includes('/produkt/')) eventName = 'product_click';
    if (href.includes('/cart') || href.includes('/kosik')) eventName = 'cart_click';
    if (href.includes('/checkout')) eventName = 'checkout_click';
    if ((target.innerText || '').toLowerCase().includes('košík')) eventName = 'add_to_cart';

    track(eventName, {
      text: textOf(target),
      href: href,
      selector: selectorOf(target)
    });

    post(heatmapEndpoint, {
      path: window.location.pathname,
      x: Math.round(event.clientX || 0),
      y: Math.round(event.clientY || 0),
      viewport_w: window.innerWidth || 0,
      viewport_h: window.innerHeight || 0,
      page_w: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth),
      page_h: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
      selector: selectorOf(target),
      text: textOf(target),
      ts: Date.now()
    });
  }, { passive: true });

  document.addEventListener('submit', (event) => {
    const form = event.target;
    const action = form.getAttribute('action') || window.location.pathname;
    let eventName = 'form_submit';
    if (action.includes('/cart') || action.includes('/kosik') || textOf(form).toLowerCase().includes('košík')) eventName = 'add_to_cart';
    if (action.includes('/checkout')) eventName = 'checkout_submit';

    track(eventName, {
      action: action,
      selector: selectorOf(form),
      text: textOf(form)
    });
  }, true);

  window.addEventListener('beforeunload', () => {
    track('page_unload', {
      time_on_page: Math.round((performance.now ? performance.now() : 0) / 1000),
      max_scroll: maxDepthSent
    });
  });
})();
