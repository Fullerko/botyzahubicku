import os
import hmac
import random
import string
import qrcode
import base64
import html
from io import BytesIO

from flask import Blueprint, current_app, abort, flash, redirect, render_template, request, session, url_for, jsonify
from flask_login import current_user, login_required, login_user

from . import db
from .models import AffiliatePartner, BlogPost, Category, Coupon, Order, OrderItem, Product, ProductSize, StoreReservation, StoreStockItem, PublicProductListing, PublicProductReservation, AffiliatePayoutRequest, User
from .utils import get_cart, setting
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from .utils import send_email
from .invoice_utils import generate_invoice_pdf
from .emailing_service import capture_cart_lead, upsert_contact_from_order
from app import db

shop_bp = Blueprint('shop', __name__)

AFF_COOKIE = 'bzh_affiliate_code'
AFF_COOKIE_MAX_AGE = 60 * 60 * 24 * 90


SHIPPING_FREE_THRESHOLD = 1199
SHIPPING_FLAT_PRICE = 99
SHIPPING_METHOD_LABEL = 'Balíkovna balík do ruky'


def shipping_price_for_subtotal(subtotal):
    subtotal = float(subtotal or 0)
    if subtotal <= 0 or subtotal >= SHIPPING_FREE_THRESHOLD:
        return 0
    return SHIPPING_FLAT_PRICE


def shipping_label(shipping):
    return 'Zdarma' if float(shipping or 0) <= 0 else f'{int(shipping)} Kč'


def qr_data_uri(payload):
    qr = qrcode.QRCode(box_size=7, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def _affiliate_code_for_partner(partner):
    base = ''.join(ch for ch in (partner.name or 'PARTNER').upper() if ch.isalnum())[:12] or 'PARTNER'
    code = base
    counter = 2
    while Coupon.query.filter_by(code=code).first():
        code = f'{base}{counter}'
        counter += 1
    return code


def _affiliate_split_from_form(value):
    if value == '10_0':
        return 10, 0
    if value == '0_10':
        return 0, 10
    return 5, 5


def _ensure_affiliate_coupon(partner, preferred_split='5_5'):
    if partner.codes:
        return

    client_percent, partner_percent = _affiliate_split_from_form(preferred_split)
    db.session.add(Coupon(
        code=_affiliate_code_for_partner(partner),
        label=f'Affiliate {partner.name}',
        description='Automaticky vytvořený affiliate kód partnera',
        discount_percent_client=client_percent,
        commission_percent_partner=partner_percent,
        affiliate_partner_id=partner.id,
        active=True,
        max_uses=0,
    ))


META_CURRENCY = 'CZK'

# Only these real shop categories are allowed in the homepage category block
# and product category filter. SEO landing categories must stay out.
HOME_CATEGORY_SLUGS = [
    'panske',
    'damske',
    'bezecke-boty',
    'tenisky',
    'kotnikove-boty',
    'zimni',
]

CATEGORY_FILTER_ALIASES = {
    'zimni': {
        'slugs': [
            'zimni',
            'zimni-boty',
            'zimni-obuv',
            'snehule',
            'panske-zimni-boty',
            'damske-zimni-boty',
        ],
        'names': [
            'Zimní',
            'Zimní boty',
            'Zímní boty',
            'Zimní obuv',
            'Sněhule',
            'Pánské zimní boty',
            'Dámské zimní boty',
        ],
    },
}


def _visible_shop_categories():
    """Return only real shop categories, never SEO landing pages."""
    q = Category.query.filter(Category.slug.in_(HOME_CATEGORY_SLUGS))

    if hasattr(Category, 'show_in_menu'):
        q = q.filter(db.or_(Category.show_in_menu.is_(True), Category.show_in_menu.is_(None)))

    if hasattr(Category, 'seo_generated'):
        q = q.filter(db.or_(Category.seo_generated.is_(False), Category.seo_generated.is_(None)))

    categories = q.all()
    order = {slug: index for index, slug in enumerate(HOME_CATEGORY_SLUGS)}
    return sorted(categories, key=lambda category: order.get(category.slug, 999))


def _money(value):
    """Bezpečně převede cenu pro Meta Pixel payload."""
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _meta_product_payload(product, quantity=1, value=None):
    """Payload pro Meta Pixel produktové události."""
    quantity = max(1, int(quantity or 1))
    product_id = str(product.id)
    price = _money(product.price)
    return {
        'content_ids': [product_id],
        'contents': [{
            'id': product_id,
            'quantity': quantity,
            'item_price': price,
        }],
        'content_type': 'product',
        'content_name': product.name,
        'content_category': product.category.name if getattr(product, 'category', None) else '',
        'value': _money(value if value is not None else price * quantity),
        'currency': META_CURRENCY,
    }


def _meta_cart_payload(items, total):
    """Payload pro košík / zahájení objednávky."""
    contents = []
    content_ids = []
    num_items = 0

    for item in items:
        product = item.get('product')
        if not product:
            continue
        quantity = max(1, int(item.get('quantity') or 1))
        product_id = str(product.id)
        content_ids.append(product_id)
        contents.append({
            'id': product_id,
            'quantity': quantity,
            'item_price': _money(product.price),
        })
        num_items += quantity

    return {
        'content_ids': content_ids,
        'contents': contents,
        'content_type': 'product',
        'num_items': num_items,
        'value': _money(total),
        'currency': META_CURRENCY,
    }


def _meta_order_payload(order):
    """Payload pro Meta Pixel Purchase po vytvoření objednávky."""
    contents = []
    content_ids = []
    num_items = 0

    for item in order.items:
        product_id = str(item.product_id)
        quantity = max(1, int(item.quantity or 1))
        content_ids.append(product_id)
        contents.append({
            'id': product_id,
            'quantity': quantity,
            'item_price': _money(item.unit_price),
        })
        num_items += quantity

    return {
        'content_ids': content_ids,
        'contents': contents,
        'content_type': 'product',
        'num_items': num_items,
        'value': _money(order.total_price),
        'currency': META_CURRENCY,
        'order_id': order.order_number,
    }


def _clean_brand(value):
    return (value or '').strip()


def _blocked_brand(value):
    return _clean_brand(value).casefold() == 'wc'


def _split_public_options(value):
    """Vrátí čistý unikátní seznam voleb pro velikosti/barvy z textového pole."""
    raw = str(value or '')
    for separator in ['\n', ';', '|']:
        raw = raw.replace(separator, ',')

    options = []
    seen = set()
    for part in raw.split(','):
        option = part.strip()
        key = option.casefold()
        if option and key not in seen:
            options.append(option)
            seen.add(key)
    return options


def _product_reservation_options(product):
    sizes = []
    colors = []

    for variant in getattr(product, 'variants', []) or []:
        if getattr(variant, 'size', ''):
            sizes.append(str(variant.size).strip())
        if getattr(variant, 'color', ''):
            colors.append(str(variant.color).strip())

    if not sizes:
        for size_row in getattr(product, 'sizes', []) or []:
            if getattr(size_row, 'size', ''):
                sizes.append(str(size_row.size).strip())

    colors.extend(_split_public_options(getattr(product, 'colors', '') or ''))
    return {
        'sizes': _split_public_options(','.join(sizes)) or ['Dle dostupnosti'],
        'colors': _split_public_options(','.join(colors)) or ['Dle dostupnosti'],
    }


def _manual_reservation_options(item):
    return {
        'sizes': _split_public_options(getattr(item, 'size', '') or '') or ['Dle dostupnosti'],
        'colors': ['Dle dostupnosti'],
    }


def _store_item_reservation_options(item):
    colors = []
    if getattr(item, 'product', None):
        colors = _product_reservation_options(item.product).get('colors', [])
    return {
        'sizes': [str(item.size).strip()] if getattr(item, 'size', '') else ['Dle dostupnosti'],
        'colors': colors or ['Dle dostupnosti'],
    }


def _public_collection_redirect(listing_type):
    endpoint = 'shop.store_stock' if listing_type == 'stock' else 'shop.ordered_products'
    return redirect(request.referrer or url_for(endpoint))


def _valid_public_reservation_email(email):
    return '@' in email and '.' in email.split('@')[-1]


def _send_public_reservation_email(listing_type, product_name, brand, size, color, email, phone, customer_name='', source_label=''):
    admin_email = setting('contact_email', '')
    if not admin_email:
        return

    def esc(value):
        return html.escape(str(value or '—'))

    page_label = '/sklad' if listing_type == 'stock' else '/objednano'
    subject = f'Nová rezervace {page_label}: {product_name} vel. {size}'
    html_body = (
        f'<h2>Nová rezervace {esc(page_label)}</h2>'
        f'<p><strong>Produkt:</strong> {esc(product_name)}<br>'
        f'<strong>Značka:</strong> {esc(brand)}<br>'
        f'<strong>Velikost:</strong> {esc(size)}<br>'
        f'<strong>Barva:</strong> {esc(color)}<br>'
        f'<strong>Jméno:</strong> {esc(customer_name)}<br>'
        f'<strong>E-mail:</strong> {esc(email)}<br>'
        f'<strong>Telefon:</strong> {esc(phone)}<br>'
        f'<strong>Zdroj:</strong> {esc(source_label or page_label)}</p>'
    )
    send_email(subject=subject, to_email=admin_email, html_body=html_body)


def _product_filter_brands():
    """Vrati znacky pro filtr.

    Znacky se netvori v samostatne tabulce - berou se automaticky
    z Product.brand. Proto tady zaroven cistime mezery, schovavame WC/wc
    a deduplikujeme rozdilne velikosti pismen.
    """
    rows = (
        db.session.query(Product.brand)
        .filter(Product.active.is_(True))
        .filter(Product.brand.isnot(None))
        .filter(db.func.trim(Product.brand) != '')
        .filter(db.func.lower(db.func.trim(Product.brand)) != 'wc')
        .order_by(db.func.lower(db.func.trim(Product.brand)).asc())
        .all()
    )

    brands = []
    seen = set()
    for value, in rows:
        clean = _clean_brand(value)
        key = clean.casefold()
        if not key or key == 'wc' or key in seen:
            continue
        brands.append(clean)
        seen.add(key)
    return brands


def _coupon_by_code(code):
    code = (code or '').strip()
    if not code:
        return None
    return Coupon.query.filter(db.func.lower(Coupon.code) == code.lower()).first()


def _affiliate_from_cookie():
    cookie_code = (request.cookies.get(AFF_COOKIE) or '').strip()
    coupon = _coupon_by_code(cookie_code)
    if coupon and coupon.active and coupon.affiliate_partner:
        return coupon
    return None


def _resolve_affiliate_for_order(coupon_info):
    manual_coupon = _coupon_by_code(coupon_info.get('code')) if coupon_info.get('code') else None
    if manual_coupon and manual_coupon.active and manual_coupon.affiliate_partner:
        return manual_coupon, manual_coupon.code

    cookie_coupon = _affiliate_from_cookie()
    if cookie_coupon:
        return cookie_coupon, ''

    return None, coupon_info.get('code', '')


@shop_bp.route('/a/<code>')
def affiliate_click(code):
    coupon = _coupon_by_code(code)
    target = (request.args.get('to') or url_for('shop.index')).strip()
    if not target.startswith('/') or target.startswith('//'):
        target = url_for('shop.index')

    response = redirect(target)
    if coupon and coupon.active and coupon.affiliate_partner:
        response.set_cookie(AFF_COOKIE, coupon.code, max_age=AFF_COOKIE_MAX_AGE, httponly=True, samesite='Lax')
    return response


def _payment_sync_secret():
    """Return the shared secret required for payment sync callbacks.

    Render environment variables are intentionally preferred over the admin DB
    setting. This prevents an old value saved in /admin/settings from silently
    overriding the production secret configured in Render.
    """
    return (
        os.environ.get('PAYMENT_SYNC_SECRET', '')
        or os.environ.get('SYNC_SECRET', '')
        or current_app.config.get('PAYMENT_SYNC_SECRET', '')
        or setting('payment_sync_secret', '')
        or ''
    ).strip()


def _mark_paid_authorized():
    configured_secret = _payment_sync_secret()
    if not configured_secret:
        current_app.logger.error('Payment sync secret is not configured; refusing /api/mark-paid request.')
        return False, 'payment sync secret is not configured', 503

    incoming_secret = (
        request.headers.get('x-sync-secret')
        or request.headers.get('X-Sync-Secret')
        or request.headers.get('authorization', '').removeprefix('Bearer ')
        or ''
    ).strip()

    if not incoming_secret or not hmac.compare_digest(incoming_secret, configured_secret):
        return False, 'unauthorized', 401

    return True, '', 200


@shop_bp.route("/api/mark-paid", methods=["POST"])
def mark_paid_api():
    authorized, reason, status_code = _mark_paid_authorized()
    if not authorized:
        return jsonify({"ok": False, "reason": reason}), status_code

    data = request.get_json(silent=True) or {}
    vs = str(data.get("variableSymbol") or data.get("variable_symbol") or "").strip()

    if not vs:
        return jsonify({"ok": False, "reason": "missing variableSymbol"}), 400

    order = (
        Order.query.filter_by(variable_symbol=vs).first()
        or Order.query.filter_by(variable_symbol=f"BZH{vs}").first()
        or Order.query.filter_by(order_number=vs).first()
        or Order.query.filter_by(order_number=f"BZH{vs}").first()
    )

    if not order:
        return jsonify({
            "ok": False,
            "reason": "not found",
            "variableSymbol": vs
        }), 404

    if order.payment_status == "paid":
        return jsonify({
            "ok": True,
            "reason": "already paid",
            "order_id": order.id
        }), 200

    order.payment_status = "paid"
    order.status = "Zaplaceno"
    order.paid_at = datetime.now()

    if order.affiliate_partner_name and order.affiliate_commission_amount:
        partner = AffiliatePartner.query.filter_by(name=order.affiliate_partner_name).first()
        if partner:
            partner.commission_balance = (partner.commission_balance or 0) + (order.affiliate_commission_amount or 0)

    db.session.commit()

    # Sumool odesílání je záměrně odpojené; objednávky se po platbě posílají jen do WooCommerce.

    # Stejný princip pro WooCommerce: zákazník zůstává na tomto webu, WooCommerce je jen backend pro dodavatele.

    invoice_pdf = generate_invoice_pdf(order)

    try:
        send_email(
            subject=f"Objednávka {order.order_number}",
            to_email=order.email,
            html_body=f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px;">

      <h2 style="margin-bottom: 10px;">Děkujeme za objednávku</h2>

      <p>Objednávka <strong>{order.order_number}</strong> byla úspěšně zaplacena.</p>

      <hr style="margin: 20px 0;">

      <h3>Detail objednávky</h3>

      <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
        <thead>
          <tr>
            <th align="left">Produkt</th>
            <th align="center">Ks</th>
            <th align="right">Cena</th>
          </tr>
        </thead>
        <tbody>
          {"".join([
            f"""
            <tr>
              <td style="padding: 8px 0;">{item.product_name}</td>
              <td align="center">{item.quantity}</td>
              <td align="right">{int(item.unit_price)} Kč</td>
            </tr>
            """
            for item in order.items
          ])}

          {f"""
          <tr>
            <td style="padding: 8px 0; color: #e53935;"><strong>SLEVA</strong></td>
            <td></td>
            <td align="right" style="color: #e53935;">-{int(order.discount_amount or 0)} Kč</td>
          </tr>
          """ if (order.discount_amount and order.discount_amount > 0) else ""}

          <tr>
            <td colspan="3" style="padding-top: 10px;">
              <hr style="border: none; border-top: 1px solid #ddd;">
            </td>
          </tr>
        </tbody>
      </table>

      <hr style="margin: 20px 0;">

      <div style="text-align: right;">
        <strong>Celkem: {int(order.total_price)} Kč</strong>
      </div>

      <p style="margin-top: 30px;">
        Fakturu naleznete v příloze tohoto emailu.
      </p>

      <p style="margin-top: 20px;">
        S pozdravem<br>
        <strong>Botyzahubicku.cz</strong>
      </p>

    </div>
    """,
            text_body=f"""
    Děkujeme za objednávku {order.order_number}.
    Celkem: {order.total_price} Kč
    """,
            attachments=[
                {
                    "filename": f"faktura_{order.order_number}.pdf",
                    "content": invoice_pdf.read(),
                    "maintype": "application",
                    "subtype": "pdf",
                }
            ]
        )
    except Exception as e:
        print("EMAIL ERROR:", e)
        
    return jsonify({
        "ok": True,
        "reason": "marked paid",
        "order_id": order.id,
        "order_number": order.order_number
    }), 200

@shop_bp.route('/api/order-status/<order_number>')
def order_status(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()

    is_paid = (
        order.payment_status == 'paid'
        or order.status == 'Zaplaceno'
        or bool(order.paid_at)
    )

    return {
        "paid": is_paid
    }

@shop_bp.route('/blog')
def blog():
    generated_posts = BlogPost.query.filter_by(status='published').order_by(BlogPost.published_at.desc(), BlogPost.created_at.desc()).all()
    return render_template('blog.html', generated_posts=generated_posts)

    
@shop_bp.route('/blog/jak-vybrat-tenisky')
def blog_jak_vybrat():
    return render_template('blog/jak-vybrat-tenisky.html')


@shop_bp.route('/blog/nejlepsi-tenisky-kazdodenni')
def blog1():
    return render_template('blog/nejlepsi-tenisky-kazdodenni.html')


@shop_bp.route('/blog/jak-vybrat-panske-tenisky')
def blog2():
    return render_template('blog/jak-vybrat-panske-tenisky.html')


@shop_bp.route('/blog/jak-vybrat-damske-tenisky')
def blog3():
    return render_template('blog/jak-vybrat-damske-tenisky.html')


@shop_bp.route('/blog/bile-tenisky-jak-nosit')
def blog4():
    return render_template('blog/bile-tenisky-jak-nosit.html')


@shop_bp.route('/blog/levne-tenisky-do-500')
def blog5():
    return render_template('blog/levne-tenisky-do-500.html')


@shop_bp.route('/blog/trendy-tenisky-2026')
def blog6():
    return render_template('blog/trendy-tenisky-2026.html')


@shop_bp.route('/blog/sportovni-vs-volnocasove')
def blog7():
    return render_template('blog/sportovni-vs-volnocasove.html')


@shop_bp.route('/blog/jak-se-starat-o-tenisky')
def blog8():
    return render_template('blog/jak-se-starat-o-tenisky.html')


@shop_bp.route('/blog/nejlepsi-tenisky-leto')
def blog9():
    return render_template('blog/nejlepsi-tenisky-leto.html')


@shop_bp.route('/blog/jak-vybrat-velikost-tenisek')
def blog10():
    return render_template('blog/jak-vybrat-velikost-tenisek.html')
    
@shop_bp.route('/blog/<slug>')
def blog_dynamic(slug):
    post = BlogPost.query.filter_by(slug=slug, status='published').first_or_404()
    from .seo_generator import products_for_blog_post, visible_related_categories
    related_products = products_for_blog_post(post, limit=8)
    related_categories = visible_related_categories(limit=8)
    return render_template('blog_detail.html', post=post, related_products=related_products, related_categories=related_categories)



@shop_bp.route('/obchodni-podminky')
def terms():
    return render_template('legal/terms.html')


@shop_bp.route('/ochrana-udaju')
def privacy():
    return render_template('legal/privacy.html')


@shop_bp.route('/reklamace')
def complaints():
    return render_template('legal/complaints.html')


@shop_bp.route('/cookies')
def cookies():
    return render_template('legal/cookies.html')


def _public_product_collection(listing_type):
    is_stock = listing_type == 'stock'
    search = (request.args.get('q') or request.args.get('search') or '').strip()
    size = (request.args.get('size') or '').strip()
    brand = _clean_brand(request.args.get('brand', ''))
    sort = request.args.get('sort', 'newest')

    product_query = Product.query.filter(Product.active.is_(True))
    if is_stock:
        product_query = product_query.filter(Product.show_stock.is_(True))
    else:
        product_query = product_query.filter(Product.show_ordered.is_(True))

    if search:
        product_query = product_query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.brand.ilike(f'%{search}%'),
                Product.short_description.ilike(f'%{search}%'),
                Product.description.ilike(f'%{search}%'),
                Product.seo_keywords.ilike(f'%{search}%'),
            )
        )

    if brand and not _blocked_brand(brand):
        product_query = product_query.filter(db.func.lower(db.func.trim(Product.brand)) == brand.casefold())

    if size:
        product_query = product_query.join(ProductSize).filter(ProductSize.size == size)

    if sort == 'price_asc':
        product_query = product_query.order_by(Product.price.asc())
    elif sort == 'price_desc':
        product_query = product_query.order_by(Product.price.desc())
    else:
        product_query = product_query.order_by(Product.created_at.desc())

    products = product_query.all()

    manual_query = PublicProductListing.query.filter_by(active=True, listing_type=listing_type)
    if search:
        manual_query = manual_query.filter(
            db.or_(
                PublicProductListing.name.ilike(f'%{search}%'),
                PublicProductListing.brand.ilike(f'%{search}%'),
                PublicProductListing.note.ilike(f'%{search}%'),
            )
        )
    if brand and not _blocked_brand(brand):
        manual_query = manual_query.filter(db.func.lower(db.func.trim(PublicProductListing.brand)) == brand.casefold())
    if size:
        manual_query = manual_query.filter(PublicProductListing.size.ilike(f'%{size}%'))
    manual_items = manual_query.order_by(PublicProductListing.created_at.desc(), PublicProductListing.name.asc()).all()

    store_items = []
    if is_stock:
        store_query = StoreStockItem.query.filter_by(active=True)
        if search:
            store_query = store_query.filter(
                db.or_(
                    StoreStockItem.name.ilike(f'%{search}%'),
                    StoreStockItem.brand.ilike(f'%{search}%'),
                    StoreStockItem.note.ilike(f'%{search}%'),
                )
            )
        if brand and not _blocked_brand(brand):
            store_query = store_query.filter(db.func.lower(db.func.trim(StoreStockItem.brand)) == brand.casefold())
        if size:
            store_query = store_query.filter(StoreStockItem.size == size)
        store_items = [item for item in store_query.order_by(StoreStockItem.created_at.desc(), StoreStockItem.name.asc()).all() if item.available_quantity > 0]

    brand_values = set()
    size_values = set()
    base_products = Product.query.filter(Product.active.is_(True))
    base_products = base_products.filter(Product.show_stock.is_(True) if is_stock else Product.show_ordered.is_(True)).all()
    for product in base_products:
        clean_brand = _clean_brand(product.brand)
        if clean_brand and not _blocked_brand(clean_brand):
            brand_values.add(clean_brand)
        for row in getattr(product, 'sizes', []) or []:
            if row.size:
                size_values.add(str(row.size))

    for item in PublicProductListing.query.filter_by(active=True, listing_type=listing_type).all():
        clean_brand = _clean_brand(item.brand)
        if clean_brand and not _blocked_brand(clean_brand):
            brand_values.add(clean_brand)
        for value in str(item.size or '').replace(';', ',').split(','):
            value = value.strip()
            if value:
                size_values.add(value)

    if is_stock:
        for item in StoreStockItem.query.filter_by(active=True).all():
            clean_brand = _clean_brand(item.display_brand)
            if clean_brand and not _blocked_brand(clean_brand):
                brand_values.add(clean_brand)
            if item.size:
                size_values.add(str(item.size))

    title = 'Sklad' if is_stock else 'Objednáno'
    subtitle = (
        'Produkty, které už jsou dostupné na naší prodejně, zarezervujte si je ještě dnes'
        if is_stock
        else 'Produkty, které jsou objednané a brzy dorazí do skladu, zarezervujte si je ještě dnes'
    )
    endpoint = 'shop.store_stock' if is_stock else 'shop.ordered_products'
    public_url = url_for(endpoint, _external=True)
    reservation_data = {
        'product': {str(product.id): _product_reservation_options(product) for product in products},
        'manual': {str(item.id): _manual_reservation_options(item) for item in manual_items},
        'store': {str(item.id): _store_item_reservation_options(item) for item in store_items},
    }

    return render_template(
        'shop/public_product_collection.html',
        listing_type=listing_type,
        page_title=title,
        page_subtitle=subtitle,
        products=products,
        manual_items=manual_items,
        store_items=store_items,
        brands=sorted(brand_values, key=lambda value: value.casefold()),
        sizes=sorted(size_values, key=lambda value: (len(str(value)), str(value))),
        search=search,
        selected_brand=brand,
        selected_size=size,
        selected_sort=sort,
        endpoint=endpoint,
        public_url=public_url,
        reservation_data=reservation_data,
    )


@shop_bp.route('/objednano')
def ordered_products():
    return _public_product_collection('ordered')


@shop_bp.route('/sklad')
def store_stock():
    return _public_product_collection('stock')


@shop_bp.route('/rezervace/<listing_type>/<item_type>/<int:item_id>', methods=['POST'])
def public_reserve(listing_type, item_type, item_id):
    if listing_type not in {'ordered', 'stock'}:
        abort(404)

    size = (request.form.get('size') or '').strip() or 'Dle dostupnosti'
    color = (request.form.get('color') or '').strip() or 'Dle dostupnosti'
    email = (request.form.get('email') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    customer_name = (request.form.get('customer_name') or '').strip()

    if not _valid_public_reservation_email(email):
        flash('Zadejte platný e-mail pro potvrzení rezervace.', 'warning')
        return _public_collection_redirect(listing_type)

    if len(phone) < 6:
        flash('Zadejte platný telefon, abychom vás mohli kontaktovat.', 'warning')
        return _public_collection_redirect(listing_type)

    if item_type == 'store':
        if listing_type != 'stock':
            abort(404)
        item = StoreStockItem.query.filter_by(id=item_id, active=True).first_or_404()
        if item.available_quantity < 1:
            flash('Tato velikost už není na prodejně volná k rezervaci.', 'warning')
            return _public_collection_redirect(listing_type)

        reservation = StoreReservation(
            store_item_id=item.id,
            customer_name=customer_name,
            email=email,
            phone=phone,
            quantity=1,
            status='aktivní',
            note=f'Barva: {color}',
            reserved_until=datetime.utcnow() + timedelta(days=3),
        )
        db.session.add(reservation)
        db.session.commit()

        try:
            _send_public_reservation_email(
                listing_type='stock',
                product_name=item.display_name,
                brand=item.display_brand or 'BotyZaHubicku.cz',
                size=item.size,
                color=color,
                email=email,
                phone=phone,
                customer_name=customer_name,
                source_label='/sklad — sklad prodejny',
            )
        except Exception as exc:
            current_app.logger.warning('Nepodařilo se odeslat e-mail o rezervaci: %s', exc)

        flash('Rezervace byla vytvořena. Produkt držíme 3 dny a kontaktujeme vás přes telefon nebo e-mail.', 'success')
        return _public_collection_redirect(listing_type)

    if item_type == 'product':
        product_query = Product.query.filter_by(id=item_id, active=True)
        product_query = product_query.filter(Product.show_stock.is_(True) if listing_type == 'stock' else Product.show_ordered.is_(True))
        product = product_query.first_or_404()
        product_name = product.name
        brand = product.brand or 'BotyZaHubicku.cz'
    elif item_type == 'manual':
        item = PublicProductListing.query.filter_by(id=item_id, active=True, listing_type=listing_type).first_or_404()
        product_name = item.display_name
        brand = item.display_brand
    else:
        abort(404)

    reservation = PublicProductReservation(
        listing_type=listing_type,
        item_type=item_type,
        item_id=item_id,
        product_name=product_name,
        brand=brand,
        size=size,
        color=color,
        email=email,
        phone=phone,
        customer_name=customer_name,
        status='nová',
    )
    db.session.add(reservation)
    db.session.commit()

    try:
        _send_public_reservation_email(
            listing_type=listing_type,
            product_name=product_name,
            brand=brand,
            size=size,
            color=color,
            email=email,
            phone=phone,
            customer_name=customer_name,
            source_label=f'/{"sklad" if listing_type == "stock" else "objednano"} — {item_type}',
        )
    except Exception as exc:
        current_app.logger.warning('Nepodařilo se odeslat e-mail o rezervaci: %s', exc)

    flash('Rezervace byla vytvořena. Ozveme se vám přes telefon nebo e-mail.', 'success')
    return _public_collection_redirect(listing_type)


@shop_bp.route('/sklad/rezervace/<int:item_id>', methods=['POST'])
def store_reserve(item_id):
    item = StoreStockItem.query.filter_by(id=item_id, active=True).first_or_404()
    customer_name = (request.form.get('customer_name') or '').strip()
    email = (request.form.get('email') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    note = (request.form.get('note') or '').strip()
    quantity = 1

    if '@' not in email or '.' not in email.split('@')[-1]:
        flash('Zadejte platný e-mail pro potvrzení rezervace.', 'warning')
        return redirect(url_for('shop.store_stock'))

    if len(phone) < 6:
        flash('Zadejte platný telefon, abychom vás mohli kontaktovat.', 'warning')
        return redirect(url_for('shop.store_stock'))

    if item.available_quantity < quantity:
        flash('Tato velikost už není na prodejně volná k rezervaci.', 'warning')
        return redirect(url_for('shop.store_stock'))

    reservation = StoreReservation(
        store_item_id=item.id,
        customer_name=customer_name,
        email=email,
        phone=phone,
        quantity=quantity,
        status='aktivní',
        note=note,
        reserved_until=datetime.utcnow() + timedelta(days=3),
    )
    db.session.add(reservation)
    db.session.commit()

    admin_email = setting('contact_email', '')
    if admin_email:
        try:
            send_email(
                subject=f'Nová rezervace na prodejně: {item.display_name} vel. {item.size}',
                to_email=admin_email,
                html_body=(
                    f'<h2>Nová rezervace /sklad</h2>'
                    f'<p><strong>Produkt:</strong> {item.display_name}<br>'
                    f'<strong>Velikost:</strong> {item.size}<br>'
                    f'<strong>Jméno:</strong> {customer_name or "—"}<br>'
                    f'<strong>E-mail:</strong> {email}<br>'
                    f'<strong>Telefon:</strong> {phone}<br>'
                    f'<strong>Platnost:</strong> 3 dny</p>'
                    f'<p>{note}</p>'
                ),
            )
        except Exception as exc:
            current_app.logger.warning('Nepodařilo se odeslat e-mail o rezervaci: %s', exc)

    flash('Rezervace byla vytvořena. Zboží držíme 3 dny a kontaktujeme vás přes telefon nebo e-mail.', 'success')
    return redirect(url_for('shop.store_stock'))

def cart_detail():
    items = []
    subtotal = 0
    cart = get_cart()
    for key, item in cart.items():
        product = Product.query.get(item['product_id'])
        if not product:
            continue
        line_total = product.price * item['quantity']
        subtotal += line_total
        items.append({'key': key, 'product': product, 'size': item['size'], 'quantity': item['quantity'], 'line_total': line_total})
    shipping = shipping_price_for_subtotal(subtotal)
    coupon_info = session.get('coupon', {})
    discount_amount = 0

    if coupon_info.get('code'):

        # 🔥 TVŮJ SECRET KÓD (CHCITOZA)
        if coupon_info.get('type') == 'fixed_final_price':
            target_price = int(coupon_info.get('target_price', subtotal))
            discount_amount = max(0, subtotal - target_price)
            total = max(0, min(subtotal, target_price) + shipping)

        # 🧾 klasický % kód
        else:
            discount_amount = round(subtotal * (float(coupon_info.get('discount_percent_client', 0)) / 100), 2)
            total = max(0, subtotal - discount_amount + shipping)

    else:
        total = subtotal + shipping
    return items, subtotal, shipping, discount_amount, total


def create_qr_for_order(order):
    account = setting('bank_account', '2301234567/2010')
    payload = (
        f'SPD*1.0*ACC:{account}*AM:{order.total_price:.2f}*CC:CZK*X-VS:{order.order_number[-8:]}*'
        f'MSG:Objednavka {order.order_number}*RN:{setting("site_name", "BotyZaHubicku")}'
    )
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white')
    filename = f'qr_{order.order_number}.png'
    filepath = os.path.join(current_app.config['QR_FOLDER'], filename)
    image.save(filepath)
    order.qr_payload = payload
    order.qr_image = 'qr/' + filename


@shop_bp.route('/')
def index():
    featured = Product.query.filter_by(active=True, featured=True).limit(8).all()
    newest = Product.query.filter_by(active=True).order_by(Product.created_at.desc()).limit(12).all()
    categories = _visible_shop_categories()
    coupons = Coupon.query.filter_by(active=True).order_by(Coupon.created_at.desc()).limit(3).all()
    return render_template('shop/index.html', featured=featured, newest=newest, categories=categories, coupons=coupons)


@shop_bp.route('/produkty')
def products():
    q = Product.query.filter_by(active=True)

    category_slug = request.args.get('category', '')
    brand = _clean_brand(request.args.get('brand', ''))
    if _blocked_brand(brand):
        brand = ''
    size = request.args.get('size', '')
    sort = request.args.get('sort', 'newest')
    search = request.args.get('search', '').strip()
    gender = request.args.get('gender', '')

    page_title = 'Všechny boty'

    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first()
        alias_data = CATEGORY_FILTER_ALIASES.get(category_slug, {})
        alias_slugs = set(alias_data.get('slugs', [])) | {category_slug}
        alias_names = set(alias_data.get('names', []))

        category_matches = Category.query.filter(
            db.or_(
                Category.slug.in_(alias_slugs),
                Category.name.in_(alias_names),
            )
        ).all()

        if category:
            page_title = category.name
        elif category_matches:
            page_title = category_matches[0].name

        category_ids = [cat.id for cat in category_matches]
        if category and category.id not in category_ids:
            category_ids.append(category.id)

        if category_ids:
            q = q.filter(
                db.or_(
                    Product.category_id.in_(category_ids),
                    Product.categories.any(Category.id.in_(category_ids)),
                )
            )

    if gender:
        q = q.filter(Product.gender.like(f'%{gender}%'))

    if brand:
        q = q.filter(db.func.lower(db.func.trim(Product.brand)) == brand.casefold())

    if search:
        q = q.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.short_description.ilike(f'%{search}%'),
                Product.description.ilike(f'%{search}%'),
                Product.seo_keywords.ilike(f'%{search}%'),
            )
        )

    if size:
        q = q.join(ProductSize).filter(ProductSize.size == size, ProductSize.stock > 0)

    if sort == 'price_asc':
        q = q.order_by(Product.price.asc())
    elif sort == 'price_desc':
        q = q.order_by(Product.price.desc())
    else:
        q = q.order_by(Product.created_at.desc())

    products = q.all()
    brands = _product_filter_brands()
    sizes = ['36', '37', '38', '39', '40', '41', '42', '43', '44', '45', '46', '47']
    categories = _visible_shop_categories()

    return render_template(
        'shop/products.html',
        products=products,
        brands=brands,
        sizes=sizes,
        categories=categories,
        page_title=page_title,
        active_category=category_slug,
        meta_search={
            'search_string': search,
            'content_category': page_title,
            'currency': META_CURRENCY,
        } if search else None
    )


@shop_bp.route('/produkt/<slug>', methods=['GET', 'POST'])
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, active=True).first_or_404()
    related = Product.query.filter(Product.category_id == product.category_id, Product.id != product.id, Product.active == True).limit(4).all()
    if request.method == 'POST':
        size = request.form.get('size', '')
        color = request.form.get('color', '').strip()
        quantity = max(1, int(request.form.get('quantity', 1)))
        size_row = ProductSize.query.filter_by(product_id=product.id, size=size).first()
        if not size_row or size_row.stock < quantity:
            flash('Vybraná velikost není skladem v požadovaném množství.', 'warning')
            return redirect(url_for('shop.product_detail', slug=slug))
        key = f'{product.id}:{size}:{color}'

        cart = get_cart()

        if key in cart:
            cart[key]['quantity'] += quantity
        else:
            cart[key] = {
                'product_id': product.id,
                'size': size,
                'color': color,
                'quantity': quantity
            }
        session['meta_add_to_cart'] = _meta_product_payload(product, quantity=quantity)
        session.modified = True
        flash('Produkt byl přidán do košíku.', 'success')
        return redirect(url_for('shop.cart'))
    return render_template('shop/product_detail.html', product=product, related=related)


@shop_bp.route('/cart')
def cart():
    items, subtotal, shipping, discount_amount, total = cart_detail()
    meta_add_to_cart = session.pop('meta_add_to_cart', None)
    return render_template(
        'shop/cart.html',
        items=items,
        subtotal=subtotal,
        shipping=shipping,
        discount_amount=discount_amount,
        total=total,
        meta_add_to_cart=meta_add_to_cart,
        shipping_threshold=SHIPPING_FREE_THRESHOLD,
        shipping_label=shipping_label(shipping),
    )



@shop_bp.route('/api/cart-lead', methods=['POST'])
def cart_lead_api():
    data = request.get_json(silent=True) or request.form
    email = (data.get('email') or '').strip()
    name = (data.get('name') or data.get('customer_name') or '').strip()
    phone = (data.get('phone') or '').strip()
    lead = capture_cart_lead(email=email, name=name, phone=phone, session_id=request.cookies.get(current_app.config.get('SESSION_COOKIE_NAME', 'session'), ''))
    if not lead:
        return jsonify({'ok': False, 'reason': 'missing_email_or_empty_cart'}), 400
    db.session.commit()
    return jsonify({'ok': True, 'email': lead.email, 'items': lead.item_count})


@shop_bp.route('/cart/update', methods=['POST'])
def cart_update():
    key = request.form.get('key')
    quantity = max(1, int(request.form.get('quantity', 1)))
    cart = get_cart()
    if key in cart:
        cart[key]['quantity'] = quantity
        session.modified = True
        flash('Košík byl aktualizován.', 'success')
    return redirect(url_for('shop.cart'))


@shop_bp.route('/cart/remove/<key>')
def cart_remove(key):
    cart = get_cart()
    if key in cart:
        del cart[key]
        session.modified = True
        flash('Položka byla odebrána.', 'info')
    return redirect(url_for('shop.cart'))


@shop_bp.route('/cart/coupon', methods=['POST'])
def apply_coupon():
    code = request.form.get('coupon_code', '').strip().upper()

    if code.startswith('CHCITOZA'):
        target_price_text = code.replace('CHCITOZA', '').strip()

        if not target_price_text.isdigit():
            flash('Neplatný slevový kód.', 'danger')
            return redirect(url_for('shop.cart'))

        target_price = int(target_price_text)

        if target_price < 1:
            flash('Neplatná částka.', 'danger')
            return redirect(url_for('shop.cart'))

        session['coupon'] = {
            'code': code,
            'type': 'fixed_final_price',
            'target_price': target_price,
            'discount_percent_client': 0,
            'commission_percent_partner': 0,
            'affiliate_partner_id': '',
            'affiliate_partner_name': '',
            'split_text': f'SLEVA na cenu {target_price} Kč',
        }

        session.modified = True
        flash(f'Kód {code} byl použit.', 'success')
        return redirect(url_for('shop.cart'))

    coupon = Coupon.query.filter_by(code=code, active=True).first()

    if not coupon:
        flash('Slevový nebo affiliate kód nebyl nalezen.', 'danger')
        return redirect(url_for('shop.cart'))

    if coupon.max_uses and coupon.uses_count >= coupon.max_uses:
        flash('Tento kód už není aktivní.', 'warning')
        return redirect(url_for('shop.cart'))

    session['coupon'] = {
        'code': coupon.code,
        'type': 'percent',
        'discount_percent_client': coupon.discount_percent_client,
        'commission_percent_partner': coupon.commission_percent_partner,
        'affiliate_partner_id': coupon.affiliate_partner_id or '',
        'affiliate_partner_name': coupon.affiliate_partner.name if coupon.affiliate_partner else '',
        'split_text': coupon.display_split,
    }

    session.modified = True
    flash(f'Kód {coupon.code} byl použit.', 'success')
    return redirect(url_for('shop.cart'))


@shop_bp.route('/cart/coupon/remove')
def remove_coupon():
    session.pop('coupon', None)
    flash('Kód byl odebrán.', 'info')
    return redirect(url_for('shop.cart'))


@shop_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    items, subtotal, shipping, discount_amount, total = cart_detail()
    if not items:
        flash('Košík je prázdný.', 'warning')
        return redirect(url_for('shop.products'))

    coupon_info = session.get('coupon', {})

    if request.method == 'POST':
        affiliate_coupon, stored_coupon_code = _resolve_affiliate_for_order(coupon_info)
        affiliate_partner_name = affiliate_coupon.affiliate_partner.name if affiliate_coupon and affiliate_coupon.affiliate_partner else ''
        affiliate_commission_percent = float(affiliate_coupon.commission_percent_partner or 0) if affiliate_coupon else 0
        order_number = 'BZH' + ''.join(random.choices(string.digits, k=8))
        order = Order(
            order_number=order_number,
            variable_symbol=order_number[-8:],
            customer_name=request.form.get('customer_name', '').strip(),
            email=request.form.get('email', '').strip(),
            phone=request.form.get('phone', '').strip(),
            street=request.form.get('street', '').strip(),
            city=request.form.get('city', '').strip(),
            postal_code=request.form.get('postal_code', '').strip(),
            shipping_method=SHIPPING_METHOD_LABEL,
            payment_method='QR kód / bankovní převod',
            shipping_price=shipping,
            subtotal=subtotal,
            discount_amount=discount_amount,
            total_price=total,
            note=request.form.get('note', '').strip(),
            user_id=current_user.id if current_user.is_authenticated else None,
            coupon_code=stored_coupon_code,
            affiliate_partner_name=affiliate_partner_name,
            affiliate_commission_amount=round(total * (affiliate_commission_percent / 100), 2),
        )
        if coupon_info.get('code'):
            coupon = Coupon.query.filter_by(code=coupon_info['code']).first()
            if coupon:
                order.coupon_id = coupon.id
                coupon.uses_count += 1
        db.session.add(order)
        db.session.flush()
        create_qr_for_order(order)
        cart = get_cart()
        for key, item in cart.items():
            product = Product.query.get(item['product_id'])
            size_row = ProductSize.query.filter_by(product_id=product.id, size=item['size']).first()
            if not size_row or size_row.stock < item['quantity']:
                db.session.rollback()
                flash(f'Produkt {product.name} už není v požadovaném množství skladem.', 'danger')
                return redirect(url_for('shop.cart'))
            size_row.stock -= item['quantity']
            product.stock = max(0, product.stock - item['quantity'])
            db.session.add(OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                size=item['size'],
                quantity=item['quantity'],
                unit_price=product.price,
                color=item.get('color', ''),
            ))
        capture_cart_lead(order.email, name=order.customer_name, phone=order.phone, session_id=request.cookies.get(current_app.config.get('SESSION_COOKIE_NAME', 'session'), ''))
        upsert_contact_from_order(order)
        db.session.commit()
        session['meta_purchase_order_number'] = order.order_number
        session['cart'] = {}
        session.pop('coupon', None)
        flash(f'Objednávka {order.order_number} byla úspěšně vytvořena.', 'success')
        return redirect(url_for('shop.order_success', order_number=order.order_number))

    return render_template(
        'shop/checkout.html',
        items=items,
        subtotal=subtotal,
        shipping=shipping,
        discount_amount=discount_amount,
        total=total,
        coupon_info=coupon_info,
        bank_account=setting('bank_account', ''),
        bank_iban=setting('bank_iban', ''),
        meta_checkout=_meta_cart_payload(items, total),
        shipping_threshold=SHIPPING_FREE_THRESHOLD,
        shipping_label=shipping_label(shipping),
        shipping_method_label=SHIPPING_METHOD_LABEL,
    )


@shop_bp.route('/objednavka/<order_number>')
def order_success(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()

    return render_template(
        'shop/order_success.html',
        order=order,
        bank_account=setting('bank_account', ''),
        bank_iban=setting('bank_iban', ''),
        track_purchase=(order.payment_status == 'paid'),
        meta_purchase=_meta_order_payload(order) if session.pop('meta_purchase_order_number', None) == order.order_number else None,
    )


@shop_bp.route('/platba/<order_number>')
def order_payment(order_number):
    # Kratší odkaz do e-mailů. Zobrazí stejnou stránku s QR kódem a bankovními údaji.
    return order_success(order_number)


@shop_bp.route('/affiliate', methods=['GET', 'POST'])
@shop_bp.route('/affiliate/register', methods=['GET', 'POST'])
def affiliate():
    codes = Coupon.query.filter_by(active=True).order_by(Coupon.code.asc()).all()
    partners = AffiliatePartner.query.order_by(AffiliatePartner.created_at.desc()).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        instagram = request.form.get('instagram', '').strip()
        note = request.form.get('note', '').strip()
        preferred_split = request.form.get('preferred_split', '5_5')

        if current_user.is_authenticated:
            user = current_user
            if not name:
                name = user.full_name
            email = user.email
        else:
            password = request.form.get('password', '')
            password2 = request.form.get('password2', '')

            if not name or not email:
                flash('Vyplň jméno a e-mail.', 'warning')
                return redirect(url_for('shop.affiliate'))
            if len(password) < 6:
                flash('Heslo musí mít alespoň 6 znaků.', 'warning')
                return redirect(url_for('shop.affiliate'))
            if password != password2:
                flash('Hesla se neshodují.', 'warning')
                return redirect(url_for('shop.affiliate'))

            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash('Tento e-mail už má účet. Přihlas se a potom otevři Affiliate.', 'warning')
                return redirect(url_for('auth.login', next=url_for('shop.affiliate')))

            user = User(
                email=email,
                full_name=name,
                password_hash=generate_password_hash(password),
                is_admin=False,
            )
            db.session.add(user)

        partner = AffiliatePartner.query.filter_by(email=user.email).first()
        if partner:
            partner.name = name or partner.name
            partner.instagram = instagram or partner.instagram
            if note:
                partner.note = note
            partner.status = 'Aktivní'
        else:
            partner = AffiliatePartner(
                name=name or user.full_name,
                email=user.email,
                instagram=instagram,
                note=(note + f"\nPreferovaný split: {preferred_split}").strip(),
                status='Aktivní',
            )
            db.session.add(partner)

        db.session.flush()
        _ensure_affiliate_coupon(partner, preferred_split)
        db.session.commit()

        if not current_user.is_authenticated:
            login_user(user)

        flash('Affiliate účet byl vytvořen a je hned aktivní.', 'success')
        return redirect(url_for('shop.affiliate_portal'))

    return render_template('shop/affiliate.html', codes=codes, partners=partners)


@shop_bp.route('/affiliate/portal', methods=['GET', 'POST'])
@login_required
def affiliate_portal():
    partner = AffiliatePartner.query.filter_by(email=current_user.email).first()

    if not partner or partner.status != 'Aktivní':
        flash('Affiliate portál je dostupný jen pro aktivní affiliate partnery.', 'warning')
        return redirect(url_for('shop.affiliate'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'payout_request':
            amount = float(request.form.get('amount', 0) or 0)
            note = request.form.get('note', '').strip()

            paid_orders = [
                o for o in Order.query.filter_by(affiliate_partner_name=partner.name).all()
                if o.payment_status == 'paid'
            ]

            available = sum(o.affiliate_commission_amount or 0 for o in paid_orders) - (partner.paid_total or 0)

            if amount <= 0 or amount > available:
                flash('Neplatná částka k výběru.', 'danger')
                return redirect(url_for('shop.affiliate_portal'))

            payout_request = AffiliatePayoutRequest(
                affiliate_partner_id=partner.id,
                amount=amount,
                note=note,
                status='Čeká'
            )

            db.session.add(payout_request)
            db.session.commit()

            flash('Žádost o výběr byla odeslána.', 'success')
            return redirect(url_for('shop.affiliate_portal'))

        if action == 'create_code':
            code_value = request.form.get('code', '').strip().upper()
            discount = float(request.form.get('discount_percent_client', 0))
            commission = float(request.form.get('commission_percent_partner', 0))

            if discount + commission != 10:
                flash('Součet musí být přesně 10 %.', 'danger')
                return redirect(url_for('shop.affiliate_portal'))

            if not code_value:
                flash('Zadej název kódu.', 'danger')
                return redirect(url_for('shop.affiliate_portal'))

            existing = Coupon.query.filter_by(code=code_value).first()
            if existing:
                flash('Tento kód už existuje.', 'danger')
                return redirect(url_for('shop.affiliate_portal'))

            new_code = Coupon(
                code=code_value,
                label=code_value,
                description='Affiliate kód',
                discount_percent_client=discount,
                commission_percent_partner=commission,
                affiliate_partner_id=partner.id,
                active=True,
                max_uses=0
            )

            db.session.add(new_code)
            db.session.commit()

            flash('Kód vytvořen.', 'success')
            return redirect(url_for('shop.affiliate_portal'))

    if not partner.codes:
        code = ''.join(ch for ch in (partner.name or 'PARTNER').upper() if ch.isalnum())[:12] or 'PARTNER'
        original = code
        counter = 2
        while Coupon.query.filter_by(code=code).first():
            code = f'{original}{counter}'
            counter += 1

        db.session.add(Coupon(
            code=code,
            label=f'Affiliate {partner.name}',
            description='Affiliate kód partnera',
            discount_percent_client=5,
            commission_percent_partner=5,
            affiliate_partner_id=partner.id,
            active=True,
            max_uses=0,
        ))
        db.session.commit()

    if request.method == 'POST':
        coupon = Coupon.query.filter_by(id=int(request.form.get('coupon_id', 0) or 0), affiliate_partner_id=partner.id).first_or_404()
        client_percent = int(request.form.get('discount_percent_client', 0) or 0)
        partner_percent = int(request.form.get('commission_percent_partner', 0) or 0)
        if client_percent < 0 or partner_percent < 0 or client_percent > 10 or partner_percent > 10 or client_percent + partner_percent != 10:
            flash('Rozdělení musí dát dohromady přesně 10 % a každá hodnota musí být 0–10 %.', 'danger')
            return redirect(url_for('shop.affiliate_portal'))
        coupon.discount_percent_client = client_percent
        coupon.commission_percent_partner = partner_percent
        db.session.commit()
        flash('Rozdělení kódu bylo uloženo.', 'success')
        return redirect(url_for('shop.affiliate_portal'))

    coupons = Coupon.query.filter_by(affiliate_partner_id=partner.id).order_by(Coupon.created_at.desc()).all()
    orders = Order.query.filter_by(affiliate_partner_name=partner.name).order_by(Order.created_at.desc()).all()
    paid_orders = [o for o in orders if o.payment_status == 'paid']
    stats = {
        'orders_count': len(orders),
        'paid_orders_count': len(paid_orders),
        'revenue': sum(o.total_price or 0 for o in paid_orders),
        'commission_earned': sum(o.affiliate_commission_amount or 0 for o in paid_orders),
        'commission_balance': partner.commission_balance or 0,
        'paid_total': partner.paid_total or 0,
    }
    return render_template('shop/affiliate_portal.html', partner=partner, coupons=coupons, orders=orders, stats=stats)

@shop_bp.route('/k/<slug>')
def category_landing(slug):
    """Dynamická SEO landing page.

    Produkty, počty, ceny a související kategorie se počítají vždy z aktuální DB.
    Žádná čísla ani výpis produktů nejsou natvrdo uložené v textu kategorie.
    """
    category = Category.query.filter_by(slug=slug).first_or_404()

    if hasattr(category, "seo_published") and not category.seo_published:
        abort(404)

    from .seo_generator import (
        build_product_stats,
        infer_product_rules_for_category,
        products_for_landing_category,
        visible_related_categories,
    )

    products = products_for_landing_category(category, limit=None)
    product_sort = request.args.get('sort', 'newest')

    def _landing_price(product):
        try:
            return float(product.price or 0)
        except Exception:
            return 0.0

    def _landing_created_at(product):
        return product.created_at or datetime.min

    if product_sort == 'price_asc':
        products = sorted(products, key=lambda p: (_landing_price(p), -int(p.stock or 0), _landing_created_at(p)))
    elif product_sort == 'price_desc':
        products = sorted(products, key=lambda p: (_landing_price(p), int(p.stock or 0), _landing_created_at(p)), reverse=True)
    else:
        product_sort = 'newest'
        products = sorted(products, key=lambda p: (_landing_created_at(p), int(p.stock or 0)), reverse=True)

    product_stats = build_product_stats(products)
    rules = infer_product_rules_for_category(category)
    related_categories = visible_related_categories(current_id=category.id, limit=10)

    stats = {
        "count": product_stats.get("count", len(products)),
        "stock_count": product_stats.get("in_stock", 0),
        "in_stock": product_stats.get("in_stock", 0),
        "price_min": product_stats.get("min_price"),
        "price_max": product_stats.get("max_price"),
        "min_price": product_stats.get("min_price"),
        "max_price": product_stats.get("max_price"),
        "avg_price": product_stats.get("avg_price"),
        "average_price": product_stats.get("avg_price"),
        "brands": product_stats.get("brands", []),
        "cheapest_product": product_stats.get("cheapest_product"),
        "cheapest_name": product_stats.get("cheapest_name", ""),
        "cheapest_price": product_stats.get("cheapest_price"),
    }

    return render_template(
        "category_landing.html",
        category=category,
        products=products,
        stats=stats,
        rules=rules,
        intent=rules,
        related_categories=related_categories,
        product_sort=product_sort,
    )
