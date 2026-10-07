from datetime import datetime
from . import db

class RewardMember(db.Model):
    __tablename__ = 'reward_member'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False, index=True)
    public_code = db.Column(db.String(12), unique=True, nullable=False)
    qr_secret = db.Column(db.String(64), unique=True, nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class RewardPurchase(db.Model):
    __tablename__ = 'reward_purchase'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    cashback_cents = db.Column(db.Integer, nullable=False)
    refunded_cents = db.Column(db.Integer, default=0, nullable=False)
    available_at = db.Column(db.DateTime, nullable=False)
    reference = db.Column(db.String(100), nullable=False)
    note = db.Column(db.String(300), default='')
    request_key = db.Column(db.String(48), unique=True, nullable=False)
    created_by = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('reference'), db.CheckConstraint('amount_cents > 0'), db.CheckConstraint('refunded_cents >= 0 AND refunded_cents <= amount_cents'))

class RewardWithdrawal(db.Model):
    __tablename__ = 'reward_withdrawal'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    bank_account = db.Column(db.String(60), nullable=False)
    account_name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(16), default='requested', nullable=False)
    request_key = db.Column(db.String(48), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    handled_by = db.Column(db.Integer, nullable=True)
    payment_reference = db.Column(db.String(100), default='')
    admin_note = db.Column(db.String(300), default='')
    __table_args__ = (db.CheckConstraint('amount_cents >= 10000'),)

class RewardLedger(db.Model):
    __tablename__ = 'reward_ledger'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    delta_cents = db.Column(db.Integer, nullable=False)
    available_at = db.Column(db.DateTime, nullable=False, index=True)
    kind = db.Column(db.String(24), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    entry_key = db.Column(db.String(100), unique=True, nullable=False)
    purchase_id = db.Column(db.Integer, db.ForeignKey('reward_purchase.id'), nullable=True)
    withdrawal_id = db.Column(db.Integer, db.ForeignKey('reward_withdrawal.id'), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
