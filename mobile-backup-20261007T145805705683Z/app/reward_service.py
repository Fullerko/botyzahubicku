"""Integer-cent append-only ledger; serialized writes prevent double withdrawals."""
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import func, text
from . import db
from .reward_models import RewardMember, RewardPurchase, RewardWithdrawal, RewardLedger

MIN_WITHDRAWAL_CENTS = 10000
HOLD_DAYS = 14


def money(cents):
    sign = '-' if cents < 0 else ''
    value = abs(int(cents))
    return f'{sign}{value//100:,}'.replace(',',' ') + f',{value%100:02d} Kč'


def parse_amount(value):
    raw = str(value or '').strip().replace(' ', '').replace(',', '.')
    if not re.fullmatch(r'\d{1,7}(\.\d{1,2})?',raw):
        raise ValueError('Částku zadejte v Kč, nejvýše se dvěma desetinnými místy.')
    try:
        cents = int(Decimal(raw) * 100)
    except InvalidOperation:
        raise ValueError('Neplatná částka.')
    if not 1 <= cents <= 100_000_000:
        raise ValueError('Zadejte kladnou částku do 1 000 000 Kč.')
    return cents


def cashback(cents):
    return int((Decimal(cents) * Decimal('0.05')).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def nonce(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{48}',value):
        raise ValueError('Obnovte stránku a zkuste akci znovu.')
    return value


def begin_money_write():
    # Auth may already have opened a read transaction. No writes precede this.
    db.session.commit()
    if db.engine.dialect.name == 'sqlite':
        db.session.execute(text('BEGIN IMMEDIATE'))
    else:
        raise RuntimeError('Tato verze odměn vyžaduje původní SQLite databázi.')


def balances(user_id, now=None):
    now = now or datetime.utcnow()
    base = db.session.query(func.coalesce(func.sum(RewardLedger.delta_cents),0)).filter(RewardLedger.user_id==user_id)
    available = int(base.filter(RewardLedger.available_at <= now).scalar())
    pending = int(base.filter(RewardLedger.available_at > now).scalar())
    reserved = int(db.session.query(func.coalesce(func.sum(RewardWithdrawal.amount_cents),0)).filter(RewardWithdrawal.user_id==user_id,RewardWithdrawal.status.in_(['requested','processing'])).scalar())
    return {'available':available, 'pending':pending, 'reserved':reserved}


def join_program(user_id):
    member = RewardMember.query.filter_by(user_id=user_id).first()
    if member:
        return member
    member = RewardMember(user_id=user_id,public_code=secrets.token_hex(5).upper(),qr_secret=secrets.token_urlsafe(32))
    db.session.add(member)
    return member


def record_purchase(member, amount, reference, note, request_key, admin_id):
    request_key = nonce(request_key)
    existing = RewardPurchase.query.filter_by(request_key=request_key).first()
    if existing:
        if existing.user_id != member.user_id:
            raise ValueError('Požadavek patří jinému zákazníkovi.')
        return existing
    reference = reference.strip()
    if not reference or len(reference)>100 or len(note)>300:
        raise ValueError('Zadejte číslo účtenky/nákupu (max. 100 znaků) a krátkou poznámku.')
    if RewardPurchase.query.filter_by(reference=reference).first():
        raise ValueError('Toto číslo účtenky už bylo připsáno. Zkontrolujte historii.')
    purchase = RewardPurchase(user_id=member.user_id,amount_cents=amount,cashback_cents=cashback(amount),available_at=datetime.utcnow()+timedelta(days=HOLD_DAYS),reference=reference,note=note,request_key=request_key,created_by=admin_id)
    db.session.add(purchase);db.session.flush()
    db.session.add(RewardLedger(user_id=member.user_id,delta_cents=purchase.cashback_cents,available_at=purchase.available_at,kind='purchase',description=f'5 % z nákupu {reference}',entry_key=f'purchase-{purchase.id}',purchase_id=purchase.id,created_by=admin_id))
    return purchase


def refund_purchase(purchase, amount, request_key, admin_id):
    request_key=nonce(request_key)
    entry_key='refund-'+request_key
    existing=RewardLedger.query.filter_by(entry_key=entry_key).first()
    if existing:
        if existing.purchase_id != purchase.id:
            raise ValueError('Požadavek patří jinému nákupu.')
        return existing
    remaining=purchase.amount_cents-purchase.refunded_cents
    if amount>remaining:
        raise ValueError('Vrácená částka převyšuje zbývající část nákupu.')
    before=cashback(remaining)
    after=cashback(remaining-amount)
    purchase.refunded_cents+=amount
    entry=RewardLedger(user_id=purchase.user_id,delta_cents=-(before-after),available_at=purchase.available_at,kind='refund',description=f'Storno odměny: vráceno {money(amount)} z nákupu {purchase.reference}',entry_key=entry_key,purchase_id=purchase.id,created_by=admin_id)
    db.session.add(entry)
    return entry


def bank_account(value):
    raw=str(value or '').strip().upper().replace(' ','')
    # Czech IBAN or Czech domestic account including bank code.
    if re.fullmatch(r'CZ\d{22}',raw):
        moved=raw[4:]+raw[:4]
        numeric=''.join(str(ord(ch)-55) if ch.isalpha() else ch for ch in moved)
        if int(numeric)%97!=1:
            raise ValueError('IBAN není platný. Zkontrolujte číslo účtu.')
        return raw
    found=re.fullmatch(r'(?:(\d{1,6})-)?(\d{1,10})/(\d{4})',raw)
    if not found:
        raise ValueError('Zadejte český účet například 123456789/0800 nebo český IBAN.')
    prefix,account,bank=found.groups()
    def check(number,weights):
        return sum(int(digit)*weight for digit,weight in zip(number.zfill(len(weights)),weights))%11==0
    if not int(account) or not check(account,[6,3,7,9,10,5,8,4,2,1]) or (prefix and not check(prefix,[10,5,8,4,2,1])):
        raise ValueError('Číslo účtu neprošlo kontrolou. Zkontrolujte jej.')
    return raw


def request_withdrawal(user_id, account, name, request_key):
    request_key=nonce(request_key)
    existing=RewardWithdrawal.query.filter_by(request_key=request_key).first()
    if existing:
        if existing.user_id != user_id:
            raise ValueError('Požadavek patří jinému zákazníkovi.')
        return existing
    if RewardWithdrawal.query.filter(RewardWithdrawal.user_id==user_id,RewardWithdrawal.status.in_(['requested','processing'])).first():
        raise ValueError('Už máte otevřenou žádost o výplatu. Vyčkejte na její zpracování.')
    name=name.strip()
    if not name or len(name)>120:
        raise ValueError('Vyplňte jméno majitele účtu (max. 120 znaků).')
    account=bank_account(account)
    amount=balances(user_id)['available']
    if amount<MIN_WITHDRAWAL_CENTS:
        raise ValueError('O výplatu můžete požádat od dostupného zůstatku 100 Kč.')
    item=RewardWithdrawal(user_id=user_id,amount_cents=amount,bank_account=account,account_name=name,request_key=request_key)
    db.session.add(item);db.session.flush()
    db.session.add(RewardLedger(user_id=user_id,delta_cents=-amount,available_at=datetime.utcnow(),kind='withdrawal_reserve',description=f'Rezervace pro výplatu č. {item.id}',entry_key=f'withdrawal-reserve-{item.id}',withdrawal_id=item.id))
    return item


def handle_withdrawal(item, action, reference, note, admin_id):
    if len(reference)>100 or len(note)>300:
        raise ValueError('Zkraťte poznámku nebo referenci platby.')
    if action=='processing':
        if item.status=='processing':return
        if item.status!='requested':raise ValueError('Tuto žádost už nelze převzít.')
        item.status='processing'
    elif action=='paid':
        if item.status=='paid':return
        if item.status not in ['requested','processing']:raise ValueError('Tuto žádost už nelze vyplatit.')
        if not reference.strip():raise ValueError('Nejdřív odešlete převod v bance a vyplňte referenci platby.')
        item.status='paid';item.payment_reference=reference.strip()
    elif action=='rejected':
        if item.status=='rejected':return
        if item.status not in ['requested','processing']:raise ValueError('Vyplacenou žádost nelze zamítnout.')
        if not note.strip():raise ValueError('Uveďte důvod zamítnutí pro zákazníka.')
        db.session.add(RewardLedger(user_id=item.user_id,delta_cents=item.amount_cents,available_at=datetime.utcnow(),kind='withdrawal_release',description=f'Vrácení rezervace zamítnuté výplaty č. {item.id}',entry_key=f'withdrawal-release-{item.id}',withdrawal_id=item.id,created_by=admin_id))
        item.status='rejected'
    else:
        raise ValueError('Neplatná změna stavu.')
    item.admin_note=note.strip();item.handled_by=admin_id;item.updated_at=datetime.utcnow()
