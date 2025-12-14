#!/usr/bin/env python3
"""
Helper script to verify Cognito domain configuration.

This script helps you:
1. Check if COGNITO_DOMAIN is set
2. Test if the domain is reachable
3. Verify the domain format
4. Get the OpenID discovery document (if domain is valid)

Usage:
    python scripts/verify_cognito_domain.py
    # Or with explicit domain:
    COGNITO_DOMAIN=your-domain.auth.us-east-1.amazoncognito.com python scripts/verify_cognito_domain.py
"""
import os
import sys
import requests
from urllib.parse import urlparse

def check_domain_format(domain):
    """Check if domain follows expected format."""
    if not domain:
        return False, "Domain is empty"
    
    # Check for protocol (should not have it)
    if domain.startswith('http://') or domain.startswith('https://'):
        return False, "Domain should not include protocol (http:// or https://)"
    
    # Check for expected Cognito domain patterns
    if '.amazoncognito.com' in domain:
        parts = domain.split('.')
        if len(parts) >= 4 and parts[-3] == 'auth':
            return True, "Domain format looks correct"
        return False, "Domain format may be incorrect. Expected: <prefix>.auth.<region>.amazoncognito.com"
    
    # Might be a custom domain
    return True, "Appears to be a custom domain (not standard Cognito format)"

def test_domain_resolution(domain):
    """Test if domain can be resolved via DNS."""
    try:
        import socket
        # Extract hostname (remove path if present)
        hostname = domain.split('/')[0]
        socket.gethostbyname(hostname)
        return True, f"DNS resolution successful for {hostname}"
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except Exception as e:
        return False, f"Error checking DNS: {e}"

def test_discovery_endpoint(domain):
    """Test if OpenID discovery endpoint is accessible."""
    discovery_url = f"https://{domain}/.well-known/openid-configuration"
    try:
        resp = requests.get(discovery_url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return True, f"Discovery endpoint accessible. Authorization endpoint: {data.get('authorization_endpoint', 'N/A')}"
        return False, f"Discovery endpoint returned status {resp.status_code}"
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection error: {e}"
    except requests.exceptions.Timeout:
        return False, "Connection timeout"
    except Exception as e:
        return False, f"Error accessing discovery endpoint: {e}"

def main():
    print("=" * 70)
    print("Cognito Domain Verification Script")
    print("=" * 70)
    print()
    
    # Get domain from environment or argument
    domain = os.getenv('COGNITO_DOMAIN')
    if not domain and len(sys.argv) > 1:
        domain = sys.argv[1]
    
    if not domain:
        print("❌ ERROR: COGNITO_DOMAIN not set")
        print()
        print("Set it via:")
        print("  export COGNITO_DOMAIN=your-domain.auth.us-east-1.amazoncognito.com")
        print("  # Or pass as argument:")
        print("  python scripts/verify_cognito_domain.py your-domain.auth.us-east-1.amazoncognito.com")
        return 1
    
    print(f"Checking domain: {domain}")
    print()
    
    # Check format
    format_ok, format_msg = check_domain_format(domain)
    if format_ok:
        print(f"✅ Format check: {format_msg}")
    else:
        print(f"❌ Format check: {format_msg}")
    print()
    
    # Test DNS resolution
    print("Testing DNS resolution...")
    dns_ok, dns_msg = test_domain_resolution(domain)
    if dns_ok:
        print(f"✅ {dns_msg}")
    else:
        print(f"❌ {dns_msg}")
        print()
        print("This means the domain cannot be resolved. Possible causes:")
        print("  1. Domain doesn't exist in Cognito User Pool")
        print("  2. Domain name is misspelled")
        print("  3. DNS propagation delay (if recently created)")
        print()
        print("To fix:")
        print("  1. Go to AWS Console → Cognito → User Pools → Your Pool")
        print("  2. Navigate to: App integration → Domain")
        print("  3. Check the domain name shown there")
        print("  4. If no domain exists, create one")
        print("  5. Update COGNITO_DOMAIN environment variable to match exactly")
        return 1
    print()
    
    # Test discovery endpoint
    print("Testing OpenID discovery endpoint...")
    discovery_ok, discovery_msg = test_discovery_endpoint(domain)
    if discovery_ok:
        print(f"✅ {discovery_msg}")
    else:
        print(f"❌ {discovery_msg}")
        print()
        print("Domain resolves but discovery endpoint is not accessible.")
        print("This might indicate:")
        print("  - Domain exists but Cognito configuration is incomplete")
        print("  - Network/firewall issues")
        print("  - Domain is not properly configured in Cognito")
        return 1
    
    print()
    print("=" * 70)
    print("✅ All checks passed! Domain appears to be correctly configured.")
    print("=" * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())

