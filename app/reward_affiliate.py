"""Invitation links and compatibility for the original affiliate URLs."""
import io
from datetime import datetime
import qrcode
from flask import Blueprint,Response,abort,flash,redirect,render_template,request,session,url_for
from flask_login import current_user,login_required
from sqlalchemy.exc import IntegrityError
from . import db
from .models import AffiliatePartner,AffiliatePayoutRequest,Coupon,User
from .utils import admin_required
from .mobile import protect_mobile_writes
from .reward_models import RewardMember,RewardPurchase,RewardLedger
from .reward_affiliate_models import RewardAffiliateAccount,RewardReferral,RewardCommission,RewardMaintenance
from .reward_affiliate_service import bind_referral,ensure_account,resolve_invite,sync_orders,review_legacy
from .reward_service import begin_money_write,balances,parse_amount,money

affiliate_bp=Blueprint('reward_affiliate',__name__)


def refresh_account(user_id):
    try:
        begin_money_write()
        account=RewardAffiliateAccount.query.filter_by(user_id=user_id).first()
        if not account:
            user=db.session.get(User,user_id)
            if AffiliatePartner.query.filter(db.func.lower(db.func.trim(AffiliatePartner.email))==user.email.strip().lower()).count():account=ensure_account(user_id)
        if account:sync_orders(account)
        db.session.commit()
    except (ValueError,IntegrityError) as problem:
        db.session.rollback()
        flash(str(problem) if isinstance(problem,ValueError) else 'Účet vyžaduje kontrolu správce.','warning')


def init_affiliate(app):
    app.register_blueprint(affiliate_bp)
    # A single customer portal and payout path replace the two legacy POST blocks.
    app.view_functions['shop.affiliate_portal']=login_required(lambda:redirect(url_for('rewards.wallet',_anchor='pozvanky')))
    app.view_functions['shop.affiliate']=lambda:redirect(url_for('rewards.wallet',_anchor='pozvanky'))
    app.view_functions['admin.affiliate_dashboard']=admin_required(lambda:redirect(url_for('reward_affiliate.admin_affiliate')))
    from . import routes_shop
    original_resolver=routes_shop._resolve_affiliate_for_order
    def stable_order_affiliate(coupon_info):
        if current_user.is_authenticated:
            referral=RewardReferral.query.filter_by(user_id=current_user.id).first()
            if referral:
                account=db.session.get(RewardAffiliateAccount,referral.affiliate_account_id)
                coupon=Coupon.query.filter_by(code=account.invite_code,active=True).first()
                if coupon and coupon.affiliate_partner.status=='Aktivní':return coupon,coupon_info.get('code','')
                return None,coupon_info.get('code','')
        return original_resolver(coupon_info)
    routes_shop._resolve_affiliate_for_order=stable_order_affiliate
    @app.before_request
    def web_invitee_discount():
        if request.endpoint not in {'shop.cart','shop.checkout'} or not current_user.is_authenticated or session.get('coupon'):return
        referral=RewardReferral.query.filter_by(user_id=current_user.id).first()
        if not referral:return
        account=db.session.get(RewardAffiliateAccount,referral.affiliate_account_id)
        coupon=Coupon.query.filter_by(code=account.invite_code,active=True).first()
        if coupon and coupon.affiliate_partner.status=='Aktivní':
            session['coupon']={'code':coupon.code,'type':'percent','discount_percent_client':5,'commission_percent_partner':5,'affiliate_partner_id':account.partner_id,'affiliate_partner_name':coupon.affiliate_partner.name,'split_text':'5 % zákazník / 5 % partner'}
    @app.before_request
    def legacy_write_guard():
        if request.method!='POST':return
        if request.endpoint=='auth.register':
            begin_money_write()
            email=request.form.get('email','').strip().lower()
            if User.query.filter(db.func.lower(db.func.trim(User.email))==email).first():
                flash('Účet s tímto e-mailem již existuje. Přihlaste se; druhý účet nebyl vytvořen.','warning')
                return redirect(url_for('auth.login'))
        if request.endpoint in {'admin.coupon_new','admin.coupon_edit'}:
            if not current_user.is_authenticated or not current_user.is_admin:abort(403)
            begin_money_write()
            proposed=request.form.get('code','').strip().upper()
            query=Coupon.query.filter(db.func.upper(db.func.trim(Coupon.code))==proposed)
            own_id=(request.view_args or {}).get('coupon_id')
            if own_id:query=query.filter(Coupon.id!=own_id)
            if query.first():
                flash('Tento kód již existuje, i když se liší velikostí písmen. Druhý kód nebyl vytvořen.','warning')
                return redirect(url_for('reward_affiliate.admin_affiliate'))
        if request.endpoint=='admin.coupon_edit':
            fixed=RewardAffiliateAccount.query.join(Coupon,Coupon.code==RewardAffiliateAccount.invite_code).filter(Coupon.id==(request.view_args or {}).get('coupon_id')).first()
            if fixed:
                try:
                    changed=(request.form.get('code','').strip().upper()!=fixed.invite_code or float(request.form.get('discount_percent_client',0))!=5 or float(request.form.get('commission_percent_partner',0))!=5 or int(request.form.get('affiliate_partner_id',0) or 0)!=fixed.partner_id)
                except ValueError:changed=True
                if changed:
                    flash('Pozvánkový kód aplikace má pevně 5 % + 5 % a své ID partnera. Upravujte jiné webové kódy.','warning')
                    return redirect(url_for('reward_affiliate.admin_affiliate'))
        if request.endpoint in {'admin.affiliate_partner_new','admin.affiliate_partner_edit'}:
            if not current_user.is_authenticated or not current_user.is_admin:abort(403)
            if request.form.get('pay_amount'):
                flash('Výplaty vyřizujte pouze přes Moje odměny. Historický formulář už nesmí odepisovat peníze.','warning')
                return redirect(url_for('reward_affiliate.admin_affiliate'))
            begin_money_write()
            email=request.form.get('email','').strip().lower()
            own_id=(request.view_args or {}).get('partner_id')
            if email:
                query=AffiliatePartner.query.filter(db.func.lower(db.func.trim(AffiliatePartner.email))==email)
                if own_id:query=query.filter(AffiliatePartner.id!=own_id)
                if query.first():
                    flash('Affiliate účet pro tento e-mail již existuje. Druhý účet nebyl vytvořen.','warning')
                    return redirect(url_for('reward_affiliate.admin_affiliate'))
    @app.after_request
    def refresh_online_payment(response):
        if request.method=='POST' and request.endpoint in {'shop.mark_paid_api','admin.order_detail'} and response.status_code<400:
            try:
                begin_money_write()
                for account in RewardAffiliateAccount.query.all():sync_orders(account)
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception('Affiliate sync failed; next wallet/withdrawal retries safely')
        return response


@affiliate_bp.before_request
def protect():return protect_mobile_writes()


@affiliate_bp.after_request
def private(response):
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer';response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


@affiliate_bp.app_context_processor
def invitation_context():
    if request.blueprint not in {'rewards','reward_affiliate'}:
        return {}
    account=None;referral=None;inviter=None
    if current_user.is_authenticated:
        account=RewardAffiliateAccount.query.filter_by(user_id=current_user.id).first()
        referral=RewardReferral.query.filter_by(user_id=current_user.id).first()
        if referral:
            a=db.session.get(RewardAffiliateAccount,referral.affiliate_account_id);inviter=db.session.get(AffiliatePartner,a.partner_id)
    return {'reward_affiliate':account,'reward_inviter':inviter,'reward_can_attach':current_user.is_authenticated and not RewardPurchase.query.filter_by(user_id=current_user.id).first(),'reward_invite_candidate':session.get('reward_invite','') or request.cookies.get('bzh_reward_invite','') or request.cookies.get('bzh_affiliate_code','')}


@affiliate_bp.get('/pozvat/<code>')
def invitation(code):
    try:
        begin_money_write();account=resolve_invite(code)
        if not account:raise ValueError('Pozvánkový kód chybí.')
        partner=db.session.get(AffiliatePartner,account.partner_id)
        name=partner.name
        db.session.commit()
    except (ValueError,IntegrityError) as problem:
        db.session.rollback()
        return render_template('rewards/invitation.html',error=str(problem),code=code,name=''),400
    session['reward_invite']=code.strip().upper()
    response=Response(render_template('rewards/invitation.html',error=None,code=code.strip().upper(),name=name))
    response.set_cookie('bzh_reward_invite',code.strip().upper(),max_age=90*86400,httponly=True,samesite='Lax',secure=request.is_secure)
    return response


@affiliate_bp.route('/odmeny/pozvanky',methods=['GET','POST'])
@login_required
def invites():
    if not RewardMember.query.filter_by(user_id=current_user.id).first():return redirect(url_for('rewards.wallet'))
    if request.method=='POST':
        try:
            begin_money_write();ensure_account(current_user.id);db.session.commit()
        except (ValueError,IntegrityError) as problem:
            db.session.rollback();flash(str(problem) if isinstance(problem,ValueError) else 'Účet už existuje. Obnovte stránku.','warning')
    refresh_account(current_user.id)
    account=RewardAffiliateAccount.query.filter_by(user_id=current_user.id).first()
    count=RewardReferral.query.filter_by(affiliate_account_id=account.id).count() if account else 0
    commissions=RewardCommission.query.filter_by(affiliate_account_id=account.id).order_by(RewardCommission.id.desc()).limit(100).all() if account else []
    coupons=Coupon.query.filter_by(affiliate_partner_id=account.partner_id).all() if account else []
    earned=db.session.query(db.func.coalesce(db.func.sum(RewardLedger.delta_cents),0)).filter(RewardLedger.user_id==current_user.id,RewardLedger.kind.in_(['referral_commission','referral_refund'])).scalar()
    return render_template('rewards/invites.html',account=account,invited_count=count,commissions=commissions,coupons=coupons,earned=int(earned),enabled=bool(account and db.session.get(AffiliatePartner,account.partner_id).status=='Aktivní'),balance=balances(current_user.id))


@affiliate_bp.post('/odmeny/pozvanka')
@login_required
def attach():
    try:
        begin_money_write()
        code=request.form.get('invite_code','').strip()
        if not code:raise ValueError('Vyplňte pozvánkový kód.')
        bind_referral(current_user.id,code)
        db.session.commit();session.pop('reward_invite',None)
        flash('Pozvánka je přiřazená. Při příštím QR nákupu se provize spáruje automaticky.','success')
    except (ValueError,IntegrityError) as problem:
        db.session.rollback();flash(str(problem) if isinstance(problem,ValueError) else 'Pozvánka už byla přiřazená.','warning')
    return redirect(url_for('rewards.wallet'))


@affiliate_bp.get('/odmeny/pozvanky/qr.png')
@login_required
def invite_qr():
    account=RewardAffiliateAccount.query.filter_by(user_id=current_user.id).first()
    if not account:abort(403)
    target=url_for('reward_affiliate.invitation',code=account.invite_code,_external=True,_scheme='https')
    output=io.BytesIO();qrcode.make(target).save(output,format='PNG')
    return Response(output.getvalue(),mimetype='image/png')


@affiliate_bp.route('/admin/odmeny/affiliate',methods=['GET','POST'])
@admin_required
def admin_affiliate():
    if request.method=='POST':
        errors=[]
        begin_money_write()
        for partner in AffiliatePartner.query.filter_by(status='Aktivní').all():
            users=User.query.filter(db.func.lower(db.func.trim(User.email))==partner.email.strip().lower()).all()
            if len(users)!=1:errors.append(f'Partner #{partner.id}: uživatelský účet není jednoznačný.');continue
            try:
                with db.session.begin_nested():ensure_account(users[0].id)
            except ValueError as problem:errors.append(f'Partner #{partner.id}: {problem}')
        db.session.commit()
        flash('Jednoznačné účty připojeny. '+(' '.join(errors) if errors else ''),'warning' if errors else 'success')
        return redirect(url_for('reward_affiliate.admin_affiliate'))
    begin_money_write()
    for account in RewardAffiliateAccount.query.all():sync_orders(account)
    db.session.commit()
    rows=[(a,db.session.get(User,a.user_id),db.session.get(AffiliatePartner,a.partner_id),balances(a.user_id)) for a in RewardAffiliateAccount.query.order_by(RewardAffiliateAccount.id.desc()).all()]
    partners=AffiliatePartner.query.order_by(AffiliatePartner.id).all()
    old_requests=AffiliatePayoutRequest.query.filter_by(status='Čeká').all()
    from .reward_audit import audit
    return render_template('rewards/admin_affiliate.html',rows=rows,partners=partners,old_requests=old_requests,audit=audit())


@affiliate_bp.post('/admin/odmeny/affiliate/<int:account_id>/historie')
@admin_required
def review(account_id):
    try:
        raw=request.form.get('amount','').strip()
        amount=0 if raw in {'0','0,00','0.00'} else parse_amount(raw)
        begin_money_write();account=db.get_or_404(RewardAffiliateAccount,account_id)
        review_legacy(account,amount,request.form.get('note','').strip(),current_user.id)
        db.session.commit();flash('Historie převedena jednou. Další výplaty už probíhají jen přes společnou peněženku.','success')
    except (ValueError,IntegrityError) as problem:
        db.session.rollback();flash(str(problem) if isinstance(problem,ValueError) else 'Převod už byl proveden.','danger')
    return redirect(url_for('reward_affiliate.admin_affiliate'))


@affiliate_bp.post('/admin/odmeny/affiliate/duplicity')
@admin_required
def cleanup():
    from .reward_audit import cleanup_exact_duplicates
    try:
        begin_money_write();report=cleanup_exact_duplicates(current_user.id);db.session.commit()
        flash(f'Záloha vytvořena. Odstraněno pouze {len(report["deleted_partners"])} prázdných duplicitních partnerů a {len(report["deleted_coupons"])} nepoužitých duplicitních kódů. Nejasné a finanční záznamy zůstaly zachované.','success')
    except (ValueError,IntegrityError,OSError) as problem:
        db.session.rollback();flash(f'Čištění neprovedeno: {problem}','danger')
    return redirect(url_for('reward_affiliate.admin_affiliate'))
