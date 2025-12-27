import os
import secrets

class Config:
    # Persistent Secret Key
    key_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'secret.key')
    if os.path.exists(key_file):
        with open(key_file, 'r') as f:
            SECRET_KEY = f.read().strip()
    else:
        SECRET_KEY = secrets.token_hex(32)
        try:
            with open(key_file, 'w') as f:
                f.write(SECRET_KEY)
        except:
            pass
            
    SQLALCHEMY_DATABASE_URI = os.environ.get('HOSEINPROXY_DATABASE_URI', 'sqlite:///panel.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
