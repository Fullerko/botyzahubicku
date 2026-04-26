from app import create_app, db
from app.models import Order

app = create_app()

with app.app_context():
    orders = Order.query.all()
    updated = 0

    for o in orders:
        if not o.variable_symbol:
            digits = ''.join(ch for ch in str(o.order_number) if ch.isdigit())
            if digits:
                o.variable_symbol = digits
                updated += 1

    db.session.commit()
    print(f"Hotovo, upraveno objednávek: {updated}")