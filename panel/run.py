from app import create_app
from app.extensions import db
from app.models import User

app = create_app()

def create_admin(username, password):
    with app.app_context():
        db.create_all()
        user = User.query.filter_by(username=username).first()
        if not user:
            u = User(username=username)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            print(f"User {username} created successfully.")
        else:
            u.set_password(password)
            db.session.commit()
            print(f"User {username} password updated.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
