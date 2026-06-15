import html
import os
import re
import time
import uuid
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from . import db
from .models import Order, ProductVariant
from .utils import send_email, setting

SUPPLIER_EMAIL_DEFAULT = 'fullerko@seznam.cz'
SUPPLIER_TIMEZONE_DEFAULT = 'Europe/Prague'


def _now_prague():
    return datetime.now(ZoneInfo(SUPPLIER_TIMEZONE_DEFAULT)).replace(tzinfo=None)


def _safe_text(value, default='-'):
    text = str(value or '').strip()
    return text if text else default


def _p(value, style):
    text = html.escape(_safe_text(value)).replace('\n', '<br/>')
    return Paragraph(text, style)


def _link_text(label, url):
    url = _safe_text(url, '')
    if not url:
        return '-'
    clean_url = html.escape(url, quote=True)
    clean_label = html.escape(label or url)
    return f'<link href="{clean_url}" color="blue">{clean_label}</link>'


def _register_fonts():
    font_dir = os.path.join(current_app.root_path, 'static', 'fonts')
    regular = os.path.join(font_dir, 'DejaVuSans.ttf')
    bold = os.path.join(font_dir, 'DejaVuSans-Bold.ttf')

    if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('DejaVu', regular))
    if 'DejaVu-Bold' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('DejaVu-Bold', bold))

COLOR_TRANSLATIONS = {
    'cerna': 'Black',
    'bila': 'White',
    'seda': 'Gray',
    'siva': 'Gray',
    'stribrna': 'Silver',
    'zlata': 'Gold',
    'cervena': 'Red',
    'modra': 'Blue',
    'zelena': 'Green',
    'zluta': 'Yellow',
    'oranzova': 'Orange',
    'ruzova': 'Pink',
    'fialova': 'Purple',
    'hneda': 'Brown',
    'bezova': 'Beige',
    'kremova': 'Cream',
    'slonovinova': 'Ivory',
    'telova': 'Nude',
    'prirodni': 'Natural',
    'khaki': 'Khaki',
    'olivova': 'Olive',
    'morska': 'Sea blue',
    'tyrkysova': 'Turquoise',
    'petrolejova': 'Petrol',
    'mintova': 'Mint',
    'matova': 'Mint',
    'limetkova': 'Lime',
    'smaragdova': 'Emerald',
    'neonova': 'Neon',
    'neonove zelena': 'Neon green',
    'neonove zluta': 'Neon yellow',
    'neonove ruzova': 'Neon pink',
    'neonove oranzova': 'Neon orange',
    'svetle cerna': 'Light black',
    'tmave cerna': 'Dark black',
    'svetle bila': 'Light white',
    'tmave bila': 'Dark white',
    'svetle seda': 'Light gray',
    'tmave seda': 'Dark gray',
    'antracitova': 'Anthracite',
    'grafitova': 'Graphite',
    'uhlikova': 'Charcoal',
    'kourova': 'Smoke gray',
    'popelava': 'Ash gray',
    'svetle modra': 'Light blue',
    'tmave modra': 'Dark blue',
    'navy': 'Navy',
    'namornicka modra': 'Navy blue',
    'kralovska modra': 'Royal blue',
    'blankytne modra': 'Sky blue',
    'nebesky modra': 'Sky blue',
    'ledove modra': 'Ice blue',
    'ocelove modra': 'Steel blue',
    'dzinova modra': 'Denim blue',
    'azurova': 'Azure',
    'kobaltova': 'Cobalt blue',
    'indigo': 'Indigo',
    'safirova': 'Sapphire blue',
    'svetle zelena': 'Light green',
    'tmave zelena': 'Dark green',
    'lesni zelena': 'Forest green',
    'travnate zelena': 'Grass green',
    'mechova': 'Moss green',
    'pistaciova': 'Pistachio',
    'salvejova': 'Sage green',
    'lahvove zelena': 'Bottle green',
    'jablkove zelena': 'Apple green',
    'vojenska zelena': 'Army green',
    'svetle cervena': 'Light red',
    'tmave cervena': 'Dark red',
    'vinova': 'Burgundy',
    'bordo': 'Burgundy',
    'vishnova': 'Cherry red',
    'tresnova': 'Cherry red',
    'rubinova': 'Ruby red',
    'koralova': 'Coral',
    'lososova': 'Salmon',
    'malinova': 'Raspberry',
    'karmínova': 'Crimson',
    'karminova': 'Crimson',
    'cihlova': 'Brick red',
    'terakotova': 'Terracotta',
    'svetle ruzova': 'Light pink',
    'tmave ruzova': 'Dark pink',
    'staroruzova': 'Dusty pink',
    'pudrova': 'Powder pink',
    'pastelove ruzova': 'Pastel pink',
    'fuchsiova': 'Fuchsia',
    'magenta': 'Magenta',
    'svetle fialova': 'Light purple',
    'tmave fialova': 'Dark purple',
    'lila': 'Lilac',
    'levandulova': 'Lavender',
    'ametystova': 'Amethyst',
    'slevova': 'Plum',
    'svestkova': 'Plum',
    'vínová': 'Burgundy',
    'svetle zluta': 'Light yellow',
    'tmave zluta': 'Dark yellow',
    'horcicova': 'Mustard',
    'citronova': 'Lemon yellow',
    'medova': 'Honey',
    'slunecne zluta': 'Sun yellow',
    'pastelove zluta': 'Pastel yellow',
    'svetle oranzova': 'Light orange',
    'tmave oranzova': 'Dark orange',
    'merunkova': 'Apricot',
    'broskvova': 'Peach',
    'mandarinkova': 'Tangerine',
    'medená': 'Copper',
    'medena': 'Copper',
    'bronzova': 'Bronze',
    'svetle hneda': 'Light brown',
    'tmave hneda': 'Dark brown',
    'cokoladova': 'Chocolate brown',
    'karamelova': 'Caramel',
    'kastanova': 'Chestnut brown',
    'orechova': 'Walnut brown',
    'kavova': 'Coffee brown',
    'piskova': 'Sand',
    'camel': 'Camel',
    'taupe': 'Taupe',
    'hnedo seda': 'Taupe',
    'pruhledna': 'Transparent',
    'duhova': 'Rainbow',
    'multicolor': 'Multicolor',
    'vicebarevna': 'Multicolor',
    'barevna': 'Multicolor',
    'maskacova': 'Camouflage',
    'leo': 'Leopard',
    'leopardi': 'Leopard',
    'zebra': 'Zebra',
    'hadí': 'Snake print',
    'hadi': 'Snake print',
    'black': 'Black',
    'white': 'White',
    'gray': 'Gray',
    'grey': 'Gray',
    'silver': 'Silver',
    'gold': 'Gold',
    'red': 'Red',
    'blue': 'Blue',
    'green': 'Green',
    'yellow': 'Yellow',
    'orange': 'Orange',
    'pink': 'Pink',
    'purple': 'Purple',
    'brown': 'Brown',
    'beige': 'Beige',
    'cream': 'Cream',
    'ivory': 'Ivory',
}


def _normalize_color_key(value):
    text = _safe_text(value, '').lower().strip()
    replacements = {
        'á': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'ě': 'e',
        'í': 'i', 'ň': 'n', 'ó': 'o', 'ř': 'r', 'š': 's',
        'ť': 't', 'ú': 'u', 'ů': 'u', 'ý': 'y', 'ž': 'z',
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = text.replace('-', ' ').replace('_', ' ')
    return ' '.join(text.split())




# Supplier-facing PDF must be understandable in English. Static labels are already
# English; these dictionaries cover common dynamic values saved from the Czech
# checkout/admin UI, so they do not leak into the supplier report.
CZECH_VALUE_TRANSLATIONS = {
    # Order statuses and payment statuses
    'nova': 'New',
    'nove': 'New',
    'vytvorena': 'Created',
    'vytvoreno': 'Created',
    'cekajici': 'Pending',
    'ceka na platbu': 'Waiting for payment',
    'cekajici na platbu': 'Waiting for payment',
    'nezaplaceno': 'Unpaid',
    'zaplaceno': 'Paid',
    'uhrazeno': 'Paid',
    'odeslano': 'Shipped',
    'vyrizeno': 'Completed',
    'dokonceno': 'Completed',
    'storno': 'Cancelled',
    'stornovano': 'Cancelled',
    'zruseno': 'Cancelled',
    'pending': 'Pending',
    'paid': 'Paid',
    'unpaid': 'Unpaid',
    'cancelled': 'Cancelled',
    'canceled': 'Cancelled',

    # Shipping methods
    'kuryr az domu zdarma': 'Home courier delivery - free of charge',
    'kuryr domu zdarma': 'Home courier delivery - free of charge',
    'kuryr az domu': 'Home courier delivery',
    'kuryr': 'Courier delivery',
    'doprava zdarma': 'Free shipping',
    'osobni odber': 'Personal pickup',
    'zasilkovna': 'Packeta pickup point',
    'balikovna': 'Balikovna pickup point',
    'posta': 'Postal delivery',
    'ceska posta': 'Czech Post delivery',

    # Payment methods
    'qr kod / bankovni prevod': 'QR code / bank transfer',
    'qr kod bankovni prevod': 'QR code / bank transfer',
    'qr platba': 'QR payment',
    'bankovni prevod': 'Bank transfer',
    'prevodem': 'Bank transfer',
    'platba prevodem': 'Bank transfer',
    'platba kartou': 'Card payment',
    'online platba kartou': 'Online card payment',
    'dobirka': 'Cash on delivery',
    'hotove': 'Cash payment',
    'hotovost': 'Cash payment',
}

PRODUCT_WORD_TRANSLATIONS = {
    # Intended wearer / category
    'damske': "women's", 'damska': "women's", 'damsky': "women's", 'damskych': "women's",
    'panske': "men's", 'panska': "men's", 'pansky': "men's", 'panskych': "men's",
    'detske': "children's", 'detska': "children's", 'detsky': "children's", 'unisex': 'unisex',

    # Product types
    'boty': 'shoes', 'obuv': 'footwear', 'tenisky': 'sneakers', 'botasky': 'sneakers',
    'sandaly': 'sandals', 'pantofle': 'slippers', 'nazouvaky': 'slip-ons', 'mokasiny': 'loafers',
    'kozacky': 'boots', 'kotnikove': 'ankle', 'kotnikova': 'ankle', 'kotnikovy': 'ankle',
    'kozačky': 'boots', 'polobotky': 'low shoes', 'lodicky': 'pumps', 'lodičky': 'pumps',

    # Styles / use
    'bezecke': 'running', 'bezecka': 'running', 'sportovni': 'sports', 'elegantni': 'elegant',
    'volnocasove': 'casual', 'vychazkove': 'casual', 'letni': 'summer', 'zimni': 'winter',
    'jarni': 'spring', 'podzimni': 'autumn', 'pracovni': 'work', 'outdoorove': 'outdoor',
    'turisticke': 'hiking', 'plazove': 'beach', 'vysoke': 'high-top', 'nizke': 'low-top',
    'lehke': 'lightweight', 'pohodlne': 'comfortable', 'protiskluzove': 'non-slip',
    'platforma': 'platform', 'platforme': 'platform', 'podpatek': 'heel', 'na podpatku': 'with heel',

    # Common color word forms in product names
    'cerne': 'black', 'cerna': 'black', 'cerny': 'black', 'black': 'black',
    'bile': 'white', 'bila': 'white', 'bily': 'white', 'white': 'white',
    'sede': 'gray', 'seda': 'gray', 'sedy': 'gray', 'stribrne': 'silver', 'stribrna': 'silver',
    'zlate': 'gold', 'zlata': 'gold', 'zlaty': 'gold', 'cervene': 'red', 'cervena': 'red',
    'modre': 'blue', 'modra': 'blue', 'zelene': 'green', 'zelena': 'green',
    'zlute': 'yellow', 'zluta': 'yellow', 'oranzove': 'orange', 'oranzova': 'orange',
    'ruzove': 'pink', 'ruzova': 'pink', 'fialove': 'purple', 'fialova': 'purple',
    'hnede': 'brown', 'hneda': 'brown', 'bezove': 'beige', 'bezova': 'beige',
    'kremove': 'cream', 'kremova': 'cream', 'khaki': 'khaki', 'multicolor': 'multicolor',
}

NOTE_PHRASE_TRANSLATIONS = [
    ('prosím', 'please'), ('prosim', 'please'), ('děkuji', 'thank you'), ('dekuji', 'thank you'),
    ('díky', 'thanks'), ('diky', 'thanks'), ('zavolejte', 'please call'), ('volejte', 'call'),
    ('nevolejte', 'do not call'), ('nechat u dveří', 'leave at the door'),
    ('nechat u dveri', 'leave at the door'), ('u dveří', 'at the door'), ('u dveri', 'at the door'),
    ('soused', 'neighbour'), ('sousedka', 'neighbour'), ('balík', 'parcel'), ('balik', 'parcel'),
    ('adresa', 'address'), ('doručení', 'delivery'), ('doruceni', 'delivery'),
    ('večer', 'evening'), ('vecer', 'evening'), ('ráno', 'morning'), ('rano', 'morning'),
]


def _translate_known_value(value, default='-'):
    text = _safe_text(value, default)
    if text == default:
        return default
    return CZECH_VALUE_TRANSLATIONS.get(_normalize_color_key(text), text)


def _translate_words_to_english(value):
    text = _safe_text(value, '')
    if not text:
        return '-'
    # Keep separators/spaces as they are, but translate known Czech words.
    parts = re.split(r'(\W+)', text, flags=re.UNICODE)
    translated = []
    changed = False
    for part in parts:
        key = _normalize_color_key(part)
        replacement = PRODUCT_WORD_TRANSLATIONS.get(key)
        if replacement:
            translated.append(replacement)
            changed = True
        elif key in COLOR_TRANSLATIONS:
            translated.append(COLOR_TRANSLATIONS[key].lower())
            changed = True
        else:
            translated.append(part)
    result = ''.join(translated).strip()
    return result if result else '-'


def _translate_customer_note(value):
    text = _safe_text(value, '')
    if not text:
        return 'No customer note.'

    translated = text
    for source, target in NOTE_PHRASE_TRANSLATIONS:
        translated = re.sub(re.escape(source), target, translated, flags=re.IGNORECASE)
    return translated

def _translate_color_to_english(value):
    text = _safe_text(value, '')
    if not text or text == '-':
        return '-'

    for separator in [',', '/', ';', '|']:
        if separator in text:
            translated_parts = [
                _translate_color_to_english(part.strip())
                for part in text.split(separator)
                if part.strip()
            ]
            return f' {separator} '.join(translated_parts) if translated_parts else '-'

    return COLOR_TRANSLATIONS.get(_normalize_color_key(text), text)

def _styles():
    _register_fonts()
    styles = getSampleStyleSheet()
    for name in ['Normal', 'Heading1', 'Heading2', 'Heading3']:
        styles[name].fontName = 'DejaVu'
    styles['Heading1'].fontName = 'DejaVu-Bold'
    styles['Heading2'].fontName = 'DejaVu-Bold'
    styles['Heading3'].fontName = 'DejaVu-Bold'
    styles['Normal'].fontSize = 8.5
    styles['Normal'].leading = 11

    styles.add(ParagraphStyle(
        name='ReportTitle',
        parent=styles['Heading1'],
        fontName='DejaVu-Bold',
        fontSize=18,
        leading=22,
        spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading2'],
        fontName='DejaVu-Bold',
        fontSize=12,
        leading=15,
        spaceBefore=4,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='Small',
        parent=styles['Normal'],
        fontSize=7.2,
        leading=9.2,
    ))
    styles.add(ParagraphStyle(
        name='Label',
        parent=styles['Normal'],
        fontName='DejaVu-Bold',
        fontSize=8.2,
        leading=10,
    ))
    return styles


def _image_candidates(product):
    values = []
    if product:
        if product.image:
            values.append(product.image)
        values.extend([g for g in (product.gallery or '').split(',') if g.strip()])
    return values


def _local_image_path(value):
    value = _safe_text(value, '')
    if not value or value.startswith(('http://', 'https://')):
        return None

    candidates = []
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    if upload_folder:
        candidates.append(os.path.join(upload_folder, value))
    candidates.extend([
        os.path.join(current_app.root_path, 'static', 'uploads', value),
        os.path.join(current_app.root_path, '..', 'uploads', value),
    ])

    for path in candidates:
        if path and os.path.exists(path) and os.path.isfile(path):
            return path
    return None


def _product_image_flowable(product, styles):
    for value in _image_candidates(product):
        path = _local_image_path(value)
        if not path:
            continue
        try:
            image = Image(path)
            image._restrictSize(35 * mm, 35 * mm)
            return image
        except Exception:
            continue
    return _p('No local image available', styles['Small'])


def _photo_references(product):
    references = []
    for value in _image_candidates(product):
        value = _safe_text(value, '')
        if not value:
            continue
        if value.startswith(('http://', 'https://')):
            references.append(value)
        else:
            references.append(value)
    return ', '.join(references) if references else '-'


def _order_shipping_block(order):
    return '\n'.join([
        f'Name: {_safe_text(order.customer_name)}',
        f'Email: {_safe_text(order.email)}',
        f'Phone: {_safe_text(order.phone)}',
        f'Street: {_safe_text(order.street)}',
        f'City: {_safe_text(order.city)}',
        f'Postal code: {_safe_text(order.postal_code)}',
        'Country: Czech Republic',
        f'Shipping method: {_translate_known_value(order.shipping_method)}',
    ])


def _payment_block(order):
    paid_at = order.paid_at.strftime('%Y-%m-%d %H:%M') if order.paid_at else '-'
    created_at = order.created_at.strftime('%Y-%m-%d %H:%M') if order.created_at else '-'
    return '\n'.join([
        f'Created at: {created_at}',
        f'Order status: {_translate_known_value(getattr(order, "status", ""))}',
        f'Payment method: {_translate_known_value(order.payment_method)}',
        f'Payment status: {_translate_known_value(order.payment_status)}',
        f'Paid at: {paid_at}',
        f'Order total: {int(order.total_price or 0)} CZK',
        f'Variable symbol: {_safe_text(order.variable_symbol)}',
    ])


def _variant_for_item(item):
    if not item.product_id:
        return None
    query = ProductVariant.query.filter_by(product_id=item.product_id, size=item.size or '')
    if item.color:
        variant = query.filter(db.func.lower(ProductVariant.color) == (item.color or '').lower()).first()
        if variant:
            return variant
    return query.first()


def _order_item_table(order, styles):
    header = [
        _p('Photo', styles['Label']),
        _p('Product and supplier identifiers', styles['Label']),
        _p('Customer selection', styles['Label']),
        _p('Supplier/source URL', styles['Label']),
    ]
    rows = [header]

    for item in order.items:
        product = item.product
        variant = _variant_for_item(item)

        translated_name = _translate_words_to_english(item.product_name)
        product_data = [
            f'Product: {translated_name}',
        ]
        product_data.extend([
            f'Brand: {_safe_text(product.brand if product else "")}',
            f'Internal product ID: {_safe_text(item.product_id)}',
            f'Store variant SKU: {_safe_text(getattr(variant, "sku", ""))}',
            f'Supplier SKU: {_safe_text(getattr(variant, "supplier_sku", ""))}',
            f'Supplier product code: {_safe_text(getattr(variant, "supplier_product_code", ""))}',
            f'Supplier EAN: {_safe_text(getattr(variant, "supplier_ean", ""))}',
        ])

        supplier_color = getattr(variant, 'supplier_color', '') if variant else ''
        selection = [
            f'Quantity: {item.quantity}',
            f'Size: {_safe_text(item.size)}',
            f'Selected color: {_translate_color_to_english(item.color)}',
            f'Supplier color: {_translate_color_to_english(supplier_color)}',
            f'Unit price on store: {int(item.unit_price or 0)} CZK',
        ]

        product_url = _safe_text(product.source_url if product else '')

        rows.append([
            _product_image_flowable(product, styles),
            _p('\n'.join(product_data), styles['Small']),
            _p('\n'.join(selection), styles['Small']),
            _p(product_url, styles['Small']),
        ])

    table = Table(rows, colWidths=[42 * mm, 62 * mm, 38 * mm, 43 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#d1d5db')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return table

def _separator():
    table = Table([['']], colWidths=[185 * mm], rowHeights=[6])
    table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, -1), 3, colors.black),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    return table


def get_pending_supplier_orders():
    query = Order.query.filter(Order.supplier_report_sent_at.is_(None))
    if setting('supplier_report_only_paid', '1') == '1':
        query = query.filter(
            db.or_(
                Order.payment_status == 'paid',
                Order.status == 'Zaplaceno',
                Order.paid_at.isnot(None),
            )
        )
    return query.order_by(Order.created_at.asc()).all()


def generate_supplier_orders_pdf(orders, batch_id=None):
    styles = _styles()
    batch_id = batch_id or f'BZH-SUP-{datetime.now().strftime("%Y%m%d-%H%M%S")}'
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f'Supplier order report {batch_id}',
    )

    elements = []
    generated_at = datetime.now(ZoneInfo(SUPPLIER_TIMEZONE_DEFAULT)).strftime('%Y-%m-%d %H:%M %Z')
    elements.append(Paragraph('Daily supplier order report', styles['ReportTitle']))
    elements.append(_p(f'Batch ID: {batch_id}', styles['Normal']))
    elements.append(_p(f'Generated at: {generated_at}\nTotal orders in this PDF: {len(orders)}', styles['Normal']))
    elements.append(Spacer(1, 6))
    elements.append(_separator())
    elements.append(Spacer(1, 6))

    for index, order in enumerate(orders, start=1):
        order_elements = []
        order_elements.append(Paragraph(f'Order {index}/{len(orders)} - {html.escape(order.order_number)}', styles['SectionTitle']))
        summary = Table([
            [_p('Customer and shipping details', styles['Label']), _p('Payment / order details', styles['Label'])],
            [_p(_order_shipping_block(order), styles['Small']), _p(_payment_block(order), styles['Small'])],
            [_p('Customer note / instructions', styles['Label']), _p(_translate_customer_note(order.note), styles['Small'])],
        ], colWidths=[92 * mm, 92 * mm])
        summary.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
            ('BACKGROUND', (0, 2), (0, 2), colors.HexColor('#f3f4f6')),
            ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#d1d5db')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('SPAN', (1, 2), (1, 2)),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        order_elements.append(summary)
        order_elements.append(Spacer(1, 8))
        order_elements.append(_order_item_table(order, styles))
        order_elements.append(Spacer(1, 8))
        order_elements.append(_separator())

        elements.append(KeepTogether(order_elements[:2]))
        elements.extend(order_elements[2:])
        if index < len(orders):
            elements.append(Spacer(1, 8))

    doc.build(elements)
    buffer.seek(0)
    return buffer

def _supplier_lock_path():
    return os.path.join(current_app.instance_path, 'supplier_report.lock')


def _acquire_lock(max_age_seconds=60 * 60):
    path = _supplier_lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        if os.path.exists(path) and time.time() - os.path.getmtime(path) > max_age_seconds:
            os.remove(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def _release_lock():
    try:
        os.remove(_supplier_lock_path())
    except FileNotFoundError:
        pass


def send_supplier_orders_report():
    if setting('supplier_report_enabled', '1') != '1':
        return {'ok': True, 'sent': False, 'count': 0, 'message': 'supplier report is disabled'}

    if not _acquire_lock():
        return {'ok': True, 'sent': False, 'count': 0, 'message': 'supplier report is already running'}

    try:
        orders = get_pending_supplier_orders()
        if not orders:
            return {'ok': True, 'sent': False, 'count': 0, 'message': 'no pending orders'}

        batch_id = f'BZH-SUP-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}'
        pdf = generate_supplier_orders_pdf(orders, batch_id=batch_id)
        pdf_bytes = pdf.read()
        recipient = setting('supplier_report_email', SUPPLIER_EMAIL_DEFAULT).strip() or SUPPLIER_EMAIL_DEFAULT
        subject = f'Daily supplier orders - {len(orders)} order(s) - {batch_id}'
        html_body = f'''
        <p>Hello,</p>
        <p>attached is today's supplier PDF report with <strong>{len(orders)}</strong> paid order(s).</p>
        <p>Batch ID: <strong>{batch_id}</strong></p>
        <p>Best regards,<br>BotyZaHubicku.cz</p>
        '''
        text_body = f"Daily supplier PDF report with {len(orders)} paid order(s). Batch ID: {batch_id}"

        reports_dir = os.path.join(current_app.instance_path, 'supplier_reports')
        os.makedirs(reports_dir, exist_ok=True)
        pdf_path = os.path.join(reports_dir, f'supplier_orders_{batch_id}.pdf')
        with open(pdf_path, 'wb') as handle:
            handle.write(pdf_bytes)

        mode = send_email(
            subject=subject,
            to_email=recipient,
            html_body=html_body,
            text_body=text_body,
            attachments=[{
                'filename': f'supplier_orders_{batch_id}.pdf',
                'content': pdf_bytes,
                'maintype': 'application',
                'subtype': 'pdf',
            }],
        )

        if mode != 'smtp':
            for order in orders:
                order.supplier_report_status = 'smtp_missing'
                order.supplier_report_message = f'PDF was generated but no SMTP is configured. Saved locally: {pdf_path}'
            db.session.commit()
            return {
                'ok': False,
                'sent': False,
                'count': len(orders),
                'batch_id': batch_id,
                'recipient': recipient,
                'mode': mode,
                'pdf_size_bytes': len(pdf_bytes),
                'pdf_path': pdf_path,
                'message': 'SMTP is not configured, so the email was saved to local outbox only.',
            }

        now = _now_prague()
        for order in orders:
            order.supplier_report_sent_at = now
            order.supplier_report_batch_id = batch_id
            order.supplier_report_status = 'sent'
            order.supplier_report_message = f'Sent to {recipient} via {mode}'
        db.session.commit()

        return {
            'ok': True,
            'sent': True,
            'count': len(orders),
            'batch_id': batch_id,
            'recipient': recipient,
            'mode': mode,
            'pdf_size_bytes': len(pdf_bytes),
            'pdf_path': pdf_path,
        }
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Supplier report failed')
        return {'ok': False, 'sent': False, 'count': 0, 'message': str(exc)}
    finally:
        _release_lock()
