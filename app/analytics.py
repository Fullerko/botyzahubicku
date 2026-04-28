import hashlib
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

from flask import Blueprint, current_app, make_response, render_template, request
from sqlalchemy import func

from . import db
from .models import AffiliatePartner, Coupon, Order, Product
from .utils import admin_required

analytics_bp = Blueprint('analytics', __name__)

BOT_PATTERNS = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|telegrambot|whatsapp|preview|monitor|uptime|render",
    re.I,
)

SOURCE_COOKIE = 'bzh_source'
MEDIUM_COOKIE = 'bzh_medium'
CAMPAIGN_COOKIE = 'bzh_campaign'
AFF_COOKIE = 'bzh_affiliate_code'
SESSION_COOKIE = 'bzh_sid'


class AnalyticsVisit(db.Model):
    __tablename__ = 'analytics_visits'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True, nullable=False)
    visit_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), index=True, nullable=False)

    session_id = db.Column(db.String(64), index=True)
    visitor_hash = db.Column(db.String(64), index=True)
    ip_hash = db.Column(db.String(64), index=True)

    path = db.Column(db.String(500), index=True)
    full_path = db.Column(db.String(1000))
    endpoint = db.Column(db.String(160), index=True)
    method = db.Column(db.String(10), default='GET')
    referrer = db.Column(db.String(1000))

    source = db.Column(db.String(120), index=True)
    medium = db.Column(db.String(120), index=True)
    campaign = db.Column(db.String(200), index=True)
    term = db.Column(db.String(200))
    content = db.Column(db.String(200))

    affiliate_code = db.Column(db.String(120), index=True)
    affiliate_partner_id = db.Column(db.Integer, db.ForeignKey('affiliate_partners.id'), nullable=True, index=True)

    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True, index=True)
    user_agent = db.Column(db.String(500))
    device = db.Column(db.String(40), index=True)
    browser = db.Column(db.String(60), index=True)
    is_bot = db.Column(db.Boolean, default=False, index=True)


class AnalyticsEvent(db.Model):
    __tablename__ = 'analytics_events'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True, nullable=False)
    visit_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), index=True, nullable=False)
    session_id = db.Column(db.String(64), index=True)
    event_name = db.Column(db.String(120), index=True)
    path = db.Column(db.String(500), index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True, index=True)
    value = db.Column(db.Float, default=0)
    source = db.Column(db.String(120), index=True)
    medium = db.Column(db.String(120), index=True)
    campaign = db.Column(db.String(200), index=True)
    affiliate_code = db.Column(db.String(120), index=True)
    affiliate_partner_id = db.Column(db.Integer, db.ForeignKey('affiliate_partners.id'), nullable=True, index=True)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_value(value):
    if not value:
        return None
    secret = current_app.config.get('SECRET_KEY', 'bzh')
    return hashlib.sha256(f'{secret}:{value}'.encode('utf-8', 'ignore')).hexdigest()


def _client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or ''


def _device_from_ua(ua):
    ua_l = (ua or '').lower()
    if 'tablet' in ua_l or 'ipad' in ua_l:
        return 'tablet'
    if 'mobile' in ua_l or 'android' in ua_l or 'iphone' in ua_l:
        return 'mobile'
    return 'desktop'


def _browser_from_ua(ua):
    ua_l = (ua or '').lower()
    if 'edg/' in ua_l:
        return 'Edge'
    if 'chrome/' in ua_l and 'chromium' not in ua_l:
        return 'Chrome'
    if 'firefox/' in ua_l:
        return 'Firefox'
    if 'safari/' in ua_l and 'chrome/' not in ua_l:
        return 'Safari'
    return 'Other'


def _source_from_referrer(referrer):
    if not referrer:
        return 'direct', 'none'
    host = urlparse(referrer).netloc.lower()
    if not host:
        return 'direct', 'none'
    if 'instagram' in host or 'l.instagram' in host:
        return 'instagram', 'social'
    if 'facebook' in host or 'fb.' in host:
        return 'facebook', 'social'
    if 'tiktok' in host:
        return 'tiktok', 'social'
    if 'google' in host:
        return 'google', 'organic'
    if 'seznam' in host:
        return 'seznam', 'organic'
    if 'bing' in host:
        return 'bing', 'organic'
    return host.replace('www.', ''), 'referral'


def _affiliate_from_request():
    code = (
        request.args.get('aff')
        or request.args.get('affiliate')
        or request.args.get('ref')
        or request.args.get('partner')
        or request.args.get('coupon')
        or request.args.get('code')
        or request.cookies.get(AFF_COOKIE)
        or ''
    ).strip()
    if not code:
        return None, None
    coupon = Coupon.query.filter(func.lower(Coupon.code) == code.lower()).first()
    if coupon and getattr(coupon, 'affiliate_partner_id', None):
        return code, coupon.affiliate_partner_id
    partner = AffiliatePartner.query.filter(func.lower(AffiliatePartner.name) == code.lower()).first()
    if partner:
        return code, partner.id
    return code, None


def _product_id_from_path():
    # Produkt detail na webu je typicky /produkt/<slug>. Pokud slug sedí, uložíme product_id.
    if not request.path.startswith('/produkt/'):
        return None
    slug = request.path.split('/produkt/', 1)[1].strip('/').split('/')[0]
    if not slug:
        return None
    product = Product.query.filter_by(slug=slug).first()
    return product.id if product else None


def _marketing_data():
    ref_source, ref_medium = _source_from_referrer(request.referrer)
    source = (request.args.get('utm_source') or request.cookies.get(SOURCE_COOKIE) or ref_source or 'direct').strip().lower()
    medium = (request.args.get('utm_medium') or request.cookies.get(MEDIUM_COOKIE) or ref_medium or 'none').strip().lower()
    campaign = (request.args.get('utm_campaign') or request.cookies.get(CAMPAIGN_COOKIE) or '').strip()
    term = (request.args.get('utm_term') or '').strip()
    content = (request.args.get('utm_content') or '').strip()
    return source, medium, campaign, term, content


def _should_track():
    if request.method != 'GET':
        return False
    path = request.path or ''
    if path.startswith(('/static/', '/uploads/', '/favicon', '/robots.txt', '/sitemap.xml')):
        return False
    if path.startswith('/admin/statistiky'):
        return False
    return True


@analytics_bp.before_app_request
def track_pageview():
    if not _should_track():
        return

    ua = request.headers.get('User-Agent', '')[:500]
    is_bot = bool(BOT_PATTERNS.search(ua))
    session_id = request.cookies.get(SESSION_COOKIE) or uuid4().hex
    ip = _client_ip()
    visitor_hash = _hash_value(f'{ip}:{ua}')
    source, medium, campaign, term, content = _marketing_data()
    affiliate_code, affiliate_partner_id = _affiliate_from_request()

    visit = AnalyticsVisit(
        created_at=_utcnow(),
        visit_date=_utcnow().date(),
        session_id=session_id,
        visitor_hash=visitor_hash,
        ip_hash=_hash_value(ip),
        path=request.path[:500],
        full_path=request.full_path[:1000],
        endpoint=(request.endpoint or '')[:160],
        method=request.method,
        referrer=(request.referrer or '')[:1000],
        source=source[:120],
        medium=medium[:120],
        campaign=campaign[:200],
        term=term[:200],
        content=content[:200],
        affiliate_code=(affiliate_code or '')[:120] or None,
        affiliate_partner_id=affiliate_partner_id,
        product_id=_product_id_from_path(),
        user_agent=ua,
        device=_device_from_ua(ua),
        browser=_browser_from_ua(ua),
        is_bot=is_bot,
    )
    db.session.add(visit)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


@analytics_bp.after_app_request
def set_tracking_cookies(response):
    if not _should_track():
        return response
    max_age = 60 * 60 * 24 * 90
    session_id = request.cookies.get(SESSION_COOKIE) or uuid4().hex
    response.set_cookie(SESSION_COOKIE, session_id, max_age=max_age, httponly=True, samesite='Lax')

    if request.args.get('utm_source'):
        response.set_cookie(SOURCE_COOKIE, request.args.get('utm_source', '').strip().lower(), max_age=max_age, httponly=True, samesite='Lax')
    if request.args.get('utm_medium'):
        response.set_cookie(MEDIUM_COOKIE, request.args.get('utm_medium', '').strip().lower(), max_age=max_age, httponly=True, samesite='Lax')
    if request.args.get('utm_campaign'):
        response.set_cookie(CAMPAIGN_COOKIE, request.args.get('utm_campaign', '').strip(), max_age=max_age, httponly=True, samesite='Lax')

    affiliate_code = (
        request.args.get('aff') or request.args.get('affiliate') or request.args.get('ref')
        or request.args.get('partner') or request.args.get('coupon') or request.args.get('code')
    )
    if affiliate_code:
        response.set_cookie(AFF_COOKIE, affiliate_code.strip(), max_age=max_age, httponly=True, samesite='Lax')
    return response


def _period_start(period):
    now = _utcnow()
    today = datetime(now.year, now.month, now.day)
    if period == 'today':
        return today
    if period == 'week':
        return today - timedelta(days=today.weekday())
    if period == 'month':
        return datetime(now.year, now.month, 1)
    if period == '7d':
        return now - timedelta(days=7)
    if period == '30d':
        return now - timedelta(days=30)
    return datetime(1970, 1, 1)


def _count_visits(start):
    base = AnalyticsVisit.query.filter(AnalyticsVisit.created_at >= start, AnalyticsVisit.is_bot == False)
    return {
        'pageviews': base.count(),
        'visitors': base.with_entities(AnalyticsVisit.visitor_hash).distinct().count(),
        'sessions': base.with_entities(AnalyticsVisit.session_id).distinct().count(),
        'affiliate_clicks': base.filter(AnalyticsVisit.affiliate_code.isnot(None)).count(),
        'ig_visits': base.filter(AnalyticsVisit.source.in_(['instagram', 'ig'])).count(),
        'google_visits': base.filter(AnalyticsVisit.source == 'google').count(),
    }


def _rows(query, limit=10):
    return query.limit(limit).all()


def _order_stats(start):
    paid = Order.query.filter(Order.created_at >= start, Order.payment_status == 'paid')
    total_orders = paid.count()
    revenue = sum((o.total_price or 0) for o in paid.all())

    affiliate_orders = 0
    affiliate_revenue = 0
    if hasattr(Order, 'affiliate_partner_id'):
        q = paid.filter(Order.affiliate_partner_id.isnot(None))
        affiliate_orders = q.count()
        affiliate_revenue = sum((o.total_price or 0) for o in q.all())
    elif hasattr(Order, 'affiliate_commission_amount'):
        q = paid.filter(Order.affiliate_commission_amount > 0)
        affiliate_orders = q.count()
        affiliate_revenue = sum((o.total_price or 0) for o in q.all())

    return {'orders': total_orders, 'revenue': revenue, 'affiliate_orders': affiliate_orders, 'affiliate_revenue': affiliate_revenue}


@analytics_bp.route('/admin/statistiky')
@admin_required
def admin_stats():
    period = request.args.get('period', '30d')
    start = _period_start(period)
    now = _utcnow()

    cards = {
        'today': _count_visits(_period_start('today')),
        'week': _count_visits(_period_start('week')),
        'month': _count_visits(_period_start('month')),
        'total': _count_visits(_period_start('all')),
    }
    order_cards = {
        'today': _order_stats(_period_start('today')),
        'week': _order_stats(_period_start('week')),
        'month': _order_stats(_period_start('month')),
        'total': _order_stats(_period_start('all')),
    }

    base = AnalyticsVisit.query.filter(AnalyticsVisit.created_at >= start, AnalyticsVisit.is_bot == False)

    daily = base.with_entities(
        AnalyticsVisit.visit_date,
        func.count(AnalyticsVisit.id),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)),
        func.count(func.distinct(AnalyticsVisit.session_id)),
    ).group_by(AnalyticsVisit.visit_date).order_by(AnalyticsVisit.visit_date.asc()).all()

    top_sources = _rows(base.with_entities(
        AnalyticsVisit.source, AnalyticsVisit.medium, func.count(AnalyticsVisit.id).label('cnt')
    ).group_by(AnalyticsVisit.source, AnalyticsVisit.medium).order_by(func.count(AnalyticsVisit.id).desc()), 15)

    top_pages = _rows(base.with_entities(
        AnalyticsVisit.path, func.count(AnalyticsVisit.id).label('cnt'), func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('vis')
    ).group_by(AnalyticsVisit.path).order_by(func.count(AnalyticsVisit.id).desc()), 15)

    top_products = _rows(base.filter(AnalyticsVisit.product_id.isnot(None)).join(Product, Product.id == AnalyticsVisit.product_id).with_entities(
        Product.name, Product.slug, func.count(AnalyticsVisit.id).label('cnt')
    ).group_by(Product.id).order_by(func.count(AnalyticsVisit.id).desc()), 15)

    affiliate_rows = _rows(base.filter(AnalyticsVisit.affiliate_code.isnot(None)).outerjoin(
        AffiliatePartner, AffiliatePartner.id == AnalyticsVisit.affiliate_partner_id
    ).with_entities(
        AnalyticsVisit.affiliate_code,
        AffiliatePartner.name,
        func.count(AnalyticsVisit.id).label('clicks'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('visitors'),
    ).group_by(AnalyticsVisit.affiliate_code, AffiliatePartner.name).order_by(func.count(AnalyticsVisit.id).desc()), 30)

    campaign_rows = _rows(base.filter(AnalyticsVisit.campaign != '').with_entities(
        AnalyticsVisit.source, AnalyticsVisit.medium, AnalyticsVisit.campaign, func.count(AnalyticsVisit.id).label('cnt')
    ).group_by(AnalyticsVisit.source, AnalyticsVisit.medium, AnalyticsVisit.campaign).order_by(func.count(AnalyticsVisit.id).desc()), 30)

    device_rows = _rows(base.with_entities(AnalyticsVisit.device, func.count(AnalyticsVisit.id)).group_by(AnalyticsVisit.device).order_by(func.count(AnalyticsVisit.id).desc()), 10)
    browser_rows = _rows(base.with_entities(AnalyticsVisit.browser, func.count(AnalyticsVisit.id)).group_by(AnalyticsVisit.browser).order_by(func.count(AnalyticsVisit.id).desc()), 10)

    return render_template(
        'admin/statistiky.html',
        period=period,
        start=start,
        now=now,
        cards=cards,
        order_cards=order_cards,
        daily=daily,
        top_sources=top_sources,
        top_pages=top_pages,
        top_products=top_products,
        affiliate_rows=affiliate_rows,
        campaign_rows=campaign_rows,
        device_rows=device_rows,
        browser_rows=browser_rows,
    )
