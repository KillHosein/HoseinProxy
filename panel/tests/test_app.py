import unittest
import os
import sys

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, User

class HoseinProxyTestCase(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['WTF_CSRF_ENABLED'] = False
        
        self.app = app.test_client()
        
        with app.app_context():
            db.create_all()
            
            # Create test user
            u = User(username='admin')
            u.set_password('password')
            db.session.add(u)
            db.session.commit()

    def tearDown(self):
        """Clean up after tests"""
        with app.app_context():
            db.session.remove()
            db.drop_all()

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
        self.assertIn(b'Login', response.data)

    def test_valid_login(self):
        """Test valid login"""
        response = self.login('admin', 'password')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dashboard', response.data)

    def test_invalid_login(self):
        """Test invalid login"""
        response = self.login('admin', 'wrongpass')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data) # Should stay on login page
        
    def test_dashboard_access_denied(self):
        """Test that dashboard requires login"""
        response = self.app.get('/', follow_redirects=True)
        self.assertIn(b'Login', response.data)

    def test_dashboard_access_granted(self):
        """Test that dashboard loads after login"""
        self.login('admin', 'password')
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Dashboard', response.data)

if __name__ == '__main__':
    unittest.main()
