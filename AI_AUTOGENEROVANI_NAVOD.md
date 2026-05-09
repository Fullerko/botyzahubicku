# AI automatické generování produktů

Upraveno tak, aby se při přidávání produktů automaticky doplňovalo maximum polí:

- název produktu
- značka/série
- slug
- krátký popis
- dlouhý popis
- SEO title
- meta description
- SEO keywords
- ALT text obrázku
- atributy produktu
- velikosti jako rozsah v atributech
- lokální SKU a varianty velikost x barva
- volitelně synchronizace do WooCommerce API, pokud je zapnutá v nastavení

## Jak zapnout OpenAI API

Doporučené nastavení na hostingu:

```bash
OPENAI_API_KEY=tvuj_api_klic
OPENAI_MODEL=gpt-5-mini
```

Alternativně lze API klíč vložit v administraci:

`Admin -> Nastavení -> AI generování produktů -> OpenAI API klíč`

Bez API klíče web nespadne. Použije lokální SEO šablonu.

## Co je potřeba po nahrání

1. Nahraj upravené soubory do projektu.
2. Spusť instalaci závislostí:

```bash
pip install -r requirements.txt
```

3. Restartuj aplikaci.
4. V adminu zkontroluj:
   - `Nastavení -> AI generování produktů`
   - `Nastavení -> WooCommerce / dodavatel API`

## Důležité

Původní kód měl v `app/routes_admin.py` vloženou druhou Flask aplikaci a špatné importy `scrape_1688` a `product_seo_generator`. To je odstraněno.
