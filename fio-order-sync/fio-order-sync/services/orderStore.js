const SHOP_API = (process.env.SHOP_API || "https://botyzahubicku.cz").replace(/\/+$/, "");
const SYNC_SECRET = (process.env.SYNC_SECRET || process.env.PAYMENT_SYNC_SECRET || "").trim();

export async function getOrderByVariableSymbol(variableSymbol) {
  return { id: variableSymbol };
}

export async function markOrderPaid(orderId, payment) {
  if (!SYNC_SECRET) {
    console.error("Missing SYNC_SECRET/PAYMENT_SYNC_SECRET in Fio sync service; cannot call shop /api/mark-paid.");
    return { updated: false, reason: "Missing sync secret in Fio service" };
  }

  try {
    const res = await fetch(`${SHOP_API}/api/mark-paid`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-sync-secret": SYNC_SECRET,
        "Authorization": `Bearer ${SYNC_SECRET}`
      },
      body: JSON.stringify({
        variableSymbol: String(payment.variableSymbol)
      })
    });

    const bodyText = await res.text();
    let data = {};
    try {
      data = bodyText ? JSON.parse(bodyText) : {};
    } catch {
      data = { ok: false, reason: bodyText || `HTTP ${res.status}` };
    }

    if (!res.ok || !data.ok) {
      console.error("Shop mark-paid API failed:", {
        status: res.status,
        reason: data.reason || data.error || "Unknown error"
      });
      return {
        updated: false,
        reason: data.reason || data.error || `HTTP ${res.status}`
      };
    }

    console.log("Shop mark-paid API ok:", {
      orderId: data.order_id,
      orderNumber: data.order_number,
      reason: data.reason
    });

    return { updated: true, order: data };
  } catch (err) {
    console.error("Shop mark-paid API request error:", err);
    return { updated: false, reason: "API request error" };
  }
}

export async function isPaymentAlreadyProcessed() {
  return false;
}

export async function rememberProcessedPayment() {
  return;
}
