import os
import logging
from urllib.parse import quote_plus

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

S3_BUCKET = os.getenv("S3_BUCKET", "terratrack-media")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

def _s3_client():
    return boto3.client("s3", region_name=AWS_REGION)

def upload_planting_image(file_obj, user_id: str, folder: str = "media/planting_images") -> str:
    """
    Upload a Django UploadedFile to S3 and return a public URL.
    Do NOT set ACL here because the bucket enforces 'no ACLs' (BucketOwnerEnforced).
    Public access is granted by bucket policy on the prefix.
    """
    import os
    from urllib.parse import quote_plus
    import boto3
    from botocore.exceptions import ClientError
    S3_BUCKET = os.getenv("S3_BUCKET", "terratrack-media")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    s3 = boto3.client("s3", region_name=AWS_REGION)

    filename = getattr(file_obj, "name", "upload").replace(" ", "_")
    key = f"{folder}/{user_id}/{filename}"
    content_type = getattr(file_obj, "content_type", "application/octet-stream")

    try:
        # DO NOT pass ExtraArgs={"ACL": "public-read"} since ACLs are disallowed on this bucket
        s3.upload_fileobj(file_obj, S3_BUCKET, key, ExtraArgs={"ContentType": content_type})
    except ClientError as e:
        # log and re-raise or return empty string based on your app pattern
        raise

    encoded_key = quote_plus(key, safe="/")
    url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{encoded_key}"
    return url

def delete_image_from_s3(url: str) -> bool:
    # (Keep your existing implementation or the one already provided.)
    from urllib.parse import urlparse
    if not url:
        return False
    parsed = urlparse(url)
    key = parsed.path.lstrip("/")
    if key.startswith(f"{S3_BUCKET}/"):
        key = key[len(f"{S3_BUCKET}/"):]
    try:
        s3 = _s3_client()
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        logger.info("Deleted S3 object %s/%s", S3_BUCKET, key)
        return True
    except Exception:
        logger.exception("Failed deleting S3 object %s", url)
        return False