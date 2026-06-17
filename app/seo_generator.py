from datetime import datetime

from . import db
from .models import BlogPost, Category, Product
from .utils import slugify, unique_slug


BLOG_TOPICS = [
    'Jak vybrat dámské tenisky na každý den',
    'Jak vybrat pánské tenisky do města',
    'Bílé tenisky: jak je nosit a čistit',
    'Černé tenisky: univerzální boty ke každému outfitu',
    'Levné tenisky do 500 Kč: podle čeho vybírat',
    'Nejpohodlnější boty na celodenní nošení',
    'Jak poznat správnou velikost bot při nákupu online',
    'Letní tenisky: lehké boty do teplého počasí',
    'Sportovní vs volnočasové tenisky: jaký je rozdíl',
    'Jak se starat o tenisky, aby déle vydržely',
    'Tenisky k džínům: jednoduchý návod pro každý den',
    'Dámské bílé tenisky: styling a výběr',
    'Pánské černé tenisky: kdy se hodí nejvíc',
    'Jak vybrat boty do práce, které budou pohodlné',
    'Jak vybrat boty pro dlouhé chození po městě',
    'Nejčastější chyby při výběru levných bot',
    'Jak čistit bílé boty doma bez poškození',
    'Jak kombinovat sportovní boty s běžným oblečením',
    'Tenisky na jaro: co sledovat při výběru',
    'Tenisky na podzim: pohodlí, styl a praktičnost',
    'Jak vybrat obuv podle tvaru chodidla',
    'Jak poznat pohodlnou podrážku u tenisek',
    'Proč řešit materiál svršku u bot',
    'Jak nakupovat boty online bez zbytečného vracení',
    'Minimalistické tenisky: kdy dávají smysl',
    'Městské tenisky: ideální boty na každý den',
    'Jak vybrat boty pro cestování',
    'Jak často měnit každodenně nošené tenisky',
    'Jak skladovat boty, aby neztratily tvar',
    'Jak rozchodit nové tenisky bez puchýřů',
]

LANDING_TOPICS = [
    ('damske-bile-tenisky', 'Dámské bílé tenisky'),
    ('damske-cerne-tenisky', 'Dámské černé tenisky'),
    ('panske-bile-tenisky', 'Pánské bílé tenisky'),
    ('panske-cerne-tenisky', 'Pánské černé tenisky'),
    ('levne-damske-tenisky', 'Levné dámské tenisky'),
    ('levne-panske-tenisky', 'Levné pánské tenisky'),
    ('tenisky-do-500-kc', 'Tenisky do 500 Kč'),
    ('tenisky-do-700-kc', 'Tenisky do 700 Kč'),
    ('tenisky-do-1000-kc', 'Tenisky do 1000 Kč'),
    ('bile-tenisky', 'Bílé tenisky'),
    ('cerne-tenisky', 'Černé tenisky'),
    ('pohodlne-tenisky', 'Pohodlné tenisky'),
    ('lehke-tenisky', 'Lehké tenisky'),
    ('letni-tenisky', 'Letní tenisky'),
    ('zimni-boty', 'Zimní boty'),
    ('sportovni-tenisky', 'Sportovní tenisky'),
    ('tenisky-na-denni-noseni', 'Tenisky na denní nošení'),
    ('damske-sportovni-tenisky', 'Dámské sportovní tenisky'),
    ('panske-sportovni-tenisky', 'Pánské sportovní tenisky'),
    ('levne-boty', 'Levné boty'),
    ('boty-na-kazdy-den', 'Boty na každý den'),
    ('boty-do-mesta', 'Boty do města'),
    ('modni-tenisky', 'Módní tenisky'),
    ('streetwear-tenisky', 'Streetwear tenisky'),
    ('tenisky-k-dzinum', 'Tenisky k džínům'),
    ('elegantni-tenisky', 'Elegantní tenisky'),
    ('unisex-tenisky', 'Unisex tenisky'),
    ('damske-boty-do-mesta', 'Dámské boty do města'),
    ('panske-boty-do-mesta', 'Pánské boty do města'),
    ('boty-s-dopravou-zdarma', 'Boty s dopravou zdarma'),
]


def _first_products(limit=6):
    return Product.query.filter_by(active=True).order_by(Product.created_at.desc()).limit(limit).all()


def _link_products_html(limit=4):
    products = _first_products(limit)
    if not products:
        return ''
    links = []
    for product in products:
        links.append(f'<li><a href="/produkt/{product.slug}">{product.name}</a></li>')
    return '<ul>' + ''.join(links) + '</ul>'


def _category_links_html():
    links = []
    for category in Category.query.filter_by(seo_published=True).order_by(Category.name.asc()).limit(8).all():
        links.append(f'<li><a href="/k/{category.slug}">{category.name}</a></li>')
    if not links:
        return ''
    return '<ul>' + ''.join(links) + '</ul>'


def make_blog_content(title):
    category_links = _category_links_html()
    product_links = _link_products_html(5)
    return f'''
<p>{title} je téma, které řeší zákazníci při výběru bot pro každodenní nošení, práci, město i volný čas. Správný výběr není jen o vzhledu. Důležitá je velikost, pohodlí, materiál, podrážka a také to, jak často budete boty nosit.</p>

<h2>Na co se zaměřit při výběru</h2>
<p>Nejdřív si ujasněte, jestli hledáte boty na běžné nošení, sportovní aktivity, dlouhé chození po městě nebo spíš univerzální model ke každému outfitu. Každé použití klade na obuv jiné požadavky. Pro každodenní nošení je obvykle nejdůležitější pohodlí, lehkost, stabilita chodidla a jednoduchá kombinovatelnost.</p>

<h2>Velikost a pohodlí</h2>
<p>U online nákupu bot je klíčové neřídit se jen číslem velikosti, ale také délkou chodidla a střihem konkrétního modelu. Pokud váháte mezi dvěma velikostmi, u tenisek na celodenní nošení se často vyplatí zvolit variantu s menší rezervou pro pohyb prstů.</p>

<h2>Materiál a údržba</h2>
<p>Lehčí textilní modely jsou vhodné hlavně na jaro a léto. Koženkové nebo pevnější syntetické modely se lépe čistí a mohou působit elegantněji. Světlé boty vyžadují častější údržbu, černé a tmavé modely jsou praktičtější pro každodenní provoz.</p>

<h2>Doporučené kategorie</h2>
{category_links}

<h2>Doporučené produkty</h2>
{product_links}

<h2>Časté otázky</h2>
<h3>Jak poznat správnou velikost?</h3>
<p>Změřte délku chodidla od paty po nejdelší prst a porovnejte ji s dostupnými velikostmi u produktu. Neřiďte se pouze velikostí, kterou nosíte u jiné značky.</p>

<h3>Jsou levné tenisky vhodné na každý den?</h3>
<p>Ano, pokud mají pohodlnou podrážku, dostatečnou stabilitu a dobře sedí na noze. Cena sama o sobě nerozhoduje o tom, jestli budou boty pohodlné.</p>

<h3>Jak prodloužit životnost bot?</h3>
<p>Boty pravidelně čistěte, nenechávejte je dlouhodobě ve vlhku a střídejte je s jiným párem, pokud je nosíte každý den.</p>
'''.strip()


def make_category_content(title):
    product_links = _link_products_html(6)
    return f'''
<p>{title} jsou vhodné pro zákazníky, kteří hledají dostupnou, pohodlnou a stylovou obuv pro běžné nošení. Tato stránka slouží jako přehled vybraných modelů a praktický průvodce výběrem.</p>

<h2>Jak vybrat {title.lower()}</h2>
<p>Při výběru sledujte hlavně velikost, pohodlí, materiál, podrážku a způsob použití. Pro každodenní nošení jsou ideální lehké modely, které dobře sedí na noze a dají se jednoduše kombinovat s běžným oblečením.</p>

<h2>Pro koho se tato kategorie hodí</h2>
<p>{title} se hodí pro zákazníky, kteří chtějí praktické boty bez složitého výběru. Využijete je do města, do práce, na volný čas i na běžné pochůzky.</p>

<h2>Materiál, barva a údržba</h2>
<p>Světlé modely působí čistě a moderně, ale vyžadují častější čištění. Tmavé modely jsou praktičtější pro každodenní nošení. Pokud boty nosíte často, doporučujeme je pravidelně čistit jemným hadříkem a nenechávat je dlouhodobě ve vlhku.</p>

<h2>Doporučené produkty</h2>
{product_links}

<h2>Časté otázky</h2>
<h3>Jak vybrat správnou velikost?</h3>
<p>Změřte délku chodidla a porovnejte ji s dostupnými velikostmi u konkrétního produktu. Při celodenním nošení je vhodné počítat s malou rezervou.</p>

<h3>Jsou tyto boty vhodné na každý den?</h3>
<p>Ano, pokud zvolíte správnou velikost a pohodlný střih. Pro dlouhé nošení vybírejte hlavně podle podrážky a stability.</p>

<h3>Jak se o boty starat?</h3>
<p>Pravidelně odstraňujte nečistoty, používejte jemný hadřík a boty nesušte přímo u radiátoru. Tím prodloužíte jejich životnost.</p>
'''.strip()


def generate_daily_seo_content(blog_count=10, landing_count=10, auto_publish=False):
    created = {'blogs': 0, 'landing_pages': 0}
    auto_publish = bool(auto_publish)

    for title in BLOG_TOPICS:
        if created['blogs'] >= int(blog_count or 0):
            break
        base_slug = slugify(title)
        if BlogPost.query.filter_by(slug=base_slug).first():
            continue
        slug = unique_slug(BlogPost, title)
        post = BlogPost(
            slug=slug,
            title=title,
            meta_description=f'{title}. Praktický průvodce výběrem bot a tenisek online.',
            content=make_blog_content(title),
            status='published' if auto_publish else 'draft',
            published_at=datetime.utcnow() if auto_publish else None,
            seo_generated=True,
        )
        db.session.add(post)
        created['blogs'] += 1

    for slug, title in LANDING_TOPICS:
        if created['landing_pages'] >= int(landing_count or 0):
            break
        if Category.query.filter_by(slug=slug).first():
            continue
        category = Category(
            name=title,
            slug=slug,
            image_url='',
            description=make_category_content(title),
            meta_description=f'{title} online. Vyberte si pohodlné a dostupné boty s dopravou zdarma.',
            show_in_menu=False,
            seo_generated=True,
            seo_published=auto_publish,
        )
        db.session.add(category)
        created['landing_pages'] += 1

    db.session.commit()
    return created
