
import json
import re
import unicodedata
from datetime import datetime
from html import escape
from urllib.parse import quote_plus

from . import db
from .models import BlogPost, Category, Product
from .utils import unique_slug


def _rule(slug, title, keyword=None, gender='', colors=None, max_price=None, min_price=None, terms=None, required_groups=None, intent='category'):
    return {
        'slug': slug,
        'title': title,
        'keyword': keyword or title.lower(),
        'gender': gender,
        'colors': colors or [],
        'max_price': max_price,
        'min_price': min_price,
        'terms': terms or [],
        'required_groups': required_groups or [],
        'intent': intent,
    }


LANDING_TOPICS = [
    _rule('damske-tenisky', 'Dámské tenisky', gender='damske', required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker', 'obuv'], intent='women'),
    _rule('panske-tenisky', 'Pánské tenisky', gender='panske', required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker', 'obuv'], intent='men'),
    _rule('levne-tenisky', 'Levné tenisky', max_price=499, required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker', 'obuv'], intent='cheap'),
    _rule('levne-boty', 'Levné boty', max_price=499, terms=['boty', 'obuv'], intent='cheap'),
    _rule('tenisky-do-500-kc', 'Tenisky do 500 Kč', max_price=500, required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker', 'obuv'], intent='price'),
    _rule('tenisky-do-700-kc', 'Tenisky do 700 Kč', max_price=700, required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker', 'obuv'], intent='price'),
    _rule('tenisky-do-1000-kc', 'Tenisky do 1000 Kč', max_price=1000, required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker', 'obuv'], intent='price'),
    _rule('bile-tenisky', 'Bílé tenisky', colors=['bil', 'bila', 'bile', 'bily', 'white', 'cream', 'smetan'], required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('cerne-tenisky', 'Černé tenisky', colors=['cern', 'cerna', 'cerne', 'cerny', 'black'], required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('damske-bile-tenisky', 'Dámské bílé tenisky', gender='damske', colors=['bil', 'bila', 'bile', 'bily', 'white', 'cream'], required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('damske-cerne-tenisky', 'Dámské černé tenisky', gender='damske', colors=['cern', 'cerna', 'cerne', 'cerny', 'black'], required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('panske-bile-tenisky', 'Pánské bílé tenisky', gender='panske', colors=['bil', 'bila', 'bile', 'bily', 'white', 'cream'], required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('panske-cerne-tenisky', 'Pánské černé tenisky', gender='panske', colors=['cern', 'cerna', 'cerne', 'cerny', 'black'], required_groups=[['tenisk', 'sneaker']], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('bezecke-boty', 'Běžecké boty', required_groups=[['bezeck', 'beh', 'running', 'runner']], terms=['běžecké', 'bezecke', 'running', 'sport'], intent='running'),
    _rule('sportovni-tenisky', 'Sportovní tenisky', required_groups=[['sport', 'fitness', 'training', 'bezeck', 'beh', 'running'], ['tenisk', 'sneaker']], terms=['sportovní', 'sportovni', 'sport', 'tenisky'], intent='sport'),
    _rule('damske-sportovni-tenisky', 'Dámské sportovní tenisky', gender='damske', required_groups=[['sport', 'fitness', 'training', 'bezeck', 'beh', 'running'], ['tenisk', 'sneaker']], terms=['sport', 'tenisky'], intent='sport'),
    _rule('panske-sportovni-tenisky', 'Pánské sportovní tenisky', gender='panske', required_groups=[['sport', 'fitness', 'training', 'bezeck', 'beh', 'running'], ['tenisk', 'sneaker']], terms=['sport', 'tenisky'], intent='sport'),
    _rule('zimni-boty', 'Zimní boty', required_groups=[['zimn', 'winter', 'zateplen', 'snih', 'snow', 'kozesin', 'teple']], terms=['zimní', 'zimni', 'zateplené', 'winter'], intent='winter'),
    _rule('kotnikove-boty', 'Kotníkové boty', required_groups=[['kotnik', 'kotníkov', 'ankle', 'high', 'mid']], terms=['kotníkové', 'kotnikove', 'kotník'], intent='ankle'),
    _rule('letni-tenisky', 'Letní tenisky', required_groups=[['letni', 'leto', 'summer', 'prodys', 'prodyš', 'lehke', 'lehké'], ['tenisk', 'sneaker']], terms=['letní', 'letni', 'lehké', 'prodyšné', 'tenisky'], intent='summer'),
    _rule('pohodlne-tenisky', 'Pohodlné tenisky', required_groups=[['pohodl', 'komfort', 'mekk', 'měkk'], ['tenisk', 'sneaker']], terms=['pohodlné', 'komfortní', 'tenisky'], intent='comfort'),
    _rule('boty-do-mesta', 'Boty do města', required_groups=[['mesto', 'město', 'urban', 'street', 'city']], terms=['městské', 'mesto', 'urban', 'street'], intent='daily'),
    _rule('boty-na-kazdy-den', 'Boty na každý den', required_groups=[['kazdoden', 'každoden', 'daily', 'everyday', 'mesto', 'město', 'pohodl']], terms=['každodenní', 'pohodlné', 'město'], intent='daily'),
    _rule('platformove-tenisky', 'Platformové tenisky', required_groups=[['platform']], terms=['platformové', 'platforma', 'tenisky'], intent='platform'),
    _rule('unisex-tenisky', 'Unisex tenisky', gender='unisex', required_groups=[['tenisk', 'sneaker']], terms=['unisex', 'tenisky', 'sneaker'], intent='unisex'),
    _rule('boty-s-dopravou-zdarma', 'Boty s dopravou zdarma', terms=['boty', 'tenisky', 'obuv'], intent='shipping'),
]

BLOG_TOPICS = [
    ('Jak vybrat dámské tenisky na každý den', {'gender': 'damske', 'required_groups': [['tenisk', 'sneaker']], 'terms': ['tenisky', 'pohodl', 'kazdoden']}, 'damske-tenisky'),
    ('Jak vybrat pánské tenisky do města', {'gender': 'panske', 'required_groups': [['tenisk', 'sneaker'], ['mesto', 'město', 'urban', 'street']], 'terms': ['tenisky', 'město', 'mesto', 'urban']}, 'panske-tenisky'),
    ('Bílé tenisky: jak je nosit, čistit a které vybrat', {'colors': ['bil', 'bila', 'bile', 'bily', 'white', 'cream'], 'required_groups': [['tenisk', 'sneaker']], 'terms': ['tenisky']}, 'bile-tenisky'),
    ('Černé tenisky: univerzální boty ke každému outfitu', {'colors': ['cern', 'cerna', 'cerne', 'cerny', 'black'], 'required_groups': [['tenisk', 'sneaker']], 'terms': ['tenisky']}, 'cerne-tenisky'),
    ('Levné tenisky do 500 Kč: podle čeho vybírat', {'max_price': 500, 'required_groups': [['tenisk', 'sneaker']], 'terms': ['tenisky', 'obuv']}, 'tenisky-do-500-kc'),
    ('Nejpohodlnější boty na celodenní nošení', {'required_groups': [['pohodl', 'komfort', 'mekk', 'měkk', 'kazdoden']], 'terms': ['pohodl', 'měkk', 'každodenn']}, 'pohodlne-tenisky'),
    ('Jak poznat správnou velikost bot při nákupu online', {'terms': ['boty', 'tenisky']}, 'tenisky-na-denni-noseni'),
    ('Letní tenisky: lehké boty do teplého počasí', {'required_groups': [['letni', 'leto', 'summer', 'prodys', 'prodyš', 'lehke', 'lehké']], 'terms': ['letní', 'lehké', 'prodyš']}, 'letni-tenisky'),
    ('Sportovní vs volnočasové tenisky: jaký typ vybrat', {'required_groups': [['sport', 'fitness', 'training', 'bezeck', 'beh', 'running']], 'terms': ['sport', 'tenisky', 'běh']}, 'sportovni-tenisky'),
    ('Jak se starat o tenisky, aby déle vydržely', {'required_groups': [['tenisk', 'sneaker']], 'terms': ['tenisky', 'boty']}, 'tenisky-na-denni-noseni'),
    ('Zimní boty: jak vybrat teplý pár do chladného počasí', {'required_groups': [['zimn', 'winter', 'zateplen', 'snih', 'snow', 'teple']], 'terms': ['zimní', 'zateplené', 'winter']}, 'zimni-boty'),
    ('Běžecké boty: podle čeho poznat vhodný model', {'required_groups': [['bezeck', 'beh', 'running', 'runner']], 'terms': ['běžecké', 'running', 'sport']}, 'bezecke-boty'),
]


def _as_rules(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _strip_accents(value):
    value = str(value or '')
    return ''.join(ch for ch in unicodedata.normalize('NFKD', value) if not unicodedata.combining(ch))


def _lower(value):
    return _strip_accents(value).casefold()


def _tokens(value):
    return re.findall(r'[a-z0-9]+', _lower(value))


def _term_in_text(text, needle):
    """Bezpečné matchování keywordů.

    Nepoužíváme prosté `needle in text`, protože krátké kořeny jako `bil`
    se pak chytají ve slovech typu `stabilita` nebo `oblibeny`.
    Jednoslovné výrazy proto musí začínat na hranici tokenu.
    """
    needle = _lower(needle).strip()
    if not needle:
        return False

    normalized_text = _lower(text)

    if ' ' in needle:
        return needle in normalized_text

    for token in _tokens(normalized_text):
        if token == needle:
            return True
        if len(needle) >= 3 and token.startswith(needle):
            return True
    return False


def _contains_any(text, needles):
    return any(_term_in_text(text, needle) for needle in (needles or []) if str(needle or '').strip())


def _product_color_text(product):
    """Text používaný pouze pro barvu.

    Barvu nebereme z dlouhého popisu nebo obecných SEO textů, protože tam se
    často objeví formulace typu `u světlých modelů...`, což pak špatně
    zařadí černý nebo šedý produkt do bílé landing page.
    """
    return _lower(' '.join([
        product.name or '',
        product.slug or '',
        product.image_alt or '',
        product.colors or '',
    ]))


def _product_own_text(product):
    """Text patřící přímo produktu.

    Důležité: nepřidáváme sem název landing/kategorie, protože by to rozbilo
    filtry typu /k/bile-tenisky. Produkt černé barvy, který je omylem
    přiřazený do kategorie Bílé tenisky, nesmí projít jen proto, že kategorie
    obsahuje slovo "bílé".
    """
    return _lower(' '.join([
        product.name or '',
        product.slug or '',
        product.brand or '',
        product.gender or '',
        product.short_description or '',
        product.description or '',
        product.seo_title or '',
        product.meta_description or '',
        product.seo_keywords or '',
        product.image_alt or '',
        product.colors or '',
        product.specifications or '',
    ]))


def _product_text(product):
    category_bits = []
    if getattr(product, 'category', None):
        category_bits.extend([product.category.name or '', product.category.slug or ''])
    for category in getattr(product, 'categories', []) or []:
        category_bits.extend([category.name or '', category.slug or ''])
    return _lower(' '.join([
        _product_own_text(product),
        ' '.join(category_bits),
    ]))


def _unique_list(values):
    seen = set()
    clean = []
    for value in values or []:
        value = str(value or '').strip()
        key = _lower(value)
        if key and key not in seen:
            clean.append(value)
            seen.add(key)
    return clean


def infer_product_rules(slug='', title='', keyword='', description=''):
    raw = f'{slug or ""} {title or ""} {keyword or ""} {description or ""}'
    text = _lower(raw.replace('-', ' '))

    rules = {
        'slug': slug or '',
        'title': title or (slug or '').replace('-', ' ').title(),
        'keyword': keyword or (title or (slug or '').replace('-', ' ')).lower(),
        'gender': '',
        'colors': [],
        'terms': [],
        'required_terms_any': [],
        'required_groups': [],
        'intent': 'category',
    }

    def add_terms(*values):
        rules['terms'].extend([v for v in values if v])

    def require_group(*values):
        group = [v for v in values if v]
        if group:
            rules['required_groups'].append(group)
            rules['required_terms_any'].extend(group)

    if any(token in text for token in ['damsk', 'zenske', 'zeny', 'pro zeny', 'women', 'female']):
        rules['gender'] = 'damske'
    elif any(token in text for token in ['pansk', 'muzi', 'pro muze', 'men', 'male']):
        rules['gender'] = 'panske'
    elif 'unisex' in text:
        rules['gender'] = 'unisex'

    color_map = [
        (['bil', 'bile', 'bila', 'bily', 'white', 'cream', 'smetan'], ['bil', 'bila', 'bile', 'bily', 'white', 'cream', 'smetan']),
        (['cern', 'cerne', 'cerna', 'cerny', 'black'], ['cern', 'cerna', 'cerne', 'cerny', 'black']),
        (['bez', 'beige'], ['bez', 'bezova', 'bezove', 'beige', 'cream']),
        (['modr', 'blue'], ['modr', 'modra', 'modre', 'blue']),
        (['ruzov', 'pink'], ['ruzov', 'ruzova', 'ruzove', 'pink']),
        (['cerven', 'red'], ['cerven', 'cervena', 'cervene', 'red']),
        (['sed', 'grey', 'gray'], ['sed', 'seda', 'sede', 'grey', 'gray']),
        (['hned', 'brown'], ['hned', 'hneda', 'hnede', 'brown']),
        (['zelen', 'green'], ['zelen', 'zelena', 'zelene', 'green']),
    ]
    for triggers, values in color_map:
        if any(trigger in text for trigger in triggers):
            rules['colors'].extend(values)
            rules['intent'] = 'color'
            break

    price_match = re.search(r'(?:do|pod|max)\D*(\d{3,5})', text)
    if price_match:
        rules['max_price'] = int(price_match.group(1))
        rules['intent'] = 'price'
    elif any(token in text for token in ['levn', 'nejlevn', 'vyhodn', 'budget']):
        rules['max_price'] = 499
        rules['intent'] = 'cheap'

    if any(token in text for token in ['tenisk', 'sneaker']):
        add_terms('tenisky', 'teniska', 'sneaker')
        require_group('tenisk', 'sneaker')
    elif any(token in text for token in ['sandal']):
        add_terms('sandály', 'sandaly', 'sandal')
        require_group('sandal', 'sandaly')
        rules['intent'] = 'sandals'
    elif any(token in text for token in ['bot', 'obuv']):
        add_terms('boty', 'obuv', 'shoes')

    if any(token in text for token in ['bezeck', 'běžeck', 'beh', 'běh', 'running', 'runner']):
        add_terms('běžecké', 'bezecke', 'běh', 'running', 'runner')
        require_group('bezeck', 'běžeck', 'beh', 'běh', 'running', 'runner')
        rules['intent'] = 'running'

    if any(token in text for token in ['sport', 'fitness', 'training']):
        add_terms('sportovní', 'sportovni', 'sport', 'fitness', 'training')
        require_group('sport', 'fitness', 'training', 'bezeck', 'běžeck', 'running')
        rules['intent'] = 'sport'

    if any(token in text for token in ['zimn', 'winter', 'zateplen', 'snih', 'sníh', 'snow', 'kozesin', 'teple']):
        add_terms('zimní', 'zimni', 'winter', 'zateplené', 'zateplene', 'sníh', 'snih')
        require_group('zimn', 'winter', 'zateplen', 'snih', 'sníh', 'snow', 'kozesin', 'teple')
        rules['intent'] = 'winter'

    if any(token in text for token in ['kotnik', 'kotník', 'ankle', 'high', 'mid']):
        add_terms('kotníkové', 'kotnikove', 'kotník', 'kotnik', 'ankle')
        require_group('kotnik', 'kotník', 'kotnikove', 'kotníkové', 'ankle')
        rules['intent'] = 'ankle'

    if any(token in text for token in ['letni', 'letní', 'leto', 'léto', 'summer', 'prodys', 'prodyš', 'lehke', 'lehké']):
        add_terms('letní', 'letni', 'summer', 'lehké', 'lehke', 'prodyšné', 'prodysne')
        require_group('letni', 'letní', 'leto', 'summer', 'prodys', 'prodyš', 'lehke', 'lehké')
        rules['intent'] = 'summer'

    if any(token in text for token in ['pohodl', 'komfort', 'mekk', 'měkk']):
        add_terms('pohodlné', 'pohodlne', 'komfort', 'měkké', 'mekke')
        require_group('pohodl', 'komfort', 'měkk', 'mekk')
        rules['intent'] = 'comfort'

    if any(token in text for token in ['mesto', 'město', 'mestsk', 'městsk', 'urban', 'street', 'city']):
        add_terms('městské', 'mestske', 'město', 'mesto', 'urban', 'street')
        require_group('město', 'mesto', 'urban', 'street', 'city')
        rules['intent'] = 'daily'

    if any(token in text for token in ['kazdy den', 'kazdoden', 'každoden', 'daily', 'everyday']):
        add_terms('každodenní', 'kazdodenni', 'daily', 'everyday')
        require_group('kazdoden', 'každoden', 'daily', 'everyday')
        rules['intent'] = 'daily'

    if any(token in text for token in ['platform']):
        add_terms('platformové', 'platformove', 'platforma', 'platform')
        require_group('platform')
        rules['intent'] = 'platform'

    for key in ['colors', 'terms', 'required_terms_any']:
        rules[key] = _unique_list(rules.get(key) or [])

    seen_groups = set()
    groups = []
    for group in rules.get('required_groups') or []:
        clean = tuple(_unique_list(group))
        key = tuple(_lower(item) for item in clean)
        if clean and key not in seen_groups:
            groups.append(list(clean))
            seen_groups.add(key)
    rules['required_groups'] = groups

    return rules


def infer_product_rules_for_category(category):
    return infer_product_rules(
        slug=getattr(category, 'slug', '') or '',
        title=getattr(category, 'name', '') or '',
        keyword=getattr(category, 'seo_target_keyword', '') or '',
        description=' '.join([
            getattr(category, 'meta_description', '') or '',
            getattr(category, 'description', '') or '',
        ]),
    )


def _price(product):
    try:
        return float(product.price or 0)
    except Exception:
        return 0.0


def _product_assigned_to_category(product, category):
    if not category or not getattr(category, 'id', None):
        return False
    if getattr(product, 'category_id', None) == category.id:
        return True
    for c in getattr(product, 'categories', []) or []:
        if c.id == category.id:
            return True
    return False


def _product_passes_hard_filters(product, rules):
    rules = _as_rules(rules)
    # Tvrdé filtry se kontrolují pouze proti datům produktu, ne proti názvu
    # landing page/kategorie. Jinak by např. černý produkt přiřazený do
    # kategorie Bílé tenisky prošel jen kvůli slovu "bílé" v kategorii.
    own_text = _product_own_text(product)

    gender = _lower(rules.get('gender'))
    if gender:
        product_gender = _lower(getattr(product, 'gender', ''))
        if gender == 'unisex':
            if product_gender and 'unisex' not in product_gender and 'unisex' not in own_text:
                return False
        elif gender not in product_gender and gender not in own_text:
            return False

    if rules.get('max_price') is not None and _price(product) > float(rules.get('max_price')):
        return False
    if rules.get('min_price') is not None and _price(product) < float(rules.get('min_price')):
        return False

    colors = rules.get('colors') or []
    if colors and not _contains_any(_product_color_text(product), colors):
        return False

    groups = rules.get('required_groups') or []
    if groups:
        for group in groups:
            if not _contains_any(own_text, group):
                return False
    else:
        required = rules.get('required_terms_any') or []
        if required and not _contains_any(own_text, required):
            return False

    return True


def _has_hard_filters(rules):
    rules = _as_rules(rules)
    return bool(
        rules.get('gender')
        or rules.get('colors')
        or rules.get('max_price') is not None
        or rules.get('min_price') is not None
        or rules.get('required_groups')
        or rules.get('required_terms_any')
    )


def _term_match_count(product, rules):
    text = _product_own_text(product)
    return sum(1 for term in (rules.get('terms') or []) if _term_in_text(text, term))


def _score_product(product, rules):
    rules = _as_rules(rules)
    text = _product_own_text(product)
    score = 0

    gender = _lower(rules.get('gender'))
    if gender:
        pg = _lower(getattr(product, 'gender', ''))
        if gender in pg or gender in text:
            score += 35

    if rules.get('max_price') is not None:
        max_price = float(rules.get('max_price'))
        if _price(product) <= max_price:
            score += 25
            score += max(0, int((max_price - _price(product)) / max(max_price, 1) * 12))
        else:
            score -= 100

    if rules.get('min_price') is not None:
        score += 12 if _price(product) >= float(rules.get('min_price')) else -50

    if rules.get('colors') and _contains_any(_product_color_text(product), rules.get('colors')):
        score += 40

    for group in rules.get('required_groups') or []:
        if _contains_any(text, group):
            score += 35

    score += _term_match_count(product, rules) * 8

    if getattr(product, 'featured', False):
        score += 6
    if product.stock and product.stock > 0:
        score += 8
    if product.original_price and product.original_price > product.price:
        score += min(10, int(getattr(product, 'discount_percent', 0) or 0) // 5)

    score -= min(15, int(_price(product) / 200))
    return score


def _active_products():
    return Product.query.filter_by(active=True).order_by(Product.created_at.desc()).all()


def _unique_products(products):
    seen = set()
    result = []
    for product in products or []:
        if not product or product.id in seen:
            continue
        seen.add(product.id)
        result.append(product)
    return result


def _limit_products(products, limit):
    products = list(products or [])
    if limit is None:
        return products
    return products[:int(limit)]


def _assigned_products_for_category(category):
    if not category or not getattr(category, 'id', None):
        return []
    return Product.query.filter(
        Product.active.is_(True),
        db.or_(
            Product.category_id == category.id,
            Product.categories.any(Category.id == category.id)
        )
    ).order_by(Product.created_at.desc()).all()


def select_products_for_rules(rules, limit=24, base_products=None):
    rules = _as_rules(rules)
    products = list(base_products) if base_products is not None else _active_products()

    if _has_hard_filters(rules):
        candidates = [p for p in products if _product_passes_hard_filters(p, rules)]
    else:
        candidates = [p for p in products if _term_match_count(p, rules) > 0]

    scored = [(p, _score_product(p, rules)) for p in candidates]
    scored.sort(key=lambda item: (item[1], item[0].stock or 0, -_price(item[0]), item[0].created_at or datetime.utcnow()), reverse=True)

    if _has_hard_filters(rules):
        selected = [p for p, score in scored if score >= 0]
    else:
        selected = [p for p, score in scored if score > 0]

    return _limit_products(selected, limit)


def _manual_rules_enabled(stored_rules):
    stored_rules = _as_rules(stored_rules)
    return bool(stored_rules.get('manual_override') or stored_rules.get('force_manual'))


def products_for_landing_category(category, limit=48):
    inferred_rules = infer_product_rules_for_category(category)
    stored_rules = _as_rules(getattr(category, 'seo_product_rules', '') or '')
    rules = stored_rules if _manual_rules_enabled(stored_rules) else inferred_rules

    assigned = _assigned_products_for_category(category)
    rule_matches = select_products_for_rules(rules, limit=None)

    if _has_hard_filters(rules):
        products = _unique_products([p for p in assigned if _product_passes_hard_filters(p, rules)] + rule_matches)
    else:
        products = _unique_products(assigned + rule_matches)

    products.sort(key=lambda p: (_score_product(p, rules), p.stock or 0, -_price(p), p.created_at or datetime.utcnow()), reverse=True)
    return _limit_products(products, limit)


def _format_price(value):
    try:
        return f"{int(round(float(value))):,}".replace(',', ' ') + ' Kč'
    except Exception:
        return 'Cena na dotaz'


def _product_url(product):
    return f"/produkt/{escape(product.slug or '')}"


def _image_src(product):
    image = (getattr(product, 'image', '') or 'default-product.svg').strip()
    if image.startswith(('http://', 'https://', '/uploads/', '/static/')):
        return escape(image)
    return f"/uploads/{escape(image)}"


def _product_plain(product):
    return f"{escape(product.name)} za {escape(_format_price(product.price))}"


def _product_names(products, limit=3):
    names = [_product_plain(p) for p in (products or [])[:limit]]
    return ', '.join(names) if names else 'vybrané modely z aktuální nabídky'


def _product_reason(product):
    text = _product_text(product)
    color_text = _product_color_text(product)
    if 'sport' in text or 'beh' in text or 'running' in text:
        return 'vhodné pro sportovnější styl a aktivnější nošení'
    if _contains_any(color_text, ['bila', 'bile', 'bily', 'white', 'cream', 'smetan']):
        return 'čistý vzhled a snadné kombinování s outfitem'
    if _contains_any(color_text, ['cerna', 'cerne', 'cerny', 'black']):
        return 'univerzální tmavá barva a jednodušší údržba'
    if 'zimn' in text or 'winter' in text or 'zateplen' in text:
        return 'praktičtější volba do chladnějšího počasí'
    if product.original_price and product.original_price > product.price:
        return f'sleva přibližně {product.discount_percent} %, dobrý poměr cena/výkon'
    return 'dobrá volba na každodenní nošení'


def _render_product_cards(products, title='Doporučené modely', subtitle=''):
    cards = []
    for product in (products or [])[:6]:
        old_price = ''
        if product.original_price and product.original_price > product.price:
            old_price = f'<div class="text-secondary small text-decoration-line-through">{_format_price(product.original_price)}</div>'
        short = escape((product.short_description or _product_reason(product) or '')[:150])
        cards.append(f'''
<a href="{_product_url(product)}" class="seo-product-card text-decoration-none text-dark" aria-label="Zobrazit produkt {escape(product.name)}">
  <div class="seo-product-card__image"><img src="{_image_src(product)}" alt="{escape(product.image_alt or product.name)}" loading="lazy"></div>
  <div class="seo-product-card__body">
    <div class="text-secondary small">{escape(product.brand or '')}</div>
    <strong class="seo-product-card__title">{escape(product.name)}</strong>
    <div class="seo-product-card__desc">{short}</div>
    <div class="d-flex align-items-end justify-content-between gap-2 mt-2">
      <div><strong>{_format_price(product.price)}</strong>{old_price}</div>
      <span class="btn btn-sm btn-dark rounded-pill">Detail</span>
    </div>
  </div>
</a>''')
    if not cards:
        return ''
    subtitle_html = f'<p class="text-secondary mb-3">{escape(subtitle)}</p>' if subtitle else ''
    return f'''
<section class="seo-product-section my-4">
  <h2>{escape(title)}</h2>
  {subtitle_html}
  <div class="seo-product-grid">{''.join(cards)}</div>
</section>
'''


def _category_button(category_slug, label='Zobrazit produkty'):
    if not category_slug:
        return '<a class="btn btn-outline-dark rounded-pill" href="/produkty">Zobrazit produkty</a>'

    category = Category.query.filter_by(slug=category_slug).first()
    if category and bool(getattr(category, 'seo_published', True)):
        return f'<a class="btn btn-outline-dark rounded-pill" href="/k/{escape(category.slug)}">{escape(label)}</a>'

    search_term = str(category_slug or '').replace('-', ' ')
    return f'<a class="btn btn-outline-dark rounded-pill" href="/produkty?search={quote_plus(search_term)}">{escape(label)}</a>'


def build_product_stats(products):
    products = list(products or [])
    prices = [float(p.price or 0) for p in products if p.price is not None]
    brands = sorted({(p.brand or '').strip() for p in products if (p.brand or '').strip()})
    cheapest_product = None
    if products:
        priced_products = [p for p in products if p.price is not None]
        if priced_products:
            cheapest_product = min(priced_products, key=lambda p: (float(p.price or 0), p.name or ''))
    if not prices:
        return {
            'count': len(products),
            'min_price': None,
            'max_price': None,
            'avg_price': None,
            'brands': brands,
            'in_stock': len([p for p in products if p.stock and p.stock > 0]),
            'cheapest_product': cheapest_product,
            'cheapest_name': cheapest_product.name if cheapest_product else '',
            'cheapest_price': float(cheapest_product.price or 0) if cheapest_product else None,
        }
    return {
        'count': len(products),
        'min_price': min(prices),
        'max_price': max(prices),
        'avg_price': sum(prices) / len(prices),
        'brands': brands,
        'in_stock': len([p for p in products if p.stock and p.stock > 0]),
        'cheapest_product': cheapest_product,
        'cheapest_name': cheapest_product.name if cheapest_product else '',
        'cheapest_price': float(cheapest_product.price or 0) if cheapest_product else None,
    }


def build_product_groups(products):
    available = list(products or [])
    cheapest = sorted(available, key=lambda p: float(p.price or 0))[:4]
    discounted = sorted([p for p in available if p.original_price and p.original_price > p.price], key=lambda p: p.discount_percent, reverse=True)[:4]
    featured = [p for p in available if getattr(p, 'featured', False)][:4]
    if len(featured) < 4:
        featured = (featured + available)[:4]
    return {'cheapest': cheapest, 'discounted': discounted, 'featured': featured}


def _faq_html(title, products):
    stats = build_product_stats(products)
    price_line = 'Ceny se liší podle modelu a dostupnosti.'
    if stats['min_price'] is not None and stats['max_price'] is not None:
        price_line = f"U vybraných modelů se cena pohybuje přibližně od {_format_price(stats['min_price'])} do {_format_price(stats['max_price'])}."
    return f'''
<h2>Časté otázky k výběru</h2>
<div class="accordion" id="seoFaq">
  <div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#faq1">Jak vybrat správnou velikost?</button></h3><div id="faq1" class="accordion-collapse collapse show" data-bs-parent="#seoFaq"><div class="accordion-body">Změřte délku chodidla večer, kdy je noha nejvíce zatížená, a nechte malou rezervu přibližně 0,5 až 1 cm. U každého produktu kontrolujte dostupné velikosti a sklad.</div></div></div>
  <div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq2">Kolik stojí {escape(title.lower())}?</button></h3><div id="faq2" class="accordion-collapse collapse" data-bs-parent="#seoFaq"><div class="accordion-body">{price_line}</div></div></div>
  <div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq3">Na co si dát pozor při nákupu online?</button></h3><div id="faq3" class="accordion-collapse collapse" data-bs-parent="#seoFaq"><div class="accordion-body">Sledujte cenu, velikosti skladem, materiál, typ podrážky a hlavně účel nošení. Jiné boty se hodí na dlouhé chození po městě a jiné ke sportovnějším outfitům.</div></div></div>
</div>
'''


def _quality_score(products, content):
    score = 35
    if len(products) >= 2:
        score += 15
    if len(products) >= 5:
        score += 15
    if len(content) >= 1800:
        score += 15
    if 'Časté otázky' in content:
        score += 10
    if 'Jak vybrat' in content:
        score += 10
    return min(100, score)


def _landing_content(title, rules, products):
    stats = build_product_stats(products)
    price_sentence = ''
    if stats['min_price'] is not None and stats['max_price'] is not None:
        price_sentence = f"Ceny se aktuálně pohybují přibližně od {_format_price(stats['min_price'])} do {_format_price(stats['max_price'])}."
    return f'''
<p><strong>{escape(title)}</strong> jsou praktický výběr produktů pro zákazníky, kteří chtějí rychle porovnat vhodné modely podle ceny, vzhledu, dostupnosti a použití. {price_sentence}</p>

<h2>Jak vybrat {escape(title.lower())}</h2>
<p>Nejdřív si ujasněte, kde budete boty nosit nejčastěji. Na každý den je důležité pohodlí, na město univerzální vzhled a u sportovnějších modelů stabilita a vhodná podrážka.</p>

<h2>Na co se zaměřit</h2>
<ul>
  <li>dostupná velikost a skladovost,</li>
  <li>cena ve vztahu k materiálu a účelu nošení,</li>
  <li>pohodlí při běžném používání,</li>
  <li>barva, údržba a kombinování s oblečením.</li>
</ul>

<h2>Rychlé doporučení</h2>
<p>Nejlepší volba je model, který odpovídá účelu nošení, sedí velikostí a cenově dává smysl. Konkrétní produkty se zobrazují na stránce automaticky podle aktuální nabídky.</p>
{_faq_html(title, products)}
'''


def _blog_content(title, rules, products, category_slug):
    stats = build_product_stats(products)
    groups = build_product_groups(products)
    intro_products = _product_names(groups['featured'][:3])
    category_cta = _category_button(category_slug, 'Zobrazit související produkty')
    price_sentence = ''
    if stats['min_price'] is not None:
        price_sentence = f" Ceny doporučených produktů začínají přibližně na {_format_price(stats['min_price'])}."

    return f'''
<p>Tenhle průvodce pomáhá rychle vybrat boty podle ceny, stylu, velikosti a způsobu nošení.{price_sentence}</p>

<h2>Rychlé doporučení</h2>
<p>Pokud chcete vybrat bez dlouhého porovnávání, začněte u modelů jako {intro_products}. Před objednávkou vždy zkontrolujte dostupnou velikost, popis produktu a cenu.</p>
<div class="my-3">{category_cta}</div>

<h2>Podle čeho vybírat</h2>
<p>U bot na každodenní nošení sledujte hlavně pohodlí, stabilitu podrážky, dostupné velikosti a to, jestli se model hodí k vašemu běžnému oblečení. U levnějších bot je dobré porovnat nejen cenu, ale i popis, materiál a způsob nošení.</p>
<p>Pokud kupujete online, berte velikost vážněji než barvu. Nejčastější chyba je objednání podle zvyku bez kontroly konkrétního střihu. Ideální je změřit chodidlo a nechat malou rezervu.</p>

{_render_product_cards(groups['featured'], 'Konkrétní modely, které stojí za zvážení', 'Vybrané produkty s aktuální cenou a dostupností.')}

<h2>Jak se rozhodnout mezi podobnými modely</h2>
<p>Když váháte mezi dvěma páry, rozhodujte podle účelu. Na delší chození vyberte pohodlnější a praktičtější model. K outfitům se vyplatí čistší design. Pokud řešíte rozpočet, seřazení podle ceny pomůže, ale nekupujte pouze nejlevnější variantu bez kontroly velikosti a popisu.</p>

<h2>Nejčastější chyby</h2>
<ul>
  <li>výběr jen podle fotky bez kontroly velikosti,</li>
  <li>ignorování účelu nošení,</li>
  <li>nákup světlé obuvi bez plánu na údržbu,</li>
  <li>výběr sportovního modelu tam, kde zákazník reálně chce městské boty.</li>
</ul>

<h2>Finální doporučení</h2>
<p>Nejlepší volba je model, který sedí účelu, ceně i velikosti. Při výběru porovnejte dostupné velikosti, materiál, cenu a celkový vzhled.</p>
<div class="my-3">{category_cta}</div>
{_faq_html(title, products)}
'''


def _meta_description_for(title, products):
    stats = build_product_stats(products)
    if stats['min_price'] is not None:
        return f"{title}: výběr podle ceny, velikosti a použití. Doporučené modely od {_format_price(stats['min_price'])}, praktické tipy a produkty skladem."
    return f"{title}: praktický výběr bot podle ceny, velikosti, použití a aktuální nabídky BotyZaHubicku.cz."


def _already_done_category(slug):
    return Category.query.filter_by(slug=slug).first() is not None


def _already_done_blog(title):
    slug = unique_slug(BlogPost, title)
    base = slug.rsplit('-', 1)[0] if slug.endswith('-2') else slug
    return BlogPost.query.filter(BlogPost.slug.in_([slug, base])).first() is not None


def products_for_blog_post(post, limit=8):
    ids = []
    try:
        ids = json.loads(post.related_product_ids or '[]')
    except Exception:
        ids = []

    products = []
    if ids:
        products = Product.query.filter(Product.id.in_(ids), Product.active.is_(True)).all()
        by_id = {p.id: p for p in products}
        products = [by_id[i] for i in ids if i in by_id]
    if products:
        return products[:limit]

    rules = infer_product_rules(
        title=getattr(post, 'title', '') or '',
        keyword=getattr(post, 'target_keyword', '') or '',
        description=getattr(post, 'meta_description', '') or '',
    )
    return select_products_for_rules(rules, limit=limit)


def _category_intent_score(base_rules, other_category):
    other = infer_product_rules_for_category(other_category)
    score = 0

    if base_rules.get('gender') and base_rules.get('gender') == other.get('gender'):
        score += 3
    if set(_lower(x) for x in base_rules.get('colors', [])) & set(_lower(x) for x in other.get('colors', [])):
        score += 3

    base_groups = {_lower(item) for group in base_rules.get('required_groups', []) for item in group}
    other_groups = {_lower(item) for group in other.get('required_groups', []) for item in group}
    if base_groups & other_groups:
        score += 2

    base_terms = {_lower(x) for x in base_rules.get('terms', [])}
    other_terms = {_lower(x) for x in other.get('terms', [])}
    if base_terms & other_terms:
        score += 1

    return score


def visible_related_categories(current_id=None, limit=8):
    q = Category.query
    if current_id:
        q = q.filter(Category.id != current_id)
    q = q.filter(db.or_(Category.seo_published.is_(True), Category.seo_generated.is_(False)))
    categories = q.all()

    if current_id:
        current = Category.query.get(current_id)
        if current:
            base_rules = infer_product_rules_for_category(current)
            scored = [(_category_intent_score(base_rules, c), c) for c in categories]
            scored.sort(key=lambda item: (-item[0], item[1].name))
            categories = [c for score, c in scored if score > 0] + [c for score, c in scored if score <= 0]

    return categories[:limit]


def _topic_for_category(category):
    slug = getattr(category, 'slug', '') or ''
    for topic in LANDING_TOPICS:
        if topic.get('slug') == slug:
            inferred = infer_product_rules_for_category(category)
            merged = {**topic, **{k: v for k, v in inferred.items() if v}}
            return merged

    return infer_product_rules_for_category(category)


def _topic_for_blog(post):
    title = getattr(post, 'title', '') or ''
    for topic_title, rules, category_slug in BLOG_TOPICS:
        if topic_title == title:
            return rules, category_slug
    keyword = getattr(post, 'target_keyword', '') or title
    return infer_product_rules(title=title, keyword=keyword), ''



def regenerate_category_content(category):
    """Manual SEO mode.

    Automatic content generation has been disabled. The function remains for
    backward compatibility only and does not overwrite manual content.
    """
    return category


def regenerate_blog_content(post):
    """Manual SEO mode.

    Automatic content generation has been disabled. The function remains for
    backward compatibility only and does not overwrite manual content.
    """
    return post


def regenerate_all_generated_content():
    """Manual SEO mode: no automatic rewrite of existing content."""
    return {'blogs': 0, 'landing_pages': 0}


def generate_daily_seo_content(blog_count=10, landing_count=10, auto_publish=False):
    """Manual SEO mode: daily automatic generation is disabled."""
    return {'blogs': 0, 'landing_pages': 0, 'skipped_low_quality_publish': 0, 'disabled': True}

