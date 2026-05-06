import base64
import json
import re
import unicodedata
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from . import db
from .models import ProductVariant
from .utils import setting


SIZE_ATTR = 'Velikost'
COLOR_ATTR = 'Barva'


def _clean_base_url(value):
    return (value or '').strip().rstrip('/')


def woocommerce_enabled():
    return setting('woocommerce_enabled', '0').strip() == '1'


def woocommerce_product_sync_enabled():
    return setting('woocommerce_auto_sync_products', '1').strip() == '1'


def woocommerce_config_ready():
    return bool(
        _clean_base_url(setting('woocommerce_base_url', ''))
        and setting('woocommerce_consumer_key', '').strip()
        and setting('woocommerce_consumer_secret', '').strip()
    )


def _split_name(full_name):
    parts = (full_name or '').strip().split()
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


def _auth_header():
    key = setting('woocommerce_consumer_key', '').strip()
    secret = setting('woocommerce_consumer_secret', '').strip()
    token = base64.b64encode(f'{key}:{secret}'.encode('utf-8')).decode('ascii')
    return f'Basic {token}'


def _request(method, path, payload=None):
    base_url = _clean_base_url(setting('woocommerce_base_url', ''))
    if not base_url:
        return {'ok': False, 'message': 'Chybí WooCommerce URL.'}

    url = urljoin(base_url + '/', path.lstrip('/'))
    body = json.dumps(payload or {}, ensure_ascii=False).encode('utf-8') if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            'Authorization': _auth_header(),
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
            'User-Agent': 'BotyZaHubicku/1.0',
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode('utf-8', errors='replace').strip()
            data = json.loads(raw) if raw else {}
            return {'ok': 200 <= response.status < 300, 'message': 'OK', 'data': data, 'raw': raw}
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace').strip()
        message = f'WooCommerce HTTP chyba {exc.code}'
        try:
            parsed = json.loads(raw)
            message = parsed.get('message') or message
        except Exception:
            pass
        return {'ok': False, 'message': message, 'raw': raw}
    except URLError as exc:
        return {'ok': False, 'message': f'WooCommerce spojení selhalo: {exc.reason}', 'raw': ''}
    except Exception as exc:
        return {'ok': False, 'message': f'WooCommerce chyba: {exc}', 'raw': ''}


def _country_code():
    return setting('woocommerce_default_country', 'CZ').strip().upper() or 'CZ'


def _sku_token(value):
    value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^A-Za-z0-9]+', '-', value).strip('-').upper()
    return value or 'VAR'


def _sku_prefix():
    return _sku_token(setting('woocommerce_sku_prefix', 'BZH') or 'BZH')


def _split_csv(value):
    return [x.strip() for x in (value or '').split(',') if x.strip()]


def product_base_sku(product):
    if (product.supplier_sku or '').strip():
        return product.supplier_sku.strip()
    return f'{_sku_prefix()}-{int(product.id):06d}'


def variant_sku(product, size, color=''):
    parts = [product_base_sku(product), _sku_token(size)]
    if color:
        parts.append(_sku_token(color))
    return '-'.join(parts)[:120]


def ensure_product_skus_and_variants(product):
    """Vytvoří lokální SKU a řádky variant pro všechny kombinace velikost × barva."""
    if not (product.supplier_sku or '').strip():
        product.supplier_sku = product_base_sku(product)

    sizes = [row.size for row in product.sizes if (row.size or '').strip()]
    colors = _split_csv(product.colors)
    if not colors:
        colors = ['']

    stock_by_size = {row.size: int(row.stock or 0) for row in product.sizes}
    wanted = set()
    for size in sizes:
        for color in colors:
            wanted.add((size, color))
            variant = ProductVariant.query.filter_by(product_id=product.id, size=size, color=color).first()
            per_variant_stock = stock_by_size.get(size, 0)
            if color and len(colors) > 1:
                per_variant_stock = max(1, per_variant_stock // len(colors)) if per_variant_stock > 0 else 0
            if not variant:
                variant = ProductVariant(
                    product_id=product.id,
                    size=size,
                    color=color,
                    sku=variant_sku(product, size, color),
                    stock=per_variant_stock,
                )
                db.session.add(variant)
            else:
                variant.sku = variant.sku or variant_sku(product, size, color)
                variant.stock = per_variant_stock

    for variant in list(product.variants):
        if (variant.size, variant.color or '') not in wanted:
            db.session.delete(variant)


def _product_images(product):
    images = []
    values = [product.image] + list(getattr(product, 'gallery_list', []) or [])
    domain = (setting('domain_name', '') or '').strip().rstrip('/')
    for value in values:
        value = (value or '').strip()
        if not value:
            continue
        if value.startswith(('http://', 'https://')):
            src = value
        elif domain:
            base = domain if domain.startswith(('http://', 'https://')) else f'https://{domain}'
            src = f'{base}/uploads/{value.lstrip("/")}'
        else:
            continue
        if src not in [img['src'] for img in images]:
            images.append({'src': src})
    return images


def _attributes_payload(product):
    sizes = [row.size for row in product.sizes if (row.size or '').strip()]
    colors = _split_csv(product.colors)
    attributes = []
    if sizes:
        attributes.append({'name': SIZE_ATTR, 'visible': True, 'variation': True, 'options': sizes})
    if colors:
        attributes.append({'name': COLOR_ATTR, 'visible': True, 'variation': True, 'options': colors})
    return attributes


def _variation_attributes(variant):
    attrs = [{'name': SIZE_ATTR, 'option': variant.size}]
    if (variant.color or '').strip():
        attrs.append({'name': COLOR_ATTR, 'option': variant.color.strip()})
    return attrs


def build_woocommerce_product(product):
    payload = {
        'name': product.name,
        'type': 'variable',
        'status': 'publish' if product.active else 'draft',
        'sku': product_base_sku(product),
        'regular_price': f'{float(product.original_price or product.price or 0):.2f}',
        'description': product.description or '',
        'short_description': product.short_description or '',
        'manage_stock': False,
        'attributes': _attributes_payload(product),
        'meta_data': [
            {'key': 'BZH produkt ID', 'value': str(product.id)},
            {'key': 'BZH zdroj', 'value': 'BotyZaHubicku.cz'},
        ],
    }
    images = _product_images(product)
    if images:
        payload['images'] = images
    return payload


def build_woocommerce_variation(product, variant):
    return {
        'sku': variant.sku or variant_sku(product, variant.size, variant.color),
        'regular_price': f'{float(product.price or 0):.2f}',
        'sale_price': f'{float(product.price or 0):.2f}' if product.original_price and product.original_price > product.price else '',
        'manage_stock': True,
        'stock_quantity': int(variant.stock or 0),
        'status': 'publish' if product.active else 'private',
        'attributes': _variation_attributes(variant),
        'meta_data': [
            {'key': 'BZH produkt ID', 'value': str(product.id)},
            {'key': 'BZH varianta ID', 'value': str(variant.id)},
            {'key': 'Velikost', 'value': variant.size},
            {'key': 'Barva', 'value': variant.color or ''},
        ],
    }


def sync_product_to_woocommerce(product):
    if not woocommerce_enabled() or not woocommerce_product_sync_enabled():
        return {'ok': False, 'message': 'Synchronizace produktů do WooCommerce je vypnutá.'}
    if not woocommerce_config_ready():
        return {'ok': False, 'message': 'WooCommerce není nakonfigurovaný.'}

    ensure_product_skus_and_variants(product)
    db.session.flush()

    product_payload = build_woocommerce_product(product)
    if (product.woocommerce_product_id or '').strip():
        result = _request('PUT', f'/wp-json/wc/v3/products/{product.woocommerce_product_id}', product_payload)
    else:
        result = _request('POST', '/wp-json/wc/v3/products', product_payload)

    product.woocommerce_sync_status = 'odeslano' if result.get('ok') else 'chyba'
    product.woocommerce_sync_message = result.get('message', '')
    product.woocommerce_synced_at = datetime.now()

    if not result.get('ok'):
        return result

    product_data = result.get('data') or {}
    if product_data.get('id'):
        product.woocommerce_product_id = str(product_data['id'])

    variant_errors = []
    variants = ProductVariant.query.filter_by(product_id=product.id).order_by(ProductVariant.sku.asc()).all()
    for variant in variants:
        payload = build_woocommerce_variation(product, variant)
        if (variant.woocommerce_variation_id or '').strip():
            v_result = _request('PUT', f'/wp-json/wc/v3/products/{product.woocommerce_product_id}/variations/{variant.woocommerce_variation_id}', payload)
        else:
            v_result = _request('POST', f'/wp-json/wc/v3/products/{product.woocommerce_product_id}/variations', payload)
        variant.woocommerce_sync_status = 'odeslano' if v_result.get('ok') else 'chyba'
        variant.woocommerce_sync_message = v_result.get('message', '')
        variant.woocommerce_synced_at = datetime.now()
        if v_result.get('ok'):
            v_data = v_result.get('data') or {}
            if v_data.get('id'):
                variant.woocommerce_variation_id = str(v_data['id'])
        else:
            variant_errors.append(f'{variant.sku}: {v_result.get("message", "chyba")}')

    if variant_errors:
        return {'ok': False, 'message': 'Produkt vytvořen, ale některé varianty se neuložily: ' + '; '.join(variant_errors[:5])}
    return {'ok': True, 'message': 'Produkt i všechny varianty byly synchronizované do WooCommerce.', 'data': product_data, 'raw': result.get('raw', '')}


def build_woocommerce_order(order):
    first_name, last_name = _split_name(order.customer_name)
    country = _country_code()

    address = {
        'first_name': first_name,
        'last_name': last_name,
        'company': '',
        'address_1': order.street,
        'address_2': '',
        'city': order.city,
        'state': '',
        'postcode': order.postal_code,
        'country': country,
    }

    billing = dict(address)
    billing.update({
        'email': order.email,
        'phone': order.phone,
    })

    line_items = []
    for item in order.items:
        product = getattr(item, 'product', None)
        variant = None
        if product:
            variant = ProductVariant.query.filter_by(
                product_id=product.id,
                size=item.size or '',
                color=item.color or '',
            ).first()
        supplier_sku = (getattr(variant, 'sku', '') or getattr(product, 'supplier_sku', '') or '').strip() if product else ''
        meta_data = [
            {'key': SIZE_ATTR, 'value': item.size or ''},
            {'key': COLOR_ATTR, 'value': item.color or ''},
            {'key': 'BZH produkt ID', 'value': str(item.product_id)},
        ]
        if supplier_sku:
            meta_data.append({'key': 'SKU dodavatele', 'value': supplier_sku})

        line_item = {
            'name': item.product_name,
            'quantity': int(item.quantity or 1),
            'subtotal': f'{float(item.unit_price or 0) * int(item.quantity or 1):.2f}',
            'total': f'{float(item.unit_price or 0) * int(item.quantity or 1):.2f}',
            'meta_data': meta_data,
        }
        if product and (product.woocommerce_product_id or '').strip():
            line_item['product_id'] = int(product.woocommerce_product_id)
        if variant and (variant.woocommerce_variation_id or '').strip():
            line_item['variation_id'] = int(variant.woocommerce_variation_id)
        line_items.append(line_item)

    payload = {
        'status': setting('woocommerce_order_status', 'processing').strip() or 'processing',
        'set_paid': True,
        'currency': setting('woocommerce_currency', 'CZK').strip().upper() or 'CZK',
        'payment_method': 'bzh_bank_transfer',
        'payment_method_title': order.payment_method or 'Platba na BotyZaHubicku.cz',
        'customer_note': order.note or '',
        'billing': billing,
        'shipping': address,
        'line_items': line_items,
        'shipping_lines': [
            {
                'method_id': 'bzh_shipping',
                'method_title': order.shipping_method or 'Doprava',
                'total': f'{float(order.shipping_price or 0):.2f}',
            }
        ],
        'meta_data': [
            {'key': 'Zdroj objednávky', 'value': 'BotyZaHubicku.cz'},
            {'key': 'BZH číslo objednávky', 'value': order.order_number},
            {'key': 'BZH variabilní symbol', 'value': order.variable_symbol or ''},
            {'key': 'BZH zaplaceno', 'value': order.paid_at.strftime('%Y-%m-%d %H:%M:%S') if order.paid_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
        ],
    }

    if order.discount_amount and order.discount_amount > 0:
        payload['fee_lines'] = [
            {
                'name': f'Sleva {order.coupon_code or ""}'.strip(),
                'tax_status': 'none',
                'total': f'-{float(order.discount_amount):.2f}',
            }
        ]

    return payload


def submit_order_to_woocommerce(order):
    if not woocommerce_enabled():
        return {'ok': False, 'message': 'WooCommerce odesílání je vypnuté.'}
    if not woocommerce_config_ready():
        return {'ok': False, 'message': 'WooCommerce není nakonfigurovaný.'}
    return _request('POST', '/wp-json/wc/v3/orders', build_woocommerce_order(order))
