import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

from flask import Blueprint, Response, current_app, jsonify, render_template, request
from sqlalchemy import case, desc, func

from . import db
from .models import AffiliatePartner, Coupon, Order, OrderItem, Product
from .utils import admin_required

analytics_bp = Blueprint('analytics', __name__)

BOT_PATTERNS = re.compile(
    r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|telegrambot|whatsapp|preview|monitor|uptime|render|"
    r"headless|lighthouse|pagespeed|python|curl|wget|httpclient|httpx|scrapy|semrush|ahrefs|mj12|dotbot|petalbot|"
    r"yandex|baidu|bytespider|claudebot|gptbot|ccbot|perplexitybot|uptimerobot",
    re.I,
)

SOURCE_COOKIE = 'bzh_source'
MEDIUM_COOKIE = 'bzh_medium'
CAMPAIGN_COOKIE = 'bzh_campaign'
AFF_COOKIE = 'bzh_affiliate_code'
SESSION_COOKIE = 'bzh_sid'
VISITOR_COOKIE = 'bzh_vid'


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
    affiliate_partner_id = db.Column(db.Integer, nullable=True, index=True)

    product_id = db.Column(db.Integer, nullable=True, index=True)
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
    product_id = db.Column(db.Integer, nullable=True, index=True)
    value = db.Column(db.Float, default=0)
    source = db.Column(db.String(120), index=True)
    medium = db.Column(db.String(120), index=True)
    campaign = db.Column(db.String(200), index=True)
    affiliate_code = db.Column(db.String(120), index=True)
    affiliate_partner_id = db.Column(db.Integer, nullable=True, index=True)


class AnalyticsHeatmapClick(db.Model):
    __tablename__ = 'analytics_heatmap_clicks'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True, nullable=False)
    visit_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), index=True, nullable=False)
    session_id = db.Column(db.String(64), index=True)
    visitor_hash = db.Column(db.String(64), index=True)
    path = db.Column(db.String(500), index=True)
    x = db.Column(db.Integer, default=0)
    y = db.Column(db.Integer, default=0)
    viewport_w = db.Column(db.Integer, default=0)
    viewport_h = db.Column(db.Integer, default=0)
    page_w = db.Column(db.Integer, default=0)
    page_h = db.Column(db.Integer, default=0)
    selector = db.Column(db.String(300), default='')
    text = db.Column(db.String(200), default='')


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
    if 'opr/' in ua_l or 'opera' in ua_l:
        return 'Opera'
    if 'chrome/' in ua_l and 'chromium' not in ua_l:
        return 'Chrome'
    if 'firefox/' in ua_l:
        return 'Firefox'
    if 'safari/' in ua_l and 'chrome/' not in ua_l:
        return 'Safari'
    return 'Other'


def _is_bot_ua(ua):
    ua = ua or ''
    if not ua.strip():
        return True
    return bool(BOT_PATTERNS.search(ua))


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
    if 'youtube' in host:
        return 'youtube', 'social'
    if 'google' in host:
        return 'google', 'organic'
    if 'seznam' in host:
        return 'seznam', 'organic'
    if 'bing' in host:
        return 'bing', 'organic'
    if 'duckduckgo' in host:
        return 'duckduckgo', 'organic'
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


def _product_id_from_path(path=None):
    path = path or request.path
    if not path.startswith('/produkt/'):
        return None
    slug = path.split('/produkt/', 1)[1].strip('/').split('/')[0]
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
    if path.startswith(('/admin', '/api/')):
        return False
    return True


@analytics_bp.before_app_request
def track_pageview():
    if not _should_track():
        return

    ua = request.headers.get('User-Agent', '')[:500]
    is_bot = _is_bot_ua(ua)
    session_id = request.cookies.get(SESSION_COOKIE) or uuid4().hex
    visitor_cookie = request.cookies.get(VISITOR_COOKIE) or uuid4().hex
    ip = _client_ip()
    visitor_hash = _hash_value(f'{visitor_cookie}:{ip}:{ua}')
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
    max_age = 60 * 60 * 24 * 180
    session_id = request.cookies.get(SESSION_COOKIE) or uuid4().hex
    visitor_id = request.cookies.get(VISITOR_COOKIE) or uuid4().hex
    response.set_cookie(SESSION_COOKIE, session_id, max_age=60 * 30, httponly=True, samesite='Lax')
    response.set_cookie(VISITOR_COOKIE, visitor_id, max_age=max_age, httponly=True, samesite='Lax')

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
    if period == 'yesterday':
        return today - timedelta(days=1)
    if period == 'week':
        return today - timedelta(days=today.weekday())
    if period == 'month':
        return datetime(now.year, now.month, 1)
    if period == '7d':
        return now - timedelta(days=7)
    if period == '14d':
        return now - timedelta(days=14)
    if period == '30d':
        return now - timedelta(days=30)
    if period == '90d':
        return now - timedelta(days=90)
    return datetime(1970, 1, 1)


def _real_visit_base(start):
    return AnalyticsVisit.query.filter(
        AnalyticsVisit.created_at >= start,
        AnalyticsVisit.is_bot.is_(False),
        AnalyticsVisit.visitor_hash.isnot(None),
    )


def _event_base(start):
    return AnalyticsEvent.query.filter(AnalyticsEvent.created_at >= start)


def _heatmap_base(start):
    return AnalyticsHeatmapClick.query.filter(AnalyticsHeatmapClick.created_at >= start)


def _orders_base(start, paid_only=False):
    q = Order.query.filter(Order.created_at >= start)
    if paid_only:
        q = q.filter(Order.payment_status == 'paid')
    return q


def _count_visits(start):
    base = _real_visit_base(start)
    organic = base.filter(AnalyticsVisit.medium == 'organic')
    return {
        'pageviews': base.count(),
        'visitors': base.with_entities(AnalyticsVisit.visitor_hash).distinct().count(),
        'sessions': base.with_entities(AnalyticsVisit.session_id).distinct().count(),
        'organic_visitors': organic.with_entities(AnalyticsVisit.visitor_hash).distinct().count(),
        'organic_sessions': organic.with_entities(AnalyticsVisit.session_id).distinct().count(),
        'affiliate_clicks': base.filter(AnalyticsVisit.affiliate_code.isnot(None)).count(),
        'product_views': base.filter(AnalyticsVisit.product_id.isnot(None)).count(),
        'cart_views': base.filter(AnalyticsVisit.path.like('/kosik%')).count() + base.filter(AnalyticsVisit.path.like('/cart%')).count(),
        'checkout_views': base.filter(AnalyticsVisit.path.like('/checkout%')).count(),
    }


def _rows(query, limit=10):
    return query.limit(limit).all()


def _safe_div(a, b):
    return round((float(a) / float(b)) if b else 0, 4)


def _money(value):
    return float(value or 0)


def _order_stats(start):
    all_orders = _orders_base(start, paid_only=False).all()
    paid_orders = [o for o in all_orders if (o.payment_status or '').lower() == 'paid']
    total_revenue = sum(_money(o.total_price) for o in all_orders)
    paid_revenue = sum(_money(o.total_price) for o in paid_orders)
    average_order = _safe_div(total_revenue, len(all_orders)) if all_orders else 0

    affiliate_orders = 0
    affiliate_revenue = 0
    if hasattr(Order, 'affiliate_partner_id'):
        affiliate_orders_q = _orders_base(start).filter(Order.affiliate_partner_id.isnot(None))
        affiliate_orders = affiliate_orders_q.count()
        affiliate_revenue = sum(_money(o.total_price) for o in affiliate_orders_q.all())
    elif hasattr(Order, 'affiliate_commission_amount'):
        affiliate_orders_q = _orders_base(start).filter(Order.affiliate_commission_amount > 0)
        affiliate_orders = affiliate_orders_q.count()
        affiliate_revenue = sum(_money(o.total_price) for o in affiliate_orders_q.all())

    return {
        'orders': len(all_orders),
        'paid_orders': len(paid_orders),
        'revenue': total_revenue,
        'paid_revenue': paid_revenue,
        'average_order': average_order,
        'affiliate_orders': affiliate_orders,
        'affiliate_revenue': affiliate_revenue,
    }


def _daily_series(start, end):
    days = []
    cursor = datetime(start.year, start.month, start.day)
    end_day = datetime(end.year, end.month, end.day)
    if cursor < datetime(2020, 1, 1):
        cursor = end_day - timedelta(days=29)
    while cursor <= end_day:
        days.append(cursor.date())
        cursor += timedelta(days=1)

    visit_rows = _real_visit_base(datetime.combine(days[0], datetime.min.time())).with_entities(
        AnalyticsVisit.visit_date,
        func.count(AnalyticsVisit.id).label('pageviews'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
        func.count(func.distinct(AnalyticsVisit.session_id)).label('sessions'),
        func.sum(case((AnalyticsVisit.medium == 'organic', 1), else_=0)).label('organic_pageviews'),
        func.count(func.distinct(case((AnalyticsVisit.medium == 'organic', AnalyticsVisit.visitor_hash)))).label('organic_users'),
        func.sum(case((AnalyticsVisit.product_id.isnot(None), 1), else_=0)).label('product_views'),
    ).group_by(AnalyticsVisit.visit_date).all()

    order_rows = Order.query.filter(Order.created_at >= datetime.combine(days[0], datetime.min.time())).with_entities(
        func.date(Order.created_at).label('date_key'),
        func.count(Order.id).label('orders'),
        func.coalesce(func.sum(Order.total_price), 0).label('revenue'),
    ).group_by(func.date(Order.created_at)).all()

    visits_by_day = {r[0]: r for r in visit_rows}
    orders_by_day = {datetime.strptime(str(r[0]), '%Y-%m-%d').date(): r for r in order_rows if r[0]}

    series = []
    for day in days:
        v = visits_by_day.get(day)
        o = orders_by_day.get(day)
        users = int(v.users or 0) if v else 0
        organic_users = int(v.organic_users or 0) if v else 0
        pageviews = int(v.pageviews or 0) if v else 0
        sessions = int(v.sessions or 0) if v else 0
        product_views = int(v.product_views or 0) if v else 0
        orders = int(o.orders or 0) if o else 0
        revenue = float(o.revenue or 0) if o else 0
        series.append({
            'date': day.strftime('%d.%m.'),
            'date_iso': day.isoformat(),
            'users': users,
            'organic': organic_users,
            'pageviews': pageviews,
            'sessions': sessions,
            'product_views': product_views,
            'orders': orders,
            'revenue': round(revenue, 2),
        })
    return series


def _top_product_revenue(start, limit=20):
    rows = db.session.query(
        Product.id,
        Product.name,
        Product.slug,
        Product.image,
        func.coalesce(func.sum(OrderItem.quantity), 0).label('qty'),
        func.coalesce(func.sum(OrderItem.quantity * OrderItem.unit_price), 0).label('revenue'),
        func.count(func.distinct(OrderItem.order_id)).label('orders'),
    ).join(OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id).filter(
        Order.created_at >= start
    ).group_by(Product.id).order_by(desc('revenue')).limit(limit).all()
    return [
        {
            'id': r.id,
            'name': r.name,
            'slug': r.slug,
            'image': r.image,
            'quantity': int(r.qty or 0),
            'revenue': float(r.revenue or 0),
            'orders': int(r.orders or 0),
        }
        for r in rows
    ]


def _top_product_views(start, limit=20):
    rows = _real_visit_base(start).filter(AnalyticsVisit.product_id.isnot(None)).join(
        Product, Product.id == AnalyticsVisit.product_id
    ).with_entities(
        Product.id,
        Product.name,
        Product.slug,
        func.count(AnalyticsVisit.id).label('views'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
    ).group_by(Product.id).order_by(func.count(AnalyticsVisit.id).desc()).limit(limit).all()
    return [
        {
            'id': r.id,
            'name': r.name,
            'slug': r.slug,
            'views': int(r.views or 0),
            'users': int(r.users or 0),
        }
        for r in rows
    ]


def _top_pages(start, limit=30):
    rows = _real_visit_base(start).with_entities(
        AnalyticsVisit.path,
        func.count(AnalyticsVisit.id).label('pageviews'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
        func.sum(case((AnalyticsVisit.medium == 'organic', 1), else_=0)).label('organic_pageviews'),
    ).group_by(AnalyticsVisit.path).order_by(func.count(AnalyticsVisit.id).desc()).limit(limit).all()
    return [
        {
            'path': r.path or '/',
            'pageviews': int(r.pageviews or 0),
            'users': int(r.users or 0),
            'organic_pageviews': int(r.organic_pageviews or 0),
        }
        for r in rows
    ]


def _sources(start):
    rows = _real_visit_base(start).with_entities(
        AnalyticsVisit.source,
        AnalyticsVisit.medium,
        func.count(AnalyticsVisit.id).label('pageviews'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
    ).group_by(AnalyticsVisit.source, AnalyticsVisit.medium).order_by(func.count(AnalyticsVisit.id).desc()).limit(20).all()
    return [
        {
            'source': r.source or 'unknown',
            'medium': r.medium or '-',
            'pageviews': int(r.pageviews or 0),
            'users': int(r.users or 0),
        }
        for r in rows
    ]


def _event_counts(start):
    rows = _event_base(start).with_entities(
        AnalyticsEvent.event_name,
        func.count(AnalyticsEvent.id).label('cnt'),
    ).group_by(AnalyticsEvent.event_name).all()
    return {r.event_name: int(r.cnt or 0) for r in rows}


def _device_rows(start):
    rows = _real_visit_base(start).with_entities(
        AnalyticsVisit.device,
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
    ).group_by(AnalyticsVisit.device).order_by(func.count(func.distinct(AnalyticsVisit.visitor_hash)).desc()).all()
    return [{'device': r.device or 'other', 'users': int(r.users or 0)} for r in rows]


def _browser_rows(start):
    rows = _real_visit_base(start).with_entities(
        AnalyticsVisit.browser,
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
    ).group_by(AnalyticsVisit.browser).order_by(func.count(func.distinct(AnalyticsVisit.visitor_hash)).desc()).limit(12).all()
    return [{'browser': r.browser or 'Other', 'users': int(r.users or 0)} for r in rows]


def _heatmap_rows(start):
    rows = _heatmap_base(start).with_entities(
        AnalyticsHeatmapClick.path,
        AnalyticsHeatmapClick.selector,
        AnalyticsHeatmapClick.text,
        func.count(AnalyticsHeatmapClick.id).label('clicks'),
    ).group_by(
        AnalyticsHeatmapClick.path,
        AnalyticsHeatmapClick.selector,
        AnalyticsHeatmapClick.text,
    ).order_by(func.count(AnalyticsHeatmapClick.id).desc()).limit(40).all()
    return [
        {
            'path': r.path or '/',
            'selector': r.selector or '-',
            'text': r.text or '',
            'clicks': int(r.clicks or 0),
        }
        for r in rows
    ]


def _campaign_rows(start):
    rows = _real_visit_base(start).filter(AnalyticsVisit.campaign != '').with_entities(
        AnalyticsVisit.source,
        AnalyticsVisit.medium,
        AnalyticsVisit.campaign,
        func.count(AnalyticsVisit.id).label('pageviews'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
    ).group_by(AnalyticsVisit.source, AnalyticsVisit.medium, AnalyticsVisit.campaign).order_by(func.count(AnalyticsVisit.id).desc()).limit(30).all()
    return [
        {
            'source': r.source or '-',
            'medium': r.medium or '-',
            'campaign': r.campaign or '-',
            'pageviews': int(r.pageviews or 0),
            'users': int(r.users or 0),
        }
        for r in rows
    ]


def _affiliate_rows(start):
    rows = _real_visit_base(start).filter(AnalyticsVisit.affiliate_code.isnot(None)).outerjoin(
        AffiliatePartner, AffiliatePartner.id == AnalyticsVisit.affiliate_partner_id
    ).with_entities(
        AnalyticsVisit.affiliate_code,
        AffiliatePartner.name,
        func.count(AnalyticsVisit.id).label('clicks'),
        func.count(func.distinct(AnalyticsVisit.visitor_hash)).label('users'),
    ).group_by(AnalyticsVisit.affiliate_code, AffiliatePartner.name).order_by(func.count(AnalyticsVisit.id).desc()).limit(30).all()
    return [
        {
            'code': r.affiliate_code or '-',
            'partner': r.name or '-',
            'clicks': int(r.clicks or 0),
            'users': int(r.users or 0),
        }
        for r in rows
    ]


def _seo_rows(start):
    pages = _top_pages(start, 100)
    wanted = []
    for page in pages:
        path = page['path']
        if path.startswith(('/k/', '/blog/', '/produkt/')) or path in ['/', '/produkty']:
            score = 0
            if page['organic_pageviews'] >= 20:
                score += 35
            elif page['organic_pageviews'] >= 5:
                score += 20
            if page['users'] >= 20:
                score += 30
            elif page['users'] >= 5:
                score += 15
            if path.startswith('/produkt/'):
                score += 10
            if path.startswith('/k/'):
                score += 15
            if path.startswith('/blog/'):
                score += 12
            score = min(100, score)
            wanted.append({**page, 'score': score})
    return sorted(wanted, key=lambda x: (x['organic_pageviews'], x['users']), reverse=True)[:30]


def _conversion_funnel(start):
    visits = _count_visits(start)
    events = _event_counts(start)
    orders = _order_stats(start)
    product_users = _real_visit_base(start).filter(AnalyticsVisit.product_id.isnot(None)).with_entities(AnalyticsVisit.visitor_hash).distinct().count()
    cart_users = _real_visit_base(start).filter(
        db.or_(AnalyticsVisit.path.like('/cart%'), AnalyticsVisit.path.like('/kosik%'))
    ).with_entities(AnalyticsVisit.visitor_hash).distinct().count()
    checkout_users = _real_visit_base(start).filter(
        AnalyticsVisit.path.like('/checkout%')
    ).with_entities(AnalyticsVisit.visitor_hash).distinct().count()

    add_to_cart = events.get('add_to_cart', 0) or events.get('cart_click', 0)
    return [
        {'step': 'Reální uživatelé', 'value': visits['visitors']},
        {'step': 'Produkt detail', 'value': product_users},
        {'step': 'Přidání do košíku', 'value': add_to_cart},
        {'step': 'Košík', 'value': cart_users},
        {'step': 'Checkout', 'value': checkout_users},
        {'step': 'Objednávky', 'value': orders['orders']},
    ]


def _recommendations(start):
    visits = _count_visits(start)
    orders = _order_stats(start)
    sources = _sources(start)
    pages = _top_pages(start, 10)
    products = _top_product_revenue(start, 10)
    product_views = _top_product_views(start, 10)

    recs = []
    conversion = _safe_div(orders['orders'] * 100, visits['visitors']) if visits['visitors'] else 0
    organic_share = _safe_div(visits['organic_visitors'] * 100, visits['visitors']) if visits['visitors'] else 0

    if visits['visitors'] == 0:
        recs.append({
            'level': 'info',
            'title': 'Zatím nejsou data',
            'text': 'Statistiky se naplní po prvních reálných návštěvách. Boti a admin provoz se do reálných uživatelů nepočítají.',
        })
        return recs

    if conversion < 1:
        recs.append({
            'level': 'danger',
            'title': 'Nízká konverze',
            'text': 'Konverze je pod 1 %. Zkontroluj produktové fotky, cenu, dostupné velikosti a viditelnost tlačítka do košíku u nejnavštěvovanějších produktů.',
        })
    elif conversion < 2.5:
        recs.append({
            'level': 'warning',
            'title': 'Konverze jde zvednout',
            'text': 'Konverze je použitelná, ale prostor je hlavně ve zrychlení výběru velikosti, jasnějším benefitu dopravy zdarma a lepších doporučených produktech.',
        })
    else:
        recs.append({
            'level': 'success',
            'title': 'Konverze vypadá dobře',
            'text': 'Aktuální poměr objednávek vůči reálným uživatelům je zdravý. Škáluj stránky a zdroje, které přinášejí nejvyšší organické návštěvy.',
        })

    if organic_share < 20:
        recs.append({
            'level': 'warning',
            'title': 'Nízký podíl organiky',
            'text': 'Organika tvoří malou část návštěv. Priorita: posílit landing pages kategorií, přidat FAQ a interní odkazy z blogů na kategorie.',
        })
    else:
        recs.append({
            'level': 'success',
            'title': 'Organika má dobrý základ',
            'text': 'Organická návštěvnost už tvoří viditelnou část provozu. Nejlepší stránky rozšiř o delší obsah a produktové bloky.',
        })

    if pages:
        recs.append({
            'level': 'info',
            'title': 'Nejsilnější stránka',
            'text': f"Nejvíc reálných návštěv má {pages[0]['path']}. Zkontroluj, že nahoře jasně vede zákazníka na produkty nebo košík.",
        })

    if products:
        recs.append({
            'level': 'success',
            'title': 'Produkt s nejvyšším obratem',
            'text': f"Největší obrat ve vybraném období dělá {products[0]['name']}. Dej ho výš na relevantní landing pages a do doporučených bloků.",
        })
    elif product_views:
        recs.append({
            'level': 'info',
            'title': 'Nejnavštěvovanější produkt',
            'text': f"Nejvíc zobrazení má {product_views[0]['name']}. Pokud neprodává, zkontroluj cenu, velikosti, fotky a popis.",
        })

    if sources:
        recs.append({
            'level': 'info',
            'title': 'Nejsilnější zdroj',
            'text': f"Nejvíc uživatelů přivádí {sources[0]['source']} ({sources[0]['medium']}). Vyplatí se mu přizpůsobit landing page a měřit objednávky.",
        })

    return recs


def _dashboard_data(period):
    start = _period_start(period)
    now = _utcnow()

    visits = _count_visits(start)
    orders = _order_stats(start)
    daily_series = _daily_series(start, now)
    sources = _sources(start)
    top_pages = _top_pages(start)
    top_product_views = _top_product_views(start)
    top_product_revenue = _top_product_revenue(start)
    devices = _device_rows(start)
    browsers = _browser_rows(start)
    heatmap = _heatmap_rows(start)
    campaigns = _campaign_rows(start)
    affiliates = _affiliate_rows(start)
    funnel = _conversion_funnel(start)
    seo = _seo_rows(start)
    recommendations = _recommendations(start)

    conversion_rate = round(_safe_div(orders['orders'] * 100, visits['visitors']), 2) if visits['visitors'] else 0
    organic_share = round(_safe_div(visits['organic_visitors'] * 100, visits['visitors']), 2) if visits['visitors'] else 0
    revenue_per_user = round(_safe_div(orders['revenue'], visits['visitors']), 2) if visits['visitors'] else 0

    return {
        'period': period,
        'generated_at': now.strftime('%d.%m.%Y %H:%M:%S'),
        'cards': {
            'real_users': visits['visitors'],
            'sessions': visits['sessions'],
            'pageviews': visits['pageviews'],
            'organic_users': visits['organic_visitors'],
            'organic_sessions': visits['organic_sessions'],
            'organic_share': organic_share,
            'orders': orders['orders'],
            'paid_orders': orders['paid_orders'],
            'revenue': round(orders['revenue'], 2),
            'paid_revenue': round(orders['paid_revenue'], 2),
            'average_order': round(orders['average_order'], 2),
            'conversion_rate': conversion_rate,
            'revenue_per_user': revenue_per_user,
            'product_views': visits['product_views'],
            'affiliate_clicks': visits['affiliate_clicks'],
        },
        'series': daily_series,
        'sources': sources,
        'top_pages': top_pages,
        'top_product_views': top_product_views,
        'top_product_revenue': top_product_revenue,
        'devices': devices,
        'browsers': browsers,
        'heatmap': heatmap,
        'campaigns': campaigns,
        'affiliates': affiliates,
        'funnel': funnel,
        'seo': seo,
        'recommendations': recommendations,
    }


def _json_response(payload):
    return jsonify(payload)


@analytics_bp.route('/api/analytics/event', methods=['POST'])
def api_track_event():
    ua = request.headers.get('User-Agent', '')[:500]
    if _is_bot_ua(ua):
        return _json_response({'ok': True, 'ignored': 'bot'})

    data = request.get_json(silent=True) or {}
    event_name = str(data.get('event') or data.get('type') or data.get('name') or 'event')[:120]
    path = str(data.get('path') or request.referrer or '')[:500]
    if path.startswith('http'):
        try:
            path = urlparse(path).path[:500]
        except Exception:
            path = ''
    if not path:
        path = request.path

    if path.startswith('/admin'):
        return _json_response({'ok': True, 'ignored': 'admin'})

    source, medium, campaign, _, _ = _marketing_data()
    affiliate_code, affiliate_partner_id = _affiliate_from_request()
    session_id = request.cookies.get(SESSION_COOKIE) or uuid4().hex

    value = 0
    try:
        value = float(data.get('value') or 0)
    except Exception:
        value = 0

    event = AnalyticsEvent(
        created_at=_utcnow(),
        visit_date=_utcnow().date(),
        session_id=session_id,
        event_name=event_name,
        path=path,
        product_id=_product_id_from_path(path),
        value=value,
        source=source[:120],
        medium=medium[:120],
        campaign=campaign[:200],
        affiliate_code=(affiliate_code or '')[:120] or None,
        affiliate_partner_id=affiliate_partner_id,
    )
    db.session.add(event)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return _json_response({'ok': False}), 500

    return _json_response({'ok': True})


@analytics_bp.route('/api/analytics/heatmap', methods=['POST'])
def api_track_heatmap():
    ua = request.headers.get('User-Agent', '')[:500]
    if _is_bot_ua(ua):
        return _json_response({'ok': True, 'ignored': 'bot'})

    data = request.get_json(silent=True) or {}
    path = str(data.get('path') or '')[:500]
    if not path or path.startswith('/admin'):
        return _json_response({'ok': True, 'ignored': 'admin'})

    visitor_cookie = request.cookies.get(VISITOR_COOKIE) or uuid4().hex
    ip = _client_ip()
    click = AnalyticsHeatmapClick(
        created_at=_utcnow(),
        visit_date=_utcnow().date(),
        session_id=request.cookies.get(SESSION_COOKIE) or uuid4().hex,
        visitor_hash=_hash_value(f'{visitor_cookie}:{ip}:{ua}'),
        path=path,
        x=int(data.get('x') or 0),
        y=int(data.get('y') or 0),
        viewport_w=int(data.get('viewport_w') or 0),
        viewport_h=int(data.get('viewport_h') or 0),
        page_w=int(data.get('page_w') or 0),
        page_h=int(data.get('page_h') or 0),
        selector=str(data.get('selector') or '')[:300],
        text=str(data.get('text') or '')[:200],
    )
    db.session.add(click)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return _json_response({'ok': False}), 500

    return _json_response({'ok': True})


@analytics_bp.route('/api/analytics/stats')
@admin_required
def api_analytics_stats():
    period = request.args.get('period', '30d')
    return _json_response(_dashboard_data(period))


@analytics_bp.route('/api/analytics/insights')
@admin_required
def api_analytics_insights():
    period = request.args.get('period', '30d')
    data = _dashboard_data(period)
    return _json_response({
        'generated_at': data['generated_at'],
        'recommendations': data['recommendations'],
        'top_product_revenue': data['top_product_revenue'],
        'top_product_views': data['top_product_views'],
        'seo': data['seo'],
    })


@analytics_bp.route('/api/analytics/realtime')
@admin_required
def api_analytics_realtime():
    period = request.args.get('period', 'today')

    def stream():
        for _ in range(120):
            payload = json.dumps(_dashboard_data(period), ensure_ascii=False)
            yield f'data: {payload}\n\n'
            time.sleep(5)

    return Response(stream(), mimetype='text/event-stream')


@analytics_bp.route('/admin/statistiky')
@admin_required
def admin_stats():
    period = request.args.get('period', '30d')
    dashboard = _dashboard_data(period)
    return render_template(
        'admin/statistiky.html',
        period=period,
        dashboard=dashboard,
    )
