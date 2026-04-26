from datetime import datetime, timedelta
import secrets
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from . import db
from .models import PasswordResetToken, User
from .utils import send_email


auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('shop.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Přihlášení proběhlo úspěšně.', 'success')
            return redirect(request.args.get('next') or url_for('shop.index'))
        flash('Neplatný e-mail nebo heslo.', 'danger')
    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('shop.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if User.query.filter_by(email=email).first():
            flash('Tento e-mail už existuje.', 'warning')
            return redirect(url_for('auth.register'))
        user = User(
            email=email,
            full_name=request.form.get('full_name', '').strip(),
            password_hash=generate_password_hash(request.form.get('password', '')),
            address=request.form.get('address', '').strip(),
            city=request.form.get('city', '').strip(),
            postal_code=request.form.get('postal_code', '').strip(),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Účet byl vytvořen.', 'success')
        return redirect(url_for('shop.index'))
    return render_template('auth/register.html')


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(32)
            row = PasswordResetToken(user_id=user.id, token=token, expires_at=datetime.utcnow() + timedelta(hours=2))
            db.session.add(row)
            db.session.commit()
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            mode = send_email(
                'Reset hesla – BotyZaHubicku',
                user.email,
                f'<p>Dobrý den,</p><p>pro reset hesla klikněte na tento odkaz:</p><p><a href="{reset_url}">{reset_url}</a></p><p>Odkaz platí 2 hodiny.</p>',
                f'Reset hesla: {reset_url}'
            )
            if mode == 'smtp':
                flash('Na e-mail byl odeslán odkaz pro reset hesla.', 'success')
            else:
                flash('SMTP není nastavené. Odkaz byl uložen do instance/outbox/emails.log pro lokální test.', 'warning')
        else:
            flash('Pokud účet existuje, odeslali jsme odkaz pro reset hesla.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    row = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not row or row.expires_at < datetime.utcnow():
        flash('Odkaz pro reset hesla je neplatný nebo vypršel.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if len(password) < 6:
            flash('Heslo musí mít alespoň 6 znaků.', 'warning')
            return redirect(request.url)
        if password != password2:
            flash('Hesla se neshodují.', 'warning')
            return redirect(request.url)
        row.user.password_hash = generate_password_hash(password)
        row.used = True
        db.session.commit()
        flash('Heslo bylo změněno. Teď se můžeš přihlásit.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Byli jste odhlášeni.', 'info')
    return redirect(url_for('shop.index'))
