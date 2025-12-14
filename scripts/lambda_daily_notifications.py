import os
import json
import logging
import time
import boto3
from botocore.exceptions import ClientError
from datetime import datetime, date, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
DYNAMO_USERS_TABLE = os.environ.get("DYNAMO_USERS_TABLE", "users")
DYNAMO_PLANTINGS_TABLE = os.environ.get("DYNAMO_PLANTINGS_TABLE", "plantings")
PK_NAME = os.environ.get("DYNAMO_USERS_PK", "user_id")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
REGION = os.environ.get("AWS_REGION", "us-east-1")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "25"))
BATCH_PAUSE_SECONDS = float(os.environ.get("BATCH_PAUSE_SECONDS", "0.5"))
DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", "7"))  # Check next 7 days for reminders

dynamodb = boto3.resource("dynamodb", region_name=REGION)
users_table = dynamodb.Table(DYNAMO_USERS_TABLE)
plantings_table = dynamodb.Table(DYNAMO_PLANTINGS_TABLE)
sns = boto3.client("sns", region_name=REGION)


def get_user_plantings(user_id):
    """Get all plantings for a specific user. Uses GSI query first, then scan fallback."""
    try:
        from boto3.dynamodb.conditions import Key, Attr
        
        # Try GSI query first (user_id-index)
        try:
            response = plantings_table.query(
                IndexName="user_id-index",
                KeyConditionExpression=Key("user_id").eq(str(user_id))
            )
            items = response.get("Items", [])
            if items:
                logger.debug(f"Queried {len(items)} plantings for user {user_id} via GSI")
                return items
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.debug(f"GSI query failed for user {user_id} (Code: {error_code}), falling back to scan")
        except Exception as e:
            logger.debug(f"GSI query error for user {user_id}: {e}, falling back to scan")
        
        # Fallback: scan with filter
        items = []
        scan_kwargs = {"FilterExpression": Attr("user_id").eq(str(user_id))}
        start_key = None
        
        while True:
            if start_key:
                scan_kwargs["ExclusiveStartKey"] = start_key
            response = plantings_table.scan(**scan_kwargs)
            batch = response.get("Items", []) or []
            items.extend(batch)
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        
        logger.debug(f"Scanned and found {len(items)} plantings for user {user_id}")
        return items
    except Exception as e:
        logger.exception(f"Error fetching plantings for user {user_id}: {e}")
        return []


def calculate_planting_plan(planting, data_json):
    """Calculate plan for a planting based on crop name and planting date.
    Uses existing plan if available, otherwise calculates from crop data."""
    try:
        # If planting already has a plan, use it (but recalculate dates to be safe)
        existing_plan = planting.get("plan", [])
        if existing_plan and isinstance(existing_plan, list) and len(existing_plan) > 0:
            # Convert existing plan dates to date objects
            plan = []
            planting_date_str = planting.get("planting_date", "")
            if planting_date_str:
                try:
                    planting_date = date.fromisoformat(planting_date_str) if isinstance(planting_date_str, str) else planting_date_str
                    for task_item in existing_plan:
                        if isinstance(task_item, dict) and task_item.get("due_date"):
                            plan.append(task_item)
                    if plan:
                        logger.debug(f"Using existing plan for {planting.get('crop_name')} with {len(plan)} tasks")
                        return plan
                except Exception as e:
                    logger.debug(f"Error parsing existing plan dates: {e}, will recalculate")
        
        # Calculate new plan
        crop_name = planting.get("crop_name", "")
        planting_date_str = planting.get("planting_date", "")
        
        if not crop_name or not planting_date_str:
            return []
        
        # Parse planting date
        try:
            planting_date = date.fromisoformat(planting_date_str) if isinstance(planting_date_str, str) else planting_date_str
        except Exception as e:
            logger.warning(f"Invalid planting_date format '{planting_date_str}': {e}")
            return []
        
        # Normalize crop name (handle variations)
        crop_name_normalized = crop_name.title()
        
        # Get crop data from library
        crop_data = data_json.get(crop_name_normalized)
        if not crop_data:
            # Try alternative names
            for key in data_json.keys():
                if key.lower() == crop_name.lower():
                    crop_data = data_json[key]
                    break
        
        if not crop_data:
            return []
        
        care_schedule = crop_data.get("care_schedule", [])
        harvest_window = crop_data.get("harvest_window", {})
        
        # Build plan with due dates
        plan = []
        today = date.today()
        
        for task in care_schedule:
            days_after_planting = task.get("days_after_planting", 0)
            task_title = task.get("task_title", "Task")
            due_date = planting_date + timedelta(days=days_after_planting)
            plan.append({
                "task": task_title,
                "due_date": due_date.isoformat(),
                "days_after_planting": days_after_planting
            })
        
        # Add harvest date if available
        if harvest_window:
            harvest_start = harvest_window.get("start", 0)
            harvest_date = planting_date + timedelta(days=harvest_start)
            plan.append({
                "task": "Harvest",
                "due_date": harvest_date.isoformat(),
                "days_after_planting": harvest_start,
                "is_harvest": True
            })
        
        return plan
    except Exception as e:
        logger.exception(f"Error calculating plan for planting {planting.get('planting_id')}: {e}")
        return []


def load_crop_data():
    """Load crop data from the embedded JSON structure."""
    # This matches the structure in tracker/data.json
    return {
        "Basil": {
            "description": "Quick-growing herb for warm weather, prefers full sun and consistent moisture.",
            "care_schedule": [
                {"task_title": "Start seeds indoors", "days_after_planting": 0},
                {"task_title": "Thin seedlings", "days_after_planting": 14},
                {"task_title": "Transplant outdoors", "days_after_planting": 28},
                {"task_title": "Regular harvest (pinch tips)", "days_after_planting": 42}
            ],
            "harvest_window": {"start": 42, "end": 120}
        },
        "Bell Peppers": {
            "description": "Warm-season crop; needs long, warm season and consistent moisture.",
            "care_schedule": [
                {"task_title": "Sow seeds indoors", "days_after_planting": 0},
                {"task_title": "Pot on seedlings", "days_after_planting": 21},
                {"task_title": "Harden off seedlings", "days_after_planting": 49},
                {"task_title": "Transplant outdoors", "days_after_planting": 56}
            ],
            "harvest_window": {"start": 80, "end": 120}
        },
        "Carrots": {
            "description": "Root crop; sow directly; thin seedlings.",
            "care_schedule": [
                {"task_title": "Sow seeds directly", "days_after_planting": 0},
                {"task_title": "First thinning", "days_after_planting": 14},
                {"task_title": "Second thinning", "days_after_planting": 28},
                {"task_title": "Weed and mulch", "days_after_planting": 21}
            ],
            "harvest_window": {"start": 60, "end": 90}
        },
        "Cucumbers": {
            "description": "Fast vining plant; trellis for space; warm-season crop.",
            "care_schedule": [
                {"task_title": "Sow or transplant seedlings", "days_after_planting": 0},
                {"task_title": "Install trellis", "days_after_planting": 7},
                {"task_title": "First trellis training", "days_after_planting": 14},
                {"task_title": "Begin harvesting", "days_after_planting": 50}
            ],
            "harvest_window": {"start": 50, "end": 100}
        },
        "Lettuce": {
            "description": "Cool-season leafy green; quick turnover; may be grown in succession.",
            "care_schedule": [
                {"task_title": "Sow seeds", "days_after_planting": 0},
                {"task_title": "Thin seedlings", "days_after_planting": 10},
                {"task_title": "Begin baby-leaf harvest", "days_after_planting": 21},
                {"task_title": "Full head harvest", "days_after_planting": 45}
            ],
            "harvest_window": {"start": 21, "end": 60}
        },
        "Mint": {
            "description": "Perennial herb; spreads vigorously; best grown in containers.",
            "care_schedule": [
                {"task_title": "Pot or transplant", "days_after_planting": 0},
                {"task_title": "Pinch back regularly", "days_after_planting": 14},
                {"task_title": "Divide in spring", "days_after_planting": 365}
            ],
            "harvest_window": {"start": 21, "end": 9999}
        },
        "Potatoes": {
            "description": "Tuber crop; plant seed potatoes; hill for more yield.",
            "care_schedule": [
                {"task_title": "Plant seed pieces", "days_after_planting": 0},
                {"task_title": "First hill", "days_after_planting": 21},
                {"task_title": "Second hill", "days_after_planting": 42},
                {"task_title": "Begin new potato harvest", "days_after_planting": 70},
                {"task_title": "Main harvest", "days_after_planting": 100}
            ],
            "harvest_window": {"start": 70, "end": 120}
        },
        "Radishes": {
            "description": "Very fast-growing root crop; great for succession planting.",
            "care_schedule": [
                {"task_title": "Sow seeds directly", "days_after_planting": 0},
                {"task_title": "Thin seedlings", "days_after_planting": 7},
                {"task_title": "Harvest early", "days_after_planting": 21}
            ],
            "harvest_window": {"start": 21, "end": 35}
        },
        "Rosemary": {
            "description": "Woody perennial herb; drought tolerant; prefers well-drained soil.",
            "care_schedule": [
                {"task_title": "Transplant or pot", "days_after_planting": 0},
                {"task_title": "Light pruning", "days_after_planting": 60},
                {"task_title": "Annual pruning", "days_after_planting": 365}
            ],
            "harvest_window": {"start": 60, "end": 9999}
        },
        "Spinach": {
            "description": "Cool-season leafy green; bolt-prone in hot weather.",
            "care_schedule": [
                {"task_title": "Sow seeds directly", "days_after_planting": 0},
                {"task_title": "Thin seedlings", "days_after_planting": 14},
                {"task_title": "Baby leaf harvest", "days_after_planting": 28},
                {"task_title": "Full harvest", "days_after_planting": 45}
            ],
            "harvest_window": {"start": 28, "end": 60}
        },
        "Tomatoes": {
            "description": "Warm-season vine; stake or cage; heavy feeder.",
            "care_schedule": [
                {"task_title": "Start seeds indoors", "days_after_planting": 0},
                {"task_title": "Pot on seedlings", "days_after_planting": 21},
                {"task_title": "Harden off", "days_after_planting": 49},
                {"task_title": "Transplant & stake", "days_after_planting": 56},
                {"task_title": "First fruit set care", "days_after_planting": 70},
                {"task_title": "Begin harvesting", "days_after_planting": 90}
            ],
            "harvest_window": {"start": 90, "end": 140}
        },
        "Zucchini": {
            "description": "Productive summer squash; harvest frequently to encourage yield.",
            "care_schedule": [
                {"task_title": "Direct sow or transplant", "days_after_planting": 0},
                {"task_title": "First flower thinning", "days_after_planting": 35},
                {"task_title": "Begin frequent harvest", "days_after_planting": 45}
            ],
            "harvest_window": {"start": 45, "end": 90}
        }
    }


def get_upcoming_tasks_and_harvests(user_plantings, days_ahead=7):
    """Get upcoming tasks and harvests for user's plantings in the next N days."""
    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    
    upcoming_tasks = []
    upcoming_harvests = []
    data_json = load_crop_data()
    
    for planting in user_plantings:
        crop_name = planting.get("crop_name", "Unknown")
        planting_id = planting.get("planting_id", "")
        
        # Get or calculate plan
        plan = planting.get("plan", [])
        if not plan:
            # Calculate plan if not present
            plan = calculate_planting_plan(planting, data_json)
        
        for task_item in plan:
            due_date_str = task_item.get("due_date", "")
            if not due_date_str:
                continue
            
            try:
                due_date = date.fromisoformat(due_date_str) if isinstance(due_date_str, str) else due_date_str
                if today <= due_date <= end_date:
                    days_until = (due_date - today).days
                    task_name = task_item.get("task", "Task")
                    is_harvest = task_item.get("is_harvest", False)
                    
                    task_info = {
                        "crop_name": crop_name,
                        "task": task_name,
                        "due_date": due_date.isoformat(),
                        "days_until": days_until,
                        "planting_id": planting_id
                    }
                    
                    if is_harvest:
                        upcoming_harvests.append(task_info)
                    else:
                        upcoming_tasks.append(task_info)
            except Exception as e:
                logger.debug(f"Error parsing due_date {due_date_str}: {e}")
                continue
    
    # Sort by due date
    upcoming_tasks.sort(key=lambda x: x["due_date"])
    upcoming_harvests.sort(key=lambda x: x["due_date"])
    
    return upcoming_tasks, upcoming_harvests


def build_message(user_item, upcoming_tasks, upcoming_harvests):
    """Build personalized daily update message for user."""
    name = (
        user_item.get("name") or 
        user_item.get("preferred_username") or 
        user_item.get("username") or
        user_item.get(PK_NAME, "Gardener")
    )
    
    subject = f"SmartHarvester Daily Update — {datetime.utcnow().strftime('%Y-%m-%d')}"
    
    body = f"Hello {name},\n\n"
    body += "Here is your SmartHarvester daily update about your plantings:\n\n"
    
    total_active = len(upcoming_tasks) + len(upcoming_harvests)
    
    if total_active == 0:
        body += "🌱 No upcoming tasks or harvests in the next 7 days. Keep up the great work!\n\n"
    else:
        # Upcoming harvests
        if upcoming_harvests:
            body += "🌾 UPCOMING HARVESTS:\n"
            for harvest in upcoming_harvests:
                days_text = "today" if harvest["days_until"] == 0 else f"in {harvest['days_until']} day(s)"
                body += f"  • {harvest['crop_name']}: Harvest due {days_text} ({harvest['due_date']})\n"
            body += "\n"
        
        # Upcoming tasks
        if upcoming_tasks:
            body += "📅 UPCOMING TASKS:\n"
            for task in upcoming_tasks:
                days_text = "today" if task["days_until"] == 0 else f"in {task['days_until']} day(s)"
                body += f"  • {task['crop_name']}: {task['task']} due {days_text} ({task['due_date']})\n"
            body += "\n"
    
    body += "Login to your dashboard to see all your plantings and manage your garden.\n\n"
    body += "Happy gardening!\n"
    body += "SmartHarvester Team"
    
    return subject, body


def check_user_notification_preference(user_item):
    """Check if user has notifications enabled."""
    # Check notification preference - defaults to True if not set
    notifications_enabled = user_item.get("notifications_enabled", True)
    
    # Handle DynamoDB boolean types (may be stored as string or bool)
    if isinstance(notifications_enabled, str):
        notifications_enabled = notifications_enabled.lower() in ("true", "1", "yes")
    
    return notifications_enabled


def scan_all_users():
    """Scan all users from DynamoDB users table."""
    if not DYNAMO_USERS_TABLE:
        raise RuntimeError("DYNAMO_USERS_TABLE not configured")
    
    users = []
    kwargs = {}
    
    while True:
        resp = users_table.scan(**kwargs)
        items = resp.get("Items", [])
        users.extend(items)
        
        if "LastEvaluatedKey" in resp:
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            break
    
    return users


def publish_to_sns(subject, message, email=None):
    """Publish message to SNS topic. If email is provided, it's included for logging."""
    if not SNS_TOPIC_ARN:
        raise RuntimeError("SNS_TOPIC_ARN not configured")
    
    try:
        # Publish to topic - SNS will deliver to all subscribers
        resp = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message
        )
        message_id = resp.get("MessageId")
        logger.info(f"Published to SNS topic {SNS_TOPIC_ARN} (MessageId: {message_id})" + 
                   (f" for email: {email}" if email else ""))
        return True, message_id
    except ClientError as e:
        logger.exception(f"SNS publish failed for email {email}: {e}")
        return False, None


def lambda_handler(event, context):
    """Main Lambda handler for daily notifications."""
    logger.info("Daily notification Lambda started")
    logger.info(f"Config: USERS_TABLE={DYNAMO_USERS_TABLE}, PLANTINGS_TABLE={DYNAMO_PLANTINGS_TABLE}, SNS_TOPIC={SNS_TOPIC_ARN}")
    
    try:
        users = scan_all_users()
        logger.info(f"Scanned {len(users)} users from DynamoDB")
    except Exception as e:
        logger.exception("Failed scanning DynamoDB users table")
        return {"status": "error", "reason": "scan_failed", "error": str(e)}
    
    total = len(users)
    sent = 0
    skipped = 0
    failed = 0
    
    # Load crop data once
    data_json = load_crop_data()
    logger.info(f"Loaded crop data for {len(data_json)} crops")
    
    for i, user in enumerate(users, start=1):
        # Try multiple keys to get user identifier
        user_id = user.get(PK_NAME) or user.get("user_id") or user.get("username")
        
        if not user_id:
            logger.warning(f"Skipping user without identifier (tried {PK_NAME}, user_id, username): {user}")
            skipped += 1
            continue
        
        # Check notification preference
        if not check_user_notification_preference(user):
            logger.info(f"Notifications disabled for user {user_id}, skipping")
            skipped += 1
            continue
        
        # Get user's email
        email = user.get("email")
        if not email:
            logger.debug(f"Skipping user without email: {user_id}")
            skipped += 1
            continue
        
        # Get user's plantings
        try:
            plantings = get_user_plantings(user_id)
            logger.debug(f"User {user_id} has {len(plantings)} plantings")
        except Exception as e:
            logger.exception(f"Error fetching plantings for user {user_id}: {e}")
            failed += 1
            continue
        
        # Get upcoming tasks and harvests
        upcoming_tasks, upcoming_harvests = get_upcoming_tasks_and_harvests(plantings, DAYS_AHEAD)
        
        # Build personalized message
        subject, message = build_message(user, upcoming_tasks, upcoming_harvests)
        
        # Publish to SNS
        ok, message_id = publish_to_sns(subject, message, email)
        if ok:
            sent += 1
            logger.info(f"Published daily update for user={user_id} email={email} MessageId={message_id} "
                       f"(tasks={len(upcoming_tasks)}, harvests={len(upcoming_harvests)})")
        else:
            failed += 1
        
        # Batch pause to avoid throttling
        if i % BATCH_SIZE == 0:
            logger.info(f"Processed {i}/{total} users (sent={sent} failed={failed} skipped={skipped})")
            time.sleep(BATCH_PAUSE_SECONDS)
    
    logger.info(f"Daily notification run complete: total={total} sent={sent} failed={failed} skipped={skipped}")
    
    return {
        "status": "ok",
        "total": total,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "timestamp": datetime.utcnow().isoformat()
    }

