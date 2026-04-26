# Fio order sync

Hotový základ pro automatické párování příchozích plateb z Fio banky s objednávkami.

## Co to dělá
- každou minutu stáhne transakce z Fio API
- vezme pouze příchozí platby
- hledá objednávku podle variabilního symbolu
- zkontroluje, že částka sedí
- označí objednávku jako `paid`
- zabrání dvojímu zpracování stejné platby

## Kam co vložit

### 1. Vytvoř složku
Například:

```bash
mkdir fio-order-sync
cd fio-order-sync
```

### 2. Nakopíruj sem soubory
- `package.json`
- `.env` podle `.env.example`
- `server.js`
- `sync-once.js`
- složku `services/`
- složku `data/`

### 3. Vlož nový Fio token do `.env`

```env
FIO_TOKEN=SEM_VLOZ_NOVY_FIO_TOKEN
```

## Spuštění

```bash
npm install
npm run dev
```

nebo jednorázově:

```bash
npm run sync
```

## Endpoint pro ruční sync

```bash
curl -X POST http://localhost:3000/api/fio/sync -H "x-sync-secret: tvoje-heslo"
```

## Nejdůležitější místo pro napojení na vlastní e-shop

Soubor:

`services/orderStore.js`

Tady jsou 2 funkce, které si ve vlastním projektu typicky přepíšeš:
- `getOrderByVariableSymbol(variableSymbol)`
- `markOrderPaid(orderId, payment)`

Místo JSON souboru tam dáš vlastní databázi nebo API e-shopu.

Příklad s SQL:

```js
export async function getOrderByVariableSymbol(variableSymbol) {
  return db.order.findFirst({ where: { variableSymbol: String(variableSymbol) } });
}

export async function markOrderPaid(orderId, payment) {
  await db.order.update({
    where: { id: Number(orderId) },
    data: {
      status: 'paid',
      paidAt: new Date(),
      paymentReference: String(payment.transactionId)
    }
  });

  return { updated: true };
}
```

## Poznámky
- Fio doporučuje minimální interval dotazu na stejný token 30 sekund.
- Pro stahování transakcí za období se používá endpoint:
  `https://fioapi.fio.cz/v1/rest/periods/{token}/{od}/{do}/transactions.json`
- Token je vázaný na konkrétní účet.
