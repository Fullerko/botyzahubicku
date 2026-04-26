import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { markOrderPaid, rememberProcessedPayment } from './orderStore.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const STATE_PATH = path.join(__dirname, '..', 'data', 'fio-state.json');

function toDateString(date) {
  return date.toISOString().slice(0, 10);
}

function subtractDays(date, days) {
  const d = new Date(date);
  d.setDate(d.getDate() - days);
  return d;
}

async function readState() {
  try {
    const raw = await fs.readFile(STATE_PATH, 'utf8');
    return JSON.parse(raw);
  } catch {
    return { lastSyncFrom: null, lastSyncTo: null };
  }
}

async function writeState(state) {
  await fs.mkdir(path.dirname(STATE_PATH), { recursive: true });
  await fs.writeFile(STATE_PATH, JSON.stringify(state, null, 2), 'utf8');
}

function normalizeTransactions(payload) {
  const txs = payload?.accountStatement?.transactionList?.transaction;
  if (!txs) return [];
  return Array.isArray(txs) ? txs : [txs];
}

function mapTransaction(tx) {
  return {
    transactionId: tx?.column22?.value ?? null,
    amount: Number(tx?.column1?.value ?? 0),
    currency: tx?.column14?.value ?? null,
    date: tx?.column0?.value ?? null,
    variableSymbol: tx?.column5?.value ? String(tx.column5.value) : '',
    message: tx?.column16?.value ?? '',
    senderName: tx?.column10?.value || tx?.column7?.value || '',
    bankReference: tx?.column25?.value ?? '',
    type: tx?.column8?.value ?? ''
  };
}

async function fetchPeriodTransactions({ token, from, to }) {
  const url = `https://fioapi.fio.cz/v1/rest/periods/${token}/${from}/${to}/transactions.json`;

  console.log('FIO URL:', url.replace(token, '***TOKEN***'));

  const response = await fetch(url, {
    headers: { Accept: 'application/json' }
  });

  const bodyText = await response.text();

  if (!response.ok) {
    throw new Error(`Fio API error ${response.status}: ${bodyText.slice(0, 500)}`);
  }

  return JSON.parse(bodyText);
}

export async function syncFioPayments() {
  const token = process.env.FIO_TOKEN?.trim();
  if (!token) {
    throw new Error('Missing FIO_TOKEN in .env');
  }

  const daysBack = Number(process.env.FIO_POLL_DAYS_BACK || 2);
  const requiredCurrency = process.env.FIO_REQUIRED_CURRENCY?.trim() || null;
  const state = await readState();

  const now = new Date();
  const defaultFrom = toDateString(subtractDays(now, daysBack));
  const from = defaultFrom;
  const to = toDateString(now);

  const payload = await fetchPeriodTransactions({ token, from, to });
  const transactions = normalizeTransactions(payload).map(mapTransaction);

  console.log('FIO raw transaction count:', transactions.length);

  const incoming = transactions.filter((tx) => Number(tx.amount) > 0);

  let matched = 0;
  let updatedOrders = 0;
  const skipped = [];

  for (const payment of incoming) {
    if (!payment.transactionId) {
      skipped.push({ reason: 'Missing transactionId', payment });
      continue;
    }

    if (requiredCurrency && payment.currency && payment.currency !== requiredCurrency) {
      skipped.push({
        reason: 'Different currency',
        transactionId: payment.transactionId,
        currency: payment.currency
      });
      continue;
    }

    if (!payment.variableSymbol) {
      skipped.push({
        reason: 'Missing variable symbol',
        transactionId: payment.transactionId
      });
      continue;
    }

    matched += 1;

    const updated = await markOrderPaid(payment.variableSymbol, payment);

    if (!updated.updated) {
      skipped.push({
        reason: updated.reason || 'Order update failed',
        transactionId: payment.transactionId,
        variableSymbol: payment.variableSymbol
      });
      continue;
    }

    await rememberProcessedPayment(payment, payment.variableSymbol);
    updatedOrders += 1;
  }

  await writeState({
    lastSyncFrom: from,
    lastSyncTo: to,
    syncedAt: new Date().toISOString()
  });

  return {
    checkedTransactions: incoming.length,
    matched,
    updatedOrders,
    from,
    to,
    skipped
  };
}