"""
Test script to verify DynamoDB user save functionality.

Run this to test if user data can be saved to DynamoDB:
    python scripts/test_dynamodb_user_save.py
"""
import os
import sys
import django
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from tracker.dynamodb_helper import save_user_to_dynamodb

def test_user_save():
    """Test saving a user to DynamoDB."""
    print("=" * 60)
    print("TESTING DYNAMODB USER SAVE")
    print("=" * 60)
    
    # Check AWS credentials
    print("\n1. Checking AWS credentials...")
    access_key = settings.AWS_ACCESS_KEY_ID
    secret_key = settings.AWS_SECRET_ACCESS_KEY
    
    if not access_key:
        print("   ✗ AWS_ACCESS_KEY_ID is not set!")
        print("   Please set it in .env file or environment variables")
        return False
    else:
        print(f"   ✓ AWS_ACCESS_KEY_ID is set (length: {len(access_key)})")
    
    if not secret_key:
        print("   ✗ AWS_SECRET_ACCESS_KEY is not set!")
        print("   Please set it in .env file or environment variables")
        return False
    else:
        print(f"   ✓ AWS_SECRET_ACCESS_KEY is set (length: {len(secret_key)})")
    
    # Check table name
    print("\n2. Checking table configuration...")
    table_name = getattr(settings, 'DYNAMODB_USERS_TABLE_NAME', 'users')
    region = getattr(settings, 'AWS_S3_REGION_NAME', 'us-east-1')
    print(f"   Table name: {table_name}")
    print(f"   Region: {region}")
    
    # Test user data
    print("\n3. Preparing test user data...")
    test_user_data = {
        'username': 'test_user_' + str(os.getpid()),  # Unique username
        'email': f'test_{os.getpid()}@example.com',
        'sub': f'test_django_{os.getpid()}',
        'name': 'Test User',
    }
    print(f"   Username: {test_user_data['username']}")
    print(f"   Email: {test_user_data['email']}")
    print(f"   User ID: {test_user_data['sub']}")
    
    # Try to save
    print("\n4. Attempting to save user to DynamoDB...")
    try:
        result = save_user_to_dynamodb(test_user_data)
        if result:
            print("   ✓✓✓ SUCCESS: User saved to DynamoDB!")
            print(f"\n5. Verify in AWS Console:")
            print(f"   aws dynamodb get-item --table-name {table_name} --key '{{\"username\":{{\"S\":\"{test_user_data['username']}\"}}}}' --region {region}")
            return True
        else:
            print("   ✗✗✗ FAILED: User was NOT saved to DynamoDB")
            print("   Check the logs above for error details")
            return False
    except Exception as e:
        print(f"   ✗✗✗ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = test_user_save()
    sys.exit(0 if success else 1)

