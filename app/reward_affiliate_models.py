from datetime import datetime
from . import db

class RewardAffiliateAccount(db.Model):
    __tablename__='reward_affiliate_account'
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),unique=True,nullable=False)
    partner_id=db.Column(db.Integer,db.ForeignKey('affiliate_partner.id'),unique=True,nullable=False)
    invite_code=db.Column(db.String(24),unique=True,nullable=False)
    legacy_imported=db.Column(db.Boolean,default=False,nullable=False)
    legacy_state=db.Column(db.String(20),default='ready',nullable=False)
    legacy_recorded_cents=db.Column(db.Integer,default=0,nullable=False)
    legacy_calculated_cents=db.Column(db.Integer,default=0,nullable=False)
    legacy_note=db.Column(db.Text,default='')
    reviewed_by=db.Column(db.Integer,nullable=True)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class RewardReferral(db.Model):
    __tablename__='reward_referral'
    id=db.Column(db.Integer,primary_key=True)
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),unique=True,nullable=False)
    affiliate_account_id=db.Column(db.Integer,db.ForeignKey('reward_affiliate_account.id'),nullable=False,index=True)
    source_code=db.Column(db.String(40),nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class RewardCommission(db.Model):
    __tablename__='reward_commission'
    id=db.Column(db.Integer,primary_key=True)
    purchase_id=db.Column(db.Integer,db.ForeignKey('reward_purchase.id'),unique=True,nullable=False)
    affiliate_account_id=db.Column(db.Integer,db.ForeignKey('reward_affiliate_account.id'),nullable=False,index=True)
    user_id=db.Column(db.Integer,db.ForeignKey('user.id'),nullable=False)
    amount_cents=db.Column(db.Integer,nullable=False)
    refunded_cents=db.Column(db.Integer,default=0,nullable=False)

class RewardAffiliateOrder(db.Model):
    __tablename__='reward_affiliate_order'
    id=db.Column(db.Integer,primary_key=True)
    order_id=db.Column(db.Integer,db.ForeignKey('order.id'),unique=True,nullable=False)
    affiliate_account_id=db.Column(db.Integer,db.ForeignKey('reward_affiliate_account.id'),nullable=False,index=True)
    credited_cents=db.Column(db.Integer,default=0,nullable=False)
    baseline_cents=db.Column(db.Integer,default=0,nullable=False)
    revision=db.Column(db.Integer,default=0,nullable=False)
    available_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class RewardMaintenance(db.Model):
    __tablename__='reward_maintenance'
    id=db.Column(db.Integer,primary_key=True)
    kind=db.Column(db.String(24),nullable=False)
    detail=db.Column(db.Text,nullable=False)
    admin_id=db.Column(db.Integer,nullable=False)
    created_at=db.Column(db.DateTime,default=datetime.utcnow,nullable=False)

class RewardOnlineAttribution(db.Model):
    __tablename__='reward_online_attribution'
    order_id=db.Column(db.Integer,db.ForeignKey('order.id'),primary_key=True)
    partner_id=db.Column(db.Integer,db.ForeignKey('affiliate_partner.id'),nullable=False,index=True)
