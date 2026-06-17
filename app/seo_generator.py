import json
from datetime import datetime
from html import escape

from . import db
from .models import BlogPost, Category, Product
from .utils import unique_slug


def _rule(slug, title, keyword=None, gender='', colors=None, max_price=None, min_price=None, terms=None, intent='category'):
    return {
        'slug': slug,
        'title': title,
        'keyword': keyword or title.lower(),
        'gender': gender,
        'colors': colors or [],
        'max_price': max_price,
        'min_price': min_price,
        'terms': terms or [],
        'intent': intent,
    }


LANDING_TOPICS = [
    _rule('damske-tenisky', 'Dámské tenisky', gender='damske', terms=['tenisky', 'sneaker', 'obuv'], intent='women'),
    _rule('panske-tenisky', 'Pánské tenisky', gender='panske', terms=['tenisky', 'sneaker', 'obuv'], intent='men'),
    _rule('levne-tenisky', 'Levné tenisky', max_price=900, terms=['tenisky', 'sneaker', 'obuv'], intent='cheap'),
    _rule('tenisky-do-500-kc', 'Tenisky do 500 Kč', max_price=500, terms=['tenisky', 'sneaker', 'obuv'], intent='price'),
    _rule('tenisky-do-700-kc', 'Tenisky do 700 Kč', max_price=700, terms=['tenisky', 'sneaker', 'obuv'], intent='price'),
    _rule('tenisky-do-1000-kc', 'Tenisky do 1000 Kč', max_price=1000, terms=['tenisky', 'sneaker', 'obuv'], intent='price'),
    _rule('damske-bile-tenisky', 'Dámské bílé tenisky', gender='damske', colors=['bíl', 'bil', 'white'], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('damske-cerne-tenisky', 'Dámské černé tenisky', gender='damske', colors=['čern', 'cern', 'black'], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('panske-bile-tenisky', 'Pánské bílé tenisky', gender='panske', colors=['bíl', 'bil', 'white'], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('panske-cerne-tenisky', 'Pánské černé tenisky', gender='panske', colors=['čern', 'cern', 'black'], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('bile-tenisky', 'Bílé tenisky', colors=['bíl', 'bil', 'white'], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('cerne-tenisky', 'Černé tenisky', colors=['čern', 'cern', 'black'], terms=['tenisky', 'sneaker'], intent='color'),
    _rule('pohodlne-tenisky', 'Pohodlné tenisky', terms=['pohodl', 'komfort', 'měkk', 'mesta', 'každodenn'], intent='comfort'),
    _rule('lehke-tenisky', 'Lehké tenisky', terms=['lehké', 'lehke', 'lehk', 'tenisky'], intent='comfort'),
    _rule('letni-tenisky', 'Letní tenisky', terms=['letní', 'letni', 'prodyš', 'lehké', 'tenisky'], intent='season'),
    _rule('sportovni-tenisky', 'Sportovní tenisky', terms=['sport', 'běh', 'fitness', 'tenisky'], intent='sport'),
    _rule('damske-sportovni-tenisky', 'Dámské sportovní tenisky', gender='damske', terms=['sport', 'běh', 'fitness', 'tenisky'], intent='sport'),
    _rule('panske-sportovni-tenisky', 'Pánské sportovní tenisky', gender='panske', terms=['sport', 'běh', 'fitness', 'tenisky'], intent='sport'),
    _rule('tenisky-na-denni-noseni', 'Tenisky na denní nošení', terms=['denní', 'denni', 'každodenn', 'město', 'mesto'], intent='daily'),
    _rule('boty-do-mesta', 'Boty do města', terms=['město', 'mesto', 'každodenn', 'street', 'urban'], intent='daily'),
    _rule('damske-boty-do-mesta', 'Dámské boty do města', gender='damske', terms=['město', 'mesto', 'každodenn', 'street', 'urban'], intent='daily'),
    _rule('panske-boty-do-mesta', 'Pánské boty do města', gender='panske', terms=['město', 'mesto', 'každodenn', 'street', 'urban'], intent='daily'),
    _rule('boty-na-kazdy-den', 'Boty na každý den', terms=['každodenn', 'kazdoden', 'město', 'mesto', 'pohodl'], intent='daily'),
    _rule('modni-tenisky', 'Módní tenisky', terms=['mód', 'modn', 'styl', 'fashion', 'streetwear'], intent='style'),
    _rule('streetwear-tenisky', 'Streetwear tenisky', terms=['street', 'urban', 'mód', 'style', 'tenisky'], intent='style'),
    _rule('elegantni-tenisky', 'Elegantní tenisky', terms=['elegant', 'minimal', 'čist', 'čistý', 'styl'], intent='style'),
    _rule('tenisky-k-dzinum', 'Tenisky k džínům', terms=['džíny', 'dziny', 'jeans', 'tenisky'], intent='style'),
    _rule('unisex-tenisky', 'Unisex tenisky', gender='unisex', terms=['unisex', 'tenisky', 'sneaker'], intent='unisex'),
    _rule('boty-s-dopravou-zdarma', 'Boty s dopravou zdarma', terms=['boty', 'tenisky', 'obuv'], intent='shipping'),
]

BLOG_TOPICS = [
    ('Jak vybrat dámské tenisky na každý den', {'gender': 'damske', 'terms': ['tenisky', 'pohodl', 'každodenn']}, 'damske-tenisky'),
    ('Jak vybrat pánské tenisky do města', {'gender': 'panske', 'terms': ['tenisky', 'město', 'mesto', 'urban']}, 'panske-tenisky'),
    ('Bílé tenisky: jak je nosit, čistit a které vybrat', {'colors': ['bíl', 'bil', 'white'], 'terms': ['tenisky']}, 'bile-tenisky'),
    ('Černé tenisky: univerzální boty ke každému outfitu', {'colors': ['čern', 'cern', 'black'], 'terms': ['tenisky']}, 'cerne-tenisky'),
    ('Levné tenisky do 500 Kč: podle čeho vybírat', {'max_price': 500, 'terms': ['tenisky', 'obuv']}, 'tenisky-do-500-kc'),
    ('Nejpohodlnější boty na celodenní nošení', {'terms': ['pohodl', 'měkk', 'každodenn']}, 'pohodlne-tenisky'),
    ('Jak poznat správnou velikost bot při nákupu online', {'terms': ['boty', 'tenisky']}, 'tenisky-na-denni-noseni'),
    ('Letní tenisky: lehké boty do teplého počasí', {'terms': ['letní', 'letni', 'lehké', 'prodyš']}, 'letni-tenisky'),
    ('Sportovní vs volnočasové tenisky: jaký typ vybrat', {'terms': ['sport', 'tenisky', 'běh']}, 'sportovni-tenisky'),
    ('Jak se starat o tenisky, aby déle vydržely', {'terms': ['tenisky', 'boty']}, 'tenisky-na-denni-noseni'),
    ('Tenisky k džínům: jednoduchý návod pro každý den', {'terms': ['džíny', 'dziny', 'tenisky']}, 'tenisky-k-dzinum'),
    ('Dámské bílé tenisky: styling a výběr podle ceny', {'gender': 'damske', 'colors': ['bíl', 'bil', 'white'], 'terms': ['tenisky']}, 'damske-bile-tenisky'),
    ('Pánské černé tenisky: kdy se hodí nejvíc', {'gender': 'panske', 'colors': ['čern', 'cern', 'black'], 'terms': ['tenisky']}, 'panske-cerne-tenisky'),
    ('Jak vybrat boty do práce, které budou pohodlné', {'terms': ['pohodl', 'město', 'elegant']}, 'boty-do-mesta'),
    ('Jak vybrat boty pro dlouhé chození po městě', {'terms': ['pohodl', 'město', 'každodenn']}, 'boty-do-mesta'),
    ('Nejčastější chyby při výběru levných bot', {'max_price': 900, 'terms': ['boty', 'tenisky']}, 'levne-tenisky'),
    ('Jak čistit bílé boty doma bez poškození', {'colors': ['bíl', 'bil', 'white'], 'terms': ['boty', 'tenisky']}, 'bile-tenisky'),
    ('Jak kombinovat sportovní boty s běžným oblečením', {'terms': ['sport', 'tenisky', 'style']}, 'sportovni-tenisky'),
    ('Minimalistické tenisky: kdy dávají smysl', {'terms': ['minimal', 'čist', 'elegant']}, 'elegantni-tenisky'),
    ('Městské tenisky: ideální boty na každý den', {'terms': ['město', 'mesto', 'urban', 'každodenn']}, 'boty-do-mesta'),
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


def _lower(value):
    return (value or '').casefold()


def _product_text(product):
    category_name = product.category.name if getattr(product, 'category', None) else ''
    return ' '.join([
        product.name or '', product.brand or '', product.gender or '', category_name,
        product.short_description or '', product.description or '', product.seo_keywords or '',
        product.colors or '', product.specifications or '',
    ]).casefold()


def _score_product(product, rules):
    score = 0
    text = _product_text(product)
    gender = _lower(rules.get('gender'))
    if gender:
        pg = _lower(product.gender)
        if gender in pg or gender in text:
            score += 35
        elif gender != 'unisex' and pg and 'unisex' not in pg:
            score -= 15

    max_price = rules.get('max_price')
    min_price = rules.get('min_price')
    try:
        price = float(product.price or 0)
    except Exception:
        price = 0
    if max_price is not None:
        score += 35 if price <= float(max_price) else -25
    if min_price is not None:
        score += 15 if price >= float(min_price) else -10

    for color in rules.get('colors') or []:
        if _lower(color) in text:
            score += 25
    for term in rules.get('terms') or []:
        if _lower(term) in text:
            score += 12

    if getattr(product, 'featured', False):
        score += 8
    if product.stock and product.stock > 0:
        score += 8
    if product.original_price and product.original_price > product.price:
        score += 5
    return score


def _active_products():
    return Product.query.filter_by(active=True).order_by(Product.created_at.desc()).all()


def select_products_for_rules(rules, limit=24):
    rules = _as_rules(rules)
    products = _active_products()
    scored = [(p, _score_product(p, rules)) for p in products]
    scored.sort(key=lambda item: (item[1], item[0].stock or 0, item[0].created_at or datetime.utcnow()), reverse=True)
    selected = [p for p, score in scored if score > 0]
    if len(selected) < 3:
        selected = [p for p, _score in scored]
    return selected[:limit]


def products_for_landing_category(category, limit=48):
    rules = _as_rules(getattr(category, 'seo_product_rules', '') or '')
    if rules:
        products = select_products_for_rules(rules, limit=limit)
        if products:
            return products

    q = Product.query.filter_by(active=True)
    products = q.filter(
        db.or_(
            Product.category_id == category.id,
            Product.categories.any(Category.id == category.id)
        )
    ).order_by(Product.created_at.desc()).limit(limit).all()
    if products:
        return products

    fallback_rules = {'terms': [part for part in (category.slug or '').replace('-', ' ').split() if len(part) > 2]}
    return select_products_for_rules(fallback_rules, limit=limit)


def _format_price(value):
    try:
        return f"{int(round(float(value))):,}".replace(',', ' ') + ' Kč'
    except Exception:
        return 'Cena na dotaz'


def _product_url(product):
    return f"/produkt/{escape(product.slug or '')}"


def _image_src(product):
    image = (getattr(product, 'image', '') or 'default-product.svg').strip()
    if image.startswith(('http://', 'https://')):
        return escape(image)
    return f"/uploads/{escape(image)}"


def _product_plain(product):
    return f"{escape(product.name)} za {escape(_format_price(product.price))}"


def _product_names(products, limit=3):
    names = [_product_plain(p) for p in (products or [])[:limit]]
    return ', '.join(names) if names else 'vybrané modely z aktuální nabídky'


def _product_reason(product):
    reason = 'dobrá volba na každodenní nošení'
    text = _product_text(product)
    if 'sport' in text or 'běh' in text or 'beh' in text:
        reason = 'vhodné pro sportovnější styl a aktivnější nošení'
    elif 'bíl' in text or 'bil' in text or 'white' in text:
        reason = 'čistý vzhled, snadno se kombinuje s outfitem'
    elif 'čern' in text or 'cern' in text or 'black' in text:
        reason = 'univerzální barva, která se snadno udržuje'
    elif product.original_price and product.original_price > product.price:
        reason = f'sleva přibližně {product.discount_percent} %, dobrý poměr cena/výkon'
    return reason


def _render_product_cards(products, title='Doporučené modely', subtitle=''):
    cards = []
    for product in (products or [])[:6]:
        old_price = ''
        if product.original_price and product.original_price > product.price:
            old_price = f'<div class="text-secondary small text-decoration-line-through">{_format_price(product.original_price)}</div>'
        short = escape((product.short_description or _product_reason(product) or '')[:140])
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


def _category_button(category_slug, label='Zobrazit celou kategorii'):
    if not category_slug:
        return '<a class="btn btn-outline-dark rounded-pill" href="/produkty">Zobrazit produkty</a>'
    return f'<a class="btn btn-outline-dark rounded-pill" href="/k/{escape(category_slug)}">{escape(label)}</a>'


def build_product_stats(products):
    prices = [float(p.price or 0) for p in products if p.price is not None]
    brands = sorted({p.brand for p in products if p.brand})
    if not prices:
        return {
            'count': len(products), 'min_price': None, 'max_price': None, 'avg_price': None,
            'brands': brands, 'in_stock': len([p for p in products if p.stock and p.stock > 0]),
        }
    return {
        'count': len(products),
        'min_price': min(prices),
        'max_price': max(prices),
        'avg_price': sum(prices) / len(prices),
        'brands': brands,
        'in_stock': len([p for p in products if p.stock and p.stock > 0]),
    }


def build_product_groups(products):
    available = list(products or [])
    cheapest = sorted(available, key=lambda p: float(p.price or 0))[:4]
    discounted = sorted([p for p in available if p.original_price and p.original_price > p.price], key=lambda p: p.discount_percent, reverse=True)[:4]
    featured = [p for p in available if getattr(p, 'featured', False)][:4]
    if len(featured) < 4:
        featured = (featured + available)[:4]
    return {'cheapest': cheapest, 'discounted': discounted, 'featured': featured}


def _render_product_table(products, title='Doporučené modely'):
    return _render_product_cards(
        products,
        title=title,
        subtitle='Klikací jsou celé produktové karty, ne textové odkazy v odstavcích.'
    )


def _faq_html(title, products):
    price_line = 'Ceny se liší podle modelu a dostupnosti.'
    stats = build_product_stats(products)
    if stats['min_price'] is not None and stats['max_price'] is not None:
        price_line = f"U vybraných modelů se cena pohybuje přibližně od {_format_price(stats['min_price'])} do {_format_price(stats['max_price'])}."
    return f'''
<h2>Časté otázky k výběru</h2>
<div class="accordion" id="seoFaq">
  <div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#faq1">Jak vybrat správnou velikost?</button></h3><div id="faq1" class="accordion-collapse collapse show" data-bs-parent="#seoFaq"><div class="accordion-body">Změřte délku chodidla večer, kdy je noha nejvíce zatížená, a nechte malou rezervu přibližně 0,5 až 1 cm. U každého produktu kontrolujte dostupné velikosti a sklad.</div></div></div>
  <div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq2">Kolik stojí {escape(title.lower())}?</button></h3><div id="faq2" class="accordion-collapse collapse" data-bs-parent="#seoFaq"><div class="accordion-body">{price_line}</div></div></div>
  <div class="accordion-item"><h3 class="accordion-header"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#faq3">Na co si dát pozor při nákupu online?</button></h3><div id="faq3" class="accordion-collapse collapse" data-bs-parent="#seoFaq"><div class="accordion-body">Sledujte cenu, velikosti skladem, materiál, typ podrážky a hlavně účel nošení. Jiné boty se hodí na dlouhé chození po městě a jiné k elegantnějším outfitům.</div></div></div>
</div>
'''


def _quality_score(products, content):
    score = 35
    if len(products) >= 3: score += 20
    if len(products) >= 8: score += 10
    if len(content) >= 3500: score += 15
    if 'seo-product-card' in content: score += 10
    if 'Časté otázky' in content: score += 10
    return min(100, score)


def _landing_content(title, rules, products):
    stats = build_product_stats(products)
    groups = build_product_groups(products)
    count = stats['count']
    brands = ', '.join(stats['brands'][:6]) if stats['brands'] else 'různé dostupné značky'
    price_sentence = 'Cenové rozpětí se bude odvíjet od aktuální nabídky.'
    if stats['min_price'] is not None and stats['max_price'] is not None:
        price_sentence = f"Aktuálně vybrané modely začínají přibližně na {_format_price(stats['min_price'])} a nejdražší doporučené kusy jsou kolem {_format_price(stats['max_price'])}."
    featured_models = _product_names(groups['featured'][:3])
    cheap_models = _product_names(groups['cheapest'][:3])

    return f'''
<p><strong>{escape(title)}</strong> jsou výběrová stránka pro zákazníky, kteří nechtějí procházet celý katalog ručně a chtějí rychle najít modely podle konkrétního záměru. Stránka kombinuje reálné produkty z e-shopu, aktuální ceny, doporučení podle použití a praktický návod, podle čeho vybírat.</p>

<div class="row g-3 my-4">
  <div class="col-md-3"><div class="border rounded-4 p-3 h-100"><div class="text-secondary small">Vybrané produkty</div><strong class="fs-4">{count}</strong></div></div>
  <div class="col-md-3"><div class="border rounded-4 p-3 h-100"><div class="text-secondary small">Od ceny</div><strong class="fs-4">{_format_price(stats['min_price']) if stats['min_price'] is not None else '—'}</strong></div></div>
  <div class="col-md-3"><div class="border rounded-4 p-3 h-100"><div class="text-secondary small">Skladem</div><strong class="fs-4">{stats['in_stock']}</strong></div></div>
  <div class="col-md-3"><div class="border rounded-4 p-3 h-100"><div class="text-secondary small">Značky</div><strong class="fs-6">{escape(brands)}</strong></div></div>
</div>

<h2>Jak vybrat {escape(title.lower())}</h2>
<p>Nejdřív si ujasněte, k čemu mají boty sloužit. Pro každodenní nošení je nejdůležitější pohodlí, měkčí došlap a univerzální vzhled. Pro město se vyplatí volit odolnější podrážku a barvu, která se snadno kombinuje. U levnějších modelů sledujte hlavně poměr ceny, vzhledu a dostupných velikostí.</p>
<p>{price_sentence} Pokud chcete co nejrychlejší výběr, začněte u modelů jako {featured_models}. Pro nejnižší cenu dávají smysl hlavně {cheap_models}. Konkrétní proklik najdete níže v produktových kartách.</p>

<h2>Doporučení podle ceny a použití</h2>
<p>U této stránky je cílem vybrat boty, které dávají smysl nejen podle názvu kategorie, ale i podle reálné nabídky. Proto jsou nahoře produkty se silnější shodou: sedí záměr vyhledávání, cena, popis produktu, značka nebo dostupnost. Níže najdete konkrétní modely a jejich hlavní důvod zařazení.</p>
{_render_product_table(groups['featured'], 'Nejlepší výběr v této kategorii')}
{_render_product_table(groups['cheapest'], 'Nejlevnější relevantní modely')}

<h2>Pro koho je tato kategorie nejlepší</h2>
<p>{escape(title)} se hodí hlavně pro zákazníky, kteří chtějí rychlý výběr bez složitého filtrování. Pokud hledáte boty na běžné nošení, zaměřte se na univerzální modely s jednoduchým designem. Pokud řešíte cenu, seřaďte produkty od nejlevnějších a kontrolujte, jestli je dostupná vaše velikost.</p>
<p>Prakticky platí: čím častěji budete boty nosit, tím více řešte pohodlí a podrážku. Pokud mají být boty spíš módním doplňkem, může dávat smysl vybírat podle barvy, stylu a kombinovatelnosti s oblečením.</p>

<h2>Rychlé shrnutí výběru</h2>
<ul>
  <li>Pro nejnižší cenu sledujte modely od {_format_price(stats['min_price']) if stats['min_price'] is not None else 'nejnižší dostupné ceny'}.</li>
  <li>Pro každodenní nošení vybírejte pohodlnější modely s univerzálním vzhledem.</li>
  <li>U barvy zvažte praktičnost: černé modely se méně špiní, bílé působí čistěji a výrazněji.</li>
  <li>U online nákupu vždy kontrolujte velikost, sklad a popis materiálu.</li>
</ul>
{_faq_html(title, products)}
'''


def _blog_content(title, rules, products, category_slug):
    stats = build_product_stats(products)
    groups = build_product_groups(products)
    intro_products = _product_names(groups['featured'][:3])
    category_cta = _category_button(category_slug, 'Zobrazit související kategorii')
    price_sentence = ''
    if stats['min_price'] is not None:
        price_sentence = f" V doporučeném výběru ceny začínají zhruba na {_format_price(stats['min_price'])}."

    return f'''
<p>Tenhle průvodce řeší praktický výběr podle reálné nabídky e-shopu, ne jen obecné rady. Cílem je rychle poznat, které boty dávají smysl podle ceny, stylu, velikosti a způsobu nošení.{price_sentence}</p>

<h2>Rychlé doporučení</h2>
<p>Pokud chcete vybrat bez dlouhého porovnávání, začněte u modelů jako {intro_products}. Konkrétní produkty najdete níže jako karty s obrázkem, cenou a tlačítkem detailu.</p>
<div class="my-3">{category_cta}</div>

<h2>Podle čeho vybírat</h2>
<p>U bot na každodenní nošení sledujte hlavně pohodlí, stabilitu podrážky, dostupné velikosti a to, jestli se model hodí k vašemu běžnému oblečení. U levnějších bot je dobré porovnat nejen cenu, ale i popis, materiál a to, jestli produkt odpovídá způsobu nošení.</p>
<p>Pokud kupujete online, berte velikost vážněji než barvu. Nejčastější chyba je objednání podle zvyku bez kontroly konkrétního střihu. Ideální je změřit chodidlo a nechat malou rezervu.</p>

{_render_product_table(groups['featured'], 'Konkrétní modely, které stojí za zvážení')}

<h2>Jak se rozhodnout mezi podobnými modely</h2>
<p>Když váháte mezi dvěma páry, rozhodujte podle účelu. Na delší chození vyberte pohodlnější a praktičtější model. K outfitům se vyplatí čistší design. Pokud řešíte rozpočet, seřazení podle ceny pomůže, ale nekupujte pouze nejlevnější variantu bez kontroly velikosti a popisu.</p>

<h2>Nejčastější chyby</h2>
<ul>
  <li>výběr jen podle fotky bez kontroly velikosti,</li>
  <li>ignorování účelu nošení,</li>
  <li>nákup bílé obuvi bez plánu na údržbu,</li>
  <li>výběr sportovního modelu tam, kde zákazník reálně chce městské boty.</li>
</ul>

<h2>Finální doporučení</h2>
<p>Nejlepší volba je model, který sedí účelu, ceně i velikosti. Pro rychlý výběr otevřete související kategorii, porovnejte dostupné velikosti a začněte od produktů s nejlepším poměrem cena/vzhled.</p>
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
    return select_products_for_rules({'terms': (post.target_keyword or post.title or '').split()}, limit=limit)


def visible_related_categories(current_id=None, limit=8):
    q = Category.query
    if current_id:
        q = q.filter(Category.id != current_id)
    q = q.filter(db.or_(Category.seo_published.is_(True), Category.seo_generated.is_(False)))
    return q.order_by(Category.name.asc()).limit(limit).all()



def _topic_for_category(category):
    slug = getattr(category, 'slug', '') or ''
    for topic in LANDING_TOPICS:
        if topic.get('slug') == slug:
            return topic
    rules = _as_rules(getattr(category, 'seo_product_rules', '') or '')
    if rules:
        return rules
    return {
        'slug': slug,
        'title': getattr(category, 'name', '') or slug.replace('-', ' ').title(),
        'keyword': getattr(category, 'seo_target_keyword', '') or (getattr(category, 'name', '') or slug.replace('-', ' ')).lower(),
        'terms': [part for part in slug.replace('-', ' ').split() if len(part) > 2],
    }


def _topic_for_blog(post):
    title = getattr(post, 'title', '') or ''
    for topic_title, rules, category_slug in BLOG_TOPICS:
        if topic_title == title:
            return rules, category_slug
    keyword = getattr(post, 'target_keyword', '') or title
    return {'terms': [part for part in keyword.replace('-', ' ').split() if len(part) > 2]}, ''


def regenerate_category_content(category):
    topic = _topic_for_category(category)
    products = select_products_for_rules(topic, limit=36)
    title = topic.get('title') or category.name
    content = _landing_content(title, topic, products)
    score = _quality_score(products, content)
    category.description = content
    category.meta_description = _meta_description_for(title, products)[:320]
    category.seo_title = category.seo_title or f"{title} | doporučené modely a ceny | BotyZaHubicku.cz"
    category.seo_target_keyword = topic.get('keyword') or category.seo_target_keyword or title.lower()
    category.seo_product_rules = json.dumps(topic, ensure_ascii=False)
    category.seo_quality_score = score
    category.seo_last_generated_at = datetime.utcnow()
    category.seo_generated = True
    return category


def regenerate_blog_content(post):
    rules, category_slug = _topic_for_blog(post)
    products = select_products_for_rules(rules, limit=12)
    content = _blog_content(post.title, rules, products, category_slug)
    score = _quality_score(products, content)
    post.content = content
    post.meta_description = _meta_description_for(post.title, products)[:320]
    post.related_product_ids = json.dumps([p.id for p in products[:8]], ensure_ascii=False)
    post.quality_score = score
    post.seo_generated = True
    return post


def regenerate_all_generated_content():
    result = {'blogs': 0, 'landing_pages': 0}
    for post in BlogPost.query.filter_by(seo_generated=True).all():
        regenerate_blog_content(post)
        result['blogs'] += 1
    for category in Category.query.filter_by(seo_generated=True).all():
        regenerate_category_content(category)
        result['landing_pages'] += 1
    db.session.commit()
    return result

def generate_daily_seo_content(blog_count=10, landing_count=10, auto_publish=False):
    created = {'blogs': 0, 'landing_pages': 0, 'skipped_low_quality_publish': 0}
    min_quality_to_publish = 80

    for topic in LANDING_TOPICS:
        if created['landing_pages'] >= landing_count:
            break
        slug = topic['slug']
        if _already_done_category(slug):
            continue
        products = select_products_for_rules(topic, limit=36)
        content = _landing_content(topic['title'], topic, products)
        score = _quality_score(products, content)
        publish_now = bool(auto_publish and score >= min_quality_to_publish and len(products) >= 3)
        if auto_publish and not publish_now:
            created['skipped_low_quality_publish'] += 1
        category = Category(
            name=topic['title'],
            slug=slug,
            description=content,
            meta_description=_meta_description_for(topic['title'], products)[:320],
            seo_title=f"{topic['title']} | doporučené modely a ceny | BotyZaHubicku.cz",
            seo_target_keyword=topic['keyword'],
            seo_product_rules=json.dumps(topic, ensure_ascii=False),
            seo_quality_score=score,
            seo_last_generated_at=datetime.utcnow(),
            seo_generated=True,
            seo_published=publish_now,
            show_in_menu=False,
        )
        db.session.add(category)
        created['landing_pages'] += 1

    for title, rules, category_slug in BLOG_TOPICS:
        if created['blogs'] >= blog_count:
            break
        if _already_done_blog(title):
            continue
        products = select_products_for_rules(rules, limit=12)
        content = _blog_content(title, rules, products, category_slug)
        score = _quality_score(products, content)
        status = 'published' if (auto_publish and score >= min_quality_to_publish and len(products) >= 3) else 'draft'
        if auto_publish and status != 'published':
            created['skipped_low_quality_publish'] += 1
        post = BlogPost(
            slug=unique_slug(BlogPost, title),
            title=title,
            seo_title=f"{title} | BotyZaHubicku.cz",
            target_keyword=title.lower(),
            meta_description=_meta_description_for(title, products)[:320],
            related_product_ids=json.dumps([p.id for p in products[:8]], ensure_ascii=False),
            quality_score=score,
            content=content,
            status=status,
            seo_generated=True,
            published_at=datetime.utcnow() if status == 'published' else None,
        )
        db.session.add(post)
        created['blogs'] += 1

    db.session.commit()
    return created
