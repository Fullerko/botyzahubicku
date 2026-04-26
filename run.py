from app import create_app

app = create_app()

@app.route('/create-admin')
def create_admin_route():
    from app import db
    from app.models import User
    from werkzeug.security import generate_password_hash

    email = "admin@admin.cz"
    password = "123456"

    existing = User.query.filter_by(email=email).first()
    if existing:
        return "Admin už existuje"

    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        full_name="Admin",
        address="",
        city="",
        postal_code="",
        is_admin=True
    )

    db.session.add(user)
    db.session.commit()

    return "Admin vytvořen: admin@admin.cz / 123456"

if __name__ == '__main__':
    app.run(debug=True)
