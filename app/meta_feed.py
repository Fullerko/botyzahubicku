from flask import Blueprint, Response
from app.models import Product

meta_feed_bp = Blueprint("meta_feed", __name__)

@meta_feed_bp.route("/meta/feed.xml")
def meta_feed():

    products = Product.query.all()

    items = []

    for p in products:

        brand = getattr(p, "brand", None) or "Boty Za Hubičku"
        availability = "in stock"

        price = f"{p.price} CZK"

        image = getattr(p, "image", "")
        image_url = f"https://botyzahubicku.cz/static/uploads/{image}"

        link = f"https://botyzahubicku.cz/produkt/{p.id}"

        items.append(f"""
<item>
    <g:id>{p.id}</g:id>
    <title>{p.name}</title>
    <description>{p.description or p.name}</description>
    <link>{link}</link>
    <g:image_link>{image_url}</g:image_link>
    <g:availability>{availability}</g:availability>
    <g:price>{price}</g:price>
    <g:brand>{brand}</g:brand>
    <g:condition>new</g:condition>
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

    return Response(xml, mimetype="application/xml")