import os
import re
import uuid
import unicodedata
import smtplib
from email.message import EmailMessage
from functools import wraps
from PIL import Image
from flask import abort, current_app, flash, session
from flask_login import current_user
from . import db


def slugify(value):
    # SEO friendly URL bez diakritiky: "Pánské lehké tenisky" -> "panske-lehke-tenisky"
    value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
    value = value.lower().strip()
    value = re.sub(r'[^a-z0-9\s-]', '', value)
    value = re.sub(r'[\s-]+', '-', value)
    return value.strip('-') or uuid.uuid4().hex[:8]


def unique_slug(model, value, current_id=None):
    base = slugify(value)
    slug = base
    counter = 2
    while True:
        query = model.query.filter_by(slug=slug)
        if current_id:
            query = query.filter(model.id != current_id)
        if not query.first():
            return slug
        slug = f'{base}-{counter}'
        counter += 1


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def get_cart():
    return session.setdefault('cart', {})


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
        flash('Podporované jsou pouze obrázky JPG, PNG a WEBP.', 'danger')
        return None
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    image = Image.open(file_storage)
    image.thumbnail((1800, 1800))
    image.save(path, optimize=True)
    return filename


def image_url(value, static_url_builder):
    if not value:
        return static_url_builder('uploads/default-product.svg')
    if value.startswith('http://') or value.startswith('https://'):
        return value
    return static_url_builder('uploads/' + value)


def setting(key, default=''):
    from .models import SiteSetting
    row = SiteSetting.query.filter_by(key=key).first()
    return row.value if row else default


def send_email(subject, to_email, html_body, text_body='', attachments=None):
    host = setting('smtp_host', '')
    port = int(setting('smtp_port', '587') or 587)
    username = setting('smtp_username', '')
    password = setting('smtp_password', '')
    sender = setting('smtp_sender', setting('contact_email', 'no-reply@botyzahubicku.cz'))
    use_tls = setting('smtp_use_tls', '1') == '1'

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to_email
    msg.set_content(text_body or re.sub(r'<[^>]+>', '', html_body))
    msg.add_alternative(html_body, subtype='html')

    attachments = attachments or []

    for attachment in attachments:
        msg.add_attachment(
            attachment["content"],
            maintype=attachment["maintype"],
            subtype=attachment["subtype"],
            filename=attachment["filename"]
        )

    if host and username and password:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)
        return 'smtp'

    outbox_dir = os.path.join(current_app.instance_path, 'outbox')
    os.makedirs(outbox_dir, exist_ok=True)

    with open(os.path.join(outbox_dir, 'emails.log'), 'a', encoding='utf-8') as f:
        f.write('\n' + '=' * 80 + '\n')
        f.write(f'TO: {to_email}\nSUBJECT: {subject}\n\n{text_body or html_body}\n')

    return 'log'


def set_setting(key, value):
    from .models import SiteSetting
    row = SiteSetting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(SiteSetting(key=key, value=value))
