import os
from flask import Flask, url_for, Response
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask import send_from_directory
from dotenv import load_dotenv
from sqlalchemy import inspect as sqlalchemy_inspect
load_dotenv()  # Načte proměnné z .env souboru

# Nyní můžeš načíst proměnné jako SYNC_SECRET
SYNC_SECRET = os.getenv("SYNC_SECRET")

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Pro pokračování se přihlaste.'



def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    upload_folder = '/data/uploads'
    qr_folder = os.path.join(upload_folder, 'qr')
    email_attachment_folder = '/data/email_attachments'

    os.makedirs(upload_folder, exist_ok=True)
    os.makedirs(qr_folder, exist_ok=True)
    os.makedirs(email_attachment_folder, exist_ok=True)
        # Jednorázově zkopíruje obrázky z projektu do Render disku
    local_uploads = os.path.join(os.getcwd(), 'uploads')
    if os.path.exists(local_uploads):
        for filename in os.listdir(local_uploads):
            src = os.path.join(local_uploads, filename)
            dst = os.path.join(upload_folder, filename)
            if os.path.isfile(src) and not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-production')
    app.config['PAYMENT_SYNC_SECRET'] = os.environ.get('PAYMENT_SYNC_SECRET') or os.environ.get('SYNC_SECRET', '')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////data/eshop.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = upload_folder
    app.config['QR_FOLDER'] = qr_folder
    app.config['EMAIL_ATTACHMENT_FOLDER'] = email_attachment_folder
    app.config['FREE_SHIPPING_THRESHOLD'] = 0
    app.config['SHIPPING_PRICE'] = 0
    app.config['DELIVERY_TEXT'] = 'Doručení 8–12 dní až ke dveřím zdarma.'

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)



    @app.route('/robots.txt')
    def robots_txt():
        body = """User-agent: *
Allow: /
Disallow: /admin
Disallow: /cart
Disallow: /checkout
Disallow: /login
Disallow: /register
Disallow: /forgot-password
Disallow: /reset-password
Disallow: /api/

Sitemap: {sitemap}
""".format(sitemap=url_for('sitemap_xml', _external=True))
        return Response(body, mimetype='text/plain; charset=utf-8')

    @app.route('/sitemap.xml')
    def sitemap_xml():
        from datetime import datetime
        from xml.sax.saxutils import escape
        from .models import BlogPost, Category, Product

        def xml_url(loc, priority='0.7', changefreq='weekly'):
            return (
                '  <url>\n'
                f'    <loc>{escape(loc)}</loc>\n'
                f'    <lastmod>{datetime.utcnow().strftime("%Y-%m-%d")}</lastmod>\n'
                f'    <changefreq>{changefreq}</changefreq>\n'
                f'    <priority>{priority}</priority>\n'
                '  </url>'
            )

        urls = [
            xml_url(url_for('shop.index', _external=True), '1.0', 'daily'),
            xml_url(url_for('shop.products', _external=True), '0.9', 'daily'),
        ]

        try:
            for category in Category.query.order_by(Category.name.asc()).all():
                if getattr(category, 'slug', None):
                    if getattr(category, 'seo_generated', False) and not getattr(category, 'seo_published', True):
                        continue
                    urls.append(xml_url(url_for('shop.category_landing', slug=category.slug, _external=True), '0.85', 'weekly'))

            for post in BlogPost.query.filter_by(status='published').order_by(BlogPost.created_at.desc()).all():
                if getattr(post, 'slug', None):
                    urls.append(xml_url(url_for('shop.blog_dynamic', slug=post.slug, _external=True), '0.75', 'weekly'))

            for product in Product.query.filter_by(active=True).order_by(Product.id.desc()).all():
                if getattr(product, 'slug', None):
                    urls.append(xml_url(url_for('shop.product_detail', slug=product.slug, _external=True), '0.9', 'weekly'))
        except Exception:
            pass

        xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + '\n'.join(urls) + '\n</urlset>\n'
        return Response(xml, mimetype='application/xml; charset=utf-8')

    db.init_app(app)
    login_manager.init_app(app)

    from .models import Category, Product, SiteSetting, User
    from .utils import get_cart

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_globals():
        settings_rows = {s.key: s.value for s in SiteSetting.query.all()}
        nav_categories_query = Category.query
        if hasattr(Category, 'show_in_menu'):
            nav_categories_query = nav_categories_query.filter(db.or_(Category.show_in_menu.is_(True), Category.show_in_menu.is_(None)))
        if hasattr(Category, 'seo_generated'):
            nav_categories_query = nav_categories_query.filter(db.or_(Category.seo_generated.is_(False), Category.seo_generated.is_(None)))
        nav_categories = nav_categories_query.order_by(Category.name.asc()).all()
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
    from .routes_emailing import emailing_bp
    from .analytics import analytics_bp

    app.register_blueprint(shop_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(emailing_bp)
    app.register_blueprint(analytics_bp)

    with app.app_context():
        from . import models
        from . import analytics
        db.create_all()
        from .seed import seed_data, ensure_schema_columns
        ensure_schema_columns()
        seed_data()

        from .supplier_scheduler import start_supplier_report_scheduler
        start_supplier_report_scheduler(app)

        from .emailing_scheduler import start_emailing_scheduler
        start_emailing_scheduler(app)

        # SEO auto generator removed: content is managed manually in /admin/seo.

        homepage_categories = [
            (
                'Pánské',
                'panske',
                'https://images.unsplash.com/photo-1549298916-b41d501d3772?auto=format&fit=crop&w=1400&q=80',
                'Pánské modely do města i na každý den.',
                [],
                [],
            ),
            (
                'Dámské',
                'damske',
                'https://images.unsplash.com/photo-1608231387042-66d1773070a5?auto=format&fit=crop&w=1400&q=80',
                'Vybrané trendy dámské modely.',
                [],
                [],
            ),
            (
                'Běžecké boty',
                'bezecke-boty',
                'https://images.unsplash.com/photo-1543508282-6319a3e2621f?auto=format&fit=crop&w=1400&q=80',
                'Lehké modely pro běh i aktivní chůzi.',
                [],
                [],
            ),
            (
                'Tenisky',
                'tenisky',
                'https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=1400&q=80',
                'Streetwear a pohodlné boty na každý den.',
                [],
                [],
            ),
            (
                'Kotníkové boty',
                'kotnikove-boty',
                'https://images.unsplash.com/photo-1549298916-b41d501d3772?auto=format&fit=crop&w=1400&q=80',
                'Vyšší střih, stabilita a výrazný look.',
                [],
                [],
            ),
            (
                'Zimní',
                'zimni',
                'zimni.jpg',
                'Teplé modely do zimy a chladného počasí.',
                ['zimni-boty', 'zimni-obuv', 'snehule', 'panske-zimni-boty', 'damske-zimni-boty'],
                ['Zimní boty', 'Zímní boty', 'Zimní obuv', 'Sněhule', 'Pánské zimní boty', 'Dámské zimní boty'],
            )
        ]
        existing_tables = set(sqlalchemy_inspect(db.engine).get_table_names())
        has_product_categories_table = 'product_categories' in existing_tables

        changed = False
        for name, slug, fallback_image_url, description, alias_slugs, alias_names in homepage_categories:
            category = Category.query.filter_by(slug=slug).first()
            if not category:
                category = Category.query.filter_by(name=name).first()

            if not category:
                category = Category(
                    name=name,
                    slug=slug,
                    image_url=fallback_image_url,
                    description=description,
                    show_in_menu=True,
                )
                db.session.add(category)
                db.session.flush()
                changed = True
            else:
                if category.name != name:
                    category.name = name
                    changed = True
                if category.slug != slug:
                    category.slug = slug
                    changed = True
                if not (category.image_url or '').strip():
                    category.image_url = fallback_image_url
                    changed = True
                if category.description != description:
                    category.description = description
                    changed = True
                if hasattr(category, 'show_in_menu') and category.show_in_menu is not True:
                    category.show_in_menu = True
                    changed = True

            if hasattr(category, 'seo_generated') and category.seo_generated is not False:
                category.seo_generated = False
                changed = True
            if hasattr(category, 'seo_published') and category.seo_published is not True:
                category.seo_published = True
                changed = True

            if alias_slugs or alias_names:
                aliases = Category.query.filter(
                    db.or_(
                        Category.slug.in_(alias_slugs),
                        Category.name.in_(alias_names),
                    )
                ).all()

                for alias in aliases:
                    if alias.id == category.id:
                        continue

                    moved = Product.query.filter_by(category_id=alias.id).update(
                        {'category_id': category.id},
                        synchronize_session=False,
                    )
                    if moved:
                        changed = True

                    if has_product_categories_table:
                        for product in Product.query.filter(Product.categories.any(Category.id == alias.id)).all():
                            if category not in product.categories:
                                product.categories.append(category)
                                changed = True

        desired_menu_items = 'Všechny:all,Pánské:panske,Dámské:damske,Běžecké:bezecke-boty,Tenisky:tenisky'
        old_menu_items = {
            '',
            'Všechny boty:all,Běžecké:bezecke-boty,Dámské:damske,Pánské:panske,Tenisky:tenisky',
            'Všechny:all,Běžecké:bezecke-boty,Dámské:damske,Pánské:panske,Tenisky:tenisky',
            'Všechny boty:all,Běžecké:bezecke-boty,Dámské:damske,Pánské:panske,Tenisky:tenisky,Zimní:zimni',
            'Všechny:all,Běžecké:bezecke-boty,Dámské:damske,Pánské:panske,Tenisky:tenisky,Zimní:zimni',
        }
        menu_setting = SiteSetting.query.filter_by(key='menu_items').first()
        if not menu_setting:
            db.session.add(SiteSetting(key='menu_items', value=desired_menu_items))
            changed = True
        elif (menu_setting.value or '').strip() in old_menu_items:
            menu_setting.value = desired_menu_items
            changed = True

        if changed:
            db.session.commit()

    return app