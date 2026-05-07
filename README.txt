BotyZaHubicku.cz – upravená verze projektu

Spuštění ve Windows CMD:
1) py -3.12 -m venv .venv
2) .venv\Scripts\activate
3) pip install -r requirements.txt
4) py run.py

Adresa: http://127.0.0.1:5000
Admin login:
- email: admin@eshop2.local
- heslo: admin1234

Novinky v této verzi:
- doprava zdarma všude
- checkout jen QR kód / bankovní převod + kurýr až domů
- doručení 8–12 dní
- slevové a affiliate kódy s různým rozdělením
- veřejná stránka /affiliate
- admin affiliate portál
- reset hesla přes e-mail
- SMTP lze nastavit v /admin/settings
- bez SMTP se reset e-maily ukládají do instance/outbox/emails.log

Dodavatelský PDF report:
- každý den v 00:00 Europe/Prague se automaticky vezmou všechny zaplacené objednávky, které ještě nemají vyplněné supplier_report_sent_at
- všechny objednávky se vloží do jednoho anglického PDF souboru, oddělené silnou čárou
- PDF obsahuje zákaznické doručovací údaje, poznámku, produkt, velikost, barvu, množství, dodavatelské SKU/EAN/kód varianty, zdrojovou URL, fotku a odkazy na galerii
- e-mail se posílá na fullerko@seznam.cz přes existující SMTP nastavení
- v adminu /admin/orders lze report ručně odeslat hned nebo stáhnout náhled PDF
- po úspěšném odeslání se objednávky označí batch ID a časem odeslání, aby se další den neposílaly znovu
