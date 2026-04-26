from io import BytesIO
from datetime import datetime
import os

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def money(value):
    return f"{int(value or 0):,}".replace(",", " ") + " Kč"


def generate_invoice_pdf(order):
    font_dir = os.path.join(current_app.root_path, "static", "fonts")

    pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(font_dir, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(font_dir, "DejaVuSans-Bold.ttf")))

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    styles["Normal"].fontName = "DejaVu"
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 12

    styles["Heading2"].fontName = "DejaVu-Bold"
    styles["Heading3"].fontName = "DejaVu-Bold"

    styles.add(ParagraphStyle(
        name="BigTitle",
        fontSize=22,
        leading=26,
        spaceAfter=20,
        textColor=colors.black,
        fontName="DejaVu-Bold"
    ))

    elements = []

    invoice_number = order.order_number.replace("BZH", "") if order.order_number else str(order.id)
    variable_symbol = order.variable_symbol or invoice_number

    elements.append(Paragraph(f"FAKTURA #{invoice_number}", styles["BigTitle"]))
    elements.append(Spacer(1, 12))

    header_data = [
        [
            Paragraph(
                "<b>DODAVATEL:</b><br/>"
                "Zbyšek Kubalák<br/>"
                "IČO: 17808871<br/>"
                "Nálepkova 887/23<br/>"
                "708 00 Ostrava",
                styles["Normal"]
            ),
            Paragraph(
                "<b>ODBĚRATEL:</b><br/>"
                f"{order.email}<br/>"
                f"VS: {variable_symbol}<br/>"
                f"Datum: {datetime.now().strftime('%d.%m.%Y')}",
                styles["Normal"]
            )
        ]
    ]

    header_table = Table(header_data, colWidths=[260, 260])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#4f46e5")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))

    elements.append(header_table)
    elements.append(Spacer(1, 24))

    rows = [["Položka", "Množství", "Cena"]]

    for item in order.items:
        rows.append([
            item.product_name,
            f"{item.quantity} ks",
            money((item.unit_price or 0) * (item.quantity or 1))
        ])

        subtotal = sum((item.unit_price or 0) * (item.quantity or 1) for item in order.items)
        discount_amount = subtotal - (order.total_price or 0)

        if discount_amount > 0:
            rows.append([
                "SLEVA",
                "",
                f"-{money(discount_amount)}"
            ])

        rows.append(["", "", ""])
        rows.append(["CELKEM ZAPLACENO", "", money(order.total_price)])

    table = Table(rows, colWidths=[310, 90, 120])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5f6f8")),
        ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 10),

        ("GRID", (0, 0), (-1, -2), 0.25, colors.HexColor("#eeeeee")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("FONTNAME", (0, -1), (-1, -1), "DejaVu-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 14),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#4f46e5")),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#4f46e5")),
        ("TOPPADDING", (0, -1), (-1, -1), 14),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 28))

    elements.append(Paragraph("Děkujeme za Váš nákup.", styles["Normal"]))

    doc.build(elements)

    buffer.seek(0)
    return buffer