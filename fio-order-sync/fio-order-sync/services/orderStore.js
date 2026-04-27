const SHOP_API = process.env.SHOP_API || "https://botyzahubicku.cz";

export async function getOrderByVariableSymbol(variableSymbol) {
  return { id: variableSymbol };
}

export async function markOrderPaid(orderId, payment) {
  try {
    const res = await fetch(`${SHOP_API}/api/mark-paid`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        variableSymbol: String(payment.variableSymbol)
      })
    });

    const data = await res.json();
    console.log("API response:", data);

    if (!data.ok) {
      return { updated: false, reason: data.reason || "Unknown error" };
    }

    return { updated: true, order: data };
  } catch (err) {
    console.error("API ERROR:", err);
    return { updated: false, reason: "API error" };
  }
}

export async function isPaymentAlreadyProcessed() {
  return false;
}

export async function rememberProcessedPayment() {
  return;
}