"""Conservative duplicate audit. No purchases, money entries or users are deleted."""
import json,os,sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from . import db
from .models import AffiliatePartner,AffiliatePayoutRequest,Coupon,Order,User
from .reward_models import RewardPurchase,RewardLedger
from .reward_affiliate_models import RewardAffiliateAccount,RewardMaintenance


def partner_used(partner):
    return bool(partner.codes or AffiliatePayoutRequest.query.filter_by(affiliate_partner_id=partner.id).first() or RewardAffiliateAccount.query.filter_by(partner_id=partner.id).first() or Order.query.filter_by(affiliate_partner_name=partner.name).first() or partner.commission_balance or partner.paid_total)


def coupon_used(coupon):
    return bool(coupon.uses_count or Order.query.filter(db.or_(Order.coupon_id==coupon.id,db.func.lower(Order.coupon_code)==coupon.code.lower())).first())


def exact_candidates():
    groups=defaultdict(list)
    for p in AffiliatePartner.query.order_by(AffiliatePartner.id).all():
        key=(p.email.strip().casefold(),p.name,p.instagram,p.note,p.status,p.commission_balance or 0,p.paid_total or 0)
        groups[key].append(p)
    deleted_partners=[]
    for group in groups.values():
        if len(group)<2:continue
        keep=next((p for p in group if partner_used(p)),group[0])
        deleted_partners.extend(p for p in group if p.id!=keep.id and not partner_used(p))
    groups=defaultdict(list)
    for c in Coupon.query.order_by(Coupon.id).all():
        key=(c.code.strip().casefold(),c.label,c.description,c.discount_percent_client,c.commission_percent_partner,c.affiliate_partner_id,c.active,c.max_uses,c.uses_count or 0)
        groups[key].append(c)
    deleted_coupons=[]
    for group in groups.values():
        if len(group)<2:continue
        keep=next((c for c in group if coupon_used(c)),group[0])
        deleted_coupons.extend(c for c in group if c.id!=keep.id and not coupon_used(c))
    return deleted_partners,deleted_coupons


def audit():
    def repeats(rows,key):
        groups=defaultdict(list)
        for row in rows:groups[key(row)].append(row.id)
        return [{'key':key,'ids':ids} for key,ids in groups.items() if len(ids)>1]
    partners=AffiliatePartner.query.all();coupons=Coupon.query.all()
    safe_p,safe_c=exact_candidates()
    return {'user_emails':repeats(User.query.all(),lambda u:u.email.strip().casefold()),'partner_emails':repeats(partners,lambda p:p.email.strip().casefold()),'partner_names':repeats(partners,lambda p:p.name),'coupon_codes':repeats(coupons,lambda c:c.code.strip().casefold()),'receipt_numbers':repeats(RewardPurchase.query.all(),lambda p:p.reference.strip().casefold()),'ledger_keys':repeats(RewardLedger.query.all(),lambda e:e.entry_key),'safe_partners':[p.id for p in safe_p],'safe_coupons':[c.id for c in safe_c]}


def cleanup_exact_duplicates(admin_id):
    p,c=exact_candidates()
    path=db.engine.url.database
    if not path or path==':memory:':raise ValueError('Databázi nelze bezpečně zálohovat.')
    original=Path(path).resolve()
    directory=original.parent/'reward-backups';directory.mkdir(mode=0o700,exist_ok=True)
    backup=directory/('before-dedup-'+datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')+'.sqlite3')
    descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
    with sqlite3.connect(original) as source,sqlite3.connect(backup) as target:source.backup(target)
    report={'deleted_partners':[row.id for row in p],'deleted_coupons':[row.id for row in c],'backup':str(backup)}
    for row in p:db.session.delete(row)
    for row in c:db.session.delete(row)
    db.session.add(RewardMaintenance(kind='exact_duplicate_cleanup',detail=json.dumps(report,ensure_ascii=False),admin_id=admin_id))
    return report
