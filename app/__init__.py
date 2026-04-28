import os
from flask import Flask, url_for
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask import send_from_directory

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Pro pokračování se přihlaste.'



def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    upload_folder = '/data/uploads'
    qr_folder = os.path.join(upload_folder, 'qr')

    os.makedirs(upload_folder, exist_ok=True)
    os.makedirs(qr_folder, exist_ok=True)
        # Jednorázově zkopíruje obrázky z projektu do Render disku
    local_uploads = os.path.join(os.getcwd(), 'uploads')
    if os.path.exists(local_uploads):
        for filename in os.listdir(local_uploads):
            src = os.path.join(local_uploads, filename)
            dst = os.path.join(upload_folder, filename)
            if os.path.isfile(src) and not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)

    app.config['SECRET_KEY'] = 'change-this-in-production'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/eshop.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = upload_folder
    app.config['QR_FOLDER'] = qr_folder
    app.config['FREE_SHIPPING_THRESHOLD'] = 0
    app.config['SHIPPING_PRICE'] = 0
    app.config['DELIVERY_TEXT'] = 'Doručení 8–12 dní až ke dveřím zdarma.'

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import Category, SiteSetting, User
    from .utils import get_cart

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_globals():
        settings_rows = {s.key: s.value for s in SiteSetting.query.all()}
        nav_categories = Category.query.order_by(Category.name.asc()).all()
        cart_count = sum(item.get('quantity', 0) for item in get_cart().values())
        return {
            'settings': settings_rows,
            'nav_categories': nav_categories,
            'cart_count': cart_count,
            'image_url': lambda value: value if (value and value.startswith(('http://', 'https://')))
            else url_for('uploaded_file', filename=(value or 'default-product.svg')),
        }

    from .routes_shop import shop_bp
    from .routes_auth import auth_bp
    from .routes_admin import admin_bp

    app.register_blueprint(shop_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        from . import models
        db.create_all()
        from .seed import seed_data, ensure_schema_columns
        ensure_schema_columns()
        seed_data()

        zimni = Category.query.filter_by(slug='zimni').first()
        if not zimni:
            zimni = Category(
                name='Zimní',
                slug='zimni',
                image_url='zimni.jpg',
                description='Teplé modely do zimy a chladného počasí.',
                show_in_menu=True
            )
            db.session.add(zimni)
            db.session.commit()

    return app