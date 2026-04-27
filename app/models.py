from datetime import datetime
from flask_login import UserMixin
from sqlalchemy.orm import validates
from . import db

product_categories = db.Table(
    'product_categories',
    db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True),
    db.Column('category_id', db.Integer, db.ForeignKey('category.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255), default='')
    city = db.Column(db.String(80), default='')
    postal_code = db.Column(db.String(20), default='')
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    orders = db.relationship('Order', backref='user', lazy=True)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    image_url = db.Column(db.String(500), default='')
    description = db.Column(db.String(255), default='')
    products = db.relationship('Product', backref='category', lazy=True)
    show_in_menu = db.Column(db.Boolean, default=True)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    site_name = db.Column(db.String(120), default="BotyZaHubicku.cz")
    hero_title = db.Column(db.String(200), default="Běžecké, sportovní i elegantní boty")
    hero_subtitle = db.Column(db.String(300), default="Lehké, stylové a pohodlné boty pro každý den")

    promo_bar = db.Column(db.String(200), default="Doprava zdarma")

    contact_email = db.Column(db.String(120))
    delivery_text = db.Column(db.String(200), default="Doručení 8–12 dní")
    menu_items = db.Column(db.Text, default="Všechny boty,Běžecké boty,Dámské,Kotníkové boty,Pánské,Sandály")

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    brand = db.Column(db.String(80), nullable=False)
    gender = db.Column(db.String(20), default='unisex')
    short_description = db.Column(db.String(255), default='')
    description = db.Column(db.Text, default='')
    price = db.Column(db.Float, nullable=False)
    original_price = db.Column(db.Float, default=0)
    image = db.Column(db.String(500), default='default-product.svg')
    gallery = db.Column(db.Text, default='')
    stock = db.Column(db.Integer, default=0)
    featured = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)

    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)

    categories = db.relationship(
        'Category',
        secondary=product_categories,
        backref=db.backref('products_multi', lazy='dynamic')
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sizes = db.relationship('ProductSize', backref='product', lazy=True, cascade='all, delete-orphan')
    order_items = db.relationship('OrderItem', backref='product', lazy=True)
    source_url = db.Column(db.String(500))
    specifications = db.Column(db.Text)
    colors = db.Column(db.Text)

    @property
    def discount_percent(self):
        if self.original_price and self.original_price > self.price:
            return int(round((1 - self.price / self.original_price) * 100))
        return 0

    @property
    def gallery_list(self):
        return [g for g in (self.gallery or '').split(',') if g]


class ProductSize(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    size = db.Column(db.String(10), nullable=False)
    stock = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('product_id', 'size', name='uq_product_size'),)


class AffiliatePartner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    instagram = db.Column(db.String(120), default='')
    note = db.Column(db.Text, default='')
    status = db.Column(db.String(30), default='Aktivní')
    commission_balance = db.Column(db.Float, default=0)
    paid_total = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    codes = db.relationship('Coupon', backref='affiliate_partner', lazy=True, foreign_keys='Coupon.affiliate_partner_id')


class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    label = db.Column(db.String(120), default='')
    description = db.Column(db.String(255), default='')
    discount_percent_client = db.Column(db.Float, default=0)
    commission_percent_partner = db.Column(db.Float, default=0)
    affiliate_partner_id = db.Column(db.Integer, db.ForeignKey('affiliate_partner.id'), nullable=True)
    active = db.Column(db.Boolean, default=True)
    max_uses = db.Column(db.Integer, default=0)
    uses_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    orders = db.relationship('Order', backref='coupon', lazy=True)

    @property
    def display_split(self):
        return f'{self.discount_percent_client:.0f}% klient / {self.commission_percent_partner:.0f}% partner'


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    street = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    shipping_method = db.Column(db.String(50), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    shipping_price = db.Column(db.Float, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    discount_amount = db.Column(db.Float, default=0)
    total_price = db.Column(db.Float, nullable=False)
    note = db.Column(db.Text, default='')
    status = db.Column(db.String(30), default='Nová')

    payment_status = db.Column(db.String(20), nullable=False, default='pending')
    variable_symbol = db.Column(db.String(30), unique=True, nullable=True, index=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    fio_transaction_id = db.Column(db.String(100), unique=True, nullable=True)

    coupon_code = db.Column(db.String(40), default='')
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupon.id'), nullable=True)
    affiliate_partner_name = db.Column(db.String(120), default='')
    affiliate_commission_amount = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    qr_payload = db.Column(db.Text, default='')
    qr_image = db.Column(db.String(255), default='')
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    product_name = db.Column(db.String(150), nullable=False)
    size = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    color = db.Column(db.String(80))
    

class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(120), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')

class AffiliatePayoutRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    affiliate_partner_id = db.Column(db.Integer, db.ForeignKey('affiliate_partner.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.Text, default='')
    status = db.Column(db.String(30), default='Čeká')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    partner = db.relationship('AffiliatePartner', backref='payout_requests')

class SiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

    @validates('key')
    def validate_key(self, key, value):
        return value.strip()
