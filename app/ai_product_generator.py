import json
import os
import re
from typing import Any, Dict, Tuple

from .import_1688 import build_seo_draft, normalize_1688_url
from .utils import slugify


PRODUCT_FIELDS = [
    'name',
    'brand',
    'slug',
    'short_description',
    'description',
    'seo_title',
    'meta_description',
    'seo_keywords',
    'image_alt',
    'specifications',
    'sizes',
]

ALLOWED_BRANDS = ['Fashion', 'Urban', 'CoreStep', 'VeloxityX']

COLOR_WORDS = [
    'cerna', 'cerny', 'cerne', 'cernou', 'black',
    'bila', 'bily', 'bile', 'bilou', 'white',
    'seda', 'sedy', 'sede', 'sedou', 'gray', 'grey',
    'cervena', 'cerveny', 'cervene', 'red',
    'modra', 'modry', 'modre', 'blue',
    'zelena', 'zeleny', 'zelene', 'green',
    'zluta', 'zluty', 'zlute', 'yellow',
    'hneda', 'hnedy', 'hnede', 'brown',
    'ruzova', 'ruzovy', 'ruzove', 'pink',
    'fialova', 'fialovy', 'fialove', 'purple',
    'oranzova', 'oranzovy', 'oranzove', 'orange',
    'bezova', 'bezovy', 'bezove', 'beige',
]

COLOR_RE = re.compile(r'\b(' + '|'.join(re.escape(w) for w in COLOR_WORDS) + r')\b', re.IGNORECASE)


def _ascii_for_matching(value: str) -> str:
    import unicodedata

    return unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode('ascii')


def strip_color_words(value: Any) -> str:
    """Odstrani z textu zakladni nazvy barev, protoze barva nema byt v SEO vystupech."""
    text = str(value or '')
    if not text:
        return ''

    # Jednoduche odstraneni i u textu s diakritikou: pracujeme po slovech a porovnavame ASCII verzi.
    cleaned_words = []
    for word in re.split(r'(\s+)', text):
        token = re.sub(r'[^\w-]', '', _ascii_for_matching(word).lower())
        if token and COLOR_RE.search(token):
            continue
        cleaned_words.append(word)
    text = ''.join(cleaned_words)
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\s+([,.!?;:])', r'\1', text)
    return text.strip()


def _category_to_shoe_word(category_name: str) -> str:
    value = (category_name or '').lower()
    if 'sandál' in value or 'sandal' in value:
        return 'sandály'
    if 'kotník' in value or 'kotnik' in value:
        return 'kotníkové boty'
    if 'běžeck' in value or 'bezeck' in value:
        return 'běžecké boty'
    if 'bot' in value and 'tenisk' not in value:
        return 'boty'
    return 'tenisky'


def _primary_gender(gender: str) -> str:
    values = [x.strip() for x in (gender or '').split(',') if x.strip()]
    if 'damske' in values:
        return 'damske'
    if 'panske' in values:
        return 'panske'
    return values[0] if values else 'unisex'


def _fallback_from_context(context: Dict[str, Any], category_name: str) -> Dict[str, str]:
    gender = _primary_gender(context.get('gender', 'unisex'))
    scraped = {
        'source_url': normalize_1688_url(context.get('source_url', '')) or context.get('source_url', ''),
        'offer_id': context.get('supplier_sku', '') or '',
        'original_title': strip_color_words(context.get('original_title') or context.get('name') or category_name or 'produkt'),
        'price_cny': None,
        'images': [],
        'sizes': context.get('sizes') or ('35-40' if gender == 'damske' else '39-45' if gender == 'panske' else '36-44'),
        'warnings': [],
    }
    draft = build_seo_draft(scraped, gender=gender, category_name=category_name or 'Tenisky')
    draft['source'] = 'fallback'
    return _normalize_generated(draft, category_name=category_name)


def _json_from_text(text: str) -> Dict[str, Any]:
    raw = (text or '').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r'\{.*\}', raw, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _openai_settings() -> Tuple[str, str, bool]:
    # Import uvnitr funkce kvuli tomu, aby slo modul pouzit i mimo Flask context pri testech.
    try:
        from .utils import setting

        api_key = os.environ.get('OPENAI_API_KEY') or setting('openai_api_key', '')
        model = setting('openai_model', os.environ.get('OPENAI_MODEL', 'gpt-5-mini')) or 'gpt-5-mini'
        enabled = setting('ai_generation_enabled', '1').strip() == '1'
    except Exception:
        api_key = os.environ.get('OPENAI_API_KEY', '')
        model = os.environ.get('OPENAI_MODEL', 'gpt-5-mini')
        enabled = True
    return api_key.strip(), model.strip(), enabled


def _call_openai(context: Dict[str, Any], category_name: str) -> Dict[str, Any]:
    api_key, model, enabled = _openai_settings()
    if not enabled:
        raise RuntimeError('AI generovani je vypnute v nastaveni.')
    if not api_key:
        raise RuntimeError('Chybi OPENAI_API_KEY nebo openai_api_key v nastaveni.')

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    gender = _primary_gender(context.get('gender', 'unisex'))
    shoe_word = _category_to_shoe_word(category_name)
    source_title = strip_color_words(context.get('original_title') or context.get('name') or '')

    system = (
        'Jsi seniorni SEO copywriter pro cesky e-shop s obuvi. '
        'Vracej pouze validni JSON bez markdownu. Nepis zadne vysvetleni.'
    )
    user = f"""
Vygeneruj kompletni produktova data v cestine pro e-shop s obuvi.

Vstup:
- Kategorie: {category_name or 'Tenisky'}
- Typ obuvi: {shoe_word}
- Pohlavi: {gender}
- Puvodni/naznaceny nazev: {source_title or 'neni zadan'}
- Zdrojova URL: {context.get('source_url', '') or 'neni zadana'}
- Velikosti: {context.get('sizes', '') or 'navrhni jako rozsah'}
- Cena: {context.get('price', '') or 'neni zadana'}

Pravidla:
- Vse musi byt cesky a vhodne pro e-shop, SEO, Google i produktovy detail.
- Nazev produktu musi byt ve stylu: "Panske/Damske/Unisex + prirozene pridavne jmeno + typ obuvi + serie/znacka + model".
- Pouzij jednu z techto serii/znacek: Fashion, Urban, CoreStep, VeloxityX.
- Nepouzivej v nazvu ani nikde ve vystupech barvu produktu.
- Nepouzivej suffix V2.
- Atributy pis jako vice radku ve formatu "Atribut: Hodnota".
- Do atributu nedavej znacku/serii.
- Velikosti pis jako rozsah, napr. "35-40", ne jako vycet.
- Dodání v atributech musi byt presne "Dodání: 8–12 dní".
- Barvy negeneruj a nezminuj.
- Meta description max 160 znaku.
- SEO title max 70 znaku.
- Kratky popis max 255 znaku.

Vrat JSON s presne temito klici:
name, brand, slug, short_description, description, seo_title, meta_description, seo_keywords, image_alt, specifications, sizes
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        response_format={'type': 'json_object'},
    )
    content = response.choices[0].message.content or '{}'
    data = _json_from_text(content)
    data['source'] = 'openai'
    return data


def _normalize_generated(data: Dict[str, Any], category_name: str = 'Tenisky') -> Dict[str, str]:
    result: Dict[str, str] = {}
    for field in PRODUCT_FIELDS:
        result[field] = strip_color_words(data.get(field, ''))

    if result.get('brand') not in ALLOWED_BRANDS:
        result['brand'] = ALLOWED_BRANDS[0]

    result['sizes'] = _normalize_size_range(result.get('sizes') or data.get('sizes') or '')
    if not result['sizes']:
        result['sizes'] = '36-44'

    result['slug'] = slugify(result.get('slug') or result.get('name') or category_name or 'produkt')

    # Kratke pojistky na delky poli v DB/UI.
    result['name'] = result.get('name', '')[:150].strip()
    result['seo_title'] = result.get('seo_title', '')[:180].strip()
    result['meta_description'] = result.get('meta_description', '')[:320].strip()
    result['short_description'] = result.get('short_description', '')[:255].strip()
    result['image_alt'] = result.get('image_alt', '')[:255].strip()

    specs = result.get('specifications', '')
    specs = _remove_brand_from_specs(specs)
    specs = _ensure_spec_line(specs, 'Velikosti', result['sizes'])
    specs = _ensure_spec_line(specs, 'Dodání', '8–12 dní')
    result['specifications'] = specs.strip()
    result['source'] = data.get('source', 'fallback')
    return result


def _normalize_size_range(value: str) -> str:
    value = str(value or '').strip()
    if not value:
        return ''
    numbers = [int(x) for x in re.findall(r'(?<!\d)(3[0-9]|4[0-9]|50)(?!\d)', value)]
    if numbers:
        return f'{min(numbers)}-{max(numbers)}'
    return value.replace('–', '-').replace('—', '-').strip()


def _remove_brand_from_specs(specs: str) -> str:
    lines = []
    for line in (specs or '').splitlines():
        label = line.split(':', 1)[0].strip().lower() if ':' in line else ''
        if label in {'znacka', 'značka', 'serie', 'série', 'brand'}:
            continue
        cleaned = line
        for brand in ALLOWED_BRANDS:
            cleaned = re.sub(rf'\b{re.escape(brand)}\b', '', cleaned, flags=re.I)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        if cleaned:
            lines.append(cleaned)
    return '\n'.join(lines)


def _ensure_spec_line(specs: str, label: str, value: str) -> str:
    lines = [line.strip() for line in (specs or '').splitlines() if line.strip()]
    normalized_label = _ascii_for_matching(label).lower()
    for index, line in enumerate(lines):
        if ':' not in line:
            continue
        current_label = _ascii_for_matching(line.split(':', 1)[0]).lower().strip()
        if current_label == normalized_label:
            lines[index] = f'{label}: {value}'
            return '\n'.join(lines)
    lines.append(f'{label}: {value}')
    return '\n'.join(lines)


def generate_product_fields(context: Dict[str, Any], category_name: str = 'Tenisky') -> Tuple[Dict[str, str], Dict[str, str]]:
    """Vrati (fields, status). Kdyz OpenAI neni dostupne, automaticky pouzije lokalni SEO sablonu."""
    try:
        ai_data = _call_openai(context, category_name)
        fields = _normalize_generated(ai_data, category_name=category_name)
        return fields, {'source': fields.get('source', 'openai'), 'message': 'AI texty byly vygenerovane pres OpenAI API.'}
    except Exception as exc:
        fields = _fallback_from_context(context, category_name=category_name)
        return fields, {'source': 'fallback', 'message': f'Pouzita lokalni SEO sablona: {exc}'}


def merge_generated_fields(current: Dict[str, Any], generated: Dict[str, str], overwrite: bool = False) -> Dict[str, Any]:
    merged = dict(current)
    for field in PRODUCT_FIELDS:
        value = (generated.get(field) or '').strip()
        if not value:
            continue
        existing = str(merged.get(field, '') or '').strip()
        if overwrite or not existing:
            merged[field] = value
    if not merged.get('slug') and merged.get('name'):
        merged['slug'] = slugify(merged['name'])
    return merged
