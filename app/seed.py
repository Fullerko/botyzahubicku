from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash
from . import db
from .models import AffiliatePartner, Category, Coupon, Product, ProductSize, SiteSetting, User
from .utils import unique_slug


PRODUCT_IMAGES = [
    'https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1543508282-6319a3e2621f?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1549298916-b41d501d3772?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1600185365926-3a2ce3cdb9eb?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1608231387042-66d1773070a5?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1584735175315-9d5df23860e6?auto=format&fit=crop&w=1400&q=80',
    'https://images.unsplash.com/photo-1575537302964-96cd47c06b1b?auto=format&fit=crop&w=1400&q=80',
]


def ensure_schema_columns():
    engine = db.engine
    inspector = inspect(engine)
    desired = {
        'category': {
            'image_url': "ALTER TABLE category ADD COLUMN image_url VARCHAR(500) DEFAULT ''",
            'description': "ALTER TABLE category ADD COLUMN description VARCHAR(255) DEFAULT ''",
            'show_in_menu': "ALTER TABLE category ADD COLUMN show_in_menu BOOLEAN DEFAULT 1",
        },
        'coupon': None,
        'affiliate_partner': None,
        'password_reset_token': None,
        'order': {
            'discount_amount': "ALTER TABLE 'order' ADD COLUMN discount_amount FLOAT DEFAULT 0",
            'coupon_code': "ALTER TABLE 'order' ADD COLUMN coupon_code VARCHAR(40) DEFAULT ''",
            'coupon_id': "ALTER TABLE 'order' ADD COLUMN coupon_id INTEGER",
            'affiliate_partner_name': "ALTER TABLE 'order' ADD COLUMN affiliate_partner_name VARCHAR(120) DEFAULT ''",
            'affiliate_commission_amount': "ALTER TABLE 'order' ADD COLUMN affiliate_commission_amount FLOAT DEFAULT 0",
            'qr_payload': "ALTER TABLE 'order' ADD COLUMN qr_payload TEXT DEFAULT ''",
            'qr_image': "ALTER TABLE 'order' ADD COLUMN qr_image VARCHAR(255) DEFAULT ''",
        },
    }
    with engine.begin() as conn:
        existing_tables = inspector.get_table_names()
        for table, columns in desired.items():
            if columns is None:
                continue
            if table in existing_tables:
                existing = {col['name'] for col in inspector.get_columns(table)}
                for name, statement in columns.items():
                    if name not in existing:
                        conn.execute(text(statement))


def seed_data():
    if not User.query.filter_by(email='admin@eshop2.local').first():
        admin = User(
            email='admin@eshop2.local',
            full_name='Admin BotyZaHubicku',
            password_hash=generate_password_hash('admin1234'),
            is_admin=True,
        )
        db.session.add(admin)

    if Category.query.count() == 0:
        categories = [
            Category(name='Tenisky', slug='tenisky', image_url=PRODUCT_IMAGES[0], description='Streetwear a daily tenisky.'),
            Category(name='Běžecké boty', slug='bezecke-boty', image_url=PRODUCT_IMAGES[1], description='Lehké modely pro běh i chůzi.'),
            Category(name='Kotníkové boty', slug='kotnikove-boty', image_url=PRODUCT_IMAGES[2], description='Vyšší střih a výrazný look.'),
            Category(name='Sandály', slug='sandaly', image_url=PRODUCT_IMAGES[3], description='Vzdušné modely na léto.'),
            Category(name='Dámské', slug='damske', image_url=PRODUCT_IMAGES[4], description='Vybrané trendy dámské modely.'),
            Category(name='Pánské', slug='panske', image_url=PRODUCT_IMAGES[5], description='Pánské modely do města i na cestu.'),
        ]
        db.session.add_all(categories)
        db.session.flush()

        demo_products = [
            ('Nike City Pulse', 'Nike', 1890, 2390, categories[0].id, PRODUCT_IMAGES[0], True),
            ('Urban Sprint X', 'Adidas', 2190, 2690, categories[1].id, PRODUCT_IMAGES[1], True),
            ('Street Flex Mid', 'Puma', 2490, 2990, categories[2].id, PRODUCT_IMAGES[2], True),
            ('Coast Walk Air', 'BirkenStyle', 1490, 0, categories[3].id, PRODUCT_IMAGES[3], False),
            ('Glow Step Women', 'Nike', 1990, 2490, categories[4].id, PRODUCT_IMAGES[4], True),
            ('Core Runner Men', 'New Balance', 2290, 2890, categories[5].id, PRODUCT_IMAGES[5], True),
            ('Cloud Motion', 'Nike', 2590, 3190, categories[0].id, PRODUCT_IMAGES[6], True),
            ('Velvet Pace', 'Adidas', 2090, 2590, categories[4].id, PRODUCT_IMAGES[7], False),
        ]
        for idx, (name, brand, price, original, category_id, image, featured) in enumerate(demo_products):
            product = Product(
                name=name,
                slug=unique_slug(Product, name),
                brand=brand,
                short_description='Moderní pohodlné boty na každý den s měkkým došlapem a čistým retail vzhledem.',
                description='Prémiově působící model se zaměřením na pohodlí, styl a univerzální použití. Vhodný do města, na cesty i na každodenní nošení.',
                price=price,
                original_price=original,
                image=image,
                gallery=image,
                stock=18 + idx,
                featured=featured,
                active=True,
                category_id=category_id,
            )
            db.session.add(product)
            db.session.flush()
            for size in ['36', '37', '38', '39', '40', '41', '42', '43', '44', '45']:
                db.session.add(ProductSize(product_id=product.id, size=size, stock=3 + idx % 4))

    defaults = {
        'site_name': 'BotyZaHubicku.cz',
        'meta_description': 'BotyZaHubicku.cz – stylový e-shop s botami, dopravou zdarma a přehledným adminem.',
        'logo_url': 'logo-bzh.svg',
        'promo_bar': 'Doprava zdarma',
        'search_placeholder': 'Hledat',
        'menu_items': 'Všechny boty,Běžecké,Dámské,Pánské,Sandály',
        'hero_badge': 'Doprava zdarma',
        'hero_title': 'Běžecké, sportovní i elegantní boty',
        'hero_subtitle': 'Lehké, stylové a pohodlné modely pro každý den.',
        'hero_primary_text': 'Nakupovat boty',
        'hero_secondary_text': 'Produkty',
        'hero_feature_1': 'Kurýrem až domů',
        'hero_feature_2': '8–12 dní doručení',
        'hero_feature_3': 'Zabezpečená platba',
        'hero_image_url': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=1600&q=80',
        'hero_stat_1_title': 'Doprava zdarma',
        'hero_stat_1_text': 'na každou objednávku',
        'hero_stat_2_title': 'Nové modely',
        'hero_stat_2_text': 'pravidelně skladem',
        'categories_title': 'Nakupujte podle kategorií',
        'categories_subtitle': 'Každá kategorie má vlastní fotku a vlastní styl.',
        'featured_title': 'Top produkty',
        'featured_subtitle': 'Výběr hlavních modelů pro homepage.',
        'newest_title': 'Novinky',
        'newest_subtitle': 'Nově přidané modely a čerstvé kusy.',
        'contact_email': 'info@botyzahubicku.cz',
        'domain_name': 'botyzahubicku.cz',
        'footer_affiliate_label': 'Affiliate',
        'footer_affiliate_url': '/affiliate',
        'bank_account': '2301234567/2010',
        'bank_iban': 'CZ6508000000192000145399',
        'delivery_text': 'Doručení 8–12 dní až ke dveřím zákazníka zdarma.',
        'smtp_host': '',
        'smtp_port': '587',
        'smtp_username': '',
        'smtp_password': '',
        'smtp_sender': 'info@botyzahubicku.cz',
        'smtp_use_tls': '1',
    }
    for key, value in defaults.items():
        if not SiteSetting.query.filter_by(key=key).first():
            db.session.add(SiteSetting(key=key, value=value))

    if AffiliatePartner.query.count() == 0:
        pepa = AffiliatePartner(name='Pepa', email='pepa@affiliate.local', instagram='@pepa', note='Ukázkový partner')
        ondra = AffiliatePartner(name='Ondra', email='ondra@affiliate.local', instagram='@ondra', note='Ukázkový partner')
        db.session.add_all([pepa, ondra])
        db.session.flush()
        db.session.add_all([
            Coupon(code='PEPA5', label='Pepa 5+5', description='5 % sleva klient + 5 % partner', discount_percent_client=5, commission_percent_partner=5, affiliate_partner_id=pepa.id),
            Coupon(code='ONDRA10', label='Ondra 10/0', description='10 % klient + 0 % partner', discount_percent_client=10, commission_percent_partner=0, affiliate_partner_id=ondra.id),
            Coupon(code='ONDRA5', label='Ondra 0/10', description='0 % klient + 10 % partner', discount_percent_client=0, commission_percent_partner=10, affiliate_partner_id=ondra.id),
            Coupon(code='VIP10', label='VIP 10/0', description='10 % klient bez partnera', discount_percent_client=10, commission_percent_partner=0, affiliate_partner_id=None),
        ])

    if Coupon.query.count() == 0:
        db.session.add(Coupon(code='WELCOME5', label='Welcome', description='5 % klient bez partnera', discount_percent_client=5, commission_percent_partner=0, affiliate_partner_id=None))

    db.session.commit()
