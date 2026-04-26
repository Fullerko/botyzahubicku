from app import create_app

app = create_app()

@app.route('/setup-admin-928471')
def setup_admin_928471():
    from app import db
    from app.models import User
    from werkzeug.security import generate_password_hash

    email = "admin@botyzahubicku.cz"
    password = "Admin12345"

    user = User.query.filter_by(email=email).first()

    if not user:
        user = User()
        user.email = email
        user.full_name = "Admin"
        user.address = ""
        user.city = ""
        user.postal_code = ""
        db.session.add(user)

    user.password_hash = generate_password_hash(password)
    user.is_admin = True

    db.session.commit()

    return "Admin účet nastaven: admin@botyzahubicku.cz / Admin12345"