from app.ai_product_generator import generate_product_fields


def generate_seo_description(product_type):
    fields, _status = generate_product_fields({'name': product_type, 'original_title': product_type}, category_name='Tenisky')
    return fields.get('short_description') or fields.get('description') or ''
