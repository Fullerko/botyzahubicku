from flask import Blueprint, Response, url_for
from xml.sax.saxutils import escape
from app.models import Product

meta_feed_bp = Blueprint("meta_feed", __name__)


def clean(value):
    return escape(str(value or "").strip())


@meta_feed_bp.route("/meta/feed.xml")
def meta_feed():
    products = Product.query.filter_by(active=True).order_by(Product.id.desc()).all()

    items = []

    for p in products:
        if not p.slug:
            continue

        price = float(p.price or 0)
        if price <= 0:
            continue

        image = (p.image or "default-product.svg").split(",")[0].strip()
        product_url = url_for("shop.product_detail", slug=p.slug, _external=True)
        image_url = url_for("uploaded_file", filename=image, _external=True)

        stock = int(getattr(p, "stock", 0) or 0)
        availability = "in stock" if stock > 0 else "out of stock"

        brand = (p.brand or "").strip() or "Boty Za Hubičku"
        description = p.meta_description or p.short_description or p.description or p.name

        items.append(f"""
<item>
    <g:id>{clean(p.id)}</g:id>
    <title>{clean(p.name)}</title>
    <description>{clean(description)}</description>
    <link>{clean(product_url)}</link>
    <g:image_link>{clean(image_url)}</g:image_link>
    <g:availability>{availability}</g:availability>
    <g:price>{price:.2f} CZK</g:price>
    <g:brand>{clean(brand)}</g:brand>
    <g:condition>new</g:condition>
    <g:identifier_exists>no</g:identifier_exists>
</item>
""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">
<channel>
<title>Boty Za Hubičku</title>
<link>https://botyzahubicku.cz</link>
<description>Meta Product Feed</description>
{''.join(items)}
</channel>
</rss>
"""

    return Response(xml, mimetype="application/xml; charset=utf-8")