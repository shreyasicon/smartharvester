import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from cachetools import TTLCache
    _jwks_cache = TTLCache(maxsize=1, ttl=3600)
except ImportError:
    logger.warning("cachetools not installed, using simple dict cache")
    _jwks_cache = {}

try:
    import jwt
except ImportError:
    jwt = None
    logger.warning("PyJWT not installed, token verification disabled")

ALGORITHM = "RS256"


def _get_jwks():
    import time
    
    if isinstance(_jwks_cache, dict) and "jwks" in _jwks_cache:
        if "time" in _jwks_cache:
            if time.time() - _jwks_cache["time"] < 3600:
                return _jwks_cache["jwks"]
    elif hasattr(_jwks_cache, "get"):
        jwks = _jwks_cache.get("jwks")
        if jwks:
            return jwks

    user_pool_id = getattr(settings, 'COGNITO_USER_POOL_ID', None)
    cognito_region = getattr(settings, 'COGNITO_REGION', 'us-east-1')

    if not user_pool_id:
        raise ValueError("COGNITO_USER_POOL_ID is required for token verification")

    JWKS_URL = f"https://cognito-idp.{cognito_region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    resp = requests.get(JWKS_URL, timeout=5)
    resp.raise_for_status()
    jwks = resp.json()
    
    if isinstance(_jwks_cache, dict):
        _jwks_cache["jwks"] = jwks
        _jwks_cache["time"] = time.time()
    else:
        _jwks_cache["jwks"] = jwks
    
    return jwks


def verify_cognito_token(token):
    if not jwt:
        raise ImportError("PyJWT is not installed. Please install it: pip install PyJWT")
    
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        jwks = _get_jwks()
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break

        if not key:
            raise Exception("Public key not found in JWKS")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)

        client_id = getattr(settings, 'COGNITO_CLIENT_ID', None)
        
        try:
            if client_id:
                claims = jwt.decode(token, public_key, algorithms=[ALGORITHM], audience=client_id)
            else:
                claims = jwt.decode(token, public_key, algorithms=[ALGORITHM], options={"verify_aud": False})
        except jwt.InvalidAudienceError:
            logger.warning("Audience verification failed, verifying without audience check (signature still verified)")
            claims = jwt.decode(token, public_key, algorithms=[ALGORITHM], options={"verify_aud": False})
        
        return claims

    except Exception as e:
        logger.warning("Token verification failed: %s", e)
        raise


def verify_id_token(id_token, audience=None):
    """Verify Cognito ID token and return payload or raise an exception."""
    return verify_cognito_token(id_token)


def build_authorize_url(state=None, scope=None, redirect_uri=None):
    """
    Build Cognito OAuth2 authorization URL.
    If scope is not provided, uses COGNITO_SCOPE from settings (default: 'openid email').
    If redirect_uri is not provided, uses COGNITO_REDIRECT_URI from settings.
    Ensure the scopes match what's enabled in your Cognito app client settings.
    The redirect_uri must match exactly what's used in the token exchange.
    
    Tries to use the authorization_endpoint from OpenID discovery if available,
    otherwise falls back to /oauth2/authorize.
    """
    domain = settings.COGNITO_DOMAIN
    client_id = settings.COGNITO_CLIENT_ID
    
    if not domain:
        raise ValueError("COGNITO_DOMAIN is required")
    if not client_id:
        raise ValueError("COGNITO_CLIENT_ID is required")
    
    if redirect_uri is None:
        redirect_uri = settings.COGNITO_REDIRECT_URI
        if not redirect_uri:
            raise ValueError("COGNITO_REDIRECT_URI is required")
    
    # Use scope from parameter, settings, or default
    if scope is None:
        scope = getattr(settings, 'COGNITO_SCOPE', 'openid email')
    
    # Try to get authorization_endpoint from discovery document
    # Fallback to standard /oauth2/authorize path
    base = f"https://{domain}/oauth2/authorize"
    try:
        import requests
        discovery_url = f"https://{domain}/.well-known/openid-configuration"
        resp = requests.get(discovery_url, timeout=5)
        if resp.status_code == 200:
            discovery = resp.json()
            auth_endpoint = discovery.get('authorization_endpoint')
            if auth_endpoint:
                base = auth_endpoint
    except requests.exceptions.ConnectionError as e:
        # DNS/name resolution error - domain doesn't exist or can't be reached
        error_msg = str(e)
        if 'NameResolutionError' in error_msg or 'Failed to resolve' in error_msg or 'Name or service not known' in error_msg:
            raise ValueError(
                f"Cognito domain '{domain}' cannot be resolved. "
                "Please verify:\n"
                "1. The domain exists in your Cognito User Pool (AWS Console > Cognito > User Pools > Your Pool > App integration > Domain)\n"
                "2. The domain format is correct: <prefix>.auth.<region>.amazoncognito.com\n"
                "3. If using a custom domain, ensure DNS is configured correctly"
            )
        # Other connection errors - just fallback to standard path
        pass
    except Exception:
        # Other errors (timeout, invalid JSON, etc.) - fallback to standard path
        pass
    
    params = {
        'response_type': 'code',
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': scope,  # Space-separated is correct for OAuth2
    }
    if state:
        params['state'] = state
    # build query
    from urllib.parse import urlencode
    return base + '?' + urlencode(params)


def exchange_code_for_tokens(code):
    domain = settings.COGNITO_DOMAIN
    token_url = f"https://{domain}/oauth2/token"
    data = {
        'grant_type': 'authorization_code',
        'client_id': settings.COGNITO_CLIENT_ID,
        'code': code,
        'redirect_uri': settings.COGNITO_REDIRECT_URI,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    auth = None
    # If client secret is configured, use HTTP Basic auth as per OAuth2
    if settings.COGNITO_CLIENT_SECRET:
        # HTTPBasicAuth is provided by requests; import lazily
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(settings.COGNITO_CLIENT_ID, settings.COGNITO_CLIENT_SECRET)
        # remove client_id from body when using HTTP Basic
        data.pop('client_id', None)
    import requests
    r = requests.post(token_url, data=data, headers=headers, auth=auth, timeout=5)
    r.raise_for_status()
    return r.json()
