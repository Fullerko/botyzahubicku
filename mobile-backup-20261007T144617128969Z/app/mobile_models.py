from datetime import datetime
from . import db

class MobileEvent(db.Model):
    __tablename__ = 'mobile_event'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(250), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    description = db.Column(db.Text, default='')
    published = db.Column(db.Boolean, default=True, nullable=False)
    cancelled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MobilePushSubscription(db.Model):
    __tablename__ = 'mobile_push_subscription'
    id = db.Column(db.Integer, primary_key=True)
    endpoint_hash = db.Column(db.String(64), unique=True, nullable=False)
    endpoint = db.Column(db.Text, nullable=False)
    p256dh = db.Column(db.String(128), nullable=False)
    auth = db.Column(db.String(64), nullable=False)
    owner_hash = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class MobilePushCampaign(db.Model):
    request_key = db.Column(db.String(48), unique=True, nullable=True)
    __tablename__ = 'mobile_push_campaign'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(80), nullable=False)
    body = db.Column(db.String(240), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, nullable=False)

class MobilePushDelivery(db.Model):
    __tablename__ = 'mobile_push_delivery'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('mobile_push_campaign.id'), nullable=False, index=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey('mobile_push_subscription.id'), nullable=False)
    status = db.Column(db.String(16), default='pending', nullable=False, index=True)
    error = db.Column(db.String(200), default='')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('campaign_id', 'subscription_id'),)
