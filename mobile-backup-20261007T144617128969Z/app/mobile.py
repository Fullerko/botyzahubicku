"""Calendar, mobile navigation and opt-in Web Push on the existing Flask DB."""
import calendar
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo
from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_login import current_user
from sqlalchemy.exc import IntegrityError
from . import db
from .utils import admin_required
from .mobile_models import MobileEvent, MobilePushSubscription, MobilePushCampaign, MobilePushDelivery
from .mobile_push import initialize_push, validated_subscription, make_campaign, campaign_counts, send_batch, safe_target

mobile_bp = Blueprint('mobile', __name__)
ASSETS = Path(__file__).parent / 'static' / 'pwa'
MONTHS = ['', 'leden', 'únor', 'březen', 'duben', 'květen', 'červen', 'červenec', 'srpen', 'září', 'říjen', 'listopad', 'prosinec']


def csrf_token():
    if 'mobile_csrf' not in session:
        session['mobile_csrf'] = secrets.token_urlsafe(32)
    return session['mobile_csrf']


def owner_hash():
    if 'mobile_device' not in session:
        session['mobile_device'] = secrets.token_urlsafe(32)
    return hashlib.sha256(session['mobile_device'].encode()).hexdigest()


def init_mobile(app):
    initialize_push(app)
    app.register_blueprint(mobile_bp)
    # Add only new tables to the SAME database; no existing table/row is replaced.
    with app.app_context():
        with db.engine.begin() as connection:
            if db.engine.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            for model in (MobileEvent, MobilePushSubscription, MobilePushCampaign, MobilePushDelivery):
                model.__table__.create(bind=connection, checkfirst=True)


@mobile_bp.before_request
def protect_mobile_writes():
    if request.method != 'POST':
        return
    if request.content_length is not None and request.content_length > 16384:
        abort(413)
    if len(request.get_data(cache=True)) > 16384:
        abort(413)
    origin = request.headers.get('Origin')
    if origin and urlsplit(origin).netloc != request.host:
        abort(403)
    expected = session.get('mobile_csrf', '')
    received = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
    if not expected or not isinstance(received, str) or not hmac.compare_digest(expected, received):
        abort(403, description='Obnovte stránku a zkuste akci znovu.')


@mobile_bp.after_request
def no_private_cache(response):
    if request.endpoint != 'mobile.worker':
        response.headers['Cache-Control'] = 'no-store'
    return response


@mobile_bp.app_context_processor
def mobile_context():
    return {'mobile_csrf': csrf_token, 'mobile_nonce': lambda: secrets.token_hex(24)}


@mobile_bp.get('/app.webmanifest')
def manifest():
    data = json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))
    return Response(json.dumps(data, ensure_ascii=False), mimetype='application/manifest+json')


@mobile_bp.get('/service-worker.js')
def worker():
    response = send_from_directory(ASSETS, 'service-worker.js', mimetype='application/javascript')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@mobile_bp.get('/aplikace')
def install():
    return render_template('pwa/install.html')


@mobile_bp.get('/aplikace/offline')
def offline():
    return send_from_directory(ASSETS, 'offline.html', mimetype='text/html')


@mobile_bp.get('/kalendar')
def events():
    now = datetime.now(ZoneInfo('Europe/Prague')).replace(tzinfo=None)
    try:
        month = datetime.strptime(request.args.get('mesic', now.strftime('%Y-%m')), '%Y-%m').date().replace(day=1)
        if not 2000 <= month.year <= 2099:
            raise ValueError()
    except ValueError:
        abort(400, description='Neplatný měsíc kalendáře.')
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous = (month - timedelta(days=1)).replace(day=1)
    rows = MobileEvent.query.filter_by(published=True).filter(MobileEvent.starts_at < datetime.combine(next_month, time.min), MobileEvent.ends_at >= datetime.combine(month, time.min)).order_by(MobileEvent.starts_at).all()
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month)
    day_events = {day: [event for event in rows if event.starts_at.date() <= day <= event.ends_at.date()] for week in weeks for day in week}
    upcoming = MobileEvent.query.filter_by(published=True, cancelled=False).filter(MobileEvent.ends_at >= now).order_by(MobileEvent.starts_at).limit(8).all()
    return render_template('pwa/calendar.html', events=rows, upcoming=upcoming, weeks=weeks, day_events=day_events,
        month=month, month_label=f'{MONTHS[month.month].capitalize()} {month.year}', previous=previous, next_month=next_month, today=now.date(), now=now,
        maps_url=lambda event: 'https://www.google.com/maps/search/?' + urlencode({'api':1, 'query':event.address + ', ' + event.location}))


@mobile_bp.get('/admin/kalendar')
@admin_required
def admin_events():
    return render_template('pwa/admin_calendar.html', events=MobileEvent.query.order_by(MobileEvent.starts_at.desc()).all())


def event_form_values():
    values = {}
    for field, limit in [('title',160), ('location',200), ('address',250), ('description',2000)]:
        value = request.form.get(field, '').strip()
        if len(value) > limit or (field != 'description' and not value):
            raise ValueError('Vyplňte název, místo a adresu; dodržte maximální délku polí.')
        values[field] = value
    try:
        start = datetime.fromisoformat(request.form.get('starts_at', ''))
        end = datetime.fromisoformat(request.form.get('ends_at', ''))
        if start.tzinfo or end.tzinfo or end < start or not 2000 <= start.year <= end.year <= 2099:
            raise ValueError()
    except ValueError:
        raise ValueError('Zadejte platné datum a čas; konec nesmí být před začátkem.')
    values.update(starts_at=start, ends_at=end, published=request.form.get('published') == 'on', cancelled=request.form.get('cancelled') == 'on')
    return values


@mobile_bp.route('/admin/kalendar/nova', methods=['GET','POST'])
@mobile_bp.route('/admin/kalendar/<int:event_id>/upravit', methods=['GET','POST'])
@admin_required
def edit_event(event_id=None):
    event = db.get_or_404(MobileEvent, event_id) if event_id else None
    if request.method == 'POST':
        try:
            values = event_form_values()
        except ValueError as error:
            return render_template('pwa/event_form.html', event=event, values=request.form, error=str(error)), 400
        if event is None:
            event = MobileEvent()
            db.session.add(event)
        for key, value in values.items():
            setattr(event,key,value)
        db.session.flush()
        if request.form.get('notify') == 'on' and event.published:
            title = 'Změna akce' if event.cancelled else 'Kde nás najdete'
            body = f'{event.title} – {event.location}, {event.starts_at:%d.%m. %H:%M}'
            if event.cancelled:
                body = f'Zrušeno: {event.title} – {event.location}'
            campaign = make_campaign(title, body[:240], f'/kalendar?mesic={event.starts_at:%Y-%m}#akce-{event.id}', current_user.id)
            db.session.commit()
            flash('Akce uložena. Oznámení je připravené; spusťte odesílání níže.', 'success')
            return redirect(url_for('mobile.campaign', campaign_id=campaign.id))
        db.session.commit()
        flash('Akce byla uložena.', 'success')
        return redirect(url_for('mobile.admin_events'))
    return render_template('pwa/event_form.html', event=event, values={}, error=None)


@mobile_bp.post('/admin/kalendar/<int:event_id>/smazat')
@admin_required
def delete_event(event_id):
    db.session.delete(db.get_or_404(MobileEvent, event_id))
    db.session.commit()
    flash('Akce byla smazána.', 'success')
    return redirect(url_for('mobile.admin_events'))


@mobile_bp.get('/api/mobile/push-config')
def push_config():
    return jsonify(publicKey=current_app.config['MOBILE_VAPID_PUBLIC'], csrf=csrf_token(), optedOut=session.get('mobile_push_optout',False), active=MobilePushSubscription.query.filter_by(owner_hash=owner_hash(), active=True).count() > 0)


@mobile_bp.post('/api/mobile/push-subscribe')
def subscribe():
    try:
        endpoint, public, auth = validated_subscription(request.get_json(silent=True))
    except (ValueError, TypeError):
        return jsonify(error='Neplatný odběr. Použijte aktuální Chrome, Firefox nebo Safari.'), 400
    digest = hashlib.sha256(endpoint.encode()).hexdigest()
    sub = MobilePushSubscription.query.filter_by(endpoint_hash=digest).first()
    if sub and (not hmac.compare_digest(sub.p256dh, public) or not hmac.compare_digest(sub.auth, auth)):
        return jsonify(error='Odběr má jiné klíče. Obnovte oprávnění oznámení.'), 409
    if sub is None:
        sub = MobilePushSubscription(endpoint_hash=digest, endpoint=endpoint, p256dh=public, auth=auth)
        db.session.add(sub)
    session['mobile_push_optout'] = False
    sub.owner_hash = owner_hash()
    sub.active = True
    sub.user_id = current_user.id if current_user.is_authenticated else None
    sub.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error='Odběr se právě ukládá. Zkuste znovu.'), 409
    return jsonify(ok=True)


@mobile_bp.post('/api/mobile/push-unsubscribe')
def unsubscribe():
    session['mobile_push_optout'] = True
    # Remove ONLY subscriptions owned by this browser's unguessable session token.
    MobilePushSubscription.query.filter_by(owner_hash=owner_hash()).update({'active':False, 'updated_at':datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return jsonify(ok=True)


@mobile_bp.route('/admin/oznameni', methods=['GET','POST'])
@admin_required
def admin_push():
    error = None
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        body = request.form.get('body','').strip()
        nonce = request.form.get('request_key','')
        try:
            if not title or not body or len(title)>80 or len(body)>240 or len(nonce)!=48 or any(ch not in '0123456789abcdef' for ch in nonce):
                raise ValueError('Vyplňte nadpis (max. 80 znaků) a zprávu (max. 240 znaků).')
            target = safe_target(request.form.get('url'))
            existing = MobilePushCampaign.query.filter_by(request_key=nonce, created_by=current_user.id).first()
            if existing:
                return redirect(url_for('mobile.campaign', campaign_id=existing.id))
            campaign = make_campaign(title, body, target, current_user.id, request.form.get('audience') == 'mine')
            campaign.request_key = nonce
            db.session.commit()
            return redirect(url_for('mobile.campaign', campaign_id=campaign.id))
        except ValueError as problem:
            error = str(problem)
        except IntegrityError:
            db.session.rollback()
            existing = MobilePushCampaign.query.filter_by(request_key=nonce, created_by=current_user.id).first()
            if existing:
                return redirect(url_for('mobile.campaign', campaign_id=existing.id))
            error = 'Požadavek už byl zpracován. Obnovte stránku.'
    return render_template('pwa/admin_push.html', error=error, values=request.form, subscribers=MobilePushSubscription.query.filter_by(active=True).count(), mine=MobilePushSubscription.query.filter_by(active=True,user_id=current_user.id).count(), campaigns=MobilePushCampaign.query.order_by(MobilePushCampaign.id.desc()).limit(30).all())


@mobile_bp.get('/admin/oznameni/<int:campaign_id>')
@admin_required
def campaign(campaign_id):
    item = db.get_or_404(MobilePushCampaign, campaign_id)
    return render_template('pwa/campaign.html', campaign=item, counts=campaign_counts(item.id))


@mobile_bp.post('/admin/oznameni/<int:campaign_id>/davka')
@admin_required
def campaign_batch(campaign_id):
    return jsonify(send_batch(db.get_or_404(MobilePushCampaign, campaign_id)))


@mobile_bp.post('/admin/oznameni/<int:campaign_id>/opakovat')
@admin_required
def campaign_retry(campaign_id):
    item = db.get_or_404(MobilePushCampaign, campaign_id)
    MobilePushDelivery.query.filter_by(campaign_id=item.id, status='failed').update({'status':'pending', 'error':'', 'updated_at':datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for('mobile.campaign', campaign_id=item.id))
