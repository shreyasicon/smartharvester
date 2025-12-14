import logging
from django.conf import settings
from django.shortcuts import redirect
from django.http import HttpResponse
from .cognito import verify_cognito_token, exchange_code_for_tokens

logger = logging.getLogger(__name__)


class CognitoTokenMiddleware:
    """Middleware that verifies Cognito ID tokens from Authorization header or session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            if request.path.startswith("/auth/callback/") or request.path.startswith("/auth/login/"):
                return self.get_response(request)

            auth = request.META.get("HTTP_AUTHORIZATION", "")
            token = None
            if auth.startswith("Bearer "):
                token = auth.split(" ", 1)[1]

            if not token:
                try:
                    token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
                except Exception:
                    pass

            if not token:
                return self.get_response(request)

            try:
                claims = verify_cognito_token(token)
                request.cognito_claims = claims
                request.cognito_payload = claims
                request.user_id = claims.get("sub")
                request.cognito_user_id = claims.get("sub")
                request.username = claims.get("cognito:username") or claims.get("username") or claims.get("preferred_username")
                request.email = claims.get("email")
                logger.info("Cognito token verified for user_id=%s", request.user_id)
            except Exception as e:
                logger.warning("ID token verify failed: %s - continuing without verification", e)
                try:
                    import jwt as pyjwt
                    unverified_claims = pyjwt.decode(token, options={"verify_signature": False})
                    request.cognito_payload = unverified_claims
                    request.cognito_user_id = unverified_claims.get("sub")
                    request.username = unverified_claims.get("cognito:username") or unverified_claims.get("username") or unverified_claims.get("preferred_username")
                    logger.info("Using unverified token claims for user_id=%s", request.cognito_user_id)
                except Exception:
                    logger.debug("Could not decode token - request will proceed without Cognito data")
        except Exception as e:
            logger.exception("Middleware error: %s", e)
            return self.get_response(request)

        return self.get_response(request)


def _refresh_with_refresh_token(refresh_token):
    # Exchange refresh token for new tokens using token endpoint
    domain = settings.COGNITO_DOMAIN
    token_url = f"https://{domain}/oauth2/token"
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': settings.COGNITO_CLIENT_ID,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    auth = None
    if settings.COGNITO_CLIENT_SECRET:
        from requests.auth import HTTPBasicAuth
        auth = HTTPBasicAuth(settings.COGNITO_CLIENT_ID, settings.COGNITO_CLIENT_SECRET)
        data.pop('client_id', None)
    import requests
    r = requests.post(token_url, data=data, headers=headers, auth=auth, timeout=5)
    r.raise_for_status()
    return r.json()
