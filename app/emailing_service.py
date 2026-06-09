import json
import mimetypes
import os
import re
import smtplib
import time
from contextlib import contextmanager
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from flask import current_app, url_for
from sqlalchemy import func, or_

from . import db
from .models import (
    AffiliatePartner,
    CartLead,
    EmailCampaign,
    EmailCampaignRecipient,
    EmailContact,
    EmailSuppression,
    Order,
    Product,
)
from .utils import get_cart, setting

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def normalize_email(value):
    email = (value or '').strip().lower()
    return email if EMAIL_RE.match(email) else ''


def _json_loads(value, default):
    try:
        if not value:
            return default
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _now():
    return datetime.utcnow()


def _site_base_url():
    """Veřejná URL webu pro odkazy v e-mailech i mimo request context scheduleru."""
    base = (setting('site_url', '') or '').strip() or (setting('domain_name', '') or '').strip() or 'botyzahubicku.cz'
    if not base.startswith(('http://', 'https://')):
        base = 'https://' + base.lstrip('/')
    return base.rstrip('/')


def _build_public_url(endpoint, **values):
    try:
        return url_for(endpoint, _external=True, **values)
    except Exception:
        try:
            with current_app.test_request_context(base_url=_site_base_url()):
                return url_for(endpoint, _external=True, **values)
        except Exception:
            return ''


def _is_unpaid_order(order):
    payment_status = (getattr(order, 'payment_status', '') or '').strip().lower()
    status = (getattr(order, 'status', '') or '').strip().lower()
    return payment_status != 'paid' and status not in {'zaplaceno', 'odeslána', 'odeslana', 'dokončena', 'dokoncena'}


def _unpaid_order_query(email=None):
    q = Order.query.filter(or_(Order.payment_status.is_(None), Order.payment_status != 'paid'))
    q = q.filter(or_(Order.status.is_(None), ~Order.status.in_(['Zaplaceno', 'Odeslána', 'Dokončena'])))
    if email:
        q = q.filter(func.lower(Order.email) == normalize_email(email))
    return q.order_by(Order.created_at.desc(), Order.id.desc())


def _latest_unpaid_order(email=None):
    return _unpaid_order_query(email=email).first()


def _format_money(value):
    try:
        amount = round(float(value or 0))
    except Exception:
        amount = 0
    return f"{amount:,}".replace(',', ' ') + ' Kč'


def _order_items_text(order):
    if not order:
        return ''
    lines = []
    for item in getattr(order, 'items', []) or []:
        details = []
        if getattr(item, 'size', ''):
            details.append(f"vel. {item.size}")
        if getattr(item, 'color', ''):
            details.append(str(item.color))
        suffix = f" ({', '.join(details)})" if details else ''
        lines.append(f"- {item.quantity}× {item.product_name}{suffix} – {_format_money((item.unit_price or 0) * (item.quantity or 1))}")
    return '\n'.join(lines)


def _order_items_html(order):
    if not order:
        return ''
    rows = []
    for item in getattr(order, 'items', []) or []:
        details = []
        if getattr(item, 'size', ''):
            details.append(f"vel. {escape(str(item.size))}")
        if getattr(item, 'color', ''):
            details.append(escape(str(item.color)))
        suffix = f" <span style=\"color:#777;\">({', '.join(details)})</span>" if details else ''
        rows.append(f"<li>{int(item.quantity or 1)}× {escape(item.product_name or '')}{suffix} – {_format_money((item.unit_price or 0) * (item.quantity or 1))}</li>")
    return '<ul>' + ''.join(rows) + '</ul>' if rows else ''


def _suppressed_emails():
    return {row.email for row in EmailSuppression.query.with_entities(EmailSuppression.email).all()}


def ensure_suppression(email, reason='manual'):
    email = normalize_email(email)
    if not email:
        return None
    row = EmailSuppression.query.filter_by(email=email).first()
    if not row:
        row = EmailSuppression(email=email, reason=reason)
        db.session.add(row)
    else:
        row.reason = reason or row.reason
    contact = EmailContact.query.filter_by(email=email).first()
    if contact:
        contact.marketing_enabled = False
        contact.unsubscribed_at = contact.unsubscribed_at or _now()
    return row


def get_or_create_contact(email, **kwargs):
    email = normalize_email(email)
    if not email:
        return None
    contact = EmailContact.query.filter_by(email=email).first()
    if not contact:
        contact = EmailContact(email=email)
        db.session.add(contact)
        db.session.flush()
    for key, value in kwargs.items():
        if value is None:
            continue
        if hasattr(contact, key):
            if isinstance(value, str):
                value = value.strip()
            # Nepřepisovat plné údaje prázdnou hodnotou.
            if value != '' or not getattr(contact, key, None):
                setattr(contact, key, value)
    contact.updated_at = _now()
    if EmailSuppression.query.filter_by(email=email).first():
        contact.marketing_enabled = False
        contact.unsubscribed_at = contact.unsubscribed_at or _now()
    return contact


def upsert_contact_from_order(order):
    email = normalize_email(getattr(order, 'email', ''))
    if not email:
        return None
    contact = get_or_create_contact(
        email,
        name=getattr(order, 'customer_name', '') or '',
        phone=getattr(order, 'phone', '') or '',
        source='order',
        has_order=True,
        last_order_at=getattr(order, 'created_at', None) or _now(),
    )
    if not contact:
        return None
    # Přepočítat základní souhrny podle všech objednávek se stejným e-mailem.
    orders = Order.query.filter(func.lower(Order.email) == email).all()
    contact.orders_count = len(orders)
    contact.has_order = bool(orders)
    contact.has_paid_order = any((o.payment_status == 'paid' or o.status == 'Zaplaceno') for o in orders)
    contact.total_spent = sum((o.total_price or 0) for o in orders if (o.payment_status == 'paid' or o.status == 'Zaplaceno'))
    latest = max((o.created_at for o in orders if o.created_at), default=getattr(order, 'created_at', None) or _now())
    contact.last_order_at = latest

    lead = CartLead.query.filter_by(email=email).first()
    if lead:
        lead.converted_order_id = getattr(order, 'id', None)
        lead.converted_at = _now()
    return contact


def _cart_snapshot():
    items = []
    subtotal = 0
    item_count = 0
    cart = get_cart()
    for key, item in cart.items():
        product = Product.query.get(item.get('product_id'))
        if not product:
            continue
        quantity = int(item.get('quantity') or 1)
        line_total = (product.price or 0) * quantity
        subtotal += line_total
        item_count += quantity
        items.append({
            'key': key,
            'product_id': product.id,
            'product_name': product.name,
            'size': item.get('size', ''),
            'color': item.get('color', ''),
            'quantity': quantity,
            'unit_price': product.price or 0,
            'line_total': line_total,
        })
    return {'items': items, 'subtotal': subtotal, 'item_count': item_count}


def capture_cart_lead(email, name='', phone='', session_id=''):
    email = normalize_email(email)
    if not email:
        return None
    snapshot = _cart_snapshot()
    if snapshot['item_count'] <= 0:
        return None
    lead = CartLead.query.filter_by(email=email).first()
    if not lead:
        lead = CartLead(email=email)
        db.session.add(lead)
    lead.name = (name or lead.name or '').strip()
    lead.phone = (phone or lead.phone or '').strip()
    lead.session_id = session_id or lead.session_id or ''
    lead.cart_json = _json_dumps(snapshot)
    lead.subtotal = snapshot['subtotal']
    lead.item_count = snapshot['item_count']
    lead.updated_at = _now()

    contact = get_or_create_contact(
        email,
        name=lead.name,
        phone=lead.phone,
        source='cart',
        has_cart=True,
        last_cart_at=_now(),
        cart_json=lead.cart_json,
    )
    if contact:
        contact.has_cart = True
        contact.last_cart_at = _now()
        contact.cart_json = lead.cart_json
    return lead


def sync_existing_contacts():
    """Doplní kontakty ze starých objednávek a affiliate partnerů bez drahého odesílání nebo mazání."""
    grouped = {}
    for order in Order.query.order_by(Order.created_at.asc()).all():
        email = normalize_email(order.email)
        if not email:
            continue
        grouped.setdefault(email, []).append(order)

    count = 0
    for email, orders in grouped.items():
        latest = max((o.created_at for o in orders if o.created_at), default=_now())
        latest_order = sorted(orders, key=lambda o: o.created_at or _now())[-1]
        contact = get_or_create_contact(
            email,
            name=latest_order.customer_name or '',
            phone=latest_order.phone or '',
            source='order',
            has_order=True,
            last_order_at=latest,
        )
        if not contact:
            continue
        contact.orders_count = len(orders)
        contact.has_order = True
        contact.has_paid_order = any((o.payment_status == 'paid' or o.status == 'Zaplaceno') for o in orders)
        contact.total_spent = sum((o.total_price or 0) for o in orders if (o.payment_status == 'paid' or o.status == 'Zaplaceno'))
        contact.last_order_at = latest
        count += 1

    for partner in AffiliatePartner.query.all():
        email = normalize_email(partner.email)
        if email:
            contact = get_or_create_contact(
                email,
                name=partner.name or '',
                source='affiliate',
                is_affiliate=True,
            )
            if contact:
                contact.is_affiliate = True
                count += 1
    db.session.commit()
    return count


def contacts_query(segment='all', search='', include_deleted=False):
    q = EmailContact.query
    if not include_deleted:
        q = q.filter(EmailContact.deleted_at.is_(None))
    segment = segment or 'all'
    if segment == 'ordered':
        q = q.filter(EmailContact.has_order.is_(True))
    elif segment == 'paid':
        q = q.filter(EmailContact.has_paid_order.is_(True))
    elif segment in ('unpaid', 'pending_payment'):
        unpaid_emails = _unpaid_order_query().with_entities(func.lower(Order.email).label('email')).subquery()
        q = q.filter(func.lower(EmailContact.email).in_(db.session.query(unpaid_emails.c.email)))
    elif segment == 'cart':
        q = q.filter(EmailContact.has_cart.is_(True))
    elif segment == 'abandoned':
        q = q.filter(EmailContact.has_cart.is_(True), EmailContact.has_order.is_(False))
    elif segment == 'affiliate':
        q = q.filter(EmailContact.is_affiliate.is_(True))
    elif segment == 'unsubscribed':
        q = q.filter(or_(EmailContact.marketing_enabled.is_(False), EmailContact.unsubscribed_at.isnot(None)))
    search = (search or '').strip()
    if search:
        like = f'%{search}%'
        q = q.filter(or_(EmailContact.email.ilike(like), EmailContact.name.ilike(like), EmailContact.phone.ilike(like)))
    return q


def _ids_from_json(value):
    raw = _json_loads(value, [])
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except Exception:
            continue
    return sorted(set(ids))


def collect_contacts_for_campaign(campaign):
    filters = _json_loads(campaign.filters_json, {})
    segment = campaign.segment_type or filters.get('segment') or 'all'
    search = filters.get('search', '')
    include_unsubscribed = bool(filters.get('include_unsubscribed'))
    selected_ids = _ids_from_json(campaign.selected_contact_ids)
    excluded_ids = set(_ids_from_json(campaign.excluded_contact_ids))

    if segment == 'manual' and selected_ids:
        q = EmailContact.query.filter(EmailContact.id.in_(selected_ids))
    else:
        q = contacts_query(segment=segment, search=search)

    q = q.filter(EmailContact.deleted_at.is_(None))
    if not include_unsubscribed:
        q = q.filter(EmailContact.marketing_enabled.is_(True), EmailContact.unsubscribed_at.is_(None))

    contacts = []
    suppressed = _suppressed_emails()
    seen = set()
    for contact in q.order_by(EmailContact.email.asc()).all():
        email = normalize_email(contact.email)
        if not email or email in seen or email in suppressed or contact.id in excluded_ids:
            continue
        if not include_unsubscribed and not contact.can_receive_email:
            continue
        contacts.append(contact)
        seen.add(email)
    return contacts


def enqueue_campaign(campaign):
    if campaign.status not in ('draft', 'queued', 'paused', 'cancelled', 'done'):
        raise ValueError('Kampaň se právě odesílá. Nejdřív ji pozastav.')
    EmailCampaignRecipient.query.filter_by(campaign_id=campaign.id).delete()
    db.session.flush()
    contacts = collect_contacts_for_campaign(campaign)
    for contact in contacts:
        db.session.add(EmailCampaignRecipient(
            campaign_id=campaign.id,
            contact_id=contact.id,
            email=contact.email,
            name=contact.name or '',
            status='pending',
        ))
    campaign.status = 'queued'
    campaign.total_recipients = len(contacts)
    campaign.sent_count = 0
    campaign.failed_count = 0
    campaign.skipped_count = 0
    campaign.queued_at = _now()
    campaign.started_at = None
    campaign.completed_at = None
    campaign.last_error = ''
    db.session.commit()
    return len(contacts)


def retry_failed_recipients(campaign):
    if campaign.status in ('sending',):
        raise ValueError('Kampaň se právě odesílá. Nejdřív ji pozastav.')
    changed = 0
    for recipient in campaign.recipients:
        if recipient.status == 'failed':
            recipient.status = 'pending'
            recipient.error_message = ''
            changed += 1
    campaign.status = 'queued'
    _recount_campaign(campaign)
    db.session.commit()
    return changed


def _recount_campaign(campaign):
    counts = {'sent': 0, 'failed': 0, 'skipped': 0, 'pending': 0}
    for status, count in db.session.query(EmailCampaignRecipient.status, func.count(EmailCampaignRecipient.id)).filter_by(campaign_id=campaign.id).group_by(EmailCampaignRecipient.status).all():
        counts[status] = count
    campaign.sent_count = counts.get('sent', 0)
    campaign.failed_count = counts.get('failed', 0)
    campaign.skipped_count = counts.get('skipped', 0)
    campaign.total_recipients = sum(counts.values())
    if campaign.total_recipients and campaign.pending_count <= 0 and campaign.status not in ('cancelled', 'paused'):
        campaign.status = 'done'
        campaign.completed_at = campaign.completed_at or _now()
    return counts


def render_body(template, contact=None, campaign=None, recipient=None, order=None):
    contact = contact or getattr(recipient, 'contact', None)
    email = normalize_email(getattr(recipient, 'email', '') or getattr(contact, 'email', ''))
    if order is None:
        order = _latest_unpaid_order(email=email)
    token = getattr(contact, 'unsubscribe_token', '') if contact else ''
    unsubscribe_url = _build_public_url('emailing.unsubscribe', token=token) if token else ''

    order_number = getattr(order, 'order_number', '') or ''
    order_url = _build_public_url('shop.order_success', order_number=order_number) if order_number else _site_base_url()
    payment_link = _build_public_url('shop.order_payment', order_number=order_number) if order_number else order_url
    qr_image = getattr(order, 'qr_image', '') or ''
    qr_image_url = _build_public_url('uploaded_file', filename=qr_image) if qr_image else ''

    data = {
        # Původní proměnné
        'name': getattr(contact, 'name', '') or getattr(recipient, 'name', '') or getattr(order, 'customer_name', '') or email,
        'email': email,
        'site_name': setting('site_name', 'BotyZaHubicku.cz'),
        'unsubscribe_url': unsubscribe_url,
        'campaign_title': getattr(campaign, 'title', '') or '',

        # Aliasy, aby fungovaly i dříve vložené šablony.
        'shop_name': setting('site_name', 'BotyZaHubicku.cz'),
        'unsubscribe_link': unsubscribe_url,

        # Objednávka / platba. Bere se poslední nezaplacená objednávka daného e-mailu.
        'payment_link': payment_link,
        'order_url': order_url,
        'order_number': order_number,
        'order_total': _format_money(getattr(order, 'total_price', 0)) if order else '',
        'order_total_czk': _format_money(getattr(order, 'total_price', 0)) if order else '',
        'order_subtotal': _format_money(getattr(order, 'subtotal', 0)) if order else '',
        'variable_symbol': getattr(order, 'variable_symbol', '') or '',
        'payment_status': getattr(order, 'payment_status', '') or '',
        'payment_method': getattr(order, 'payment_method', '') or '',
        'bank_account': setting('bank_account', ''),
        'bank_iban': setting('bank_iban', ''),
        'qr_image_url': qr_image_url,
        'order_items': _order_items_text(order),
        'order_items_html': _order_items_html(order),
        'customer_name': getattr(order, 'customer_name', '') or getattr(contact, 'name', '') or '',
        'customer_phone': getattr(order, 'phone', '') or getattr(contact, 'phone', '') or '',
    }
    rendered = template or ''
    for key, value in data.items():
        rendered = rendered.replace('{{ ' + key + ' }}', str(value))
        rendered = rendered.replace('{{' + key + '}}', str(value))
    return rendered


def _html_with_footer(html, contact=None, campaign=None, recipient=None, order=None):
    body = render_body(html, contact=contact, campaign=campaign, recipient=recipient, order=order)
    contact = contact or getattr(recipient, 'contact', None)
    token = getattr(contact, 'unsubscribe_token', '') if contact else ''
    unsubscribe_url = ''
    if token:
        try:
            unsubscribe_url = _build_public_url('emailing.unsubscribe', token=token)
        except Exception:
            unsubscribe_url = ''
    if unsubscribe_url and 'unsubscribe' not in body.lower() and 'odhl' not in body.lower():
        body += f'''
        <hr style="border:0;border-top:1px solid #e5e5e5;margin:28px 0;">
        <p style="font-size:12px;color:#777;line-height:1.5;">
          E-mail posílá {setting('site_name', 'BotyZaHubicku.cz')}. Pokud už tyto zprávy nechcete dostávat,
          <a href="{unsubscribe_url}">odhlaste se zde</a>.
        </p>
        '''
    return body


def _text_with_footer(text, contact=None, campaign=None, recipient=None, order=None):
    body = render_body(text, contact=contact, campaign=campaign, recipient=recipient, order=order)
    contact = contact or getattr(recipient, 'contact', None)
    token = getattr(contact, 'unsubscribe_token', '') if contact else ''
    if token:
        try:
            unsubscribe_url = _build_public_url('emailing.unsubscribe', token=token)
        except Exception:
            unsubscribe_url = ''
        if unsubscribe_url and unsubscribe_url not in body:
            body += f"\n\nOdhlášení z e-mailů: {unsubscribe_url}"
    return body


def _attachment_payloads(campaign):
    payloads = []
    for attachment in campaign.attachments:
        if not attachment.file_path or not os.path.exists(attachment.file_path):
            continue
        mime_type = attachment.mime_type or mimetypes.guess_type(attachment.filename)[0] or 'application/octet-stream'
        maintype, subtype = (mime_type.split('/', 1) + ['octet-stream'])[:2]
        with open(attachment.file_path, 'rb') as f:
            payloads.append({
                'filename': attachment.filename,
                'content': f.read(),
                'maintype': maintype,
                'subtype': subtype,
            })
    return payloads


def _smtp_config():
    sender_raw = setting('smtp_sender', setting('contact_email', 'no-reply@botyzahubicku.cz'))
    sender_name = setting('emailing_sender_name', '').strip()
    reply_to = setting('emailing_reply_to', '').strip()
    return {
        'host': setting('smtp_host', '').strip(),
        'port': int(setting('smtp_port', '587') or 587),
        'username': setting('smtp_username', '').strip(),
        'password': setting('smtp_password', ''),
        'sender': formataddr((sender_name, sender_raw)) if sender_name else sender_raw,
        'reply_to': reply_to,
        'use_tls': setting('smtp_use_tls', '1') == '1',
    }


@contextmanager
def _smtp_or_log():
    config = _smtp_config()
    smtp = None
    if config['host'] and config['username'] and config['password']:
        smtp = smtplib.SMTP(config['host'], config['port'], timeout=30)
        try:
            if config['use_tls']:
                smtp.starttls()
            smtp.login(config['username'], config['password'])
            yield smtp, config
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
    else:
        yield None, config


def _send_message(smtp, config, to_email, subject, html_body, text_body, attachments):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = config['sender']
    msg['To'] = to_email
    if config.get('reply_to'):
        msg['Reply-To'] = config['reply_to']
    msg.set_content(text_body or re.sub(r'<[^>]+>', '', html_body or ''))
    if html_body:
        msg.add_alternative(html_body, subtype='html')
    for attachment in attachments:
        msg.add_attachment(
            attachment['content'],
            maintype=attachment['maintype'],
            subtype=attachment['subtype'],
            filename=attachment['filename'],
        )
    if smtp:
        smtp.send_message(msg)
        return 'smtp'

    outbox_dir = os.path.join(current_app.instance_path, 'outbox')
    os.makedirs(outbox_dir, exist_ok=True)
    with open(os.path.join(outbox_dir, 'emailing.log'), 'a', encoding='utf-8') as f:
        f.write('\n' + '=' * 80 + '\n')
        f.write(f'TO: {to_email}\nSUBJECT: {subject}\n\n{text_body or html_body}\n')
    return 'log'


def send_test_campaign_email(campaign, to_email):
    to_email = normalize_email(to_email)
    if not to_email:
        raise ValueError('Neplatný testovací e-mail.')
    attachments = _attachment_payloads(campaign)
    contact = EmailContact.query.filter_by(email=to_email).first()
    dummy = type('Recipient', (), {'email': to_email, 'name': getattr(contact, 'name', 'Test') or 'Test', 'contact': contact})()
    # Pro test se použije nezaplacená objednávka testovacího kontaktu; když žádná není, vezme se poslední nezaplacená objednávka jako náhled dat.
    order = _latest_unpaid_order(email=to_email) or _latest_unpaid_order()
    html = _html_with_footer(campaign.html_body, contact=contact, campaign=campaign, recipient=dummy, order=order)
    text = _text_with_footer(campaign.text_body or re.sub(r'<[^>]+>', '', campaign.html_body or ''), contact=contact, campaign=campaign, recipient=dummy, order=order)
    subject = render_body(campaign.subject, contact=contact, campaign=campaign, recipient=dummy, order=order)
    with _smtp_or_log() as (smtp, config):
        return _send_message(smtp, config, to_email, '[TEST] ' + subject, html, text, attachments)


def send_campaign_batch(app=None, campaign_id=None, limit=None):
    """Odešle malou dávku čekajících příjemců. Vhodné pro scheduler i ruční tlačítko."""
    if app is not None:
        with app.app_context():
            return send_campaign_batch(None, campaign_id=campaign_id, limit=limit)

    q = EmailCampaign.query.filter(EmailCampaign.status.in_(('queued', 'sending')))
    if campaign_id:
        q = q.filter_by(id=campaign_id)
    campaigns = q.order_by(EmailCampaign.queued_at.asc(), EmailCampaign.id.asc()).all()
    total_sent = 0
    total_failed = 0
    total_skipped = 0

    for campaign in campaigns:
        batch_size = int(limit or campaign.batch_size or setting('emailing_batch_size', '50') or 50)
        if batch_size <= 0:
            batch_size = 50
        pending = (
            EmailCampaignRecipient.query
            .filter_by(campaign_id=campaign.id, status='pending')
            .order_by(EmailCampaignRecipient.id.asc())
            .limit(batch_size)
            .all()
        )
        if not pending:
            _recount_campaign(campaign)
            db.session.commit()
            continue

        if not campaign.started_at:
            campaign.started_at = _now()
        campaign.status = 'sending'
        db.session.commit()

        attachments = _attachment_payloads(campaign)
        delay_seconds = int(campaign.delay_seconds or setting('emailing_delay_seconds', '0') or 0)

        try:
            with _smtp_or_log() as (smtp, config):
                for recipient in pending:
                    contact = recipient.contact
                    recipient.attempts = (recipient.attempts or 0) + 1
                    email = normalize_email(recipient.email)
                    if not email or EmailSuppression.query.filter_by(email=email).first() or (contact and not contact.can_receive_email):
                        recipient.status = 'skipped'
                        recipient.error_message = 'Kontakt je odhlášený, smazaný nebo na blacklistu.'
                        total_skipped += 1
                        db.session.commit()
                        continue
                    try:
                        order = _latest_unpaid_order(email=email)
                        html = _html_with_footer(campaign.html_body, contact=contact, campaign=campaign, recipient=recipient, order=order)
                        text_source = campaign.text_body or re.sub(r'<[^>]+>', '', campaign.html_body or '')
                        text = _text_with_footer(text_source, contact=contact, campaign=campaign, recipient=recipient, order=order)
                        subject = render_body(campaign.subject, contact=contact, campaign=campaign, recipient=recipient, order=order)
                        _send_message(smtp, config, email, subject, html, text, attachments)
                        recipient.status = 'sent'
                        recipient.sent_at = _now()
                        recipient.error_message = ''
                        total_sent += 1
                    except Exception as exc:
                        recipient.status = 'failed'
                        recipient.error_message = str(exc)[:1000]
                        campaign.last_error = str(exc)[:2000]
                        total_failed += 1
                    db.session.commit()
                    if delay_seconds > 0:
                        time.sleep(min(delay_seconds, 5))
        except Exception as exc:
            campaign.status = 'queued'
            campaign.last_error = str(exc)[:2000]
            db.session.commit()
            total_failed += len(pending)
            continue

        _recount_campaign(campaign)
        if campaign.pending_count > 0 and campaign.status != 'paused':
            campaign.status = 'queued'
        db.session.commit()

    return {'sent': total_sent, 'failed': total_failed, 'skipped': total_skipped}
