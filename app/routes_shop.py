import os
import random
import string
import qrcode

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for, jsonify
from flask_login import current_user, login_required

from . import db
from .models import AffiliatePartner, Category, Coupon, Order, OrderItem, Product, ProductSize, AffiliatePayoutRequest
from .utils import get_cart, setting
from datetime import datetime
from .utils import send_email
from .invoice_utils import generate_invoice_pdf

shop_bp = Blueprint('shop', __name__)


@shop_bp.route("/api/mark-paid", methods=["POST"])
def mark_paid_api():
    data = request.get_json() or {}
    vs = str(data.get("variableSymbol") or data.get("variable_symbol") or "").strip()

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
          <tr style="border-bottom: 2px solid #ddd;">
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
    shipping = 0
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
    categories = Category.query.order_by(Category.name.asc()).limit(6).all()
    coupons = Coupon.query.filter_by(active=True).order_by(Coupon.created_at.desc()).limit(3).all()
    return render_template('shop/index.html', featured=featured, newest=newest, categories=categories, coupons=coupons)


@shop_bp.route('/produkty')
def products():
    q = Product.query.filter_by(active=True)
    category_slug = request.args.get('category', '')
    brand = request.args.get('brand', '')
    size = request.args.get('size', '')
    sort = request.args.get('sort', 'newest')
    search = request.args.get('search', '').strip()

    if category_slug:
        category = Category.query.filter_by(slug=category_slug).first()
        if category:
            q = q.filter_by(category_id=category.id)
    if brand:
        q = q.filter(Product.brand == brand)
    if search:
        q = q.filter(Product.name.ilike(f'%{search}%'))
    if size:
        q = q.join(ProductSize).filter(ProductSize.size == size, ProductSize.stock > 0)

    if sort == 'price_asc':
        q = q.order_by(Product.price.asc())
    elif sort == 'price_desc':
        q = q.order_by(Product.price.desc())
    else:
        q = q.order_by(Product.created_at.desc())

    products = q.all()
    brands = [x[0] for x in db.session.query(Product.brand).distinct().order_by(Product.brand.asc()).all()]
    sizes = ['36', '37', '38', '39', '40', '41', '42', '43', '44', '45']
    return render_template('shop/products.html', products=products, brands=brands, sizes=sizes)


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
        session.modified = True
        flash('Produkt byl přidán do košíku.', 'success')
        return redirect(url_for('shop.cart'))
    return render_template('shop/product_detail.html', product=product, related=related)


@shop_bp.route('/cart')
def cart():
    items, subtotal, shipping, discount_amount, total = cart_detail()
    return render_template('shop/cart.html', items=items, subtotal=subtotal, shipping=shipping, discount_amount=discount_amount, total=total)


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
        order = Order(
            order_number='BZH' + ''.join(random.choices(string.digits, k=8)),
            customer_name=request.form.get('customer_name', '').strip(),
            email=request.form.get('email', '').strip(),
            phone=request.form.get('phone', '').strip(),
            street=request.form.get('street', '').strip(),
            city=request.form.get('city', '').strip(),
            postal_code=request.form.get('postal_code', '').strip(),
            shipping_method='Kurýr až domů zdarma',
            payment_method='QR kód / bankovní převod',
            shipping_price=shipping,
            subtotal=subtotal,
            discount_amount=discount_amount,
            total_price=total,
            note=request.form.get('note', '').strip(),
            user_id=current_user.id if current_user.is_authenticated else None,
            coupon_code=coupon_info.get('code', ''),
            affiliate_partner_name=coupon_info.get('affiliate_partner_name', '') if coupon_info.get('type') != 'fixed_final_price' else '',
            affiliate_commission_amount=round(total * (float(coupon_info.get('commission_percent_partner', 0)) / 100), 2) if coupon_info.get('type') != 'fixed_final_price' else 0,
        )
        if coupon_info.get('code'):
            coupon = Coupon.query.filter_by(code=coupon_info['code']).first()
            if coupon:
                order.coupon_id = coupon.id
                coupon.uses_count += 1
                if coupon.affiliate_partner:
                    coupon.affiliate_partner.commission_balance += order.affiliate_commission_amount
        db.session.add(order)
        db.session.flush()
        create_qr_for_order(order)
        cart = get_cart()
        for key, item in cart.items():
            product = Product.query.get(item['product_id'])
            size_row = ProductSize.query.filter_by(product_id=product.id, size=item['size']).first()
            if not size_row or size_row.stock < item['quantity']:
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
        db.session.commit()
        session['cart'] = {}
        session.pop('coupon', None)
        flash(f'Objednávka {order.order_number} byla úspěšně vytvořena.', 'success')
        return redirect(url_for('shop.order_success', order_number=order.order_number))

    return render_template('shop/checkout.html', items=items, subtotal=subtotal, shipping=shipping, discount_amount=discount_amount, total=total, coupon_info=coupon_info, bank_account=setting('bank_account', ''), bank_iban=setting('bank_iban', ''))


@shop_bp.route('/objednavka/<order_number>')
def order_success(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    return render_template('shop/order_success.html', order=order, bank_account=setting('bank_account', ''), bank_iban=setting('bank_iban', ''))


@shop_bp.route('/affiliate', methods=['GET', 'POST'])
def affiliate():
    codes = Coupon.query.filter_by(active=True).order_by(Coupon.code.asc()).all()
    partners = AffiliatePartner.query.order_by(AffiliatePartner.created_at.desc()).all()
    if request.method == 'POST':
        partner = AffiliatePartner(
            name=request.form.get('name', '').strip(),
            email=request.form.get('email', '').strip(),
            instagram=request.form.get('instagram', '').strip(),
            note=request.form.get('note', '').strip() + f"\nPreferovaný split: {request.form.get('preferred_split', '')}",
            status='Nová žádost',
        )
        db.session.add(partner)
        db.session.commit()
        flash('Žádost do affiliate programu byla odeslána.', 'success')
        return redirect(url_for('shop.affiliate'))
    return render_template('shop/affiliate.html', codes=codes, partners=partners)


@shop_bp.route('/affiliate/portal', methods=['GET', 'POST'])
@login_required
def affiliate_portal():
    partner = AffiliatePartner.query.filter_by(email=current_user.email).first()

    if not partner or partner.status != 'Aktivní':
        flash('Affiliate portál je dostupný až po schválení žádosti administrátorem.', 'warning')
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

@shop_bp.route('/create-admin')
def create_admin():
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
        is_admin=True
    )

    db.session.add(user)
    db.session.commit()

    return "Admin vytvořen"

@shop_bp.route('/ucet')
@login_required
def account():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('shop/account.html', orders=orders)
