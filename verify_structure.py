import sys
import os

# Add panel to path
sys.path.append(os.path.join(os.getcwd(), 'panel'))

try:
    from panel.app import create_app
    app = create_app()
    print("App created successfully!")
except Exception as e:
    print(f"Error creating app: {e}")
    import traceback
    traceback.print_exc()
