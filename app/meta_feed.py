from flask import Blueprint, Response
from app.models import Product

meta_feed_bp = Blueprint("meta_feed", __name__)

@meta_feed_bp.route("/meta/feed.xml")
def meta_feed():
    products = Product.query.all()

    items = []

    for p in products:
        items.append(f"""
        <item>
            <g:id>{p.id}</g:id>
            <title>{p.name}</title>
            <description>{p.description or p.name}</description>
            <link>https://botyzahubicku.cz/produkt/{p.id}</link>
            <g:image_link>https://botyzahubicku.cz/static/uploads/{p.image}</g:image_link>
            <g:availability>{"in stock" if p.in_stock else "out of stock"}</g:availability>
            <g:price>{p.price} CZK</g:price>
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