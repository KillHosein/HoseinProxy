
import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

from app import create_app
from app.extensions import db
from sqlalchemy import inspect, text

app = create_app()

with app.app_context():
    print("Checking database schema...")
    inspector = inspect(db.engine)
    
    if not inspector.has_table('proxy'):
        print("Error: 'proxy' table does not exist!")
        sys.exit(1)
        
    columns = {c['name'] for c in inspector.get_columns('proxy')}
    print(f"Existing columns in 'proxy' table: {columns}")
    
    required_columns = ['name', 'proxy_ip', 'proxy_type', 'tls_domain']
    missing = [c for c in required_columns if c not in columns]
    
    if missing:
        print(f"Error: Missing columns: {missing}")
        print("Attempting to fix...")
        try:
            with db.engine.connect() as conn:
                for col in missing:
                    print(f"Adding column {col}...")
                    if col == 'name':
                        conn.execute(text('ALTER TABLE proxy ADD COLUMN name VARCHAR(100)'))
                    elif col == 'proxy_ip':
                        conn.execute(text('ALTER TABLE proxy ADD COLUMN proxy_ip VARCHAR(50)'))
                    elif col == 'proxy_type':
                         conn.execute(text('ALTER TABLE proxy ADD COLUMN proxy_type VARCHAR(20) DEFAULT "standard"'))
                    elif col == 'tls_domain':
                         conn.execute(text('ALTER TABLE proxy ADD COLUMN tls_domain VARCHAR(255)'))
                conn.commit()
            print("Fix attempted. Please restart the panel.")
        except Exception as e:
            print(f"Failed to fix database: {e}")
    else:
        print("Database schema looks correct.")
        
    print("Testing query...")
    try:
        from app.models import Proxy
        p = Proxy.query.first()
        print("Query successful.")
    except Exception as e:
        print(f"Query failed: {e}")
        import traceback
        traceback.print_exc()
