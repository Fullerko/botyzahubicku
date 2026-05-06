import random
import string

from flask import Blueprint, flash, redirect, render_template, request, url_for
from . import db
from .models import AffiliatePartner, Category, Coupon, Order, Product, ProductSize, ProductVariant, SiteSetting, User
from .utils import admin_required, save_image, set_setting, unique_slug, send_email
from .sumool_api import submit_order_to_sumool
from .woocommerce_api import ensure_product_skus_and_variants, submit_order_to_woocommerce, sync_product_to_woocommerce
from datetime import datetime
from sqlalchemy import func
from werkzeug.security import generate_password_hash



admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def _affiliate_code_for_partner(partner):
    base = ''.join(ch for ch in (partner.name or 'PARTNER').upper() if ch.isalnum())[:12] or 'PARTNER'
    code = base
    counter = 2
    while Coupon.query.filter_by(code=code).first():
        code = f"{base}{counter}"
        counter += 1
    return code


def _parse_split_from_note(note):
    note = note or ''
    if '10 % klient / 0 % partner' in note:
        return 10, 0
    if '0 % klient / 10 % partner' in note:
        return 0, 10
    return 5, 5


def _sync_product_after_save(product):
    """Zajistí lokální SKU/varianty a volitelně je pošle do WooCommerce."""
    ensure_product_skus_and_variants(product)
    db.session.commit()
    result = sync_product_to_woocommerce(product)
    if result.get('ok'):
        db.session.commit()
        flash('Produkt, barvy, velikosti a SKU byly automaticky synchronizované do WooCommerce.', 'success')
    else:
        db.session.commit()
        msg = result.get('message', 'WooCommerce synchronizace se neprovedla.')
        flash(f'Produkt je uložený lokálně. WooCommerce: {msg}', 'warning')



@admin_bp.route('/')
@admin_required
def dashboard():
    stats = {
        'products': Product.query.filter_by(active=True).count(),
        'orders': Order.query.filter_by(payment_status='paid').count(),
        'revenue': sum((o.total_price or 0) for o in Order.query.filter_by(payment_status='paid').all()),
        'partners': AffiliatePartner.query.count(),
        'coupon_codes': Coupon.query.count(),
        'affiliate_balance': sum((p.commission_balance or 0) for p in AffiliatePartner.query.all()),
    }

    latest_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()

    return render_template('admin/dashboard.html', stats=stats, latest_orders=latest_orders)

@admin_bp.route('/products')
@admin_required
def products():
    products = Product.query.filter_by(active=True).order_by(Product.created_at.desc()).all()
    return render_template('admin/products.html', products=products)


@admin_bp.route('/products/new', methods=['GET', 'POST'])
@admin_required
def product_new():
    categories = Category.query.order_by(Category.name.asc()).all()
    if request.method == 'POST':
        product = Product(
            name=request.form.get('name', '').strip(),
            slug=unique_slug(Product, request.form.get('name', '')),
            brand=request.form.get('brand', '').strip(),
            short_description=request.form.get('short_description', '').strip(),
            description=request.form.get('description', '').strip(),
            price=float(request.form.get('price', 0) or 0),
            original_price=float(request.form.get('original_price', 0) or 0),
            stock=int(request.form.get('stock', 0) or 0),
            featured=bool(request.form.get('featured')),
            active=bool(request.form.get('active')),
            category_id=int(request.form.get('category_id')),
            image=request.form.get('image_url', '').strip() or 'default-product.svg',
            gallery=request.form.get('gallery', '').strip(),
            source_url=request.form.get('source_url', '').strip(),
            supplier_sku=request.form.get('supplier_sku', '').strip(),
            specifications=request.form.get('specifications', '').strip(),
            colors=request.form.get('colors', '').strip(),
            gender=','.join(request.form.getlist('gender')) or 'unisex',
        )
        image = save_image(request.files.get('image'))
        gallery_files = request.files.getlist('gallery_images')
        gallery_images = []

        for file in gallery_files[:4]:
            saved = save_image(file)
            if saved:
                gallery_images.append(saved)

        if gallery_images:
            product.gallery = ",".join(gallery_images)
        if image:
            product.image = image
        db.session.add(product)
        db.session.flush()

        selected_categories = request.form.getlist('categories')

        if selected_categories:
            product.categories = []
            for cat_id in selected_categories:
                cat = Category.query.get(int(cat_id))
                if cat:
                    product.categories.append(cat)
        else:
            if product.category:
                product.categories.append(product.category)
        sizes = [s.strip() for s in request.form.get('sizes', '').split(',') if s.strip()]
        default_size_stock = max(1, product.stock // max(1, len(sizes) or 1))
        for size in sizes:
            db.session.add(ProductSize(product_id=product.id, size=size, stock=default_size_stock))
        db.session.flush()
        _sync_product_after_save(product)
        return redirect(url_for('admin.products'))
    return render_template('admin/product_form.html', categories=categories, product=None)


@admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    categories = Category.query.order_by(Category.name.asc()).all()
    if request.method == 'POST':
        product.name = request.form.get('name', '').strip()
        product.slug = unique_slug(Product, product.name, current_id=product.id)
        product.brand = request.form.get('brand', '').strip()
        product.short_description = request.form.get('short_description', '').strip()
        product.description = request.form.get('description', '').strip()
        product.price = float(request.form.get('price', 0) or 0)
        product.original_price = float(request.form.get('original_price', 0) or 0)
        product.stock = int(request.form.get('stock', 0) or 0)
        product.featured = bool(request.form.get('featured'))
        product.active = bool(request.form.get('active'))
        product.category_id = int(request.form.get('category_id'))
        selected_categories = request.form.getlist('categories')
        product.gender = ','.join(request.form.getlist('gender')) or 'unisex'

        product.categories = []

        if selected_categories:
            for cat_id in selected_categories:
                cat = Category.query.get(int(cat_id))
                if cat:
                    product.categories.append(cat)
        else:
            if product.category:
                product.categories.append(product.category)
        product.image = request.form.get('image_url', '').strip() or product.image

        new_gallery_text = request.form.get('gallery', '').strip()
        if new_gallery_text:
            product.gallery = new_gallery_text
                
        image = save_image(request.files.get('image'))
        gallery_files = request.files.getlist('gallery_images')
        gallery_images = []
        product.specifications = request.form.get('specifications', '').strip()
        product.colors = request.form.get('colors', '').strip()

        for file in gallery_files[:4]:
            saved = save_image(file)
            if saved:
                gallery_images.append(saved)

        if gallery_images:
            product.gallery = ",".join(gallery_images)
        product.source_url = request.form.get('source_url', '').strip()
        product.supplier_sku = request.form.get('supplier_sku', '').strip()
        if image:
            product.image = image
        ProductSize.query.filter_by(product_id=product.id).delete()
        sizes = [s.strip() for s in request.form.get('sizes', '').split(',') if s.strip()]
        default_size_stock = max(1, product.stock // max(1, len(sizes) or 1))
        for size in sizes:
            db.session.add(ProductSize(product_id=product.id, size=size, stock=default_size_stock))
        db.session.flush()
        _sync_product_after_save(product)
        return redirect(url_for('admin.products'))
    return render_template('admin/product_form.html', categories=categories, product=product)


@admin_bp.route('/products/<int:product_id>/woocommerce/sync', methods=['POST'])
@admin_required
def product_woocommerce_sync(product_id):
    product = Product.query.get_or_404(product_id)
    _sync_product_after_save(product)
    return redirect(url_for('admin.product_edit', product_id=product.id))


@admin_bp.route('/products/<int:product_id>/delete')
@admin_required
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)

    product.active = False
    db.session.commit()

    flash('Produkt byl skrytý.', 'info')
    return redirect(url_for('admin.products'))


@admin_bp.route('/orders')
@admin_required
def orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders)


@admin_bp.route('/orders/<int:order_id>', methods=['GET', 'POST'])
@admin_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)
    if request.method == 'POST':
        order.status = request.form.get('status', 'Nová')
        if order.status == 'Zaplaceno' and order.payment_status != 'paid':
            order.payment_status = 'paid'
            order.paid_at = datetime.now()
        db.session.commit()
        flash('Stav objednávky byl změněn.', 'success')
    return render_template('admin/order_detail.html', order=order, Product=Product)


@admin_bp.route('/orders/<int:order_id>/sumool/send', methods=['POST'])
@admin_required
def order_sumool_send(order_id):
    order = Order.query.get_or_404(order_id)
    result = submit_order_to_sumool(order)
    order.sumool_status = 'odeslano' if result.get('ok') else 'chyba'
    order.sumool_message = result.get('message', '')
    order.sumool_response = result.get('raw') or ''
    order.sumool_submitted_at = datetime.now()
    db.session.commit()
    flash('Objednávka byla odeslána do Sumool API.' if result.get('ok') else f'Sumool chyba: {result.get("message", "neznámá chyba")}', 'success' if result.get('ok') else 'danger')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/orders/<int:order_id>/woocommerce/send', methods=['POST'])
@admin_required
def order_woocommerce_send(order_id):
    order = Order.query.get_or_404(order_id)
    result = submit_order_to_woocommerce(order)
    order.woocommerce_status = 'odeslano' if result.get('ok') else 'chyba'
    order.woocommerce_message = result.get('message', '')
    order.woocommerce_response = result.get('raw') or ''
    order.woocommerce_submitted_at = datetime.now()
    data = result.get('data') or {}
    if data.get('id'):
        order.woocommerce_order_id = str(data.get('id'))
    db.session.commit()
    flash('Objednávka byla odeslána do WooCommerce.' if result.get('ok') else f'WooCommerce chyba: {result.get("message", "neznámá chyba")}', 'success' if result.get('ok') else 'danger')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/affiliate')
@admin_required
def affiliate_dashboard():
    partners = AffiliatePartner.query.order_by(AffiliatePartner.created_at.desc()).all()
    coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    orders = Order.query.all()

    total_commission_earned = sum(
        (o.affiliate_commission_amount or 0) for o in orders if o.payment_status == 'paid'
    )

    total_commission_balance = sum(p.commission_balance or 0 for p in partners)
    total_commission_paid = sum(p.paid_total or 0 for p in partners)

    return render_template(
        'admin/affiliate_dashboard.html',
        partners=partners,
        coupons=coupons,
        total_commission_earned=total_commission_earned,
        total_commission_balance=total_commission_balance,
        total_commission_paid=total_commission_paid
    )


@admin_bp.route('/affiliate/partners/new', methods=['GET', 'POST'])
@admin_required
def affiliate_partner_new():
    if request.method == 'POST':
        partner = AffiliatePartner(
            name=request.form.get('name', '').strip(),
            email=request.form.get('email', '').strip(),
            instagram=request.form.get('instagram', '').strip(),
            note=request.form.get('note', '').strip(),
            status=request.form.get('status', 'Aktivní').strip(),
        )
        db.session.add(partner)
        db.session.commit()
        flash('Affiliate partner byl vytvořen.', 'success')
        return redirect(url_for('admin.affiliate_dashboard'))
    return render_template('admin/affiliate_partner_form.html', partner=None)


@admin_bp.route('/affiliate/partners/<int:partner_id>/approve', methods=['POST'])
@admin_required
def affiliate_partner_approve(partner_id):
    partner = AffiliatePartner.query.get_or_404(partner_id)
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    user = User.query.filter_by(email=partner.email).first()
    created_user = False
    if not user:
        user = User(email=partner.email, full_name=partner.name, password_hash=generate_password_hash(password), is_admin=False)
        db.session.add(user)
        created_user = True

    partner.status = 'Aktivní'
    if not partner.codes:
        client_percent, partner_percent = _parse_split_from_note(partner.note)
        db.session.add(Coupon(
            code=_affiliate_code_for_partner(partner),
            label=f'Affiliate {partner.name}',
            description='Automaticky vytvořený affiliate kód',
            discount_percent_client=client_percent,
            commission_percent_partner=partner_percent,
            affiliate_partner_id=partner.id,
            active=True,
            max_uses=0,
        ))
    db.session.commit()

    if created_user:
        try:
            send_email(
                subject='Affiliate účet byl schválen',
                to_email=partner.email,
                html_body=f'<p>Dobrý den, váš affiliate účet byl schválen.</p><p>Přihlášení: <strong>{partner.email}</strong><br>Heslo: <strong>{password}</strong></p><p>Portál najdete na /affiliate/portal.</p>',
                text_body=f'Dobrý den, váš affiliate účet byl schválen. Přihlášení: {partner.email} Heslo: {password} Portál: /affiliate/portal',
            )
            flash('Partner byl schválen, účet a kód byly vytvořeny. Přihlašovací údaje byly odeslány e-mailem.', 'success')
        except Exception:
            flash(f'Partner byl schválen. Účet vytvořen: {partner.email}, dočasné heslo: {password}', 'warning')
    else:
        flash('Partner byl schválen a napojen na existující účet.', 'success')
    return redirect(url_for('admin.affiliate_dashboard'))


@admin_bp.route('/affiliate/partners/<int:partner_id>/reject', methods=['POST'])
@admin_required
def affiliate_partner_reject(partner_id):
    partner = AffiliatePartner.query.get_or_404(partner_id)
    partner.status = 'Odmítnuto'
    db.session.commit()
    flash('Žádost byla odmítnuta.', 'info')
    return redirect(url_for('admin.affiliate_dashboard'))


@admin_bp.route('/affiliate/partners/<int:partner_id>/edit', methods=['GET', 'POST'])
@admin_required
def affiliate_partner_edit(partner_id):
    partner = AffiliatePartner.query.get_or_404(partner_id)
    if request.method == 'POST':
        partner.name = request.form.get('name', '').strip()
        partner.email = request.form.get('email', '').strip()
        partner.instagram = request.form.get('instagram', '').strip()
        partner.note = request.form.get('note', '').strip()
        partner.status = request.form.get('status', 'Aktivní').strip()
        if request.form.get('pay_amount'):
            amount = float(request.form.get('pay_amount') or 0)
            partner.commission_balance = max(0, partner.commission_balance - amount)
            partner.paid_total += amount
        db.session.commit()
        flash('Affiliate partner byl upraven.', 'success')
        return redirect(url_for('admin.affiliate_dashboard'))
    return render_template('admin/affiliate_partner_form.html', partner=partner)


@admin_bp.route('/affiliate/coupons/new', methods=['GET', 'POST'])
@admin_required
def coupon_new():
    partners = AffiliatePartner.query.order_by(AffiliatePartner.name.asc()).all()
    if request.method == 'POST':
        coupon = Coupon(
            code=request.form.get('code', '').strip().upper(),
            label=request.form.get('label', '').strip(),
            description=request.form.get('description', '').strip(),
            discount_percent_client=float(request.form.get('discount_percent_client', 0) or 0),
            commission_percent_partner=float(request.form.get('commission_percent_partner', 0) or 0),
            affiliate_partner_id=int(request.form.get('affiliate_partner_id')) if request.form.get('affiliate_partner_id') else None,
            active=bool(request.form.get('active')),
            max_uses=int(request.form.get('max_uses', 0) or 0),
        )
        db.session.add(coupon)
        db.session.commit()
        flash('Kód byl vytvořen.', 'success')
        return redirect(url_for('admin.affiliate_dashboard'))
    return render_template('admin/coupon_form.html', coupon=None, partners=partners)


@admin_bp.route('/affiliate/coupons/<int:coupon_id>/edit', methods=['GET', 'POST'])
@admin_required
def coupon_edit(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    partners = AffiliatePartner.query.order_by(AffiliatePartner.name.asc()).all()
    if request.method == 'POST':
        coupon.code = request.form.get('code', '').strip().upper()
        coupon.label = request.form.get('label', '').strip()
        coupon.description = request.form.get('description', '').strip()
        coupon.discount_percent_client = float(request.form.get('discount_percent_client', 0) or 0)
        coupon.commission_percent_partner = float(request.form.get('commission_percent_partner', 0) or 0)
        coupon.affiliate_partner_id = int(request.form.get('affiliate_partner_id')) if request.form.get('affiliate_partner_id') else None
        coupon.active = bool(request.form.get('active'))
        coupon.max_uses = int(request.form.get('max_uses', 0) or 0)
        db.session.commit()
        flash('Kód byl upraven.', 'success')
        return redirect(url_for('admin.affiliate_dashboard'))
    return render_template('admin/coupon_form.html', coupon=coupon, partners=partners)


@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    settings = {s.key: s.value for s in SiteSetting.query.order_by(SiteSetting.key.asc()).all()}
    sections = {
        'Brand a navigace': [
            ('site_name', 'Název webu'),
            ('meta_description', 'Meta popis'),
            ('logo_url', 'Logo URL nebo název souboru ve static/uploads'),
            ('promo_bar', 'Horní žlutý pruh'),
            ('search_placeholder', 'Placeholder vyhledávání'),
            ('menu_items', 'Menu nahoře (oddělit čárkou)'),
        ],
        'Hero sekce': [
            ('hero_badge', 'Badge nad nadpisem'),
            ('hero_title', 'Hlavní nadpis'),
            ('hero_subtitle', 'Podnadpis'),
            ('hero_primary_text', 'Primární tlačítko'),
            ('hero_secondary_text', 'Sekundární tlačítko'),
            ('hero_feature_1', 'Info pill 1'),
            ('hero_feature_2', 'Info pill 2'),
            ('hero_feature_3', 'Info pill 3'),
            ('hero_image_url', 'Hero obrázek URL'),
            ('hero_stat_1_title', 'Mini box 1 nadpis'),
            ('hero_stat_1_text', 'Mini box 1 text'),
            ('hero_stat_2_title', 'Mini box 2 nadpis'),
            ('hero_stat_2_text', 'Mini box 2 text'),
        ],
        'Homepage sekce': [
            ('categories_title', 'Nadpis kategorií'),
            ('categories_subtitle', 'Podnadpis kategorií'),
            ('featured_title', 'Nadpis top produktů'),
            ('featured_subtitle', 'Podnadpis top produktů'),
            ('newest_title', 'Nadpis novinek'),
            ('newest_subtitle', 'Podnadpis novinek'),
        ],
        'Kontakt a footer': [
            ('contact_email', 'Kontaktní e-mail'),
            ('domain_name', 'Doména'),
            ('delivery_text', 'Text dopravy'),
            ('footer_affiliate_label', 'Spodní odkaz affiliate - text'),
            ('footer_affiliate_url', 'Spodní odkaz affiliate - URL'),
        ],
        'Platba a e-mail': [
            ('bank_account', 'Číslo účtu'),
            ('bank_iban', 'IBAN'),
            ('smtp_host', 'SMTP host'),
            ('smtp_port', 'SMTP port'),
            ('smtp_username', 'SMTP uživatel'),
            ('smtp_password', 'SMTP heslo'),
            ('smtp_sender', 'SMTP odesílatel'),
            ('smtp_use_tls', 'SMTP TLS (1 nebo 0)'),
        ],
        'Sumool / dodavatel API': [
            ('sumool_enabled', 'Zapnout automatické odesílání objednávek do Sumool (1 nebo 0)'),
            ('sumool_base_url', 'Sumool API URL, např. https://hzmhkj.sumool.com'),
            ('sumool_tokenkeys', 'Tokenkeys'),
            ('sumool_tokens', 'Tokens / API key'),
            ('sumool_user_id', 'UserId obchodu u dodavatele'),
            ('sumool_currency', 'Měna objednávky, např. CZK'),
            ('sumool_default_country', 'Výchozí země zákazníka, např. CZ'),
            ('sumool_store_no', 'StoreNo / sklad, volitelné'),
            ('sumool_logistic_name', 'LogisticName, volitelné'),
            ('sumool_logistic_mode_code', 'LogisticModeCode, volitelné'),
        ],
        'WooCommerce / dodavatel API': [
            ('woocommerce_enabled', 'Zapnout automatické odesílání objednávek do WooCommerce (1 nebo 0)'),
            ('woocommerce_base_url', 'WooCommerce URL, např. https://dodavatel.cz'),
            ('woocommerce_consumer_key', 'WooCommerce Consumer Key'),
            ('woocommerce_consumer_secret', 'WooCommerce Consumer Secret'),
            ('woocommerce_order_status', 'Stav nové objednávky ve WooCommerce, např. processing'),
            ('woocommerce_auto_sync_products', 'Automaticky vytvářet/upravovat produkty a varianty ve WooCommerce (1 nebo 0)'),
            ('woocommerce_sku_prefix', 'Prefix automatického SKU, např. BZH'),
            ('woocommerce_currency', 'Měna objednávky, např. CZK'),
            ('woocommerce_default_country', 'Výchozí země zákazníka, např. CZ'),
        ],
    }

    if request.method == 'POST':
        for fields in sections.values():
            for key, _label in fields:
                set_setting(key, request.form.get(key, ''))
        db.session.commit()
        flash('Nastavení bylo uloženo.', 'success')
        return redirect(url_for('admin.settings'))

    return render_template('admin/settings.html', settings=settings, sections=sections)
