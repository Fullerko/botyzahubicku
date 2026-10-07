"""One inviter per member, one commission per purchase, one shared payout ledger."""
import json
import secrets
from datetime import datetime,timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import func
from . import db
from .models import AffiliatePartner,AffiliatePayoutRequest,Coupon,Order,User
from .reward_models import RewardMember,RewardPurchase,RewardLedger
from .reward_affiliate_models import RewardAffiliateAccount,RewardReferral,RewardCommission,RewardAffiliateOrder,RewardMaintenance,RewardOnlineAttribution
from .reward_service import HOLD_DAYS,cashback,join_program,money


def cents(value):
    result=Decimal(str(value or 0))
    if not result.is_finite():raise ValueError('Historická částka není platná. Kontaktujte správce.')
    return int((result*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def partner_orders(partner):
    """Coupon ID is authoritative. A name is used only when globally unambiguous."""
    name_unique=AffiliatePartner.query.filter_by(name=partner.name).count()==1
    result=[];ambiguous=[]
    for order in Order.query.filter(db.or_(Order.affiliate_partner_name==partner.name,Order.coupon_id.in_([c.id for c in partner.codes]),Order.id.in_(db.session.query(RewardOnlineAttribution.order_id).filter_by(partner_id=partner.id)))).all():
        attribution=db.session.get(RewardOnlineAttribution,order.id)
        if attribution:
            if attribution.partner_id==partner.id:result.append(order)
            continue
        coupon=db.session.get(Coupon,order.coupon_id) if order.coupon_id else None
        if coupon and coupon.affiliate_partner_id:
            if coupon.affiliate_partner_id==partner.id:result.append(order)
        elif order.affiliate_partner_name==partner.name:
            (result if name_unique else ambiguous).append(order)
    return result,ambiguous


def order_target(order):
    cancelled=(order.status or '').casefold() in {'storno','stornováno','zrušeno','vráceno','cancelled','refunded'}
    return max(0,cents(order.affiliate_commission_amount)) if order.payment_status=='paid' and not cancelled else 0


def ensure_account(user_id):
    account=RewardAffiliateAccount.query.filter_by(user_id=user_id).first()
    if account:return account
    user=db.session.get(User,user_id)
    matches=AffiliatePartner.query.filter(func.lower(func.trim(AffiliatePartner.email))==user.email.strip().lower()).all()
    if len(matches)>1:raise ValueError('Pro tento e-mail existuje více affiliate účtů. Správce musí nejdříve ověřit duplicity.')
    if matches:
        partner=matches[0]
        if RewardAffiliateAccount.query.filter_by(partner_id=partner.id).first():raise ValueError('Affiliate partner už je připojený k jinému uživatelskému účtu.')
    else:
        partner=AffiliatePartner(name=user.full_name or user.email,email=user.email.strip().lower(),status='Aktivní',note='Pozvánky v aplikaci: zákazník 5 % zpět, partner 5 % provize.')
        db.session.add(partner);db.session.flush()
    account=RewardAffiliateAccount(user_id=user_id,partner_id=partner.id,invite_code='BZH'+secrets.token_hex(8).upper())
    db.session.add(account);db.session.flush()
    db.session.add(Coupon(code=account.invite_code,label='Pozvánka 5 + 5',description='Pozvánka do aplikace a webu',discount_percent_client=5,commission_percent_partner=5,affiliate_partner_id=partner.id,active=True,max_uses=0))
    db.session.flush()
    join_program(user_id)
    orders,ambiguous=partner_orders(partner)
    earned=0
    for order in orders:
        target=order_target(order);earned+=target
        db.session.add(RewardAffiliateOrder(order_id=order.id,affiliate_account_id=account.id,credited_cents=target,baseline_cents=target,available_at=datetime.utcnow()))
    account.legacy_recorded_cents=cents(partner.commission_balance)
    account.legacy_calculated_cents=earned-cents(partner.paid_total)
    open_requests=AffiliatePayoutRequest.query.filter_by(affiliate_partner_id=partner.id,status='Čeká').count()
    if ambiguous or open_requests or abs(account.legacy_recorded_cents-account.legacy_calculated_cents)>1 or account.legacy_calculated_cents<0:
        account.legacy_state='review'
        account.legacy_note=f'Nejednoznačné objednávky: {len(ambiguous)}; otevřené staré žádosti: {open_requests}; historické zůstatky se musí ověřit.'
    else:
        account.legacy_state='ready';account.legacy_imported=True
        if account.legacy_calculated_cents:
            db.session.add(RewardLedger(user_id=user_id,delta_cents=account.legacy_calculated_cents,available_at=datetime.utcnow(),kind='legacy_affiliate',description='Jednorázový převod dosavadního affiliate zůstatku',entry_key=f'affiliate-legacy-{account.id}'))
    return account


def resolve_invite(code):
    code=(code or '').strip().upper()
    if not code:return None
    account=RewardAffiliateAccount.query.filter_by(invite_code=code).first()
    if not account:
        coupons=Coupon.query.filter(func.upper(Coupon.code)==code,Coupon.active==True,Coupon.affiliate_partner_id.isnot(None)).all()
        if len(coupons)!=1:raise ValueError('Pozvánkový kód není platný nebo není jednoznačný.')
        partner=db.session.get(AffiliatePartner,coupons[0].affiliate_partner_id)
        users=User.query.filter(func.lower(func.trim(User.email))==partner.email.strip().lower()).all()
        if len(users)!=1:raise ValueError('Tento partner nemá jednoznačně připojený uživatelský účet. Kontaktujte správce.')
        account=ensure_account(users[0].id)
    partner=db.session.get(AffiliatePartner,account.partner_id)
    if partner.status!='Aktivní':raise ValueError('Tato pozvánka už není aktivní.')
    return account


def bind_referral(user_id,code):
    if not code:return None
    account=resolve_invite(code)
    if account.user_id==user_id:raise ValueError('Nemůžete pozvat sami sebe.')
    existing=RewardReferral.query.filter_by(user_id=user_id).first()
    if existing:
        if existing.affiliate_account_id!=account.id:raise ValueError('Účet už je přiřazen původnímu pozývajícímu. Nelze jej přepsat.')
        return existing
    if RewardPurchase.query.filter_by(user_id=user_id).first():raise ValueError('Pozvánku lze přiřadit jen před prvním potvrzeným QR nákupem.')
    cursor=account.user_id;visited={user_id}
    while cursor:
        if cursor in visited:raise ValueError('Vzájemné nebo kruhové pozvání není povoleno.')
        visited.add(cursor)
        row=RewardReferral.query.filter_by(user_id=cursor).first()
        cursor=db.session.get(RewardAffiliateAccount,row.affiliate_account_id).user_id if row else None
    row=RewardReferral(user_id=user_id,affiliate_account_id=account.id,source_code=code.strip().upper())
    db.session.add(row);return row


def credit_referral(purchase,admin_id):
    referral=RewardReferral.query.filter_by(user_id=purchase.user_id).first()
    if not referral:return None
    account=db.session.get(RewardAffiliateAccount,referral.affiliate_account_id)
    partner=db.session.get(AffiliatePartner,account.partner_id)
    if partner.status!='Aktivní':return None
    if account.user_id==purchase.user_id:raise ValueError('Vlastní nákup nemůže vytvořit affiliate provizi.')
    existing=RewardCommission.query.filter_by(purchase_id=purchase.id).first()
    if existing:return existing
    item=RewardCommission(purchase_id=purchase.id,affiliate_account_id=account.id,user_id=account.user_id,amount_cents=cashback(purchase.amount_cents))
    db.session.add(item)
    db.session.add(RewardLedger(user_id=account.user_id,delta_cents=item.amount_cents,available_at=purchase.available_at,kind='referral_commission',description=f'5 % provize za doporučený nákup {purchase.reference}',entry_key=f'referral-purchase-{purchase.id}',purchase_id=purchase.id,created_by=admin_id))
    return item


def refund_referral(purchase,delta,request_key,admin_id):
    item=RewardCommission.query.filter_by(purchase_id=purchase.id).first()
    if not item:return
    item.refunded_cents+=delta
    db.session.add(RewardLedger(user_id=item.user_id,delta_cents=-delta,available_at=purchase.available_at,kind='referral_refund',description=f'Storno provize za doporučený nákup {purchase.reference}',entry_key='referral-refund-'+request_key,purchase_id=purchase.id,created_by=admin_id))


def sync_orders(account):
    partner=db.session.get(AffiliatePartner,account.partner_id)
    orders,ambiguous=partner_orders(partner)
    if ambiguous and account.reviewed_by is None:
        account.legacy_state='review';account.legacy_note='Objednávky podle jména nejsou jednoznačné. Nutná kontrola správce.'
    for order in orders:
        identities=[order.order_number,order.variable_symbol,order.fio_transaction_id]
        if RewardPurchase.query.filter(db.func.lower(RewardPurchase.reference).in_([x.lower() for x in identities if x])).first():
            account.legacy_state='review';account.legacy_note='Stejné číslo nákupu existuje na webu i v QR programu. Nová webová provize nebyla připsána.';continue
        row=RewardAffiliateOrder.query.filter_by(order_id=order.id).first()
        if row and row.affiliate_account_id!=account.id:
            account.legacy_state='review';account.legacy_note='Objednávka už je přiřazená jinému affiliate účtu.';continue
        if not row:
            row=RewardAffiliateOrder(order_id=order.id,affiliate_account_id=account.id,credited_cents=0,baseline_cents=0,revision=0,available_at=datetime.utcnow());db.session.add(row)
        target=order_target(order);difference=target-row.credited_cents
        if not difference:continue
        row.revision+=1;row.credited_cents=target
        key=f'affiliate-order-{order.id}-{row.revision}'
        if difference>0:
            movements=[(difference,datetime.utcnow()+timedelta(days=HOLD_DAYS))]
        else:
            # Reverse future and matured components at their original maturity.
            # This also handles edited commissions with several 14-day holds.
            buckets={row.available_at:row.baseline_cents}
            for entry in RewardLedger.query.filter(RewardLedger.entry_key.like(f'affiliate-order-{order.id}-%')).all():
                buckets[entry.available_at]=buckets.get(entry.available_at,0)+entry.delta_cents
            remaining=-difference;movements=[]
            for available_at,net in sorted(buckets.items(),reverse=True):
                if net<=0:continue
                take=min(remaining,net)
                if take:movements.append((-take,available_at));remaining-=take
                if not remaining:break
            if remaining:raise ValueError('Historie webové provize není konzistentní. Správce ji musí ověřit.')
        for index,(delta,available_at) in enumerate(movements):
            db.session.add(RewardLedger(user_id=account.user_id,delta_cents=delta,available_at=available_at,kind='online_affiliate',description=f'Affiliate provize webové objednávky {order.order_number}',entry_key=key+(f'-{index+1}' if index else '')))


def guard_withdrawal(user_id):
    account=RewardAffiliateAccount.query.filter_by(user_id=user_id).first()
    if account:
        sync_orders(account)
        if account.legacy_state!='ready':raise ValueError('Historický affiliate zůstatek musí nejdříve ověřit správce. Další odměny se neztrácejí.')
    else:
        user=db.session.get(User,user_id)
        if AffiliatePartner.query.filter(func.lower(func.trim(AffiliatePartner.email))==user.email.strip().lower()).count():
            account=ensure_account(user_id);sync_orders(account)
            if account.legacy_state!='ready':raise ValueError('Správce musí nejdříve ověřit historický affiliate zůstatek.')


def review_legacy(account,confirmed_cents,note,admin_id):
    if account.legacy_state=='ready':raise ValueError('Historický zůstatek už byl převeden. Nelze jej připsat podruhé.')
    if not note.strip():raise ValueError('Uveďte, jak jste ověřili zůstatek a dosavadní bankovní výplaty.')
    if account.legacy_imported and confirmed_cents:raise ValueError('Historie již byla připsaná. Pro uzavření kontroly zadejte 0; původní peníze se znovu nepřipisují.')
    for item in AffiliatePayoutRequest.query.filter_by(affiliate_partner_id=account.partner_id,status='Čeká').all():
        item.status='Převedeno';item.note=(item.note or '')+'\nPřevedeno do jednotné peněženky; nová žádost přes Moje odměny.'
    if confirmed_cents and not account.legacy_imported:
        db.session.add(RewardLedger(user_id=account.user_id,delta_cents=confirmed_cents,available_at=datetime.utcnow(),kind='legacy_affiliate',description='Ověřený převod historického affiliate zůstatku',entry_key=f'affiliate-legacy-{account.id}',created_by=admin_id))
    account.legacy_state='ready';account.legacy_imported=True;account.legacy_note=note[:2000];account.reviewed_by=admin_id
    db.session.add(RewardMaintenance(kind='legacy_review',admin_id=admin_id,detail=json.dumps({'account':account.id,'confirmed_cents':confirmed_cents,'note':note},ensure_ascii=False)))


def capture_online_order(order,coupon):
    if coupon and coupon.affiliate_partner_id:
        db.session.add(RewardOnlineAttribution(order_id=order.id,partner_id=coupon.affiliate_partner_id))


def credit_legacy_until_connected(order):
    attribution=db.session.get(RewardOnlineAttribution,order.id)
    coupon=db.session.get(Coupon,order.coupon_id) if order.coupon_id else None
    if attribution:partner=db.session.get(AffiliatePartner,attribution.partner_id)
    elif coupon and coupon.affiliate_partner_id:partner=db.session.get(AffiliatePartner,coupon.affiliate_partner_id)
    else:
        candidates=AffiliatePartner.query.filter_by(name=order.affiliate_partner_name).all()
        partner=candidates[0] if len(candidates)==1 else None
    if partner and not RewardAffiliateAccount.query.filter_by(partner_id=partner.id).first():
        partner.commission_balance=float(Decimal(cents(partner.commission_balance)+order_target(order))/100)
