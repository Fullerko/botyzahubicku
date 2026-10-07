"""Persistent Web Push keys and resumable delivery batches."""
import base64
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import current_app
from sqlalchemy import func
from pywebpush import webpush, WebPushException
from . import db
from .mobile_models import MobilePushSubscription, MobilePushCampaign, MobilePushDelivery


def b64encode(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def b64decode(value):
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError('Neplatný klíč odběru.')
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def validated_subscription(data):
    if not isinstance(data, dict):
        raise ValueError('Neplatný odběr oznámení.')
    endpoint = data.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError('Neplatná adresa push služby.')
    url = urlsplit(endpoint)
    host = (url.hostname or '').lower()
    allowed = host in {'fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com'}
    if not allowed or url.scheme != 'https' or url.port not in (None, 443) or url.username or url.password or url.fragment:
        raise ValueError('Tato push služba není podporovaná. Použijte Chrome, Firefox nebo Safari.')
    keys = data.get('keys')
    if not isinstance(keys, dict):
        raise ValueError('Chybí klíče odběru.')
    public = b64decode(keys.get('p256dh'))
    auth = b64decode(keys.get('auth'))
    if len(public) != 65 or len(auth) != 16:
        raise ValueError('Neplatné klíče odběru.')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
    return endpoint, keys['p256dh'], keys['auth']


def initialize_push(app):
    keyfile = Path(app.config.get('MOBILE_VAPID_PATH') or os.getenv('MOBILE_VAPID_PATH') or str(Path(app.config['UPLOAD_FOLDER']).parent / 'mobile-vapid.pem'))
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    if not keyfile.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        temporary = keyfile.with_name(keyfile.name + '.' + secrets.token_hex(8))
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(pem)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, keyfile)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    key = serialization.load_pem_private_key(keyfile.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('Neplatný VAPID klíč na persistentním disku.')
    app.config['MOBILE_VAPID_PATH'] = str(keyfile)
    app.config['MOBILE_VAPID_PUBLIC'] = b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    app.config.setdefault('MOBILE_VAPID_SUBJECT', os.getenv('MOBILE_VAPID_SUBJECT', 'https://botyzahubicku.cz'))


def safe_target(value):
    value = (value or '/kalendar').strip()
    url = urlsplit(value)
    if len(value) > 500 or url.scheme or url.netloc or not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Odkaz musí vést na váš web, například /kalendar.')
    return value


def make_campaign(title, body, url, user_id, only_mine=False):
    campaign = MobilePushCampaign(title=title, body=body, url=safe_target(url), created_by=user_id)
    db.session.add(campaign)
    db.session.flush()
    query = MobilePushSubscription.query.filter_by(active=True)
    if only_mine:
        query = query.filter_by(user_id=user_id)
    for sub_id, in query.with_entities(MobilePushSubscription.id):
        db.session.add(MobilePushDelivery(campaign_id=campaign.id, subscription_id=sub_id))
    return campaign


def campaign_counts(campaign_id):
    rows = dict(db.session.query(MobilePushDelivery.status, func.count(MobilePushDelivery.id)).filter_by(campaign_id=campaign_id).group_by(MobilePushDelivery.status).all())
    counts = {key: rows.get(key, 0) for key in ('pending', 'sending', 'sent', 'failed', 'expired', 'unknown')}
    counts['total'] = sum(counts.values())
    return counts


def send_batch(campaign):
    MobilePushDelivery.query.filter_by(campaign_id=campaign.id, status='sending').filter(MobilePushDelivery.updated_at < datetime.utcnow()-timedelta(minutes=2)).update({'status':'unknown', 'error':'Výsledek po přerušení nelze potvrdit.'}, synchronize_session=False)
    db.session.commit()
    ids = [row.id for row in MobilePushDelivery.query.filter_by(campaign_id=campaign.id, status='pending').order_by(MobilePushDelivery.id).limit(3)]
    for delivery_id in ids:
        claimed = MobilePushDelivery.query.filter_by(id=delivery_id, status='pending').update({'status':'sending', 'updated_at':datetime.utcnow()}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        row = db.session.get(MobilePushDelivery, delivery_id)
        sub = db.session.get(MobilePushSubscription, row.subscription_id)
        if not sub or not sub.active:
            row.status = 'expired'
        else:
            try:
                validated_subscription({'endpoint':sub.endpoint, 'keys':{'p256dh':sub.p256dh, 'auth':sub.auth}})
                webpush(subscription_info={'endpoint':sub.endpoint, 'keys':{'p256dh':sub.p256dh, 'auth':sub.auth}},
                    data=json.dumps({'title':campaign.title, 'body':campaign.body, 'url':campaign.url, 'tag':f'bzh-campaign-{campaign.id}'}, ensure_ascii=False),
                    vapid_private_key=current_app.config['MOBILE_VAPID_PATH'],
                    vapid_claims={'sub':current_app.config['MOBILE_VAPID_SUBJECT']},
                    ttl=86400, timeout=5, headers={'Urgency':'normal'})
                row.status = 'sent'
                row.error = ''
            except WebPushException as error:
                status = error.response.status_code if error.response is not None else None
                if status in (404, 410):
                    sub.active = False
                    row.status = 'expired'
                    row.error = 'Odběr již není platný.'
                else:
                    row.status = 'failed' if status else 'unknown'
                    row.error = f'Push služba odmítla zprávu (HTTP {status}).' if status else 'Výsledek nelze potvrdit; spojení selhalo.'
            except ValueError:
                row.status = 'failed'
                row.error = 'Neplatný odběr nebo konfigurace.'
            except Exception:
                row.status = 'unknown'
                row.error = 'Výsledek nelze potvrdit; spojení selhalo.'
        row.updated_at = datetime.utcnow()
        db.session.commit()
    return campaign_counts(campaign.id)
