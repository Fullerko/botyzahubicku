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
