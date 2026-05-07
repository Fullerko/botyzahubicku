# Oprava Fio -> /api/mark-paid 401

Změněné soubory:
- app/__init__.py
- app/routes_shop.py
- fio-order-sync/fio-order-sync/services/orderStore.js

Co oprava řeší:
1. Flask shop bere PAYMENT_SYNC_SECRET/SYNC_SECRET z Render env před hodnotou uloženou v admin DB nastavení.
2. Fio sync neposílá prázdný request bez secretu; když secret chybí, vypíše jasnou chybu.
3. Fio sync posílá secret v hlavičce x-sync-secret i Authorization: Bearer.
4. Odstraněn debug výpis secretu před deklarací, který shazoval Node import.

Po nasazení nastav v Renderu stejnou hodnotu proměnné SYNC_SECRET nebo PAYMENT_SYNC_SECRET u obou služeb:
- Flask/shop služba
- Node fio-order-sync služba

Nepoužívej starou hodnotu v /admin/settings -> Platba a e-mail -> Tajný klíč pro Fio sync, pokud se liší od Render env.
