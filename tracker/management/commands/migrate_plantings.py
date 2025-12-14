from django.core.management.base import BaseCommand
import logging
import boto3
import os
from tracker.dynamodb_helper import _table, DYNAMO_USERS_TABLE, DYNAMO_PLANTINGS_TABLE, dynamo_resource
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

S3_BUCKET = os.getenv("S3_BUCKET", "terratrack-media")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


class Command(BaseCommand):
    help = "Migrate plantings: add user_id from users table when missing and set image_url if a matching S3 object exists."

    def handle(self, *args, **options):
        dynamo = dynamo_resource()
        plantings_table = dynamo.Table(os.getenv("DYNAMO_PLANTINGS_TABLE", DYNAMO_PLANTINGS_TABLE))
        users_table = dynamo.Table(os.getenv("DYNAMO_USERS_TABLE", DYNAMO_USERS_TABLE))
        s3 = boto3.client("s3", region_name=AWS_REGION)

        logger.info("Scanning plantings table...")
        resp = plantings_table.scan()
        items = resp.get("Items", []) or []
        count = 0
        updated = 0

        while True:
            for it in items:
                count += 1
                planting_id = it.get("planting_id")
                username = it.get("username")
                user_id = it.get("user_id")
                image_url = it.get("image_url", "")

                needs_update = False
                update_attrs = {}

                # If user_id missing but username present, fetch users table item to get user_id
                if not user_id and username:
                    try:
                        user_resp = users_table.get_item(Key={"username": username})
                        user_item = user_resp.get("Item")
                        if user_item:
                            resolved_user_id = user_item.get("user_id") or user_item.get("sub") or user_item.get("id")
                            if resolved_user_id:
                                update_attrs["user_id"] = resolved_user_id
                                needs_update = True
                                logger.info("Resolved user_id=%s for planting %s (username=%s)", resolved_user_id, planting_id, username)
                    except ClientError:
                        logger.exception("Error fetching user %s from users table", username)

                # If image_url empty, try to find an S3 object containing the planting_id in its key
                if (not image_url or image_url == "") and planting_id:
                    try:
                        # list objects under media/planting_images/ and try to match planting_id substring
                        prefix = "media/planting_images/"
                        found_key = None
                        lo = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
                        for obj in lo.get("Contents", []):
                            key = obj.get("Key")
                            if planting_id in key:
                                found_key = key
                                break
                        if found_key:
                            # construct public URL (adjust region/bucket style if needed)
                            url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{found_key}"
                            update_attrs["image_url"] = url
                            needs_update = True
                            logger.info("Found S3 object for planting %s -> %s", planting_id, found_key)
                    except ClientError:
                        logger.exception("Error listing S3 objects for planting %s", planting_id)

                if needs_update and update_attrs:
                    # Build UpdateExpression
                    expr = "SET " + ", ".join(f"#{k}=:{k}" for k in update_attrs.keys())
                    expr_attr_names = {f"#{k}": k for k in update_attrs.keys()}
                    expr_attr_values = {f":{k}": v for k, v in update_attrs.items()}
                    try:
                        plantings_table.update_item(
                            Key={"planting_id": planting_id},
                            UpdateExpression=expr,
                            ExpressionAttributeNames=expr_attr_names,
                            ExpressionAttributeValues=expr_attr_values
                        )
                        updated += 1
                        logger.info("Updated planting %s with %s", planting_id, list(update_attrs.keys()))
                    except ClientError:
                        logger.exception("Failed updating planting %s", planting_id)

            # paginate
            if resp.get("LastEvaluatedKey"):
                resp = plantings_table.scan(ExclusiveStartKey=resp.get("LastEvaluatedKey"))
                items = resp.get("Items", []) or []
            else:
                break

        logger.info("Scan complete. Processed %d items, updated %d items.", count, updated)