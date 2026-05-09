import hashlib
import html as html_lib
import json
import os
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flask import current_app
from PIL import Image

from .utils import slugify


BRANDS = ['Fashion', 'Urban', 'CoreStep', 'VeloxityX']
ADJECTIVES = ['lehké', 'moderní', 'vzdušné', 'pohodlné', 'sportovní', 'městské', 'prémiové', 'prodyšné']
MODEL_PREFIXES = ['Aero', 'Flex', 'Street', 'Cloud', 'Knit', 'Nova', 'Prime', 'Pulse', 'Swift', 'Breeze', 'Stride', 'Air']
MODEL_SUFFIXES = ['Walk', 'Fit', 'Run', 'Step', 'Motion', 'Flow', 'Lite', 'Max', 'Core', 'Nest', 'Line', 'Grip']

IMAGE_RE = re.compile(r'(?:https?:)?//[^\"\'\s<>\\]+?\.(?:jpg|jpeg|png|webp)(?:_[^\"\'\s<>\\]*)?', re.IGNORECASE)
SIZE_RE = re.compile(r'(?<!\d)(3[0-9]|4[0-9]|50)(?!\d)')


def normalize_1688_url(url):
    """Vrátí čistý detail URL bez tracking parametrů."""
    value = (url or '').strip()
    if not value:
        return ''
    if value.startswith('//'):
        value = 'https:' + value
    match = re.search(r'(?:https?:)?//detail\.1688\.com/offer/(\d+)\.html', value)
    if match:
        return f'https://detail.1688.com/offer/{match.group(1)}.html'
    return value


def offer_id_from_url(url):
    match = re.search(r'/offer/(\d+)\.html', url or '')
    return match.group(1) if match else ''


def stable_index(value, modulo):
    digest = hashlib.sha1((value or uuid.uuid4().hex).encode('utf-8')).hexdigest()
    return int(digest[:8], 16) % modulo


def parse_urls(raw_text, limit=100):
    seen = set()
    urls = []
    for line in (raw_text or '').replace(',', '\n').splitlines():
        url = normalize_1688_url(line)
        if not url or url in seen:
            continue
        if '1688.com' not in url:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def fetch_public_html(url, timeout=25):
    request = Request(
        normalize_1688_url(url),
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/123.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'cs-CZ,cs;q=0.9,en;q=0.8,zh-CN;q=0.7',
            'Referer': 'https://www.1688.com/',
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or 'utf-8'
        return raw.decode(charset, errors='replace')


def clean_text(value):
    value = html_lib.unescape(str(value or ''))
    value = re.sub(r'<[^>]+>', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip()
    return value


def extract_meta(html, key):
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html or '', re.IGNORECASE | re.DOTALL)
        if match:
            return clean_text(match.group(1))
    return ''


def extract_title(html):
    for key in ['og:title', 'twitter:title', 'title']:
        value = extract_meta(html, key)
        if value:
            return value
    match = re.search(r'<title[^>]*>(.*?)</title>', html or '', re.IGNORECASE | re.DOTALL)
    if match:
        title = clean_text(match.group(1))
        title = re.sub(r'[-_\s]*1688.*$', '', title, flags=re.IGNORECASE).strip()
        return title
    match = re.search(r'"(?:subject|title|offerTitle)"\s*:\s*"([^"]+)"', html or '')
    if match:
        return clean_text(match.group(1).encode('utf-8').decode('unicode_escape', errors='ignore'))
    return ''


def extract_price(html):
    text = html or ''
    patterns = [
        r'"(?:price|salePrice|discountPrice|offerPrice)"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)"?',
        r'¥\s*([0-9]+(?:\.[0-9]+)?)',
        r'￥\s*([0-9]+(?:\.[0-9]+)?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except Exception:
                pass
    return None


def normalize_image_url(url):
    value = html_lib.unescape((url or '').replace('\\/', '/').strip())
    if value.startswith('//'):
        value = 'https:' + value
    value = value.split('"')[0].split("'")[0]
    return value


def extract_images(html):
    html = (html or '').replace('\\/', '/')
    candidates = []

    for key in ['og:image', 'twitter:image']:
        meta_url = normalize_image_url(extract_meta(html, key))
        if meta_url:
            candidates.append(meta_url)

    candidates.extend(normalize_image_url(match.group(0)) for match in IMAGE_RE.finditer(html))

    filtered = []
    seen = set()
    for url in candidates:
        low = url.lower()
        if not url.startswith(('http://', 'https://')):
            continue
        if not any(domain in low for domain in ['alicdn.com', 'cbu01.alicdn.com', 'img.alicdn.com']):
            continue
        if any(skip in low for skip in ['avatar', 'logo', 'icon', 'sprite', 'transparent']):
            continue
        # Malé náhledy nechceme preferovat. Větší 1688 produktovky často obsahují O1CN nebo /ibank/.
        if url in seen:
            continue
        seen.add(url)
        filtered.append(url)

    product_like = [u for u in filtered if ('/ibank/' in u.lower() or 'o1cn' in u.lower())]
    return (product_like or filtered)[:12]


def detect_sizes(text, gender='unisex'):
    values = sorted({int(x) for x in SIZE_RE.findall(text or '') if 30 <= int(x) <= 50})
    # Odstraní podezřele široké/nesmyslné rozsahy z náhodných čísel ve stránce.
    if values and (max(values) - min(values)) <= 16 and len(values) >= 2:
        return f'{min(values)}-{max(values)}'
    if gender == 'panske':
        return '39-45'
    if gender == 'damske':
        return '35-40'
    return '36-44'


def expand_size_range(size_range):
    value = (size_range or '').strip().replace('–', '-').replace('—', '-')
    match = re.search(r'(\d{2})\s*-\s*(\d{2})', value)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if 20 <= start <= end <= 55:
            return [str(size) for size in range(start, end + 1)]
    return [x.strip() for x in re.split(r'[,;\s]+', value) if x.strip()]


def guess_material(source_text):
    lower = (source_text or '').lower()
    if any(token in lower for token in ['mesh', '网面', '透气', 'síť', 'sitov']):
        return 'Síťovaná textilie', 'prodyšným síťovaným svrškem'
    if any(token in lower for token in ['knit', 'flying weave', '飞织', '针织', 'pleten']):
        return 'Pletený textil', 'pružným pleteným svrškem'
    if any(token in lower for token in ['leather', '皮', 'kožen']):
        return 'Syntetická kůže', 'svrškem s koženým vzhledem'
    return 'Textil a syntetický materiál', 'pohodlným textilním svrškem'


def scrape_1688_product(url, gender='unisex'):
    clean_url = normalize_1688_url(url)
    warnings = []
    html = ''
    try:
        html = fetch_public_html(clean_url)
    except HTTPError as exc:
        warnings.append(f'1688 vrátil HTTP {exc.code}. Bez přihlášení může být část dat skrytá.')
    except URLError as exc:
        warnings.append(f'Nepodařilo se načíst 1688 stránku: {exc.reason}')
    except Exception as exc:
        warnings.append(f'Nepodařilo se načíst 1688 stránku: {exc}')

    title = extract_title(html)
    images = extract_images(html)
    price_cny = extract_price(html)
    sizes = detect_sizes(html + ' ' + title, gender=gender)

    if not title:
        title = f'1688 produkt {offer_id_from_url(clean_url) or "bez ID"}'
    if not images:
        warnings.append('Nenašel jsem obrázky v public HTML. U tohoto odkazu je možná potřeba jiný zdroj dat nebo ruční nahrání fotek.')

    return {
        'source_url': clean_url,
        'offer_id': offer_id_from_url(clean_url),
        'original_title': title,
        'price_cny': price_cny,
        'images': images,
        'sizes': sizes,
        'warnings': warnings,
        'raw_text_sample': clean_text(title),
    }


def build_seo_draft(scraped, gender='unisex', category_name='Tenisky'):
    source_key = scraped.get('source_url') or scraped.get('original_title') or uuid.uuid4().hex
    brand = BRANDS[stable_index(source_key + 'brand', len(BRANDS))]
    adjective = ADJECTIVES[stable_index(source_key + 'adj', len(ADJECTIVES))]
    prefix = MODEL_PREFIXES[stable_index(source_key + 'prefix', len(MODEL_PREFIXES))]
    suffix = MODEL_SUFFIXES[stable_index(source_key + 'suffix', len(MODEL_SUFFIXES))]
    model = f'{prefix}{suffix}'

    gender_label = 'Dámské' if gender == 'damske' else 'Pánské' if gender == 'panske' else 'Unisex'
    category_lower = (category_name or 'tenisky').lower()
    shoe_word = 'tenisky'
    if 'sandál' in category_lower:
        shoe_word = 'sandály'
    elif 'bot' in category_lower and 'tenisk' not in category_lower:
        shoe_word = 'boty'

    material, material_phrase = guess_material(scraped.get('original_title', ''))
    sizes = scraped.get('sizes') or ('35-40' if gender == 'damske' else '39-45' if gender == 'panske' else '36-44')
    name = f'{gender_label} {adjective} {shoe_word} {brand} {model}'
    slug = slugify(name)

    use_cases = 'každodenní nošení, chůzi, město, cestování i volný čas'
    short_description = (
        f'{name} jsou pohodlné volnočasové boty s {material_phrase}, měkkou stélkou '
        f'a stabilní podešví pro {use_cases}.'
    )
    long_description = (
        f'{name} jsou ideální volbou pro zákazníky, kteří hledají pohodlnou, moderní a univerzální obuv na každý den. '
        f'Svršek je navržený s důrazem na komfort při běžném nošení a dobře se hodí pro chůzi ve městě, práci, cestování i volnočasové aktivity.\n\n'
        f'Měkké vnitřní zpracování podporuje pohodlí při každém kroku, zatímco pružná a stabilní podešev pomáhá s jistějším došlapem na běžných površích. Nízký střih, kulatá špička a praktické šněrování dodávají obuvi univerzální vzhled pro každodenní outfity.\n\n'
        f'Model {brand} {model} je vhodný pro zákazníky, kteří chtějí spojit pohodlí, praktičnost a moderní styl v jednom páru obuvi. Skvěle poslouží pro běžné denní nošení, procházky, cestování i aktivní volný čas.'
    )
    seo_title = f'{name} | Pohodlná obuv pro každý den'
    meta_description = (
        f'{name} s {material_phrase}, měkkou stélkou a stabilní podešví. Ideální pro chůzi, město, cestování i volný čas.'
    )[:300]
    keywords = ', '.join([
        f'{gender_label.lower()} {shoe_word}',
        f'{adjective} {shoe_word}',
        'pohodlná obuv',
        'obuv na chůzi',
        'volnočasová obuv',
        'boty pro každý den',
        'městská obuv',
    ])
    image_alt = f'{name} s pohodlným svrškem, šněrováním a stabilní podešví pro každodenní nošení'
    specs = '\n'.join([
        f'Pohlaví: {gender_label}',
        f'Typ obuvi: {shoe_word.capitalize()}',
        'Styl: Sportovní, volnočasový, městský',
        'Vhodné použití: Každodenní nošení, chůze, město, cestování, práce, volný čas',
        f'Svrchní materiál: {material}',
        'Vnitřní materiál: Textil',
        'Materiál stélky: EVA',
        'Materiál podrážky: Syntetický materiál',
        'Typ zapínání: Klasické šněrování',
        'Výška obuvi: Nízká',
        'Tvar špičky: Kulatá',
        'Vlastnosti: Pohodlné, lehké, pružné, odolné proti opotřebení',
        'Podešev: Pružná, stabilní',
        'Sezóna: Jaro, léto, podzim',
        f'Velikosti: {sizes}',
        'Vhodné pro: Dospělé',
        f'Kategorie: {gender_label} volnočasová obuv',
        'Dodání: 8–12 dní',
    ])

    return {
        'source_url': scraped.get('source_url', ''),
        'original_title': scraped.get('original_title', ''),
        'offer_id': scraped.get('offer_id', ''),
        'name': name,
        'brand': brand,
        'slug': slug,
        'gender': gender,
        'short_description': short_description,
        'description': long_description,
        'seo_title': seo_title,
        'meta_description': meta_description,
        'seo_keywords': keywords,
        'image_alt': image_alt,
        'specifications': specs,
        'sizes': sizes,
        'size_list': expand_size_range(sizes),
        'colors': '',
        'image_urls': scraped.get('images', [])[:8],
        'price_cny': scraped.get('price_cny'),
        'warnings': scraped.get('warnings', []),
    }


def _extension_from_url(url):
    path = urlparse(url or '').path.lower()
    for ext in ['.webp', '.jpg', '.jpeg', '.png']:
        if ext in path:
            return ext
    return '.jpg'


def download_image_to_uploads(url, timeout=30):
    """Stáhne obrázek do /data/uploads. Když se to nepovede, vrátí původní URL jako fallback."""
    url = normalize_image_url(url)
    if not url:
        return ''
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://detail.1688.com/'})
        with urlopen(req, timeout=timeout) as response:
            data = response.read()
        ext = _extension_from_url(url)
        filename = f'{uuid.uuid4().hex}{ext}'
        upload_folder = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, '..', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        path = os.path.join(upload_folder, filename)
        with open(path, 'wb') as f:
            f.write(data)
        try:
            image = Image.open(path)
            image.thumbnail((1800, 1800))
            image.save(path, optimize=True)
        except Exception:
            # Pokud Pillow nerozpozná formát, necháme soubor tak, jak přišel.
            pass
        return filename
    except Exception:
        return url


def download_product_images(urls, max_gallery=7):
    cleaned = []
    seen = set()
    for url in urls or []:
        value = normalize_image_url(url)
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    if not cleaned:
        return 'default-product.svg', ''
    saved = [download_image_to_uploads(url) for url in cleaned[:max_gallery + 1]]
    saved = [item for item in saved if item]
    if not saved:
        return 'default-product.svg', ''
    main = saved[0]
    gallery = ','.join(saved[1:max_gallery + 1])
    return main, gallery
