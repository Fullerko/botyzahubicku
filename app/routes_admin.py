import json
import mimetypes
import os
import random
import string
import uuid

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for
from . import db
from .models import AffiliatePartner, BlogPost, Category, Coupon, EmailAttachment, EmailCampaign, EmailCampaignRecipient, EmailContact, Order, Product, ProductSize, ProductVariant, SiteSetting, User
from .utils import admin_required, save_image, set_setting, setting, unique_slug, send_email
from .supplier_import import import_supplier_sku_file
from .supplier_report_utils import generate_supplier_orders_pdf, get_pending_supplier_orders, send_supplier_orders_report
from .emailing_service import contacts_query, enqueue_campaign, ensure_suppression, retry_failed_recipients, send_campaign_batch, send_test_campaign_email, sync_existing_contacts
from .seo_generator import generate_daily_seo_content, regenerate_all_generated_content, regenerate_blog_content, regenerate_category_content
from datetime import datetime
from sqlalchemy import func
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
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
    """Uloží produkt lokálně bez WooCommerce synchronizace."""
    db.session.commit()
    flash('Produkt byl uložen lokálně bez WooCommerce synchronizace.', 'success')



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
        'email_contacts': EmailContact.query.filter(EmailContact.deleted_at.is_(None)).count(),
        'seo_drafts': BlogPost.query.filter_by(status='draft').count() + Category.query.filter_by(seo_generated=True, seo_published=False).count(),
    }

    latest_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()

    return render_template('admin/dashboard.html', stats=stats, latest_orders=latest_orders)

def _float_form(name, default=0):
    try:
        return float(str(request.form.get(name, default) or default).replace(',', '.'))
    except Exception:
        return float(default or 0)


def _int_form(name, default=0):
    try:
        return int(float(str(request.form.get(name, default) or default).replace(',', '.')))
    except Exception:
        return int(default or 0)


def _normalize_brand(value, default='Fashion'):
    brand = (value or '').strip()
    if not brand or brand.casefold() == 'wc':
        return default
    return brand


def _selected_gender(default='unisex'):
    values = request.form.getlist('gender')
    if values:
        return ','.join(values)
    return request.form.get('gender', default) or default


def _primary_gender(value):
    parts = [part.strip() for part in (value or '').split(',') if part.strip()]
    if 'damske' in parts:
        return 'damske'
    if 'panske' in parts:
        return 'panske'
    return parts[0] if parts else 'unisex'



def expand_size_range(value):
    """Převede text velikostí na seznam.

    Podporuje:
    - "35-40" -> ["35", "36", "37", "38", "39", "40"]
    - "35,36,37" -> ["35", "36", "37"]
    - kombinace: "35-37,40"
    """
    raw = str(value or '').replace(';', ',')
    sizes = []

    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            start_raw, end_raw = part.split('-', 1)
            start_raw = start_raw.strip()
            end_raw = end_raw.strip()

            try:
                start = int(float(start_raw.replace(',', '.')))
                end = int(float(end_raw.replace(',', '.')))
            except Exception:
                if part not in sizes:
                    sizes.append(part)
                continue

            if start <= end:
                for number in range(start, end + 1):
                    item = str(number)
                    if item not in sizes:
                        sizes.append(item)
            else:
                for number in range(start, end - 1, -1):
                    item = str(number)
                    if item not in sizes:
                        sizes.append(item)
        else:
            if part not in sizes:
                sizes.append(part)

    return sizes


def _size_sort_key(value):
    value = str(value or '').strip()
    try:
        return (0, int(float(value.replace(',', '.'))))
    except Exception:
        return (1, value.lower())


def format_product_sizes(product):
    values = []
    for size_row in getattr(product, 'sizes', []) or []:
        value = str(getattr(size_row, 'size', '') or '').strip()
        if value and value not in values:
            values.append(value)

    if not values:
        return 'Nenastaveno'

    values = sorted(values, key=_size_sort_key)

    numeric_values = []
    for value in values:
        try:
            numeric_values.append(int(float(value.replace(',', '.'))))
        except Exception:
            numeric_values = []
            break

    if numeric_values and len(numeric_values) == len(values):
        unique_numbers = sorted(set(numeric_values))
        if len(unique_numbers) == 1:
            return str(unique_numbers[0])
        if unique_numbers == list(range(unique_numbers[0], unique_numbers[-1] + 1)):
            return f'{unique_numbers[0]}-{unique_numbers[-1]}'
        return ', '.join(str(number) for number in unique_numbers)

    return ', '.join(values)


def _product_payload_from_form(product=None):
    return {
        'name': request.form.get('name', getattr(product, 'name', '') if product else '').strip(),
        'brand': _normalize_brand(request.form.get('brand', getattr(product, 'brand', '') if product else '')),
        'slug': request.form.get('slug', getattr(product, 'slug', '') if product else '').strip(),
        'short_description': request.form.get('short_description', getattr(product, 'short_description', '') if product else '').strip(),
        'description': request.form.get('description', getattr(product, 'description', '') if product else '').strip(),
        'seo_title': request.form.get('seo_title', getattr(product, 'seo_title', '') if product else '').strip(),
        'meta_description': request.form.get('meta_description', getattr(product, 'meta_description', '') if product else '').strip(),
        'seo_keywords': request.form.get('seo_keywords', getattr(product, 'seo_keywords', '') if product else '').strip(),
        'image_alt': request.form.get('image_alt', getattr(product, 'image_alt', '') if product else '').strip(),
        'specifications': request.form.get('specifications', getattr(product, 'specifications', '') if product else '').strip(),
        'sizes': request.form.get('sizes', '').strip() if request.form.get('sizes') is not None else ','.join([s.size for s in getattr(product, 'sizes', [])]),
        'colors': request.form.get('colors', getattr(product, 'colors', '') if product else '').strip(),
        'source_url': request.form.get('source_url', getattr(product, 'source_url', '') if product else '').strip(),
        'supplier_sku': request.form.get('supplier_sku', getattr(product, 'supplier_sku', '') if product else '').strip(),
        'gender': _selected_gender(getattr(product, 'gender', 'unisex') if product else 'unisex'),
        'price': str(request.form.get('price', getattr(product, 'price', '') if product else '')).strip(),
        'original_price': str(request.form.get('original_price', getattr(product, 'original_price', '') if product else '')).strip(),
    }





@admin_bp.route('/import-1688', methods=['GET', 'POST'])
@admin_required
def import_1688():
    """Bezpečná záslepka pro staré odkazy v šablonách."""
    flash('Import z 1688 je vypnutý. Produkt prosím přidej ručně.', 'info')
    return redirect(url_for('admin.products'))


@admin_bp.route('/products')
@admin_required
def products():
    search_query = (request.args.get('q') or '').strip()
    products_query = Product.query.filter_by(active=True)

    if search_query:
        products_query = products_query.filter(Product.name.ilike(f'%{search_query}%'))

    products = products_query.order_by(Product.created_at.desc()).all()
    return render_template(
        'admin/products.html',
        products=products,
        search_query=search_query,
        format_product_sizes=format_product_sizes,
    )


@admin_bp.route('/products/new', methods=['GET', 'POST'])
@admin_required
def product_new():
    categories = Category.query.order_by(Category.name.asc()).all()
    if request.method == 'POST':
        category_id = request.form.get('category_id')
        category = Category.query.get(int(category_id)) if category_id else None
        if not category:
            flash('Vyber prosím hlavní kategorii produktu.', 'warning')
            return render_template('admin/product_form.html', categories=categories, product=None)

        payload = _product_payload_from_form()

        product_name = payload.get('name') or f"{category.name} {''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
        product = Product(
            name=product_name,
            slug=unique_slug(Product, payload.get('slug') or product_name),
            brand=payload.get('brand') or 'Fashion',
            short_description=payload.get('short_description', ''),
            description=payload.get('description', ''),
            seo_title=payload.get('seo_title', ''),
            meta_description=payload.get('meta_description', ''),
            seo_keywords=payload.get('seo_keywords', ''),
            image_alt=payload.get('image_alt', ''),
            price=_float_form('price', 0),
            original_price=_float_form('original_price', 0),
            stock=_int_form('stock', 0),
            featured=bool(request.form.get('featured')),
            active=bool(request.form.get('active')),
            category_id=category.id,
            image=request.form.get('image_url', '').strip() or 'default-product.svg',
            gallery=request.form.get('gallery', '').strip(),
            source_url=payload.get('source_url', ''),
            supplier_sku=payload.get('supplier_sku', ''),
            specifications=payload.get('specifications', ''),
            colors=payload.get('colors', ''),
            gender=payload.get('gender') or 'unisex',
        )
        image = save_image(request.files.get('image'))
        gallery_files = request.files.getlist('gallery_images')
        gallery_images = []

        for file in gallery_files[:8]:
            saved = save_image(file)
            if saved:
                gallery_images.append(saved)

        if gallery_images:
            product.gallery = ','.join(gallery_images)
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
            product.categories.append(category)

        sizes = expand_size_range(payload.get('sizes', ''))
        if not sizes:
            sizes = expand_size_range('35-40' if _primary_gender(product.gender) == 'damske' else '39-45' if _primary_gender(product.gender) == 'panske' else '36-44')
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
        category_id = request.form.get('category_id')
        category = Category.query.get(int(category_id)) if category_id else product.category
        if not category:
            flash('Vyber prosím hlavní kategorii produktu.', 'warning')
            return render_template('admin/product_form.html', categories=categories, product=product)

        payload = _product_payload_from_form(product)

        product.name = payload.get('name') or product.name
        product_slug = payload.get('slug') or product.name
        product.slug = unique_slug(Product, product_slug, current_id=product.id)
        product.brand = payload.get('brand') or product.brand or 'Fashion'
        product.short_description = payload.get('short_description', '')
        product.description = payload.get('description', '')
        product.seo_title = payload.get('seo_title', '')
        product.meta_description = payload.get('meta_description', '')
        product.seo_keywords = payload.get('seo_keywords', '')
        product.image_alt = payload.get('image_alt', '')
        product.price = _float_form('price', 0)
        product.original_price = _float_form('original_price', 0)
        product.stock = _int_form('stock', 0)
        product.featured = bool(request.form.get('featured'))
        product.active = bool(request.form.get('active'))
        product.category_id = category.id
        selected_categories = request.form.getlist('categories')
        product.gender = payload.get('gender') or 'unisex'

        product.categories = []

        if selected_categories:
            for cat_id in selected_categories:
                cat = Category.query.get(int(cat_id))
                if cat:
                    product.categories.append(cat)
        else:
            product.categories.append(category)
        product.image = request.form.get('image_url', '').strip() or product.image
        if request.form.get('delete_main_image'):
            product.image = 'default-product.svg'

        existing_gallery = list(product.gallery_list)
        delete_gallery_images = set(request.form.getlist('delete_gallery_images'))
        existing_gallery = [img for img in existing_gallery if img not in delete_gallery_images]

        new_gallery_text = request.form.get('gallery', '').strip()
        if new_gallery_text:
            existing_gallery = [img.strip() for img in new_gallery_text.split(',') if img.strip()]

        image = save_image(request.files.get('image'))
        gallery_files = request.files.getlist('gallery_images')
        gallery_images = []
        product.specifications = payload.get('specifications', '')
        product.colors = payload.get('colors', '')

        for file in gallery_files[:8]:
            saved = save_image(file)
            if saved:
                gallery_images.append(saved)

        product.gallery = ','.join(existing_gallery + gallery_images)
        product.source_url = payload.get('source_url', '')
        product.supplier_sku = payload.get('supplier_sku', '')
        if image:
            product.image = image
        ProductSize.query.filter_by(product_id=product.id).delete()
        sizes = expand_size_range(payload.get('sizes', ''))
        if not sizes:
            sizes = expand_size_range('35-40' if _primary_gender(product.gender) == 'damske' else '39-45' if _primary_gender(product.gender) == 'panske' else '36-44')
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
    """Bezpečná záslepka pro staré WooCommerce tlačítko v šabloně."""
    product = Product.query.get_or_404(product_id)
    db.session.commit()
    flash('WooCommerce synchronizace je vypnutá. Produkt zůstal uložený pouze lokálně.', 'info')
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




@admin_bp.route('/orders/<int:order_id>/woocommerce/send', methods=['POST'])
@admin_required
def order_woocommerce_send(order_id):
    """Bezpečná záslepka pro staré WooCommerce tlačítko u objednávky."""
    order = Order.query.get_or_404(order_id)
    db.session.commit()
    flash('WooCommerce odesílání objednávky je vypnuté. Objednávka zůstala pouze lokálně.', 'info')
    return redirect(url_for('admin.order_detail', order_id=order.id))


@admin_bp.route('/supplier-report/send-now', methods=['POST'])
@admin_required
def supplier_report_send_now():
    result = send_supplier_orders_report()
    if result.get('ok') and result.get('sent'):
        flash(
            f'Dodavatelský PDF report byl odeslán na {result.get("recipient")} '
            f'({result.get("count")} objednávek, {result.get("pdf_size_bytes")} B).',
            'success'
        )
    elif result.get('ok'):
        flash(f'Dodavatelský PDF report nebyl odeslán: {result.get("message")}.', 'info')
    else:
        flash(f'Dodavatelský PDF report se nepodařilo odeslat: {result.get("message")}.', 'danger')
    return redirect(url_for('admin.orders'))


@admin_bp.route('/supplier-report/preview.pdf')
@admin_required
def supplier_report_preview_pdf():
    orders = get_pending_supplier_orders()
    if not orders:
        flash('Nejsou žádné nové objednávky pro dodavatelský report.', 'info')
        return redirect(url_for('admin.orders'))
    pdf = generate_supplier_orders_pdf(orders, batch_id='BZH-SUP-PREVIEW')
    return send_file(
        pdf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='supplier_orders_preview.pdf',
    )


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
    flash('Affiliate přístup byl odebrán.', 'info')
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


@admin_bp.route('/supplier-sku-import', methods=['GET', 'POST'])
@admin_required
def supplier_sku_import():
    result = None
    if request.method == 'POST':
        uploaded = request.files.get('supplier_file')
        update_woocommerce = False
        if not uploaded or not uploaded.filename:
            flash('Nahraj prosím CSV nebo XLSX soubor od dodavatele.', 'warning')
        else:
            try:
                result = import_supplier_sku_file(uploaded, update_woocommerce=update_woocommerce)
                db.session.commit()
                message = f"Import hotový: spárováno {result['matched']} z {result['total']} řádků."
                if update_woocommerce:
                    message += f" WooCommerce aktualizováno: {result['updated_wc']}, chyby: {result['wc_errors']}."
                if result['unmatched'] or result['missing_supplier_sku']:
                    flash(message + ' Některé řádky je potřeba zkontrolovat dole v přehledu.', 'warning')
                else:
                    flash(message, 'success')
            except Exception as exc:
                db.session.rollback()
                flash(f'Import se nepovedl: {exc}', 'danger')
    return render_template('admin/supplier_sku_import.html', result=result)


EMAIL_SEGMENTS = [
    ('all', 'Všechny aktivní kontakty'),
    ('ordered', 'Objednali aspoň jednou'),
    ('paid', 'Objednali a zaplatili'),
    ('unpaid', 'Vytvořili objednávku, ale nezaplatili'),
    ('cart', 'Zadali e-mail v košíku / checkoutu'),
    ('abandoned', 'Košík bez objednávky'),
    ('affiliate', 'Affiliate partneři'),
    ('manual', 'Ručně vybrané kontakty'),
    ('unsubscribed', 'Odhlášení / blokovaní'),
]


def _pagination_args(default_per_page=50):
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(200, max(10, request.args.get('per_page', default_per_page, type=int)))
    return page, per_page


def _safe_int_list(values):
    ids = []
    for value in values:
        for part in str(value or '').replace(';', ',').split(','):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except Exception:
                continue
    return sorted(set(ids))


def _campaign_from_form(campaign):
    campaign.title = request.form.get('title', '').strip() or request.form.get('subject', '').strip() or 'Nová kampaň'
    campaign.subject = request.form.get('subject', '').strip() or campaign.title
    campaign.html_body = request.form.get('html_body', '').strip()
    campaign.text_body = request.form.get('text_body', '').strip()
    campaign.segment_type = request.form.get('segment_type', 'all').strip() or 'all'
    recipient_mode = request.form.get('recipient_mode', 'all').strip() or 'all'
    campaign.recipient_mode = recipient_mode if recipient_mode in ('all', 'new') else 'all'
    campaign.batch_size = max(1, min(1000, int(request.form.get('batch_size', setting('emailing_batch_size', '50')) or 50)))
    campaign.delay_seconds = max(0, min(60, int(request.form.get('delay_seconds', setting('emailing_delay_seconds', '0')) or 0)))

    selected_ids = _safe_int_list(request.form.getlist('contact_ids') + [request.form.get('selected_contact_ids', '')])
    excluded_ids = _safe_int_list([request.form.get('excluded_contact_ids', '')])
    campaign.selected_contact_ids = json.dumps(selected_ids)
    campaign.excluded_contact_ids = json.dumps(excluded_ids)
    campaign.filters_json = json.dumps({
        'segment': campaign.segment_type,
        'search': request.form.get('contact_search', '').strip(),
        'include_unsubscribed': bool(request.form.get('include_unsubscribed')),
    }, ensure_ascii=False)
    return campaign


def _save_campaign_attachments(campaign):
    files = request.files.getlist('attachments')
    if not files:
        return 0
    max_mb = int(setting('emailing_max_attachment_mb', '10') or 10)
    max_bytes = max_mb * 1024 * 1024
    base_folder = current_app.config.get('EMAIL_ATTACHMENT_FOLDER') or os.path.join(current_app.instance_path, 'email_attachments')
    campaign_folder = os.path.join(base_folder, str(campaign.id))
    os.makedirs(campaign_folder, exist_ok=True)
    saved = 0
    for uploaded in files:
        if not uploaded or not uploaded.filename:
            continue
        original = secure_filename(uploaded.filename)
        if not original:
            continue
        uploaded.stream.seek(0, os.SEEK_END)
        size = uploaded.stream.tell()
        uploaded.stream.seek(0)
        if size > max_bytes:
            flash(f'Příloha {original} je větší než limit {max_mb} MB a nebyla uložena.', 'warning')
            continue
        stored = f'{uuid.uuid4().hex}_{original}'
        path = os.path.join(campaign_folder, stored)
        uploaded.save(path)
        mime_type = mimetypes.guess_type(original)[0] or 'application/octet-stream'
        db.session.add(EmailAttachment(
            campaign_id=campaign.id,
            filename=original,
            stored_filename=stored,
            file_path=path,
            mime_type=mime_type,
            size_bytes=size,
        ))
        saved += 1
    return saved


def _campaign_contact_options(campaign=None):
    segment = request.args.get('segment_type') or request.form.get('segment_type') or getattr(campaign, 'segment_type', 'all') or 'all'
    search = request.args.get('contact_search') or request.form.get('contact_search') or ''
    return contacts_query(segment=segment, search=search).order_by(EmailContact.email.asc()).limit(250).all()


@admin_bp.route('/emailing')
@admin_required
def emailing_index():
    stats = {
        'contacts': EmailContact.query.filter(EmailContact.deleted_at.is_(None)).count(),
        'subscribed': EmailContact.query.filter(EmailContact.deleted_at.is_(None), EmailContact.marketing_enabled.is_(True), EmailContact.unsubscribed_at.is_(None)).count(),
        'cart': EmailContact.query.filter(EmailContact.deleted_at.is_(None), EmailContact.has_cart.is_(True)).count(),
        'ordered': EmailContact.query.filter(EmailContact.deleted_at.is_(None), EmailContact.has_order.is_(True)).count(),
        'campaigns': EmailCampaign.query.count(),
        'queued': EmailCampaign.query.filter(EmailCampaign.status.in_(('queued', 'sending', 'paused'))).count(),
    }
    latest_campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).limit(8).all()
    return render_template('admin/emailing/index.html', stats=stats, latest_campaigns=latest_campaigns)


@admin_bp.route('/emailing/sync', methods=['POST'])
@admin_required
def emailing_sync():
    count = sync_existing_contacts()
    flash(f'Kontakty byly synchronizovány z objednávek a affiliate partnerů. Zpracováno: {count}.', 'success')
    return redirect(url_for('admin.emailing_contacts'))


@admin_bp.route('/emailing/contacts')
@admin_required
def emailing_contacts():
    q = request.args.get('q', '').strip()
    segment = request.args.get('segment', 'all').strip() or 'all'
    include_deleted = bool(request.args.get('deleted'))
    page, per_page = _pagination_args(50)
    query = contacts_query(segment=segment, search=q, include_deleted=include_deleted).order_by(EmailContact.updated_at.desc(), EmailContact.email.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        'admin/emailing/contacts.html',
        contacts=pagination.items,
        pagination=pagination,
        q=q,
        segment=segment,
        segments=EMAIL_SEGMENTS,
        include_deleted=include_deleted,
    )


@admin_bp.route('/emailing/contacts/bulk', methods=['POST'])
@admin_required
def emailing_contacts_bulk():
    action = request.form.get('action', '')
    selected_ids = _safe_int_list(request.form.getlist('contact_ids'))
    if request.form.get('all_filtered'):
        q = request.form.get('q', '').strip()
        segment = request.form.get('segment', 'all')
        selected_ids = [c.id for c in contacts_query(segment=segment, search=q).with_entities(EmailContact.id).all()]
    if not selected_ids:
        flash('Nebyl vybrán žádný kontakt.', 'warning')
        return redirect(url_for('admin.emailing_contacts'))
    contacts = EmailContact.query.filter(EmailContact.id.in_(selected_ids)).all()
    now = datetime.utcnow()
    for contact in contacts:
        if action == 'suppress':
            ensure_suppression(contact.email, reason='admin')
        elif action == 'delete':
            contact.deleted_at = now
        elif action == 'restore':
            contact.deleted_at = None
            if not contact.unsubscribed_at:
                contact.marketing_enabled = True
        elif action == 'enable':
            contact.marketing_enabled = True
            contact.unsubscribed_at = None
        elif action == 'disable':
            contact.marketing_enabled = False
    db.session.commit()
    flash(f'Akce byla provedena pro {len(contacts)} kontaktů.', 'success')
    return redirect(url_for('admin.emailing_contacts', q=request.form.get('q', ''), segment=request.form.get('segment', 'all')))


@admin_bp.route('/emailing/contacts/<int:contact_id>/<action>', methods=['POST'])
@admin_required
def emailing_contact_action(contact_id, action):
    contact = EmailContact.query.get_or_404(contact_id)
    if action == 'suppress':
        ensure_suppression(contact.email, reason='admin')
        flash('Kontakt byl trvale odhlášen z rozesílek.', 'success')
    elif action == 'delete':
        contact.deleted_at = datetime.utcnow()
        flash('Kontakt byl skrytý/smazaný z marketingové databáze.', 'info')
    elif action == 'restore':
        contact.deleted_at = None
        if not contact.unsubscribed_at:
            contact.marketing_enabled = True
        flash('Kontakt byl obnoven.', 'success')
    elif action == 'disable':
        contact.marketing_enabled = False
        flash('Kontakt byl vypnutý pro rozesílky.', 'info')
    elif action == 'enable':
        contact.marketing_enabled = True
        contact.unsubscribed_at = None
        flash('Kontakt byl zapnutý pro rozesílky.', 'success')
    db.session.commit()
    return redirect(request.referrer or url_for('admin.emailing_contacts'))


@admin_bp.route('/emailing/campaigns')
@admin_required
def emailing_campaigns():
    page, per_page = _pagination_args(25)
    status = request.args.get('status', '').strip()
    q = EmailCampaign.query
    if status:
        q = q.filter_by(status=status)
    pagination = q.order_by(EmailCampaign.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/emailing/campaigns.html', campaigns=pagination.items, pagination=pagination, status=status)


@admin_bp.route('/emailing/campaigns/new', methods=['GET', 'POST'])
@admin_required
def emailing_campaign_new():
    campaign = EmailCampaign(title='', subject='')
    if request.method == 'POST':
        _campaign_from_form(campaign)
        db.session.add(campaign)
        db.session.flush()
        _save_campaign_attachments(campaign)
        db.session.commit()
        action = request.form.get('action', 'save')
        if action == 'test':
            try:
                send_test_campaign_email(campaign, request.form.get('test_email', ''))
                flash('Testovací e-mail byl odeslán / uložen do logu.', 'success')
            except Exception as exc:
                flash(f'Test se nepovedl: {exc}', 'danger')
            return redirect(url_for('admin.emailing_campaign_edit', campaign_id=campaign.id))
        if action == 'queue':
            try:
                count = enqueue_campaign(campaign)
                flash(f'Kampaň byla zařazena k odeslání pro {count} příjemců.', 'success')
            except Exception as exc:
                flash(f'Kampaň se nepodařilo zařadit: {exc}', 'danger')
            return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))
        flash('Kampaň byla uložena jako koncept.', 'success')
        return redirect(url_for('admin.emailing_campaign_edit', campaign_id=campaign.id))
    contacts = _campaign_contact_options(campaign)
    return render_template('admin/emailing/campaign_form.html', campaign=campaign, segments=EMAIL_SEGMENTS, contacts=contacts, selected_ids=[])


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/edit', methods=['GET', 'POST'])
@admin_required
def emailing_campaign_edit(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if request.method == 'POST':
        if campaign.status == 'sending':
            flash('Kampaň se právě odesílá. Nejdřív ji pozastav.', 'warning')
            return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))
        _campaign_from_form(campaign)
        _save_campaign_attachments(campaign)
        db.session.commit()
        action = request.form.get('action', 'save')
        if action == 'test':
            try:
                send_test_campaign_email(campaign, request.form.get('test_email', ''))
                flash('Testovací e-mail byl odeslán / uložen do logu.', 'success')
            except Exception as exc:
                flash(f'Test se nepovedl: {exc}', 'danger')
            return redirect(url_for('admin.emailing_campaign_edit', campaign_id=campaign.id))
        if action == 'queue':
            try:
                count = enqueue_campaign(campaign)
                flash(f'Kampaň byla zařazena k odeslání pro {count} příjemců.', 'success')
            except Exception as exc:
                flash(f'Kampaň se nepodařilo zařadit: {exc}', 'danger')
            return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))
        flash('Kampaň byla uložena.', 'success')
        return redirect(url_for('admin.emailing_campaign_edit', campaign_id=campaign.id))
    selected_ids = json.loads(campaign.selected_contact_ids or '[]')
    contacts = _campaign_contact_options(campaign)
    return render_template('admin/emailing/campaign_form.html', campaign=campaign, segments=EMAIL_SEGMENTS, contacts=contacts, selected_ids=selected_ids)


@admin_bp.route('/emailing/campaigns/<int:campaign_id>')
@admin_required
def emailing_campaign_detail(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    status = request.args.get('recipient_status', '')
    page, per_page = _pagination_args(100)
    q = EmailCampaignRecipient.query.filter_by(campaign_id=campaign.id)
    if status:
        q = q.filter_by(status=status)
    pagination = q.order_by(EmailCampaignRecipient.id.asc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('admin/emailing/campaign_detail.html', campaign=campaign, recipients=pagination.items, pagination=pagination, recipient_status=status)


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/queue', methods=['POST'])
@admin_required
def emailing_campaign_queue(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    try:
        count = enqueue_campaign(campaign)
        flash(f'Kampaň byla zařazena k odeslání pro {count} příjemců.', 'success')
    except Exception as exc:
        flash(f'Kampaň se nepodařilo zařadit: {exc}', 'danger')
    return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/send-batch', methods=['POST'])
@admin_required
def emailing_campaign_send_batch(campaign_id):
    result = send_campaign_batch(campaign_id=campaign_id)
    flash(f'Dávka hotová: odesláno {result.get("sent", 0)}, chyby {result.get("failed", 0)}, přeskočeno {result.get("skipped", 0)}.', 'success')
    return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign_id))


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/pause', methods=['POST'])
@admin_required
def emailing_campaign_pause(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status in ('queued', 'sending'):
        campaign.status = 'paused'
        db.session.commit()
        flash('Kampaň byla pozastavena.', 'info')
    return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/resume', methods=['POST'])
@admin_required
def emailing_campaign_resume(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status == 'paused':
        campaign.status = 'queued'
        db.session.commit()
        flash('Kampaň bude pokračovat v další dávce.', 'success')
    return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/cancel', methods=['POST'])
@admin_required
def emailing_campaign_cancel(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status in ('queued', 'sending', 'paused'):
        campaign.status = 'cancelled'
        db.session.commit()
        flash('Kampaň byla zrušena.', 'info')
    return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/retry-failed', methods=['POST'])
@admin_required
def emailing_campaign_retry_failed(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    try:
        count = retry_failed_recipients(campaign)
        flash(f'Neúspěšní příjemci byli vráceni do fronty: {count}.', 'success')
    except Exception as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))


@admin_bp.route('/emailing/campaigns/<int:campaign_id>/delete', methods=['POST'])
@admin_required
def emailing_campaign_delete(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if campaign.status == 'sending':
        flash('Právě odesílanou kampaň nejdřív pozastav.', 'warning')
        return redirect(url_for('admin.emailing_campaign_detail', campaign_id=campaign.id))
    for attachment in list(campaign.attachments):
        try:
            if attachment.file_path and os.path.exists(attachment.file_path):
                os.remove(attachment.file_path)
        except Exception:
            pass
    db.session.delete(campaign)
    db.session.commit()
    flash('Kampaň byla smazána.', 'info')
    return redirect(url_for('admin.emailing_campaigns'))


@admin_bp.route('/emailing/attachments/<int:attachment_id>/delete', methods=['POST'])
@admin_required
def emailing_attachment_delete(attachment_id):
    attachment = EmailAttachment.query.get_or_404(attachment_id)
    campaign_id = attachment.campaign_id
    try:
        if attachment.file_path and os.path.exists(attachment.file_path):
            os.remove(attachment.file_path)
    except Exception:
        pass
    db.session.delete(attachment)
    db.session.commit()
    flash('Příloha byla smazána.', 'info')
    return redirect(url_for('admin.emailing_campaign_edit', campaign_id=campaign_id))


@admin_bp.route('/seo', methods=['GET', 'POST'])
@admin_required
def seo_dashboard():
    if request.method == 'POST':
        blog_count = max(0, min(50, _int_form('blog_count', 10)))
        landing_count = max(0, min(50, _int_form('landing_count', 10)))
        auto_publish = bool(request.form.get('auto_publish'))
        result = generate_daily_seo_content(blog_count=blog_count, landing_count=landing_count, auto_publish=auto_publish)
        flash(f"Vygenerováno: {result.get('blogs', 0)} blog draftů a {result.get('landing_pages', 0)} landing pages. Nízká kvalita nepublikována: {result.get('skipped_low_quality_publish', 0)}.", 'success')
        return redirect(url_for('admin.seo_dashboard'))

    blog_posts = BlogPost.query.order_by(BlogPost.created_at.desc()).limit(100).all()
    categories = Category.query.order_by(Category.id.desc()).limit(150).all()
    return render_template('admin/seo_dashboard.html', blog_posts=blog_posts, categories=categories)


@admin_bp.route('/seo/regenerate-all', methods=['POST'])
@admin_required
def seo_regenerate_all():
    result = regenerate_all_generated_content()
    flash(f"Přegenerováno do card-only verze: {result.get('blogs', 0)} blogů a {result.get('landing_pages', 0)} landing pages.", 'success')
    return redirect(url_for('admin.seo_dashboard'))


@admin_bp.route('/seo/blog/<int:post_id>/edit', methods=['GET', 'POST'])
@admin_required
def seo_blog_edit(post_id):
    post = BlogPost.query.get_or_404(post_id)
    if request.method == 'POST':
        post.title = request.form.get('title', '').strip() or post.title
        post.slug = request.form.get('slug', '').strip() or post.slug
        post.seo_title = request.form.get('seo_title', '').strip()
        post.target_keyword = request.form.get('target_keyword', '').strip()
        post.meta_description = request.form.get('meta_description', '').strip()
        post.related_product_ids = request.form.get('related_product_ids', '').strip() or '[]'
        post.content = request.form.get('content', '').strip()
        action = request.form.get('action', 'save')
        if action == 'publish':
            post.status = 'published'
            post.published_at = post.published_at or datetime.utcnow()
        elif action == 'draft':
            post.status = 'draft'
            post.published_at = None
        db.session.commit()
        flash('Blog článek byl uložen.', 'success')
        return redirect(url_for('admin.seo_dashboard'))
    return render_template('admin/seo_blog_form.html', post=post)


@admin_bp.route('/seo/blog/<int:post_id>/<action>', methods=['POST'])
@admin_required
def seo_blog_action(post_id, action):
    post = BlogPost.query.get_or_404(post_id)
    if action == 'publish':
        post.status = 'published'
        post.published_at = post.published_at or datetime.utcnow()
        flash('Blog článek byl publikován.', 'success')
    elif action == 'draft':
        post.status = 'draft'
        post.published_at = None
        flash('Blog článek byl vrácen do draftu.', 'info')
    elif action == 'regenerate':
        regenerate_blog_content(post)
        flash('Blog článek byl přegenerován do verze s produktovými kartami místo textových odkazů.', 'success')
    elif action == 'delete':
        db.session.delete(post)
        flash('Blog článek byl smazán.', 'info')
    db.session.commit()
    return redirect(url_for('admin.seo_dashboard'))




@admin_bp.route('/seo/category/new', methods=['GET', 'POST'])
@admin_required
def seo_category_new():
    category = Category(
        name='',
        slug='',
        description='',
        meta_description='',
        seo_title='',
        seo_target_keyword='',
        seo_product_rules='{}',
        seo_quality_score=0,
        seo_generated=True,
        seo_published=False,
        show_in_menu=False,
    )

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        slug = request.form.get('slug', '').strip()
        if not name:
            flash('Vyplň název landing page.', 'warning')
            return render_template('admin/seo_category_form.html', category=category, is_new=True)

        category.name = name
        category.slug = unique_slug(Category, slug or name)
        category.seo_title = request.form.get('seo_title', '').strip()
        category.seo_target_keyword = request.form.get('seo_target_keyword', '').strip() or name.lower()
        category.meta_description = request.form.get('meta_description', '').strip()
        category.seo_product_rules = request.form.get('seo_product_rules', '').strip() or '{}'
        category.description = request.form.get('description', '').strip()
        category.show_in_menu = bool(request.form.get('show_in_menu'))
        category.seo_generated = True
        category.seo_published = False

        db.session.add(category)
        db.session.flush()

        # Když není ručně vložený SEO text, vytvoří se product-aware obsah z reálných produktů.
        if not category.description:
            regenerate_category_content(category)

        action = request.form.get('action', 'save')
        if action == 'publish':
            category.seo_published = True
        elif action == 'draft':
            category.seo_published = False

        db.session.commit()
        flash(f'Landing page /k/{category.slug} byla vytvořena.', 'success')
        return redirect(url_for('admin.seo_category_edit', category_id=category.id))

    return render_template('admin/seo_category_form.html', category=category, is_new=True)


@admin_bp.route('/seo/category/bile-tenisky/create', methods=['POST'])
@admin_required
def seo_category_create_bile_tenisky():
    rules = {
        'slug': 'bile-tenisky',
        'title': 'Bílé tenisky',
        'keyword': 'bílé tenisky',
        'colors': ['bíl', 'bil', 'white'],
        'terms': ['tenisky', 'sneaker'],
        'intent': 'color',
    }

    category = Category.query.filter_by(slug='bile-tenisky').first()
    if not category:
        category = Category(
            name='Bílé tenisky',
            slug='bile-tenisky',
            description='',
            meta_description='',
            seo_title='Bílé tenisky | doporučené modely a ceny | BotyZaHubicku.cz',
            seo_target_keyword='bílé tenisky',
            seo_product_rules=json.dumps(rules, ensure_ascii=False),
            seo_quality_score=0,
            seo_generated=True,
            seo_published=True,
            show_in_menu=True,
        )
        db.session.add(category)
        db.session.flush()
    else:
        category.name = 'Bílé tenisky'
        category.seo_title = category.seo_title or 'Bílé tenisky | doporučené modely a ceny | BotyZaHubicku.cz'
        category.seo_target_keyword = category.seo_target_keyword or 'bílé tenisky'
        category.seo_product_rules = json.dumps(rules, ensure_ascii=False)
        category.seo_generated = True
        category.seo_published = True
        category.show_in_menu = True

    regenerate_category_content(category)
    category.seo_published = True
    category.show_in_menu = True
    db.session.commit()

    flash('Landing page /k/bile-tenisky byla vytvořena a publikována.', 'success')
    return redirect(url_for('admin.seo_category_edit', category_id=category.id))


@admin_bp.route('/seo/category/<int:category_id>/edit', methods=['GET', 'POST'])
@admin_required
def seo_category_edit(category_id):
    category = Category.query.get_or_404(category_id)
    if request.method == 'POST':
        category.name = request.form.get('name', '').strip() or category.name
        category.slug = request.form.get('slug', '').strip() or category.slug
        category.seo_title = request.form.get('seo_title', '').strip()
        category.seo_target_keyword = request.form.get('seo_target_keyword', '').strip()
        category.meta_description = request.form.get('meta_description', '').strip()
        category.seo_product_rules = request.form.get('seo_product_rules', '').strip() or '{}'
        category.description = request.form.get('description', '').strip()
        category.show_in_menu = bool(request.form.get('show_in_menu'))
        action = request.form.get('action', 'save')
        if action == 'publish':
            category.seo_published = True
        elif action == 'draft':
            category.seo_published = False
        db.session.commit()
        flash('Landing page byla uložena.', 'success')
        return redirect(url_for('admin.seo_dashboard'))
    return render_template('admin/seo_category_form.html', category=category)


@admin_bp.route('/seo/category/<int:category_id>/<action>', methods=['POST'])
@admin_required
def seo_category_action(category_id, action):
    category = Category.query.get_or_404(category_id)
    if action == 'publish':
        category.seo_published = True
        flash('Landing page byla publikována.', 'success')
    elif action == 'draft':
        category.seo_published = False
        flash('Landing page byla vrácena do draftu.', 'info')
    elif action == 'regenerate':
        regenerate_category_content(category)
        flash('Landing page byla přegenerována do verze s produktovými kartami místo textových odkazů.', 'success')
    elif action == 'delete' and getattr(category, 'seo_generated', False):
        db.session.delete(category)
        flash('Generovaná landing page byla smazána.', 'info')
    db.session.commit()
    return redirect(url_for('admin.seo_dashboard'))


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
            ('site_url', 'Veřejná URL webu pro e-maily, např. https://botyzahubicku.cz'),
            ('delivery_text', 'Text dopravy'),
            ('footer_affiliate_label', 'Spodní odkaz affiliate - text'),
            ('footer_affiliate_url', 'Spodní odkaz affiliate - URL'),
        ],
        'Platba a e-mail': [
            ('bank_account', 'Číslo účtu'),
            ('bank_iban', 'IBAN'),
            ('payment_sync_secret', 'Tajný klíč pro Fio sync /api/mark-paid'),
            ('smtp_host', 'SMTP host'),
            ('smtp_port', 'SMTP port'),
            ('smtp_username', 'SMTP uživatel'),
            ('smtp_password', 'SMTP heslo'),
            ('smtp_sender', 'SMTP odesílatel'),
            ('smtp_use_tls', 'SMTP TLS (1 nebo 0)'),
        ],
        'Dodavatel PDF report': [
            ('supplier_report_enabled', 'Zapnout denní PDF report dodavateli (1 nebo 0)'),
            ('supplier_report_email', 'E-mail dodavatele'),
            ('supplier_report_hour', 'Hodina odeslání 0–23'),
            ('supplier_report_minute', 'Minuta odeslání 0–59'),
            ('supplier_report_timezone', 'Časové pásmo'),
            ('supplier_report_only_paid', 'Posílat jen zaplacené objednávky (1 nebo 0)'),
        ],
        'Emailing rozesílka': [
            ('emailing_sender_name', 'Jméno odesílatele pro kampaně'),
            ('emailing_reply_to', 'Reply-To e-mail pro kampaně'),
            ('emailing_batch_size', 'Počet e-mailů v jedné dávce'),
            ('emailing_delay_seconds', 'Pauza mezi e-maily v dávce (sekundy)'),
            ('emailing_max_attachment_mb', 'Maximální velikost jedné přílohy v MB'),
        ],
        'SEO automat': [
            ('seo_generator_enabled', 'Zapnout denní SEO generátor (1 nebo 0)'),
            ('seo_generator_hour', 'Hodina generování 0–23'),
            ('seo_generator_minute', 'Minuta generování 0–59'),
            ('seo_generator_timezone', 'Časové pásmo'),
            ('seo_generate_blogs_per_day', 'Počet blog draftů denně'),
            ('seo_generate_categories_per_day', 'Počet landing page draftů denně'),
            ('seo_auto_publish', 'Automaticky publikovat bez kontroly (1 nebo 0)'),
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
