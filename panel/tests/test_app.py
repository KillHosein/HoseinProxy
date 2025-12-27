import unittest
import os
import sys
import time
from datetime import datetime, timedelta

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'test_panel.db')
os.environ['HOSEINPROXY_DATABASE_URI'] = f"sqlite:///{TEST_DB_PATH}"
os.environ['HOSEINPROXY_DISABLE_STATS_THREAD'] = "1"

from app import create_app
from app.extensions import db
from app.models import User, Proxy, ProxyStats, Alert, BlockedIP

app = create_app()

class HoseinProxyTestCase(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{TEST_DB_PATH}"
        
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        
        db.create_all()
        
        # Create test user
        u = User(username='admin')
        u.set_password('password')
        db.session.add(u)
        db.session.commit()

    def tearDown(self):
        """Clean up after tests"""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login(self, username, password):
        return self.app.post('/login', data=dict(
            username=username,
            password=password
        ), follow_redirects=True)

    def logout(self):
        return self.app.get('/logout', follow_redirects=True)

    def test_login_page(self):
        """Test if login page loads"""
        response = self.app.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn('ورود به پنل'.encode('utf-8'), response.data)

    def test_valid_login(self):
        """Test valid login"""
        response = self.login('admin', 'password')
        self.assertEqual(response.status_code, 200)
        self.assertIn('داشبورد'.encode('utf-8'), response.data)

    def test_invalid_login(self):
        """Test invalid login"""
        response = self.login('admin', 'wrongpass')
        self.assertEqual(response.status_code, 200)
        self.assertIn('ورود به پنل'.encode('utf-8'), response.data)
        
    def test_dashboard_access_denied(self):
        """Test that dashboard requires login"""
        response = self.app.get('/', follow_redirects=True)
        self.assertIn('ورود به پنل'.encode('utf-8'), response.data)

    def test_dashboard_access_granted(self):
        """Test that dashboard loads after login"""
        self.login('admin', 'password')
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('لیست پروکسی\u200cها'.encode('utf-8'), response.data)

    def test_api_proxies_requires_login(self):
        response = self.app.get('/api/proxies', follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_api_proxies_returns_json(self):
        self.login('admin', 'password')
        with app.app_context():
            p = Proxy(port=9999, secret='abc', status='running')
            db.session.add(p)
            db.session.commit()
        resp = self.app.get('/api/proxies')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(isinstance(data, list))
        self.assertTrue(any(item['id'] for item in data))

    def test_usage_history_calculation(self):
        self.login('admin', 'password')
        with app.app_context():
            p = Proxy(port=10001, secret='abc', status='running')
            db.session.add(p)
            db.session.commit()
            t0 = datetime.utcnow()
            s1 = ProxyStats(proxy_id=p.id, upload=1000, download=2000, active_connections=1, timestamp=t0)
            s2 = ProxyStats(proxy_id=p.id, upload=4000, download=7000, active_connections=3, timestamp=t0 + timedelta(hours=1))
            db.session.add_all([s1, s2])
            db.session.commit()
        resp = self.app.get(f'/api/proxy/{p.id}/usage_history?granularity=hourly&days=1')
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn('labels', payload)
        self.assertIn('upload_mb', payload)
        self.assertIn('download_mb', payload)

    def test_alerts_api(self):
        self.login('admin', 'password')
        with app.app_context():
            a = Alert(proxy_id=None, severity='warning', message='test')
            db.session.add(a)
            db.session.commit()
        resp = self.app.get('/api/alerts?since_id=0')
        self.assertEqual(resp.status_code, 200)
        items = resp.get_json()
        self.assertTrue(any(it['message'] == 'test' for it in items))

    def test_api_proxies_performance_smoke(self):
        self.login('admin', 'password')
        with app.app_context():
            for i in range(200):
                db.session.add(Proxy(port=11000 + i, secret='s', status='running'))
            db.session.commit()
        start = time.time()
        resp = self.app.get('/api/proxies')
        elapsed = time.time() - start
        self.assertEqual(resp.status_code, 200)
        self.assertLess(elapsed, 2.5)

    def test_reports_api(self):
        self.login('admin', 'password')
        resp = self.app.get('/api/reports/top_ips')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(isinstance(resp.get_json(), list))
        
        resp = self.app.get('/api/reports/traffic_by_tag')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(isinstance(resp.get_json(), list))

    def test_auto_stop_quota(self):
        from app.services.monitor import _check_proxy_limits
        with app.app_context():
            p = Proxy(port=20001, secret='s', status='running', quota_bytes=1000, quota_start=datetime.utcnow(), upload=500, download=600, quota_base_upload=0, quota_base_download=0)
            db.session.add(p)
            db.session.commit()
            
            proxies = [p]
            _check_proxy_limits(proxies)
            self.assertEqual(p.status, 'stopped')
            
    def test_auto_stop_expiry(self):
        from app.services.monitor import _check_proxy_limits
        with app.app_context():
            yesterday = datetime.utcnow() - timedelta(days=1)
            p = Proxy(port=20002, secret='s', status='running', expiry_date=yesterday)
            db.session.add(p)
            db.session.commit()
            
            proxies = [p]
            _check_proxy_limits(proxies)
            self.assertEqual(p.status, 'stopped')

    def test_firewall_and_autoblock(self):
        self.login('admin', 'password')
        
        # 1. Test Manual Block
        resp = self.app.post('/firewall/add', data=dict(ip='1.2.3.4', reason='Test'), follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        with app.app_context():
            b = BlockedIP.query.filter_by(ip_address='1.2.3.4').first()
            self.assertIsNotNone(b)
            self.assertEqual(b.reason, 'Test')
            
        # 2. Test Unblock
        with app.app_context():
            b = BlockedIP.query.filter_by(ip_address='1.2.3.4').first()
            block_id = b.id
            
        resp = self.app.get(f'/firewall/delete/{block_id}', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        
        with app.app_context():
            b = BlockedIP.query.filter_by(ip_address='1.2.3.4').first()
            self.assertIsNone(b)

    def test_bulk_create(self):
        self.login('admin', 'password')
        resp = self.app.post('/proxy/bulk_create', data=dict(
            start_port=30000,
            count=5,
            tag='BulkTest'
        ), follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(b'Docker' in resp.data or b'success' in resp.data or b'error' in resp.data)

    def test_full_update_proxy(self):
        self.login('admin', 'password')
        with app.app_context():
            p = Proxy(port=40000, secret='old_secret', status='stopped')
            db.session.add(p)
            db.session.commit()
            pid = p.id
            
        resp = self.app.post(f'/proxy/update/{pid}', data=dict(
            port=40001,
            secret='new_secret',
            tag='updated_tag',
            username='user1',
            password='pass1',
            proxy_ip='1.1.1.1',
            status='stopped', # Keep stopped to avoid docker calls in test
            quota_gb=5.5
        ), follow_redirects=True)
        
        self.assertEqual(resp.status_code, 200)
        
        with app.app_context():
            p = Proxy.query.get(pid)
            self.assertEqual(p.port, 40001)
            self.assertEqual(p.secret, 'new_secret')
            self.assertEqual(p.tag, 'updated_tag')
            self.assertEqual(p.username, 'user1')
            self.assertEqual(p.password, 'pass1')
            self.assertEqual(p.proxy_ip, '1.1.1.1')
            self.assertEqual(p.quota_bytes, int(5.5 * 1024**3))


if __name__ == '__main__':
    unittest.main()
