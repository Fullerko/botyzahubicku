"""Customer wallet + admin QR scanning, purchases, refunds and manual payouts."""
import io
import secrets
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo
import qrcode
from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for, send_file
from flask_login import current_user, login_required
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from . import db
from .models import User, Order, Product
from .utils import admin_required
from .mobile import csrf_token, protect_mobile_writes
from .reward_models import RewardMember, RewardPurchase, RewardWithdrawal, RewardLedger
from .reward_service import HOLD_DAYS, MIN_WITHDRAWAL_CENTS, balances, bank_account, begin_money_write, handle_withdrawal, join_program, money, nonce, parse_amount, record_purchase, refund_purchase, request_withdrawal

rewards_bp=Blueprint('rewards',__name__)
STATUS_LABELS={'requested':'Čeká na vyřízení','processing':'Zpracovává se','paid':'Vyplaceno','rejected':'Zamítnuto'}


def init_rewards(app):
    app.register_blueprint(rewards_bp)
    with app.app_context():
        with db.engine.begin() as connection:
            if db.engine.dialect.name=='sqlite':connection.exec_driver_sql('BEGIN IMMEDIATE')
            from .reward_affiliate_models import RewardAffiliateAccount,RewardReferral,RewardCommission,RewardAffiliateOrder,RewardMaintenance,RewardOnlineAttribution
            for model in (RewardMember,RewardPurchase,RewardWithdrawal,RewardLedger,RewardAffiliateAccount,RewardReferral,RewardCommission,RewardAffiliateOrder,RewardMaintenance,RewardOnlineAttribution):
                model.__table__.create(bind=connection,checkfirst=True)
    from .reward_affiliate import init_affiliate
    init_affiliate(app)


@rewards_bp.before_request
def protect():
    return protect_mobile_writes()


@rewards_bp.after_request
def private(response):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


@rewards_bp.app_context_processor
def context():
    def local_date(value):
        if not value:return ''
        from datetime import timezone
        return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/Prague')).strftime('%d.%m.%Y %H:%M')
    return {'reward_money':money,'reward_local_date':local_date,'reward_status':STATUS_LABELS,'reward_hold_days':HOLD_DAYS}


def member_for_user():
    return RewardMember.query.filter_by(user_id=current_user.id).first()


def signer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'],salt='bzh-reward-qr-v1')


@rewards_bp.route('/muj-ucet', methods=['GET','POST'])
@login_required
def account():
    if request.method == 'POST':
        name=request.form.get('full_name','').strip()
        address=request.form.get('address','').strip()
        city=request.form.get('city','').strip()
        postal=request.form.get('postal_code','').strip()
        if not name or len(name)>120 or len(address)>255 or len(city)>80 or len(postal)>20:
            flash('Zkontrolujte prosím zadané údaje.','danger')
        else:
            current_user.full_name=name
            current_user.address=address
            current_user.city=city
            current_user.postal_code=postal
            db.session.commit()
            flash('Údaje účtu byly uloženy.','success')
        return redirect(url_for('rewards.account'))
    member=member_for_user()
    page=max(1,request.args.get('page',1,type=int) or 1)
    pagination=Order.query.filter_by(user_id=current_user.id).options(selectinload(Order.items)).order_by(Order.created_at.desc(),Order.id.desc()).paginate(page=page,per_page=20,error_out=False)
    orders=pagination.items
    product_ids={item.product_id for order in orders for item in order.items}
    products={p.id:p for p in Product.query.filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    return render_template('rewards/account.html',member=member,balance=balances(current_user.id),orders=orders,
        order_count=pagination.total,pagination=pagination,products=products)


@rewards_bp.get('/odmeny')
@login_required
def wallet():
    from .reward_affiliate import refresh_account
    refresh_account(current_user.id)
    from .reward_affiliate_models import RewardAffiliateAccount,RewardReferral
    affiliate=RewardAffiliateAccount.query.filter_by(user_id=current_user.id).first()
    invited_count=RewardReferral.query.filter_by(affiliate_account_id=affiliate.id).count() if affiliate else 0
    member=member_for_user()
    return render_template('rewards/wallet.html',affiliate=affiliate,invited_count=invited_count,member=member,balance=balances(current_user.id),
        ledger=RewardLedger.query.filter_by(user_id=current_user.id).order_by(RewardLedger.id.desc()).limit(100).all(),
        withdrawals=RewardWithdrawal.query.filter_by(user_id=current_user.id).order_by(RewardWithdrawal.id.desc()).limit(30).all(),now=datetime.utcnow())


@rewards_bp.post('/odmeny/aktivovat')
@login_required
def activate():
    if request.form.get('accept')!='on':
        flash('Pro aktivaci potvrďte podmínky programu odměn.','danger')
        return redirect(url_for('rewards.wallet'))
    try:
        begin_money_write()
        from .reward_affiliate_service import ensure_account,bind_referral
        from flask import session
        code=request.form.get('invite_code','').strip() if 'invite_code' in request.form else (session.get('reward_invite','') or request.cookies.get('bzh_reward_invite','') or request.cookies.get('bzh_affiliate_code',''))
        if code:bind_referral(current_user.id,code)
        join_program(current_user.id)
        try:
            with db.session.begin_nested():ensure_account(current_user.id)
        except ValueError as affiliate_problem:
            flash('Odměny aktivované, ale affiliate účet potřebuje kontrolu: '+str(affiliate_problem),'warning')
        db.session.commit()
        session.pop('reward_invite',None)
    except (IntegrityError,ValueError) as problem:
        db.session.rollback()
        flash(str(problem) if isinstance(problem,ValueError) else 'Aktivace již byla zpracována. Obnovte stránku.','danger')
        return redirect(url_for('rewards.wallet'))
    flash('Moje odměny jsou aktivní. Při nákupu ukažte svůj QR kód.','success')
    return redirect(url_for('rewards.wallet'))


@rewards_bp.get('/odmeny/qr.png')
@login_required
def customer_qr():
    member=member_for_user()
    if not member:abort(403)
    token=signer().dumps({'member':member.id,'secret':member.qr_secret})
    target=url_for('rewards.scan',t=token,_external=True,_scheme='https')
    image=qrcode.make(target,error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=8,border=4)
    output=io.BytesIO();image.save(output,format='PNG')
    return Response(output.getvalue(),mimetype='image/png')


def lookup_member(value):
    value=(value or '').strip()
    if len(value)>3000:raise ValueError('Neplatný QR kód.')
    if value.startswith(('https://','http://')):
        parsed=urlsplit(value)
        if parsed.netloc!=request.host or parsed.path!='/admin/odmeny/nacist':
            raise ValueError('Tento QR kód nepatří našemu programu odměn.')
        value=parse_qs(parsed.query).get('t',[''])[0]
    elif value.startswith('reward:'):
        value=value[7:]
    if len(value)==10 and all(ch in '0123456789abcdefABCDEF' for ch in value):
        member=RewardMember.query.filter_by(public_code=value.upper()).first()
        if not member:raise ValueError('Zákaznický kód nebyl nalezen.')
        return member
    try:
        data=signer().loads(value,max_age=180)
        if not isinstance(data,dict):raise BadSignature('invalid')
        member=db.session.get(RewardMember,data.get('member'))
        if not member or not secrets.compare_digest(member.qr_secret,str(data.get('secret',''))):raise BadSignature('invalid')
        return member
    except SignatureExpired:
        raise ValueError('QR kód vypršel. Požádejte zákazníka, aby jej v aplikaci obnovil.')
    except (BadSignature,TypeError,ValueError):
        raise ValueError('Neplatný QR kód. Zkuste zákaznický kód pod QR obrázkem.')


@rewards_bp.route('/admin/odmeny/nacist',methods=['GET','POST'])
@admin_required
def scan():
    error=None
    value=request.form.get('code') if request.method=='POST' else request.args.get('t')
    if value:
        try:
            member=lookup_member(value)
            return redirect(url_for('rewards.admin_member',member_id=member.id))
        except ValueError as problem:error=str(problem)
    return render_template('rewards/scanner.html',error=error)


@rewards_bp.get('/admin/odmeny')
@admin_required
def admin_index():
    search=request.args.get('q','').strip()[:120]
    query=db.session.query(RewardMember,User).join(User,User.id==RewardMember.user_id)
    if search:query=query.filter(db.or_(User.email.contains(search),User.full_name.contains(search),RewardMember.public_code.contains(search.upper())))
    members=query.order_by(RewardMember.id.desc()).limit(100).all()
    withdrawals=db.session.query(RewardWithdrawal,User).join(User,User.id==RewardWithdrawal.user_id).order_by(RewardWithdrawal.status.in_(['requested','processing']).desc(),RewardWithdrawal.id.desc()).limit(100).all()
    return render_template('rewards/admin_index.html',members=members,withdrawals=withdrawals,search=search)


@rewards_bp.get('/admin/odmeny/clen/<int:member_id>')
@admin_required
def admin_member(member_id):
    member=db.get_or_404(RewardMember,member_id)
    user=db.get_or_404(User,member.user_id)
    from .reward_affiliate_service import RewardReferral,RewardAffiliateAccount
    referral=RewardReferral.query.filter_by(user_id=user.id).first()
    inviter=db.session.get(User,db.session.get(RewardAffiliateAccount,referral.affiliate_account_id).user_id) if referral else None
    return render_template('rewards/admin_member.html',inviter=inviter,member=member,user=user,balance=balances(user.id),purchases=RewardPurchase.query.filter_by(user_id=user.id).order_by(RewardPurchase.id.desc()).limit(100).all(),ledger=RewardLedger.query.filter_by(user_id=user.id).order_by(RewardLedger.id.desc()).limit(100).all())


@rewards_bp.post('/admin/odmeny/clen/<int:member_id>/nakup')
@admin_required
def purchase(member_id):
    try:
        amount=parse_amount(request.form.get('amount'))
        reference=request.form.get('reference','').strip()
        note=request.form.get('note','').strip()
        key=nonce(request.form.get('request_key'))
        begin_money_write()
        member=db.get_or_404(RewardMember,member_id)
        item=record_purchase(member,amount,reference,note,key,current_user.id)
        db.session.commit()
        flash(f'Nákup uložen. Odměna {money(item.cashback_cents)} bude dostupná za {HOLD_DAYS} dní.','success')
    except (ValueError,IntegrityError) as problem:
        db.session.rollback()
        flash(str(problem) if isinstance(problem,ValueError) else 'Tento nákup už byl uložen. Zkontrolujte historii.','danger')
    return redirect(url_for('rewards.admin_member',member_id=member_id))


@rewards_bp.post('/admin/odmeny/nakup/<int:purchase_id>/storno')
@admin_required
def refund(purchase_id):
    member_id=None
    try:
        amount=parse_amount(request.form.get('amount'))
        key=nonce(request.form.get('request_key'))
        begin_money_write()
        item=db.get_or_404(RewardPurchase,purchase_id)
        member_id=RewardMember.query.filter_by(user_id=item.user_id).first().id
        refund_purchase(item,amount,key,current_user.id)
        db.session.commit()
        flash('Vrácená část nákupu byla uložena. Odměna zákazníka i případná provize pozývajícího byly stornovány.','success')
    except (ValueError,IntegrityError) as problem:
        db.session.rollback()
        flash(str(problem) if isinstance(problem,ValueError) else 'Storno už bylo zpracováno.','danger')
    return redirect(url_for('rewards.admin_member',member_id=member_id) if member_id else url_for('rewards.admin_index'))


@rewards_bp.route('/odmeny/vyber',methods=['GET','POST'])
@login_required
def withdraw():
    if not member_for_user():return redirect(url_for('rewards.wallet'))
    error=None
    if request.method=='POST':
        try:
            key=nonce(request.form.get('request_key'))
            begin_money_write()
            item=request_withdrawal(current_user.id,request.form.get('account'),request.form.get('name',''),key)
            db.session.commit()
            flash(f'Žádost o výplatu {money(item.amount_cents)} byla přijata. Částka je nyní rezervovaná.','success')
            return redirect(url_for('rewards.wallet'))
        except (ValueError,IntegrityError) as problem:
            db.session.rollback()
            error=str(problem) if isinstance(problem,ValueError) else 'Žádost už byla zpracována. Zkontrolujte přehled.'
    return render_template('rewards/withdraw.html',balance=balances(current_user.id),error=error,values=request.form)


@rewards_bp.route('/admin/odmeny/vyplata/<int:withdrawal_id>',methods=['GET','POST'])
@admin_required
def payout(withdrawal_id):
    error=None
    if request.method=='POST':
        try:
            begin_money_write()
            item=db.get_or_404(RewardWithdrawal,withdrawal_id)
            handle_withdrawal(item,request.form.get('action'),request.form.get('reference','').strip(),request.form.get('note','').strip(),current_user.id)
            db.session.commit()
            flash('Stav žádosti byl uložen.','success')
            return redirect(url_for('rewards.payout',withdrawal_id=item.id))
        except (ValueError,IntegrityError) as problem:
            db.session.rollback()
            error=str(problem) if isinstance(problem,ValueError) else 'Změna už byla zpracována.'
    item=db.get_or_404(RewardWithdrawal,withdrawal_id)
    user=db.get_or_404(User,item.user_id)
    return render_template('rewards/payout.html',item=item,user=user,error=error,balance=balances(user.id))


@rewards_bp.get('/muj-ucet/objednavky/<int:order_id>')
@login_required
def order_detail(order_id):
    # Scope the query to the owner, including for admins viewing the customer area.
    order=Order.query.filter_by(id=order_id,user_id=current_user.id).options(selectinload(Order.items)).first_or_404()
    product_ids={item.product_id for item in order.items}
    products={p.id:p for p in Product.query.filter(Product.id.in_(product_ids)).all()} if product_ids else {}
    return render_template('rewards/order_detail.html',order=order,products=products)


@rewards_bp.get('/muj-ucet/objednavky/<int:order_id>/doklad.pdf')
@login_required
def order_invoice(order_id):
    order=Order.query.filter_by(id=order_id,user_id=current_user.id).options(selectinload(Order.items)).first_or_404()
    from .invoice_utils import generate_invoice_pdf
    return send_file(generate_invoice_pdf(order),mimetype='application/pdf',as_attachment=True,download_name=f'objednavka-{order.order_number}.pdf')
