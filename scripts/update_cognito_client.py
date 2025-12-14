"""
Update AWS Cognito App Client with the required callback/logout URLs and OAuth settings.
Run on EC2 (or any machine with AWS credentials) with:

python3 scripts/update_cognito_client.py

Environment variables supported (optional):
- AWS_REGION (default: us-east-1)
- COGNITO_USER_POOL_ID (default in script)
- COGNITO_CLIENT_ID (default in script)

This script uses boto3. Install with:
  python3 -m pip install --user boto3

"""
import os
import json
import sys
from botocore.exceptions import ClientError

try:
    import boto3
except Exception as e:
    print("boto3 is required. Install with: python3 -m pip install --user boto3", file=sys.stderr)
    raise

REGION = os.environ.get("AWS_REGION", "us-east-1")
USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "us-east-1_HGEM2vRNI")
CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "4l8j19f73h5hqmlldgc6jigk3k")

CALLBACK_URLS = [os.environ.get("COGNITO_CALLBACK_URL", "http://3.235.196.246:8000/auth/callback/")]
LOGOUT_URLS = [os.environ.get("COGNITO_LOGOUT_URL", "http://3.235.196.246:8000/")]
ALLOWED_OAUTH_FLOWS = ["code"]
ALLOWED_OAUTH_SCOPES = ["openid", "email", "profile"]

print(f"Region: {REGION}")
print(f"UserPoolId: {USER_POOL_ID}")
print(f"ClientId: {CLIENT_ID}")
print("Callback URLs:", CALLBACK_URLS)
print("Logout URLs:", LOGOUT_URLS)
print("Allowed OAuth Flows:", ALLOWED_OAUTH_FLOWS)
print("Allowed OAuth Scopes:", ALLOWED_OAUTH_SCOPES)

client = boto3.client("cognito-idp", region_name=REGION)

try:
    resp = client.update_user_pool_client(
        UserPoolId=USER_POOL_ID,
        ClientId=CLIENT_ID,
        CallbackURLs=CALLBACK_URLS,
        LogoutURLs=LOGOUT_URLS,
        AllowedOAuthFlows=ALLOWED_OAUTH_FLOWS,
        AllowedOAuthScopes=ALLOWED_OAUTH_SCOPES,
        AllowedOAuthFlowsUserPoolClient=True,
    )
    print("Update successful. Server response (trimmed):")
    print(json.dumps({
        "ClientId": resp.get('UserPoolClient', {}).get('ClientId'),
        "CallbackURLs": resp.get('UserPoolClient', {}).get('CallbackURLs'),
        "LogoutURLs": resp.get('UserPoolClient', {}).get('LogoutURLs'),
        "AllowedOAuthFlows": resp.get('UserPoolClient', {}).get('AllowedOAuthFlows'),
        "AllowedOAuthScopes": resp.get('UserPoolClient', {}).get('AllowedOAuthScopes'),
    }, indent=2))
except ClientError as e:
    print("AWS ClientError:", e.response.get('Error', {}).get('Message', str(e)), file=sys.stderr)
    sys.exit(2)
except Exception as e:
    print("Unexpected error:", str(e), file=sys.stderr)
    sys.exit(3)

# Also print describe to confirm
try:
    r = client.describe_user_pool_client(UserPoolId=USER_POOL_ID, ClientId=CLIENT_ID)
    print("\nDescribe after update:")
    print(json.dumps({
        "Callback": r['UserPoolClient'].get('CallbackURLs'),
        "Logout": r['UserPoolClient'].get('LogoutURLs'),
        "Flows": r['UserPoolClient'].get('AllowedOAuthFlows'),
        "Scopes": r['UserPoolClient'].get('AllowedOAuthScopes')
    }, indent=2))
except Exception as e:
    print("Describe failed:", str(e), file=sys.stderr)
    sys.exit(4)
