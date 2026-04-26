from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    email = "admin@admin.cz"
    password = "110216845zk"

    existing = User.query.filter_by(email=email).first()
    if existing:
        print("Admin už existuje")
    else:
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=True
        )
        db.session.add(user)
        db.session.commit()
        print("Admin vytvořen:", email, password)