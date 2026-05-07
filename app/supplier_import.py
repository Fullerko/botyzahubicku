
import csv
import io
import re
import unicodedata
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from flask_mail import Message
from . import mail, db
from .models import Order, Product, ProductVariant
from .woocommerce_api import update_supplier_variant_in_woocommerce

HEADER_ALIASES = {
    'product_name': {
        'product_name', 'product', 'name', 'nazev', 'nazev_produktu', 'název', 'název produktu',
        'produkt', 'model', 'item_name', 'title'
    }, 
    'internal_sku': {
        'internal_sku', 'bzh_sku', 'interni_sku', 'interní sku', 'sku_we'
    }
}

# Function to get orders for the day and send them in an email
def send_daily_orders_email():
    orders_today = Order.query.filter(Order.date == datetime.today().date()).all()

    if not orders_today:
        return  # No orders for the day, do not send email

    # Prepare the email content
    email_body = "Orders for today:\n"
    for order in orders_today:
        email_body += f"Order ID: {order.id}, Customer: {order.customer_name}, Total: {order.total}\n"
        email_body += f"Details: {order.details}\n"

    # Send the email to the supplier
    msg = Message('Daily Order Summary', sender='your_email@example.com', recipients=['supplier_email@example.com'])
    msg.body = email_body
    mail.send(msg)

# Schedule the daily email to be sent at midnight
scheduler = BackgroundScheduler()
scheduler.add_job(func=send_daily_orders_email, trigger='cron', hour=0, minute=0)
scheduler.start()

# Admin functionality to manually send the email
def send_email_manually():
    send_daily_orders_email()
