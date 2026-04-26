import os
import sqlite3

db_path = r"instance\eshop.db"

print("DB exists:", os.path.exists(db_path))
print("DB path:", os.path.abspath(db_path))

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("PRAGMA table_info('order')")
cols_before = cur.fetchall()
print("Columns before:")
for c in cols_before:
    print(c)

commands = [
    """ALTER TABLE "order" ADD COLUMN payment_status VARCHAR(20) NOT NULL DEFAULT 'pending'""",
    """ALTER TABLE "order" ADD COLUMN variable_symbol VARCHAR(30)""",
    """ALTER TABLE "order" ADD COLUMN paid_at DATETIME""",
    """ALTER TABLE "order" ADD COLUMN fio_transaction_id VARCHAR(100)""",
]

for cmd in commands:
    try:
        cur.execute(cmd)
        print("OK:", cmd)
    except Exception as e:
        print("SKIP/ERR:", e)

try:
    cur.execute("""UPDATE "order" SET payment_status = 'pending' WHERE payment_status IS NULL""")
    cur.execute("""UPDATE "order" SET variable_symbol = order_number WHERE variable_symbol IS NULL""")
    print("OK: updated existing rows")
except Exception as e:
    print("UPDATE ERR:", e)

conn.commit()

cur.execute("PRAGMA table_info('order')")
cols_after = cur.fetchall()
print("\nColumns after:")
for c in cols_after:
    print(c)

conn.close()
print("Hotovo")