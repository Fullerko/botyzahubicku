import 'dotenv/config';
import { syncFioPayments } from './services/fio.js';

const result = await syncFioPayments();
console.log(JSON.stringify(result, null, 2));
