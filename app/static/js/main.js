document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-autodismiss]').forEach((el) => setTimeout(() => el.remove(), 3000));
});
function changeProductImage(button, imageUrl) {
  const mainImage = document.getElementById("mainProductImage");

  if (!mainImage) return;

  mainImage.src = imageUrl;

  document.querySelectorAll(".product-thumb").forEach((thumb) => {
    thumb.classList.remove("active");
  });

  button.classList.add("active");
  document.addEventListener("click", function (event) {
    const btn = event.target.closest(".copy-url-btn");

    if (!btn) return;

    const url = btn.dataset.url;

    navigator.clipboard.writeText(url).then(() => {
      const oldText = btn.innerHTML;
      btn.innerHTML = "✅ Zkopírováno";

      setTimeout(() => {
        btn.innerHTML = oldText;
      }, 1200);
    });
  });
  document.addEventListener("click", async function (event) {
    const btn = event.target.closest("#checkPaymentBtn");

    if (!btn) return;

    const orderNumber = btn.dataset.orderNumber;
    const messageBox = document.getElementById("paymentStatusMessage");

    btn.disabled = true;
    btn.innerText = "Kontroluji platbu...";
    messageBox.innerText = "";

    try {
      const response = await fetch(`/api/order-status/${orderNumber}`);
      const data = await response.json();

      if (data.paid) {
        messageBox.className = "mt-3 fw-semibold text-success";
        messageBox.innerText = "Děkujeme za Vaši objednávku, podrobnosti jsme Vám zaslali emailem.";
      } else {
        messageBox.className = "mt-3 fw-semibold text-warning";
        messageBox.innerText = "Platba neexistuje, nebo stále nedorazila, vyčkejte prosím 30 vteřin a zkuste zkontrolovat stav znovu.";
      }
    } catch (error) {
      messageBox.className = "mt-3 fw-semibold text-danger";
      messageBox.innerText = "Nepodařilo se ověřit stav platby. Zkuste to prosím znovu.";
    }

    btn.disabled = false;
    btn.innerText = "Zkontrolovat stav platby";
  });
}

document.addEventListener("click", async function (event) {
  const btn = event.target.closest(".copy-url-btn");

  if (!btn) return;

  const url = btn.dataset.url;

  if (!url) return;

  try {
    await navigator.clipboard.writeText(url);

    const oldText = btn.innerHTML;
    btn.innerHTML = "✅";

    setTimeout(() => {
      btn.innerHTML = oldText;
    }, 1200);
  } catch (error) {
    const textarea = document.createElement("textarea");
    textarea.value = url;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);

    const oldText = btn.innerHTML;
    btn.innerHTML = "✅";

    setTimeout(() => {
      btn.innerHTML = oldText;
    }, 1200);
  }
});
// Emailing: zachycení e-mailu z košíku / checkoutu pro opuštěný košík v adminu.
async function saveCartLead(email, name = '', phone = '', messageBox = null) {
  if (!email || !email.includes('@')) return false;
  try {
    const response = await fetch('/api/cart-lead', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, name, phone })
    });
    const data = await response.json().catch(() => ({}));
    const ok = response.ok && data.ok;
    if (messageBox) {
      if (ok) {
        messageBox.className = 'small text-success';
        messageBox.textContent = 'Košík byl uložen k e-mailu.';
      } else {
        messageBox.className = 'small text-danger';
        messageBox.textContent = 'Košík se nepodařilo uložit.';
      }
    }
    return ok;
  } catch (error) {
    if (messageBox) {
      messageBox.className = 'small text-danger';
      messageBox.textContent = 'Košík se nepodařilo uložit.';
    }
    return false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const cartLeadForm = document.getElementById('cartLeadForm');
  if (cartLeadForm) {
    cartLeadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const messageBox = document.getElementById('cartLeadMessage');
      const email = cartLeadForm.querySelector('[name="email"]')?.value || '';
      const name = cartLeadForm.querySelector('[name="name"]')?.value || '';
      const saved = await saveCartLead(email, name, '', messageBox);
      if (saved && typeof fbq === 'function') {
        fbq('track', 'Lead', {
          content_name: 'Uložený košík',
          content_category: 'cart_lead'
        });
      }
    });
  }

  const checkoutEmail = document.querySelector('[data-cart-lead-email]');
  if (checkoutEmail) {
    let timer = null;
    const sendCheckoutLead = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        saveCartLead(
          checkoutEmail.value || '',
          document.getElementById('checkoutName')?.value || '',
          document.getElementById('checkoutPhone')?.value || ''
        );
      }, 700);
    };
    checkoutEmail.addEventListener('input', sendCheckoutLead);
    checkoutEmail.addEventListener('blur', sendCheckoutLead);
  }
});

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-reviews-carousel]').forEach((carousel) => {
    const track = carousel.querySelector('[data-reviews-track]');
    const cards = Array.from(track?.querySelectorAll('.review-card') || []);
    const nextButton = carousel.querySelector('[data-reviews-next]');

    if (!track || !cards.length || !nextButton) return;

    const getRating = (card) => {
      const explicitRating = Number.parseFloat(card.dataset.rating || '');
      if (Number.isFinite(explicitRating)) return explicitRating;

      const starsLabel = card.querySelector('.review-stars')?.getAttribute('aria-label') || '';
      const labelMatch = starsLabel.match(/([0-5](?:[.,]\d+)?)\s*z\s*5/i);
      if (labelMatch) return Number.parseFloat(labelMatch[1].replace(',', '.'));

      const starsText = card.querySelector('.review-stars')?.textContent || '';
      const filledStars = (starsText.match(/★/g) || []).length;
      return filledStars || null;
    };

    const updateReviewSummary = () => {
      const ratings = cards
        .map(getRating)
        .filter((rating) => Number.isFinite(rating) && rating > 0);

      if (!ratings.length) return;

      const average = ratings.reduce((sum, rating) => sum + rating, 0) / ratings.length;
      const averageText = average.toFixed(1);
      const averageEl = carousel.querySelector('[data-reviews-average]');
      const countEl = carousel.querySelector('[data-reviews-count]');
      const starsEl = carousel.querySelector('[data-reviews-summary-stars]');

      if (averageEl) averageEl.textContent = averageText;
      if (countEl) countEl.textContent = String(ratings.length);
      if (starsEl) starsEl.setAttribute('aria-label', `${averageText} z 5 hvězdiček`);
    };

    updateReviewSummary();

    let currentIndex = 0;
    let autoplayTimer = null;

    const cardsPerView = () => window.matchMedia('(max-width: 767px)').matches ? 1 : 3;
    const maxIndex = () => Math.max(0, cards.length - cardsPerView());
    const gapSize = () => parseFloat(window.getComputedStyle(track).gap) || 0;

    const moveTo = (index) => {
      const max = maxIndex();
      if (index > max) {
        currentIndex = 0;
      } else if (index < 0) {
        currentIndex = max;
      } else {
        currentIndex = index;
      }

      const cardWidth = cards[0].getBoundingClientRect().width;
      const offset = (cardWidth + gapSize()) * currentIndex;
      track.style.transform = `translate3d(${-offset}px, 0, 0)`;
    };

    const next = () => moveTo(currentIndex + 1);

    const stopAutoplay = () => {
      if (autoplayTimer) {
        window.clearInterval(autoplayTimer);
        autoplayTimer = null;
      }
    };

    const startAutoplay = () => {
      stopAutoplay();
      if (cards.length <= cardsPerView()) return;
      autoplayTimer = window.setInterval(next, 4500);
    };

    nextButton.addEventListener('click', () => {
      next();
      startAutoplay();
    });

    carousel.addEventListener('mouseenter', stopAutoplay);
    carousel.addEventListener('mouseleave', startAutoplay);
    carousel.addEventListener('focusin', stopAutoplay);
    carousel.addEventListener('focusout', startAutoplay);

    window.addEventListener('resize', () => moveTo(0));

    moveTo(0);
    startAutoplay();
  });
});

