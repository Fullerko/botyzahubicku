from app import create_app, db
from app.utils import set_setting

app = create_app()

with app.app_context():
    set_setting('smtp_host', 'smtp.websupport.cz')
    set_setting('smtp_port', '587')
    set_setting('smtp_username', 'info@botyzahubicku.cz')
    set_setting('smtp_password', '123456Web!')
    set_setting('smtp_sender', 'info@botyzahubicku.cz')
    set_setting('smtp_use_tls', '1')
    db.session.commit()

print("SMTP nastaveno.")