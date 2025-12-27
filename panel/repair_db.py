
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
    try:
        inspector = inspect(db.engine)
        
        if not inspector.has_table('proxy'):
            print("Error: 'proxy' table does not exist!")
            # We rely on create_app -> _ensure_db_initialized to create it if it's missing entirely
            # But if it exists, we check columns
        else:
            columns = {c['name'] for c in inspector.get_columns('proxy')}
            print(f"Existing columns in 'proxy' table: {columns}")
            
            # Map of column name to SQL definition
            required_columns = {
                'name': 'ALTER TABLE proxy ADD COLUMN name VARCHAR(100)',
                'proxy_ip': 'ALTER TABLE proxy ADD COLUMN proxy_ip VARCHAR(50)',
                'proxy_type': 'ALTER TABLE proxy ADD COLUMN proxy_type VARCHAR(20) DEFAULT "standard"',
                'tls_domain': 'ALTER TABLE proxy ADD COLUMN tls_domain VARCHAR(255)',
                'active_connections': 'ALTER TABLE proxy ADD COLUMN active_connections INTEGER DEFAULT 0',
                'upload_rate_bps': 'ALTER TABLE proxy ADD COLUMN upload_rate_bps BIGINT DEFAULT 0',
                'download_rate_bps': 'ALTER TABLE proxy ADD COLUMN download_rate_bps BIGINT DEFAULT 0',
                'quota_bytes': 'ALTER TABLE proxy ADD COLUMN quota_bytes BIGINT DEFAULT 0',
                'quota_start': 'ALTER TABLE proxy ADD COLUMN quota_start DATETIME',
                'quota_base_upload': 'ALTER TABLE proxy ADD COLUMN quota_base_upload BIGINT DEFAULT 0',
                'quota_base_download': 'ALTER TABLE proxy ADD COLUMN quota_base_download BIGINT DEFAULT 0',
                'expiry_date': 'ALTER TABLE proxy ADD COLUMN expiry_date DATETIME',
                'telegram_chat_id': 'ALTER TABLE proxy ADD COLUMN telegram_chat_id VARCHAR(50)',
                'username': 'ALTER TABLE proxy ADD COLUMN username VARCHAR(100)',
                'password': 'ALTER TABLE proxy ADD COLUMN password VARCHAR(100)',
                'created_at': 'ALTER TABLE proxy ADD COLUMN created_at DATETIME'
            }
            
            missing = [c for c in required_columns if c not in columns]
            
            if missing:
                print(f"Missing columns: {missing}")
                print("Attempting to fix...")
                with db.engine.connect() as conn:
                    for col in missing:
                        print(f"Adding column {col}...")
                        try:
                            conn.execute(text(required_columns[col]))
                            # Some DBs need commit per DDL or at end
                            conn.commit()
                        except Exception as e:
                            print(f"Error adding {col}: {e}")
                print("Database repair attempt finished.")
            else:
                print("Database schema is up to date.")
                
    except Exception as e:
        print(f"Critical error during DB repair: {e}")
        import traceback
        traceback.print_exc()
