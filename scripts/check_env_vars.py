#!/usr/bin/env python3
"""
Check if required Cognito environment variables are set.

This script helps diagnose why COGNITO_DOMAIN might not be loaded.
"""
import os
import sys

def check_env_var(name, required=True):
    """Check if an environment variable is set."""
    value = os.getenv(name)
    if value:
        # Don't print secrets in full
        if 'SECRET' in name or 'PASSWORD' in name:
            display_value = value[:4] + '...' if len(value) > 4 else '***'
        else:
            display_value = value
        print(f"✅ {name}={display_value}")
        return True
    else:
        status = "❌ MISSING" if required else "⚠️  NOT SET (optional)"
        print(f"{status} {name}")
        return False

def main():
    print("=" * 70)
    print("Cognito Environment Variables Check")
    print("=" * 70)
    print()
    
    required_vars = [
        'COGNITO_DOMAIN',
        'COGNITO_CLIENT_ID',
        'COGNITO_REDIRECT_URI',
    ]
    
    optional_vars = [
        'COGNITO_CLIENT_SECRET',
        'COGNITO_REGION',
        'COGNITO_SCOPE',
        'COGNITO_LOGOUT_REDIRECT_URI',
    ]
    
    print("Required Variables:")
    print("-" * 70)
    all_ok = True
    for var in required_vars:
        if not check_env_var(var, required=True):
            all_ok = False
    
    print()
    print("Optional Variables:")
    print("-" * 70)
    for var in optional_vars:
        check_env_var(var, required=False)
    
    print()
    print("=" * 70)
    
    if not all_ok:
        print("❌ Some required variables are missing!")
        print()
        print("To fix:")
        print("1. Check your systemd environment file:")
        print("   sudo cat /etc/systemd/system/smartharvester.service.d/env.conf")
        print()
        print("2. Verify the service unit includes EnvironmentFile:")
        print("   sudo systemctl show smartharvester | grep EnvironmentFile")
        print()
        print("3. Check if environment is loaded:")
        print("   sudo systemctl show smartharvester --property=Environment")
        print()
        print("4. If variables are missing, add them to:")
        print("   /etc/systemd/system/smartharvester.service.d/env.conf")
        print()
        print("5. Then reload and restart:")
        print("   sudo systemctl daemon-reload")
        print("   sudo systemctl restart smartharvester")
        return 1
    else:
        print("✅ All required variables are set!")
        return 0

if __name__ == '__main__':
    sys.exit(main())

