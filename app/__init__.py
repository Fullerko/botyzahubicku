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
        # Primárně servírujeme persistentní upload složku (/data/uploads).
        # Pokud soubor existuje jen v projektové složce /uploads, použije se jako fallback.
        upload_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(upload_path):
            return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

        local_uploads = os.path.join(app.root_path, '..', 'uploads')
        local_path = os.path.join(local_uploads, filename)
        if os.path.exists(local_path):
            return send_from_directory(local_uploads, filename)

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


    @app.route('/merchant-feed.xml')
    def merchant_feed_xml():
        """Google Merchant Center product feed for free listings.

        URL pro Merchant Center:
        https://botyzahubicku.cz/merchant-feed.xml
        """
        from datetime import datetime
        from xml.sax.saxutils import escape
        import html
        import re
        from .models import Product

        STORE_NAME = 'BotyZaHubicku.cz'
        CURRENCY = 'CZK'
        GOOGLE_PRODUCT_CATEGORY = 'Apparel & Accessories > Shoes'

        def clean_text(value, fallback='', max_length=5000):
            value = html.unescape(str(value or fallback or ''))
            value = re.sub(r'<[^>]+>', ' ', value)
            value = re.sub(r'\s+', ' ', value).strip()
            if len(value) > max_length:
                value = value[:max_length - 1].rstrip() + '…'
            return value

        def absolute_url(value):
            value = (value or '').strip()
            if value.startswith(('http://', 'https://')):
                return value
            if value.startswith('/'):
                return url_for('shop.index', _external=True).rstrip('/') + value
            return url_for('uploaded_file', filename=(value or 'default-product.svg'), _external=True)

        def product_image_url(product):
            image = (getattr(product, 'image', '') or '').strip()
            if not image:
                image = 'default-product.svg'
            # Pokud by se do hlavního obrázku omylem dostal seznam, vezmeme první hodnotu.
            image = image.split(',')[0].strip()
            return absolute_url(image)

        def product_description(product):
            return clean_text(
                getattr(product, 'meta_description', '')
                or getattr(product, 'short_description', '')
                or getattr(product, 'description', ''),
                fallback=f'{product.name} - pohodlná obuv z nabídky {STORE_NAME}.',
                max_length=5000,
            )

        def product_type(product):
            category = getattr(product, 'category', None)
            category_name = clean_text(getattr(category, 'name', ''), fallback='Boty', max_length=120)
            return f'Boty > {category_name}' if category_name.lower() != 'boty' else 'Boty'

        def normalized_gender(product):
            raw = f"{getattr(product, 'gender', '')} {getattr(product, 'name', '')}".lower()
            if any(token in raw for token in ['dáms', 'dams', 'žensk', 'zensk', 'women', 'female']):
                return 'female'
            if any(token in raw for token in ['pánsk', 'pansk', 'muž', 'muz', 'men', 'male']):
                return 'male'
            return 'unisex'

        def inferred_color(product, variant_color=''):
            raw_color = clean_text(variant_color or getattr(product, 'colors', ''), max_length=120)
            if raw_color:
                return raw_color.split(',')[0].strip()

            name = f"{getattr(product, 'name', '')} {getattr(product, 'slug', '')}".lower()
            color_map = [
                (['bíl', 'bile', 'bila', 'white', '-bl-'], 'bílá'),
                (['čern', 'cern', 'black'], 'černá'),
                (['šed', 'sed', 'gray', 'grey'], 'šedá'),
                (['modr', 'blue'], 'modrá'),
                (['béž', 'bez', 'beige'], 'béžová'),
                (['hněd', 'hned', 'brown'], 'hnědá'),
                (['růž', 'ruz', 'pink'], 'růžová'),
                (['zelen', 'green'], 'zelená'),
                (['červen', 'cerven', 'red'], 'červená'),
                (['žlut', 'zlut', 'yellow'], 'žlutá'),
                (['fial', 'purple'], 'fialová'),
                (['oranž', 'oranz', 'orange'], 'oranžová'),
            ]
            for tokens, color in color_map:
                if any(token in name for token in tokens):
                    return color
            return 'vícebarevná'

        def safe_id_part(value):
            value = clean_text(value, max_length=80)
            value = re.sub(r'[^A-Za-z0-9_-]+', '-', value).strip('-')
            return value or 'default'

        def product_stock(product):
            try:
                if getattr(product, 'stock', 0) and int(product.stock) > 0:
                    return int(product.stock)
            except Exception:
                pass
            try:
                return sum(max(0, int(row.stock or 0)) for row in getattr(product, 'sizes', []) or [])
            except Exception:
                return 0

        def variants_for_product(product):
            variants = []

            # Priorita: detailní varianty velikost + barva, pokud existují.
            for variant in getattr(product, 'variants', []) or []:
                size = clean_text(getattr(variant, 'size', ''), max_length=40)
                color = clean_text(getattr(variant, 'color', ''), max_length=80)
                stock = int(getattr(variant, 'stock', 0) or 0)
                if size or color:
                    variants.append({
                        'id_suffix': safe_id_part(f'{size}-{color}' if color else size),
                        'size': size,
                        'color': color,
                        'stock': stock,
                    })

            if variants:
                return variants

            # Fallback: původní velikosti produktu.
            for size_row in getattr(product, 'sizes', []) or []:
                size = clean_text(getattr(size_row, 'size', ''), max_length=40)
                stock = int(getattr(size_row, 'stock', 0) or 0)
                if size:
                    variants.append({
                        'id_suffix': safe_id_part(size),
                        'size': size,
                        'color': '',
                        'stock': stock,
                    })

            if variants:
                return variants

            # Poslední fallback: jeden item pro produkt bez velikostí.
            return [{
                'id_suffix': '',
                'size': '',
                'color': '',
                'stock': product_stock(product),
            }]

        def xml_tag(name, value):
            return f'<{name}>{escape(clean_text(value))}</{name}>'

        def render_item(product, variant):
            product_url = url_for('shop.product_detail', slug=product.slug, _external=True)
            image_url = product_image_url(product)
            price = max(float(getattr(product, 'price', 0) or 0), 0)
            size = variant.get('size', '')
            color = inferred_color(product, variant.get('color', ''))
            stock = int(variant.get('stock', 0) or 0)
            in_stock = stock > 0 or (not size and product_stock(product) > 0)
            availability = 'in_stock' if in_stock else 'out_of_stock'
            item_id = f'BZH-{product.id}' + (f'-{variant["id_suffix"]}' if variant.get('id_suffix') else '')
            title = clean_text(product.name, max_length=150)
            if size:
                title = clean_text(f'{title} - velikost {size}', max_length=150)

            parts = [
                '    <item>',
                f'      <g:id>{escape(item_id)}</g:id>',
                f'      <g:item_group_id>BZH-{product.id}</g:item_group_id>',
                f'      <title>{escape(title)}</title>',
                f'      <description>{escape(product_description(product))}</description>',
                f'      <link>{escape(product_url)}</link>',
                f'      <g:image_link>{escape(image_url)}</g:image_link>',
                f'      <g:availability>{availability}</g:availability>',
                f'      <g:price>{price:.2f} {CURRENCY}</g:price>',
                '      <g:condition>new</g:condition>',
                f'      <g:brand>{escape(clean_text(getattr(product, "brand", "") or STORE_NAME, max_length=70))}</g:brand>',
                f'      <g:google_product_category>{escape(GOOGLE_PRODUCT_CATEGORY)}</g:google_product_category>',
                f'      <g:product_type>{escape(product_type(product))}</g:product_type>',
                '      <g:identifier_exists>no</g:identifier_exists>',
                '      <g:adult>no</g:adult>',
                '      <g:age_group>adult</g:age_group>',
                f'      <g:gender>{normalized_gender(product)}</g:gender>',
                f'      <g:color>{escape(color)}</g:color>',
            ]
            if size:
                parts.append(f'      <g:size>{escape(size)}</g:size>')
            supplier_sku = clean_text(getattr(product, 'supplier_sku', ''), max_length=120)
            if supplier_sku:
                parts.append(f'      <g:mpn>{escape(supplier_sku)}</g:mpn>')
            parts.extend([
                '      <g:shipping>',
                '        <g:country>CZ</g:country>',
                '        <g:service>Doprava zdarma</g:service>',
                f'        <g:price>0.00 {CURRENCY}</g:price>',
                '      </g:shipping>',
                '    </item>',
            ])
            return '\n'.join(parts)

        items = []
        try:
            products = Product.query.filter_by(active=True).order_by(Product.id.desc()).all()
            for product in products:
                if not getattr(product, 'slug', None):
                    continue
                if float(getattr(product, 'price', 0) or 0) <= 0:
                    continue
                if not product_image_url(product):
                    continue
                for variant in variants_for_product(product):
                    # Do feedu dáváme i vyprodané varianty jako out_of_stock.
                    # Google tak může stav správně zobrazit; aktivní produkty se neztratí.
                    items.append(render_item(product, variant))
        except Exception as exc:
            items.append(
                '    <!-- Feed se nepodařilo kompletně vygenerovat: '
                + escape(clean_text(str(exc), max_length=500))
                + ' -->'
            )

        now = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">\n'
            '  <channel>\n'
            f'    <title>{escape(STORE_NAME)} produktový feed</title>\n'
            f'    <link>{escape(url_for("shop.index", _external=True))}</link>\n'
            f'    <description>Automatický produktový feed pro Google Merchant Center.</description>\n'
            f'    <lastBuildDate>{now}</lastBuildDate>\n'
            + '\n'.join(items)
            + '\n  </channel>\n</rss>\n'
        )
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

        def resolved_image_url(value):
            value = (value or '').strip()
            if value.startswith(('http://', 'https://', '/')):
                return value
            return url_for('uploaded_file', filename=(value or 'default-product.svg'))

        def category_home_image_url(category):
            filename = (getattr(category, 'image_url', '') or '').strip()
            if not filename and getattr(category, 'slug', None):
                filename = f'{category.slug}.jpg'
            return resolved_image_url(filename)

        return {
            'settings': settings_rows,
            'nav_categories': nav_categories,
            'cart_count': cart_count,
            'image_url': resolved_image_url,
            'category_home_image_url': category_home_image_url,
        }

    from .routes_shop import shop_bp
    from .routes_auth import auth_bp
    from .routes_admin import admin_bp
    from .routes_emailing import emailing_bp
    from .analytics import analytics_bp
    from app.meta_feed import meta_feed_bp

    app.register_blueprint(shop_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(emailing_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(meta_feed_bp)

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