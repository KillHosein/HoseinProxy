from app import app, db
from sqlalchemy import inspect

with app.app_context():
    try:
        inspector = inspect(db.engine)
        columns = [c['name'] for c in inspector.get_columns('proxy')]
        print(f"Proxy columns: {columns}")
        if 'active_connections' in columns:
            print("SUCCESS: active_connections column exists.")
        else:
            print("FAILURE: active_connections column MISSING.")
            
        # Check ProxyStats table
        if inspector.has_table('proxy_stats'):
             print("SUCCESS: proxy_stats table exists.")
        else:
             print("FAILURE: proxy_stats table MISSING.")
             
    except Exception as e:
        print(f"Error: {e}")
