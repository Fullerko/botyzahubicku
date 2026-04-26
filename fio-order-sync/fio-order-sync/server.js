import 'dotenv/config';
import express from 'express';
import { syncFioPayments } from './services/fio.js';

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ ok: true, service: 'fio-order-sync' });
});

app.post('/api/fio/sync', async (req, res) => {
  try {
    const configuredSecret = process.env.SYNC_SECRET?.trim();
    if (configuredSecret) {
      const incoming = req.header('x-sync-secret');
      if (incoming !== configuredSecret) {
        return res.status(401).json({ ok: false, error: 'Unauthorized' });
      }
    }

    const result = await syncFioPayments();
    res.json({ ok: true, ...result });
  } catch (error) {
    console.error('Manual sync failed:', error);
    res.status(500).json({ ok: false, error: error.message });
  }
});

const port = Number(process.env.PORT || 3000);
app.listen(port, () => {
  console.log(`Fio sync server running on http://localhost:${port}`);

  const interval = Math.max(Number(process.env.AUTO_SYNC_INTERVAL_MS || 60000), 30000);
  console.log(`Auto-sync every ${interval} ms`);

  syncFioPayments()
    .then((result) => console.log('Initial sync:', result))
    .catch((error) => console.error('Initial sync failed:', error.message));

  setInterval(async () => {
    try {
      const result = await syncFioPayments();
      console.log('Periodic sync:', result);
    } catch (error) {
      console.error('Periodic sync failed:', error.message);
    }
  }, interval);
});
