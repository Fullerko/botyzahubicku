from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from . import db
from .emailing_service import ensure_suppression
from .models import EmailContact

emailing_bp = Blueprint('emailing', __name__)


@emailing_bp.route('/unsubscribe/<token>', methods=['GET', 'POST'])
def unsubscribe(token):
    contact = EmailContact.query.filter_by(unsubscribe_token=token).first_or_404()
    if request.method == 'POST':
        contact.marketing_enabled = False
        contact.unsubscribed_at = contact.unsubscribed_at or datetime.utcnow()
        ensure_suppression(contact.email, reason='unsubscribe')
        db.session.commit()
        flash('Byli jste odhlášeni z marketingových e-mailů.', 'success')
        return redirect(url_for('shop.index'))
    return render_template('shop/unsubscribe.html', contact=contact)


@emailing_bp.route('/unsubscribe/<token>/confirm', methods=['POST'])
def unsubscribe_confirm(token):
    return unsubscribe(token)
