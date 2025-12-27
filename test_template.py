from flask import Flask, render_template
from datetime import datetime

app = Flask(__name__, template_folder='panel/app/templates')
app.secret_key = 'test'

# Mock objects
class MockProxy:
    def __init__(self, id):
        self.id = id
        self.port = 443 + id
        self.name = f"Proxy {id}"
        self.tag = "test"
        self.status = "running"
        self.active_connections = 5
        self.quota_bytes = 1024 * 1024 * 1024 * 10 # 10 GB
        self.secret = "abcdef123456"
        self.username = "user"
        self.password = "pass"
        self.proxy_ip = "0.0.0.0"
        self.expiry_date = datetime.now()
        self.created_at = datetime.now()

class MockLog:
    def __init__(self):
        self.action = "Test Action"
        self.details = "Test Details"
        self.timestamp = datetime.now()

@app.route('/')
def index():
    proxies = [MockProxy(1), MockProxy(2)]
    logs = [MockLog()]
    return render_template('pages/admin/dashboard.html', proxies=proxies, logs=logs, now=datetime.now(), server_ip="127.0.0.1", server_domain="example.com")

if __name__ == '__main__':
    try:
        with app.app_context():
            print(index())
            print("Template rendered successfully!")
    except Exception as e:
        print(f"Error rendering template: {e}")
        import traceback
        traceback.print_exc()
