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
