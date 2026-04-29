import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from .utils import setting


def _clean_base_url(value):
    base = (value or '').strip().rstrip('/')
    if base and not base.startswith(('http://', 'https://')):
        base = 'https://' + base
    return base


def sumool_enabled():
    return setting('sumool_enabled', '0') == '1'


def sumool_config_ready():
    return bool(
        _clean_base_url(setting('sumool_base_url', ''))
        and setting('sumool_tokenkeys', '').strip()
        and setting('sumool_tokens', '').strip()
        and setting('sumool_user_id', '').strip()
    )


def _sumool_request(method, params):
    base_url = _clean_base_url(setting('sumool_base_url', ''))
    if not base_url:
        return {'ok': False, 'message': 'Chybí Sumool API URL.'}

    query = {
        'tokenkeys': setting('sumool_tokenkeys', '').strip(),
        'tokens': setting('sumool_tokens', '').strip(),
    }
    query.update(params or {})

    url = f"{base_url}/{method.lstrip('/')}?{urlencode(query)}"
    request = Request(url, headers={'User-Agent': 'BotyZaHubicku/1.0'})

    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read().decode('utf-8', errors='replace').strip()
    except HTTPError as exc:
        return {'ok': False, 'message': f'Sumool HTTP chyba {exc.code}', 'raw': ''}
    except URLError as exc:
        return {'ok': False, 'message': f'Sumool spojení selhalo: {exc.reason}', 'raw': ''}
    except Exception as exc:
        return {'ok': False, 'message': f'Sumool chyba: {exc}', 'raw': ''}

    cleaned = raw
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = cleaned[1:-1].strip()

    try:
        data = json.loads(cleaned)
    except Exception:
        return {'ok': False, 'message': 'Sumool vrátil neplatný JSON.', 'raw': raw}

    if data.get('HasError'):
        return {
            'ok': False,
            'message': data.get('Message') or data.get('Mssage') or 'Sumool API vrátilo chybu.',
            'data': data,
            'raw': raw,
        }

    return {'ok': True, 'message': 'OK', 'data': data, 'raw': raw}


def _country_code(order):
    # Web zatím nemá samostatné pole země. Sumool chce dvoupísmenný kód země.
    return setting('sumool_default_country', 'CZ').strip().upper() or 'CZ'


def _item_sku(item):
    product = getattr(item, 'product', None)
    sku = (getattr(product, 'supplier_sku', '') or '').strip() if product else ''
    if sku:
        return sku
    return (getattr(product, 'slug', '') or f'PRODUCT-{item.product_id}').strip()


def build_sumool_orderdata(order):
    user_id = setting('sumool_user_id', '').strip()
    currency = setting('sumool_currency', 'CZK').strip().upper() or 'CZK'

    payload = {
        'OrderNo': order.order_number,
        'UserId': user_id,
        'OrderTime': order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'PaymentTime': order.paid_at.strftime('%Y-%m-%d %H:%M:%S') if order.paid_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Currency': currency,
        'PayableAmount': round(float(order.total_price or 0), 2),
        'Remarks': (order.note or '')[:500],
        'Address': {
            'contact': order.customer_name,
            'country': _country_code(order),
            'province': '',
            'city': order.city,
            'area': '',
            'address1': order.street,
            'Address2': '',
            'mobilephone': order.phone,
            'tel': order.phone,
            'email': order.email,
            'zipcode': order.postal_code,
        },
        'Details': [],
    }

    store_no = setting('sumool_store_no', '').strip()
    logistic_name = setting('sumool_logistic_name', '').strip()
    logistic_mode_code = setting('sumool_logistic_mode_code', '').strip()
    if store_no:
        payload['StoreNo'] = store_no
    if logistic_name:
        payload['LogisticName'] = logistic_name
    if logistic_mode_code:
        payload['LogisticModeCode'] = logistic_mode_code

    for item in order.items:
        detail = {
            'sku': _item_sku(item),
            'price': round(float(item.unit_price or 0), 2),
            'num': int(item.quantity or 1),
        }
        size = (item.size or '').strip()
        color = (item.color or '').strip()
        memo = ' / '.join(x for x in [f'Velikost: {size}' if size else '', f'Barva: {color}' if color else ''] if x)
        if memo:
            detail['Memo'] = memo
        payload['Details'].append(detail)

    return payload


def submit_order_to_sumool(order):
    if not sumool_enabled():
        return {'ok': False, 'message': 'Sumool odesílání je vypnuté.'}
    if not sumool_config_ready():
        return {'ok': False, 'message': 'Sumool není nakonfigurovaný.'}
    orderdata = json.dumps(build_sumool_orderdata(order), ensure_ascii=False)
    return _sumool_request('PdaApi/CreateOrder', {'orderdata': orderdata})


def fetch_sumool_order_list(begin_time, end_time='', status='', orderno=''):
    params = {'beginTime': begin_time}
    if end_time:
        params['endTime'] = end_time
    if status:
        params['status'] = status
    if orderno:
        params['orderno'] = orderno
    return _sumool_request('PdaApi/GetOrderReceiptList', params)
