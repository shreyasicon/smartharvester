import json
import os
import uuid
import logging
from datetime import date, timedelta

from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# local imports
from .forms import SignUpForm
from .models import UserProfile

# Lazy import helper will locate the plan function at call time.
def _get_calculate_plan():
    """Return a callable to calculate a plan.

    First tries built-in plan calculator, then tries external library,
    finally returns fallback if neither is available.
    """
    # Try built-in plan calculator first
    try:
        from .plan_calculator import calculate_plan
        logger.info('Using built-in calculate_plan from tracker.plan_calculator')
        return calculate_plan
    except Exception as e:
        logger.debug('Could not import built-in plan calculator: %s', e)
    
    # Try external library (smartharvest_plan) as fallback
    try:
        import importlib
        mod = importlib.import_module('smartharvest_plan.plan')
        for name in ('calculate_plan', 'generate_plan', 'create_plan', 'build_plan', 'plan'):
            if hasattr(mod, name):
                candidate = getattr(mod, name)
                if callable(candidate):
                    logger.info('Using %s from smartharvest_plan.plan', name)
                    return candidate
        logger.warning('Imported smartharvest_plan.plan but no callable plan function found')
    except Exception as e:
        logger.debug('Could not import smartharvest_plan.plan: %s', e)

    # Final fallback
    def _fallback(*args, **kwargs):
        logger.warning('Using fallback plan calculator (returns empty plan)')
        return []

    return _fallback

DATA_FILE_PATH = os.path.join(settings.BASE_DIR, 'tracker', 'data.json')


def load_plant_data():
    with open(DATA_FILE_PATH, 'r') as f:
        return json.load(f)


def normalize_crop_name(crop_name: str, plant_data: dict = None) -> str:
    """
    Normalize crop name to match exact key in data.json.
    Returns the exact key from data.json if found, otherwise returns original crop_name.
    """
    if not crop_name:
        return crop_name
    
    if plant_data is None:
        plant_data = load_plant_data()
    
    if not isinstance(plant_data, dict):
        return crop_name.strip()
    
    crop_name_clean = crop_name.strip()
    
    # Check exact match first
    if crop_name_clean in plant_data:
        logger.debug('normalize_crop_name: Exact match found: "%s"', crop_name_clean)
        return crop_name_clean
    
    # Check title case (e.g., "tomatoes" -> "Tomatoes", "bell peppers" -> "Bell Peppers")
    crop_title = crop_name_clean.title()
    if crop_title in plant_data:
        logger.debug('normalize_crop_name: Title case match: "%s" -> "%s"', crop_name, crop_title)
        return crop_title
    
    # Check case-insensitive exact match
    crop_lower = crop_name_clean.lower()
    for key in plant_data.keys():
        if isinstance(plant_data.get(key), dict) and key.lower() == crop_lower:
            logger.info('normalize_crop_name: Case-insensitive match: "%s" -> "%s"', crop_name, key)
            return key
    
    # Try fuzzy matching: singular/plural variations (e.g., "Tomato" -> "Tomatoes")
    crop_base = crop_lower.rstrip('s')  # Remove trailing 's'
    for key in plant_data.keys():
        if not isinstance(plant_data.get(key), dict):
            continue
        key_lower = key.lower()
        key_base = key_lower.rstrip('s')
        if crop_base and key_base and crop_base == key_base:
            logger.info('normalize_crop_name: Singular/plural match: "%s" -> "%s"', crop_name, key)
            return key
    
    # Try partial match (e.g., "Bell Pepper" matches "Bell Peppers")
    for key in plant_data.keys():
        if not isinstance(plant_data.get(key), dict):
            continue
        key_lower = key.lower()
        if crop_lower in key_lower or key_lower in crop_lower:
            logger.info('normalize_crop_name: Partial match: "%s" -> "%s"', crop_name, key)
            return key
    
    # If not found, return original (stripped) but log warning
    available_plants = [k for k in plant_data.keys() if isinstance(plant_data.get(k), dict)]
    logger.warning('normalize_crop_name: Could not normalize "%s" to match any plant. Available: %s', 
                  crop_name, available_plants[:10])
    return crop_name_clean


# Small dynamic importer to try multiple helper names from tracker.dynamodb_helper
def _get_helper(*names):
    """
    Try to import functions by name from tracker.dynamodb_helper.
    Returns the first callable found or None.
    """
    for name in names:
        try:
            mod = __import__('tracker.dynamodb_helper', fromlist=[name])
            fn = getattr(mod, name, None)
            if fn:
                return fn
        except Exception:
            continue
    return None


def index(request):
    """
    Display the user's saved plantings.
    Loads per-user plantings from DynamoDB when possible, otherwise falls back to session storage.
    """
    # helpers (may or may not exist depending on which dynamodb_helper version is installed)
    load_user_plantings = _get_helper('load_user_plantings')
    get_user_id_from_token = _get_helper('get_user_id_from_token', 'get_user_id_from_request')
    get_user_data_from_token = _get_helper('get_user_data_from_token', 'get_user_id_from_token')
    get_user_notification_preference = _get_helper('get_user_notification_preference', 'get_notification_preference')

    user_plantings = []

    # Determine user id - check middleware first, then helpers, then fallback
    user_id = None
    user_email = None
    user_name = None
    username = None  # For filtering session plantings
    try:
        # First check if middleware attached user info (fastest path)
        if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
            user_id = request.cognito_user_id
            if hasattr(request, 'cognito_payload') and request.cognito_payload:
                payload = request.cognito_payload
                user_email = payload.get('email')
                user_name = payload.get('name') or payload.get('preferred_username')
                username = (
                    payload.get('cognito:username') or
                    payload.get('preferred_username') or
                    payload.get('username') or
                    payload.get('email')
                )
            logger.info('Index: Using user_id from middleware: %s', user_id)
        elif get_user_id_from_token:
            user_id = get_user_id_from_token(request)
            if hasattr(request, 'cognito_payload') and request.cognito_payload:
                payload = request.cognito_payload
                user_email = payload.get('email')
                user_name = payload.get('name') or payload.get('preferred_username')
                username = (
                    payload.get('cognito:username') or
                    payload.get('preferred_username') or
                    payload.get('username') or
                    payload.get('email')
                )
            logger.info('Index: Using user_id from helper: %s', user_id)
        else:
            # Fallback: use django auth user id if logged in
            if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
                user_id = str(request.user.pk)
                user_email = getattr(request.user, 'email', None)
                user_name = getattr(request.user, 'username', None)
                username = getattr(request.user, 'username', None)
            logger.info('Index: Using user_id from Django auth: %s', user_id)
    except Exception as e:
        logger.exception('Error fetching user id: %s', e)

    logger.info('Index: user_id = %s, email = %s, name = %s, username = %s', 
                user_id if user_id else 'None', user_email, user_name, username)

    # STEP 1: Load user data from DynamoDB (primary source for Cognito users)
    # This ensures we have the latest user profile data from DynamoDB
    if user_id or username:
        try:
            from .dynamodb_helper import get_user_from_dynamodb
            dynamodb_user = None
            # Try loading by user_id first, then username
            if user_id:
                dynamodb_user = get_user_from_dynamodb(user_id)
            if not dynamodb_user and username:
                dynamodb_user = get_user_from_dynamodb(username)
            
            if dynamodb_user:
                # Use DynamoDB user data as source of truth
                if not user_email and dynamodb_user.get('email'):
                    user_email = dynamodb_user.get('email')
                if not user_name and dynamodb_user.get('name'):
                    user_name = dynamodb_user.get('name')
                if not username and dynamodb_user.get('username'):
                    username = dynamodb_user.get('username')
                if not user_id and dynamodb_user.get('user_id'):
                    user_id = dynamodb_user.get('user_id')
                logger.info('✅ Loaded user data from DynamoDB: user_id=%s, username=%s, email=%s', 
                           user_id, username, user_email)
        except Exception as e:
            logger.debug('Could not load user from DynamoDB (will use token data): %s', e)

    # STEP 2: ALWAYS load plantings from DynamoDB first if user_id exists (permanent storage)
    # Then merge with session for immediate display (newly saved items may not be in DynamoDB yet)
    dynamodb_load_failed = False
    dynamodb_plantings = []
    
    if user_id and load_user_plantings:
        try:
            dynamodb_plantings = load_user_plantings(user_id)
            # Convert DynamoDB types (Decimal, etc.) to Python types
            if dynamodb_plantings:
                from decimal import Decimal
                def convert_dynamo_types(obj):
                    """Convert DynamoDB types to Python types."""
                    if isinstance(obj, Decimal):
                        # Convert Decimal to float or int
                        if obj % 1 == 0:
                            return int(obj)
                        return float(obj)
                    elif isinstance(obj, dict):
                        return {k: convert_dynamo_types(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_dynamo_types(item) for item in obj]
                    return obj
                
                dynamodb_plantings = [convert_dynamo_types(p) for p in dynamodb_plantings]
                logger.info('✅ Loaded %d plantings from DynamoDB for user_id: %s (permanent storage)', len(dynamodb_plantings), user_id)
            else:
                logger.info('DynamoDB returned empty list for user_id: %s (no plantings saved yet)', user_id)
        except Exception as e:
            logger.exception('❌ Error loading from DynamoDB: %s - will try session fallback', e)
            dynamodb_load_failed = True

    # Start with DynamoDB plantings
    user_plantings = dynamodb_plantings.copy() if dynamodb_plantings else []
    
    # Merge with session plantings for immediate display (newly saved items)
    # This ensures newly added plantings appear immediately even if DynamoDB save is delayed
    session_plantings = request.session.get('user_plantings', [])
    if session_plantings:
        # Filter session plantings by user_id to avoid cross-user data
        if user_id:
            filtered_session = [
                p for p in session_plantings 
                if p.get('user_id') == user_id or p.get('username') == username
            ]
            # Merge: add session items that aren't already in DynamoDB results
            # Use planting_id to deduplicate
            dynamodb_ids = {p.get('planting_id') for p in user_plantings if p.get('planting_id')}
            for session_item in filtered_session:
                session_id = session_item.get('planting_id')
                if session_id and session_id not in dynamodb_ids:
                    # This is a new item in session not yet in DynamoDB - add it
                    user_plantings.append(session_item)
                    logger.debug('Merged session planting %s (not yet in DynamoDB)', session_id)
            
            if filtered_session and not dynamodb_plantings:
                logger.info('Using %d plantings from session (DynamoDB empty, filtered by user_id: %s)', len(filtered_session), user_id)
        else:
            # No user_id - use all session plantings (anonymous users)
            if not user_plantings:
                user_plantings = session_plantings
                logger.info('Using %d plantings from session (no user_id - anonymous user)', len(user_plantings))
    
    # If DynamoDB failed and we have session, use session
    if dynamodb_load_failed and not user_plantings and session_plantings:
        if user_id:
            filtered_session = [
                p for p in session_plantings 
                if p.get('user_id') == user_id or p.get('username') == username
            ]
            if filtered_session:
                user_plantings = filtered_session
                logger.warning('⚠️ Using %d plantings from session (DynamoDB failed, filtered by user_id: %s)', len(user_plantings), user_id)
        else:
            user_plantings = session_plantings
            logger.warning('⚠️ Using %d plantings from session (DynamoDB failed, no user_id filter)', len(user_plantings))
    
    logger.info('Final plantings count: %d (DynamoDB: %d, Session merged: %d)', 
                len(user_plantings), len(dynamodb_plantings), len(session_plantings))

    today = date.today()
    ongoing, upcoming, past = [], [], []

    # Process plantings - robust parsing for dates and image_url
    # Ensure all fields from DynamoDB are properly extracted, especially image_url
    plans_regenerated = 0
    plans_with_steps = 0
    for i, planting_data in enumerate(user_plantings):
        try:
            planting = dict(planting_data)  # copy
            planting['id'] = i
            
            # Extract image_url - prioritize direct field, then nested access
            # DynamoDB stores it as 'image_url' directly
            planting['image_url'] = (
                planting.get('image_url') or 
                planting_data.get('image_url') or 
                ''
            )
            
            # Log if image_url exists for debugging
            if planting.get('image_url'):
                logger.debug('Planting %d has image_url: %s', i, planting.get('image_url'))

            # planting_date must be parsed (ISO string expected)
            if 'planting_date' in planting:
                if isinstance(planting['planting_date'], str):
                    planting['planting_date'] = date.fromisoformat(planting['planting_date'])
                elif isinstance(planting['planting_date'], date):
                    pass
                else:
                    logger.warning('Planting at index %d has unexpected planting_date type: %s', i, type(planting['planting_date']))
                    continue
            else:
                logger.warning('Planting at index %d missing planting_date, skipping', i)
                continue

            # CRITICAL: ALWAYS regenerate plan using library to ensure it's up-to-date
            # This ensures all plants show steps from care_schedule in data.json
            crop_name_raw = planting.get('crop_name', '').strip()
            planting_date_obj = planting.get('planting_date')
            old_plan = planting.get('plan', [])  # Keep old plan as fallback only
            
            # FORCE regenerate plan for EVERY planting - this is MANDATORY
            # The plan MUST be generated from care_schedule in data.json
            calculated_plan = []
            plan_generation_success = False
            
            if crop_name_raw and planting_date_obj:
                try:
                    # Ensure planting_date is a date object
                    if isinstance(planting_date_obj, str):
                        planting_date_obj = date.fromisoformat(planting_date_obj)
                    
                    # Always regenerate plan to ensure latest data.json is used
                    plant_data = load_plant_data()
                    
                    # Normalize crop_name to match exact key in data.json
                    crop_name = normalize_crop_name(crop_name_raw, plant_data)
                    
                    # Update planting dict with normalized name (ALWAYS update to ensure consistency)
                    planting['crop_name'] = crop_name
                    if crop_name != crop_name_raw:
                        logger.info('📝 Normalized crop_name: "%s" -> "%s"', crop_name_raw, crop_name)
                    
                    # Log what we're about to calculate
                    logger.info('🔄 FORCING plan regeneration for crop: "%s" (original: "%s"), planting_date: %s', 
                              crop_name, crop_name_raw, planting_date_obj.isoformat())
                    
                    # Verify plant exists in data.json before calculating
                    if isinstance(plant_data, dict) and crop_name in plant_data:
                        plant_info = plant_data[crop_name]
                        care_schedule = plant_info.get('care_schedule', [])
                        logger.info('✅ Crop "%s" found in data.json with %d care schedule items', crop_name, len(care_schedule))
                    else:
                        logger.error('❌ Crop "%s" NOT found in data.json. Available plants: %s', 
                                   crop_name, list(plant_data.keys())[:12] if isinstance(plant_data, dict) else 'N/A')
                        # Don't continue if crop not found - this is a real error
                        planting['plan'] = []
                        continue
                    
                    calculate = _get_calculate_plan()
                    calculated_plan = calculate(crop_name, planting_date_obj, plant_data)
                    
                    # Log plan generation result
                    if calculated_plan and len(calculated_plan) > 0:
                        logger.info('✅ Plan calculator returned %d tasks for "%s"', len(calculated_plan), crop_name)
                        for idx, task in enumerate(calculated_plan):
                            logger.debug('  Task %d: %s (due: %s)', idx+1, task.get('task'), task.get('due_date'))
                    else:
                        logger.error('❌ Plan calculator returned empty list for "%s". This should not happen!', crop_name)
                    
                    if calculated_plan and len(calculated_plan) > 0:
                        plan_generation_success = True
                        logger.info('✅ Generated %d tasks for "%s" from care_schedule', len(calculated_plan), crop_name)
                        
                        # Keep dates as date objects for template rendering (don't convert to ISO strings here)
                        # The template needs date objects for the date filter to work
                        # Ensure all dates are date objects (not strings) for template rendering
                        for task in calculated_plan:
                            if 'due_date' in task and isinstance(task['due_date'], str):
                                try:
                                    task['due_date'] = date.fromisoformat(task['due_date'])
                                except (ValueError, TypeError):
                                    logger.warning('Could not parse due_date string: %s', task.get('due_date'))
                                    task['due_date'] = None
                        
                        # CRITICAL: Always set the plan on the planting dict
                        planting['plan'] = calculated_plan
                        plans_regenerated += 1
                        plans_with_steps += 1
                        
                        logger.debug('✅ Set plan with %d tasks for planting %d (crop: %s)', len(calculated_plan), i, crop_name)
                        was_empty = not old_plan or len(old_plan) == 0
                        logger.info('✅ Regenerated plan for planting %d (crop: %s, planted: %s) - %d tasks from care_schedule (was empty: %s)', 
                                  i, crop_name, planting_date_obj.isoformat(), len(calculated_plan), was_empty)
                        
                        # Log each task for debugging
                        for idx, task in enumerate(calculated_plan):
                            logger.debug('  Task %d: "%s" due on %s', idx+1, task.get('task'), task.get('due_date'))
                        
                        # Auto-save updated plan back to DynamoDB with all required fields
                        try:
                            from .dynamodb_helper import save_planting_to_dynamodb
                            planting_id = planting.get('planting_id')
                            if not planting_id:
                                planting_id = planting.get('id')
                            if planting_id:
                                updated_planting = dict(planting)
                                # For DynamoDB save, convert dates to ISO strings
                                plan_for_db = []
                                for task in calculated_plan:
                                    task_copy = dict(task)
                                    if 'due_date' in task_copy and isinstance(task_copy['due_date'], date):
                                        task_copy['due_date'] = task_copy['due_date'].isoformat()
                                    plan_for_db.append(task_copy)
                                
                                updated_planting['plan'] = plan_for_db
                                updated_planting['crop_name'] = crop_name  # Ensure normalized name is saved
                                # Ensure required fields for DynamoDB save
                                if 'user_id' not in updated_planting and user_id:
                                    updated_planting['user_id'] = user_id
                                if 'username' not in updated_planting and username:
                                    updated_planting['username'] = username
                                if 'planting_id' not in updated_planting:
                                    updated_planting['planting_id'] = str(planting_id)
                                
                                saved_id = save_planting_to_dynamodb(updated_planting)
                                if saved_id:
                                    logger.info('✅ Auto-saved regenerated plan to DynamoDB for planting_id: %s (crop: %s)', saved_id, crop_name)
                        except Exception as save_error:
                            logger.warning('⚠️ Could not auto-save regenerated plan to DynamoDB: %s', save_error)
                    else:
                        # Plan calculator returned empty - this should NOT happen if crop is in data.json
                        logger.error('❌ CRITICAL: Plan calculator returned empty plan for "%s" (normalized from "%s"). Available plants: %s', 
                                    crop_name, crop_name_raw, 
                                    list(plant_data.keys())[:12] if isinstance(plant_data, dict) else 'N/A')
                        # Set empty plan - this will show "No steps available"
                        planting['plan'] = []
                        planting['crop_name'] = crop_name
                        plan_generation_success = False
                except Exception as e:
                    logger.exception('❌ Error regenerating plan for planting %d (crop: "%s"): %s', i, crop_name_raw, e)
                    # On error, try to use old plan, but log the error
                    planting['plan'] = old_plan if old_plan else []
                    logger.warning('⚠️ Using old plan as fallback for planting %d (crop: "%s")', i, crop_name_raw)
                    plan_generation_success = False
            else:
                logger.warning('⚠️ CRITICAL: Skipping plan regeneration - missing crop_name or planting_date (crop_name=%s, planting_date=%s)', 
                             crop_name_raw, planting_date_obj)
                # If missing required fields, use old plan or empty
                planting['plan'] = old_plan if old_plan else []
                
            # FINAL CHECK: Ensure planting always has a 'plan' key
            if 'plan' not in planting:
                planting['plan'] = []
                logger.error('❌ CRITICAL: Planting %d missing plan key - added empty plan', i)
            
            # Final step: Ensure all plan dates are date objects for template rendering
            # This ensures the template can use Django's date filter
            plan_list = planting.get('plan', [])
            if plan_list and len(plan_list) > 0:
                logger.debug('Final normalization: %d plan tasks for planting %d (crop: %s)', len(plan_list), i, planting.get('crop_name'))
                for task_idx, task in enumerate(plan_list):
                    if 'due_date' in task and task['due_date']:
                        try:
                            if isinstance(task['due_date'], str):
                                task['due_date'] = date.fromisoformat(task['due_date'])
                                logger.debug('  Task %d: Converted ISO string to date: %s', task_idx, task['due_date'])
                            elif isinstance(task['due_date'], date):
                                # Already a date object - perfect!
                                pass
                            else:
                                logger.warning('  Task %d: Unexpected due_date type: %s for crop %s', task_idx, type(task['due_date']), planting.get('crop_name'))
                                task['due_date'] = None
                        except (ValueError, TypeError) as e:
                            logger.warning('Error parsing due_date in planting %d, task %d: %s - due_date value: %s', i, task_idx, e, task.get('due_date'))
                            task['due_date'] = None
                planting['plan'] = plan_list
                logger.info('✅ Final plan for planting %d (crop: %s): %d tasks with dates', i, planting.get('crop_name'), len(plan_list))
            else:
                logger.warning('⚠️ Planting %d (crop: %s) has no plan or empty plan after regeneration', i, planting.get('crop_name'))
                planting['plan'] = []

            # Determine harvest_date from last task that has due_date
            plan_list = planting.get('plan', [])
            harvest_task = None
            
            # Find the last task with a valid due_date
            if plan_list:
                for task in reversed(plan_list):
                    due_date_val = task.get('due_date')
                    if due_date_val:
                        # Ensure it's a date object
                        if isinstance(due_date_val, str):
                            try:
                                due_date_val = date.fromisoformat(due_date_val)
                            except (ValueError, TypeError):
                                continue
                        if isinstance(due_date_val, date):
                            harvest_task = task
                            break
            
            if harvest_task and harvest_task.get('due_date'):
                harvest_date = harvest_task['due_date']
                # Ensure harvest_date is a date object
                if isinstance(harvest_date, str):
                    try:
                        harvest_date = date.fromisoformat(harvest_date)
                    except (ValueError, TypeError):
                        harvest_date = None
                
                if harvest_date:
                    planting['harvest_date'] = harvest_date
                    days_until_harvest = (harvest_date - today).days
                    
                    # Categorize: past (already harvested), upcoming (within 7 days), ongoing (more than 7 days away)
                    if days_until_harvest < 0:
                        # Harvest date is in the past
                        past.append(planting)
                        logger.info('📅 Planting %d (crop: %s) categorized as PAST - harvest_date: %s (was %d days ago, today: %s)', 
                                   i, crop_name, harvest_date.isoformat(), abs(days_until_harvest), today.isoformat())
                    elif days_until_harvest <= 7:
                        # Harvest date is within 7 days
                        upcoming.append(planting)
                        logger.info('📅 Planting %d (crop: %s) categorized as UPCOMING - harvest_date: %s (in %d days, today: %s)', 
                                   i, crop_name, harvest_date.isoformat(), days_until_harvest, today.isoformat())
                    else:
                        # Harvest date is more than 7 days away
                        ongoing.append(planting)
                        logger.info('📅 Planting %d (crop: %s) categorized as ONGOING - harvest_date: %s (in %d days, today: %s)', 
                                   i, crop_name, harvest_date.isoformat(), days_until_harvest, today.isoformat())
                else:
                    # Invalid harvest_date - treat as ongoing
                    ongoing.append(planting)
                    logger.warning('Planting %d has invalid harvest_date format, categorizing as ONGOING', i)
            else:
                # No harvest_date - treat as ongoing
                ongoing.append(planting)
                logger.debug('Planting %d has no harvest_date, categorizing as ONGOING', i)
        except Exception as e:
            logger.exception('Error processing planting at index %d: %s', i, e)
            continue

    logger.info('Processed plantings: ongoing=%d, upcoming=%d, past=%d', len(ongoing), len(upcoming), len(past))

    # Get user info and notification preference (best-effort)
    # Get user information for display and notifications
    notifications_enabled = True
    # Use the user data we already extracted above (from middleware or helpers)
    # If not set, try to get it again
    if not user_email or not user_name:
        try:
            # Check Cognito payload first (from middleware - fastest)
            if hasattr(request, 'cognito_payload') and request.cognito_payload:
                payload = request.cognito_payload
                if not user_email:
                    user_email = payload.get('email')
                if not user_name:
                    user_name = payload.get('name') or payload.get('preferred_username') or payload.get('cognito:username')
                username = user_name or user_email
                logger.info('Index: Using user data from Cognito payload: email=%s, name=%s', user_email, user_name)
            elif get_user_data_from_token:
                try:
                    user_data = get_user_data_from_token(request)
                    if user_data:
                        if not user_email:
                            user_email = user_data.get('email')
                        if not user_name:
                            user_name = user_data.get('name') or user_data.get('preferred_username') or user_data.get('cognito:username')
                        username = user_name or user_email
                except Exception:
                    # If function expects a token string, try using session id_token
                    try:
                        id_token = request.session.get('id_token')
                        if id_token:
                            user_data = get_user_data_from_token(id_token)
                            if user_data:
                                if not user_email:
                                    user_email = user_data.get('email')
                                if not user_name:
                                    user_name = user_data.get('name') or user_data.get('preferred_username') or user_data.get('cognito:username')
                                username = user_name or user_email
                    except Exception:
                        pass

            # Fallback to Django auth
            if (not user_email or not user_name) and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
                if not user_email:
                    user_email = getattr(request.user, 'email', None)
                if not user_name:
                    user_name = request.user.get_full_name() or request.user.username
                username = user_name or user_email
        except Exception as e:
            logger.exception('Error getting user data: %s', e)

    # Set username for template (use name or email as fallback)
    username = user_name or user_email or username if 'username' in locals() else (user_name or user_email or 'User')

    # Get notification preference
    if username and get_user_notification_preference:
        try:
            notifications_enabled = get_user_notification_preference(username)
        except Exception:
            logger.exception('Error getting notification preference for %s', username)

    logger.info('Index: Final user data - email=%s, name=%s, username=%s, user_id=%s', 
                user_email, user_name, username, user_id)

    # Create a user-like object for the template (works for both Cognito and Django users)
    class UserData:
        def __init__(self, username, email, name=None, user_id=None):
            self.username = username or email or 'User'
            self.email = email or ''
            self.name = name or username or email or 'User'
            self.user_id = user_id
            # For compatibility with Django user methods
            self.get_full_name = lambda: self.name
            self.first_name = name.split()[0] if name and ' ' in name else ''
            self.last_name = ' '.join(name.split()[1:]) if name and ' ' in name else ''
    
    template_user = UserData(
        username=username or user_email or 'User',
        email=user_email or '',
        name=user_name or username or user_email or 'User',
        user_id=user_id
    )

    # Log summary of plans generated
    total_plantings = len(ongoing) + len(upcoming) + len(past)
    plantings_with_plans = sum(1 for p in ongoing + upcoming + past if p.get('plan') and len(p.get('plan', [])) > 0)
    # Count plantings with plans
    plantings_with_plans = sum(1 for p in ongoing + upcoming + past if p.get('plan') and len(p.get('plan', [])) > 0)
    logger.info('📊 Index view summary: %d total plantings, %d with plans (regenerated: %d, with steps: %d)', 
                total_plantings, plantings_with_plans, plans_regenerated, plans_with_steps)
    
    context = {
        'ongoing': ongoing,
        'upcoming': upcoming,
        'past': past,
        'notifications_enabled': notifications_enabled,
        'user': template_user,  # Main user object for template
        'user_email': user_email,
        'username': username,
        'user_name': user_name,
        'user_id': user_id,
    }
    return render(request, 'tracker/index.html', context)


def add_planting_view(request):
    """
    Display form to add a new planting.
    Requires authentication (Cognito or Django).
    """
    # Check for authentication - same logic as save_planting
    user_id = None
    is_authenticated = False
    
    # Check for Cognito user first (from middleware)
    if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
        user_id = request.cognito_user_id
        is_authenticated = True
        logger.info('add_planting_view: Using Cognito user_id from middleware: %s', user_id)
    else:
        # Check for Cognito tokens in session (user might be logged in but middleware hasn't processed yet)
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            # User has a token in session - they're authenticated
            # Even if verification fails, if they have a token, they're logged in
            is_authenticated = True
            logger.info('add_planting_view: Found id_token in session, user is authenticated')
            
            # Try to get user_id from token (best effort)
            try:
                from .dynamodb_helper import get_user_id_from_token
                user_id = get_user_id_from_token(request)
                if user_id:
                    logger.info('add_planting_view: Using user_id from helper: %s', user_id)
                else:
                    # Try to decode token directly to get sub
                    try:
                        import jwt as pyjwt
                        decoded = pyjwt.decode(id_token, options={"verify_signature": False})
                        user_id = decoded.get('sub') or decoded.get('cognito:username')
                        if user_id:
                            logger.info('add_planting_view: Extracted user_id from token: %s', user_id)
                    except Exception:
                        logger.debug("Could not extract user_id from token, but user is authenticated")
            except Exception:
                logger.debug("Error extracting user identity, but user has token - allowing access")
        
        # Try helper functions if no token found in session
        if not is_authenticated:
            try:
                from .dynamodb_helper import get_user_id_from_token
                user_id = get_user_id_from_token(request)
                if user_id:
                    is_authenticated = True
                    logger.info('add_planting_view: Using user_id from helper: %s', user_id)
            except Exception:
                logger.debug("No user_id found from helper functions")
    
    # Fallback to Django auth
    if not is_authenticated and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        user_id = f"django_{getattr(request.user, 'pk', '')}"
        is_authenticated = True
        logger.info('add_planting_view: Using Django user_id: %s', user_id)
    
    # Require authentication - redirect to Cognito login if no user found
    if not is_authenticated:
        # Final check: if there's a token in session, user is authenticated even if we can't extract user_id
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            # User has a token - they're authenticated, allow access
            is_authenticated = True
            logger.info('add_planting_view: Found token in session, allowing access even without user_id')
        else:
            logger.warning('add_planting_view: No authenticated user found, redirecting to Cognito login')
            logger.debug('add_planting_view: Session keys: %s', list(request.session.keys()))
            logger.debug('add_planting_view: Has cognito_user_id attr: %s', hasattr(request, 'cognito_user_id'))
            if hasattr(request, 'cognito_user_id'):
                logger.debug('add_planting_view: cognito_user_id value: %s', getattr(request, 'cognito_user_id', None))
            # Save the current URL so we can redirect back after login
            request.session['next_url'] = request.path
            request.session.modified = True
            logger.info('add_planting_view: Saved next_url=%s for redirect after login', request.path)
            # Redirect to Cognito login instead of Django login
            return redirect('cognito_login')
    
    logger.info('add_planting_view: User authenticated (user_id=%s), rendering add planting form', user_id)
    plant_data = load_plant_data()
    # New structure: plant names are keys in the flat dict (e.g., {"Basil": {...}, "Cucumbers": {...}})
    if isinstance(plant_data, dict):
        # Extract plant names from keys (filter out non-dict values)
        plant_names = sorted([name for name in plant_data.keys() if isinstance(plant_data.get(name), dict)])
    else:
        # Fallback: empty list if structure is unexpected
        plant_names = []
        logger.warning('Unexpected plant_data structure in add_planting_view')
    
    context = {
        'plant_names': plant_names,
        'is_editing': False
    }
    return render(request, 'tracker/edit.html', context)


def save_planting(request):
    """
    Save planting:
     - upload image to S3 (if provided) and set image_url (public URL)
     - resolve username (table PK) and a stable user_id (Cognito sub or django_<pk>)
     - persist planting to DynamoDB (including username and user_id)
     - always save to session for immediate UI
     
    Works like Django login - checks Django user first, then Cognito user.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if request.method != 'POST':
        return redirect('index')

    from datetime import date as _date
    import uuid

    # STEP 1: Check Django user first (same as Django login pattern)
    user_id = None
    username = None
    
    if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        username = getattr(request.user, 'username', None)
        user_id = f"django_{getattr(request.user, 'pk', '')}"
        logger.info('save_planting: Using Django user - user_id: %s, username: %s', user_id, username)
    
    # STEP 2: If no Django user, check Cognito user (from middleware)
    if not user_id:
        if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
            user_id = request.cognito_user_id
            if hasattr(request, 'cognito_payload') and request.cognito_payload:
                payload = request.cognito_payload
                username = (
                    payload.get('cognito:username') or
                    payload.get('preferred_username') or
                    payload.get('username') or
                    payload.get('email')
                )
            logger.info('save_planting: Using Cognito user from middleware - user_id: %s, username: %s', user_id, username)
    
    # STEP 3: If still no user, try to get from session token
    if not user_id:
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            try:
                import jwt as pyjwt
                decoded = pyjwt.decode(id_token, options={"verify_signature": False})
                user_id = decoded.get('sub')
                if not username:
                    username = (
                        decoded.get('cognito:username') or
                        decoded.get('preferred_username') or
                        decoded.get('username') or
                        decoded.get('email')
                    )
                logger.info('save_planting: Extracted from session token - user_id: %s, username: %s', user_id, username)
            except Exception as e:
                logger.warning('save_planting: Cannot extract user_id from token: %s', e)
    
    # STEP 4: Require authentication - redirect to login if no user found
    if not user_id:
        logger.warning('save_planting: No authenticated user found - redirecting to login')
        try:
            request.session['next_url'] = '/add/'
            request.session.modified = True
        except Exception:
            pass
        return redirect('cognito_login')
    
    # Ensure username is set (use user_id as fallback)
    if not username:
        username = user_id
        logger.warning('save_planting: No username found, using user_id as username: %s', username)
    
    # Wrap the rest in try-except to catch any errors
    try:
        crop_name_raw = request.POST.get('crop_name')
        planting_date_str = request.POST.get('planting_date')
        # fixed quoting for strftime
        batch_id = request.POST.get('batch_id', f"batch-{_date.today().strftime('%Y%m%d')}")
        notes = request.POST.get('notes', '')

        # Lazy helpers - always import DynamoDB helpers for Cognito users
        from .dynamodb_helper import save_planting_to_dynamodb, get_user_from_dynamodb
        from .s3_helper import upload_planting_image
        
        # TRUST LAMBDA TRIGGER: Load user from DynamoDB (Lambda already saved it)
        # Use DynamoDB user data as source of truth for user_id and username
        if user_id and not user_id.startswith('django_'):
            try:
                dynamodb_user = None
                # Try loading by user_id first, then username
                if user_id:
                    dynamodb_user = get_user_from_dynamodb(user_id)
                if not dynamodb_user and username:
                    dynamodb_user = get_user_from_dynamodb(username)
                
                if dynamodb_user:
                    # Use DynamoDB user data as source of truth (Lambda trigger saved it)
                    dynamodb_user_id = dynamodb_user.get('user_id') or dynamodb_user.get('sub')
                    dynamodb_username = dynamodb_user.get('username') or dynamodb_user.get('preferred_username')
                    
                    if dynamodb_user_id:
                        user_id = dynamodb_user_id
                        logger.info('✅ Using user_id from DynamoDB (Lambda trigger saved it): %s', user_id)
                    if dynamodb_username:
                        username = dynamodb_username
                        logger.info('✅ Using username from DynamoDB (Lambda trigger saved it): %s', username)
                else:
                    logger.warning('⚠️ Cognito user not found in DynamoDB (user_id=%s, username=%s). '
                                  'Lambda trigger may not have run yet. Using token data as fallback.', 
                                  user_id, username)
                    # Don't save user here - Lambda trigger will handle it
            except Exception as e:
                logger.debug('Could not load user from DynamoDB: %s', e)
                # Don't fail planting save if DynamoDB lookup fails - use token data as fallback

        # Image upload -> returns public URL if s3_helper uses public-read, otherwise presigned URL
        image_url = ""
        if 'image' in request.FILES and request.FILES['image'].name:
            try:
                upload_owner = user_id or username or "anonymous"
                image_url = upload_planting_image(request.FILES['image'], upload_owner)
                logger.info("upload_planting_image returned: %s", image_url)
            except Exception:
                logger.exception("Image upload failed")

        # Validate required fields
        if not crop_name_raw or not planting_date_str:
            logger.error("Missing required fields in save_planting: crop_name=%s, planting_date_str=%s", crop_name_raw, planting_date_str)
            # Return a proper error response instead of redirect to avoid 502
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest("Missing required fields: crop_name and planting_date are required")

        # Parse planting date with error handling
        try:
            planting_date = _date.fromisoformat(planting_date_str)
        except (ValueError, AttributeError) as e:
            logger.error("Invalid planting_date format in save_planting: %s - %s", planting_date_str, e)
            from django.http import HttpResponseBadRequest
            return HttpResponseBadRequest(f"Invalid planting_date format: {planting_date_str}")

        # Normalize crop_name to match exact key in data.json
        plant_data = load_plant_data()
        crop_name = normalize_crop_name(crop_name_raw, plant_data)
        if crop_name != crop_name_raw:
            logger.info('Normalized crop_name for save: "%s" -> "%s"', crop_name_raw, crop_name)

        # Build plan with error handling
        try:
            calculate = _get_calculate_plan()
            calculated_plan = calculate(crop_name, planting_date, plant_data)
        except Exception as e:
            logger.exception("Error building planting plan: %s", e)
            # Use empty plan if calculation fails
            calculated_plan = []
            logger.warning("Using empty plan due to calculation error")

        # Convert due_date in plan to ISO strings for storage
        for task in calculated_plan:
            if 'due_date' in task and isinstance(task['due_date'], _date):
                task['due_date'] = task['due_date'].isoformat()

        # Username should already be set from authentication checks above
        if not username:
            # Fallback: use user_id as username if no username found
            # This ensures the planting can still be saved
            username = user_id
            logger.warning('save_planting: No username found, using user_id as username: %s', username)
        
        # Compose planting dict; include both identifiers (required for DynamoDB queries)
        new_planting = {
            'crop_name': crop_name,
            'planting_date': planting_date.isoformat(),
            'batch_id': batch_id,
            'notes': notes,
            'plan': calculated_plan,
            'image_url': image_url,
            'user_id': user_id,  # Cognito sub or django_<pk>
            'username': username,  # Username from Cognito or Django
        }
        
        logger.info('save_planting: Saving planting with user_id=%s, username=%s', user_id, username)

        # Ensure a planting_id for session immediacy
        local_planting_id = str(uuid.uuid4())
        new_planting['planting_id'] = new_planting.get('planting_id') or local_planting_id

        # Initialize returned_id before try block to avoid NameError
        returned_id = None

        # Persist to DynamoDB - this is critical for permanent storage
        # The planting will be associated with the logged-in user via user_id and username
        try:
            # Log the planting data before saving (for debugging)
            logger.debug('Attempting to save planting to DynamoDB: user_id=%s, username=%s, crop_name=%s, planting_date=%s', 
                        user_id, username, crop_name, planting_date.isoformat())
            logger.debug('Planting data keys: %s', list(new_planting.keys()))
            
            returned_id = save_planting_to_dynamodb(new_planting)
            if returned_id:
                new_planting['planting_id'] = returned_id
                logger.info('✅ Saved planting %s to DynamoDB for user_id=%s, username=%s', returned_id, user_id, username)
            else:
                logger.error('❌ save_planting_to_dynamodb returned None - planting NOT saved to DynamoDB!')
                logger.error('Planting data: user_id=%s, username=%s, crop_name=%s', user_id, username, crop_name)
                logger.error('Check logs above for DynamoDB errors (ClientError, permissions, etc.)')
                logger.warning('Using local id %s for session only', local_planting_id)
        except Exception as e:
            logger.exception('❌ Exception saving planting to DynamoDB: %s', e)
            logger.error('Exception type: %s', type(e).__name__)
            logger.error('Planting data: user_id=%s, username=%s, crop_name=%s', user_id, username, crop_name)
            logger.error('Planting will be lost if session expires!')

        # Always save to session so it appears immediately
        try:
            user_plantings = request.session.get('user_plantings', [])
            user_plantings.append(new_planting)
            request.session['user_plantings'] = user_plantings
            request.session.modified = True
            logger.info('✅ Saved planting to session: total=%d, planting_id=%s, user_id=%s, username=%s', 
                        len(user_plantings), new_planting.get('planting_id'), user_id, username)
        except Exception as session_error:
            logger.exception('❌ Error saving planting to session: %s', session_error)
            # Don't fail the request if session save fails - DynamoDB save succeeded
            logger.warning('⚠️ Planting saved to DynamoDB but session save failed - user may need to refresh to see it')
        logger.info('Planting data: crop_name=%s, planting_date=%s, image_url=%s', 
                    crop_name, planting_date.isoformat(), image_url[:50] if image_url else 'None')

        # Create in-app notification when planting is saved (works locally with session storage)
        try:
            from .dynamodb_helper import save_notification
            # Use returned_id if available, otherwise fall back to planting_id or local_planting_id
            planting_id_for_notification = returned_id if returned_id else (new_planting.get('planting_id') or local_planting_id)
            if user_id:
                logger.info('🔔 Attempting to create in-app notification for user_id=%s, crop_name=%s', user_id, crop_name)
                notification_id = save_notification(
                    user_id=str(user_id).strip(),
                    notification_type='plant_added',
                    title=f'Planting Added: {crop_name}',
                    message=f'You\'ve successfully added {crop_name}. Planting date: {planting_date.strftime("%B %d, %Y")}.',
                    planting_id=str(planting_id_for_notification),
                    metadata={'crop_name': crop_name, 'planting_date': planting_date.isoformat()},
                    request=request  # Pass request for session fallback
                )
                if notification_id:
                    logger.info('✅ Created in-app notification for new planting: notification_id=%s, user_id=%s', notification_id, user_id)
                else:
                    logger.warning('⚠️ save_notification returned None - notification not created.')
            else:
                logger.warning('⚠️ No user_id available - skipping in-app notification creation')
        except Exception as e:
            logger.exception('❌ Error creating in-app notification for new planting: %s', e)
            # Don't fail the request if notification creation fails

        # Send SNS email notification when planting is saved
        logger.info('🔔 SNS Notification: Starting notification process for planting save (user_id=%s, username=%s)', user_id, username)
        try:
            from .sns_helper import publish_notification, ensure_email_subscribed, get_topic_arn
            from .dynamodb_helper import get_user_data_from_token
            
            # Get user's email - try multiple sources
            user_email = None
            email_source = None
            logger.debug('🔔 SNS Notification: Attempting to retrieve email for user_id=%s, username=%s', user_id, username)
            
            # Try Cognito payload first (most reliable)
            if hasattr(request, 'cognito_payload') and request.cognito_payload:
                user_email = request.cognito_payload.get('email')
                if user_email:
                    email_source = 'cognito_payload'
                    logger.info('save_planting: Found email from cognito_payload: %s', user_email)
            
            # Try helper function
            if not user_email:
                try:
                    user_data = get_user_data_from_token(request)
                    if user_data:
                        user_email = user_data.get('email')
                        if user_email:
                            email_source = 'get_user_data_from_token'
                            logger.info('save_planting: Found email from get_user_data_from_token: %s', user_email)
                except Exception as e:
                    logger.debug('save_planting: Error getting user data from token: %s', e)
            
            # Fallback to Django user email
            if not user_email and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
                user_email = getattr(request.user, 'email', None)
                if user_email:
                    email_source = 'django_user'
                    logger.info('save_planting: Found email from Django user: %s', user_email)
            
            # Final fallback: try to get email from DynamoDB user record
            if not user_email and username:
                try:
                    from .dynamodb_helper import dynamo_resource, DYNAMO_USERS_TABLE
                    from boto3.dynamodb.conditions import Attr
                    table = dynamo_resource().Table(DYNAMO_USERS_TABLE)
                    # Try to get user by username (PK) or user_id
                    try:
                        resp = table.get_item(Key={'username': username})
                        if 'Item' in resp:
                            user_email = resp['Item'].get('email')
                            if user_email:
                                email_source = 'dynamodb_users_table'
                                logger.info('save_planting: Found email from DynamoDB users table: %s', user_email)
                    except Exception:
                        pass
                    # If not found by username, try scanning by user_id
                    if not user_email and user_id:
                        try:
                            resp = table.scan(FilterExpression=Attr('user_id').eq(str(user_id)), Limit=1)
                            items = resp.get('Items', [])
                            if items:
                                user_email = items[0].get('email')
                                if user_email:
                                    email_source = 'dynamodb_users_table_scan'
                                    logger.info('save_planting: Found email from DynamoDB users table (scan): %s', user_email)
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug('save_planting: Error getting email from DynamoDB: %s', e)
            
            if user_email:
                logger.info('save_planting: Sending SNS notification to %s (source: %s)', user_email, email_source)
                
                # Ensure email is subscribed to SNS topic (checks if already subscribed)
                topic_arn = get_topic_arn()
                if not topic_arn:
                    logger.error('save_planting: SNS_TOPIC_ARN not configured - cannot send notification')
                else:
                    # Try to ensure subscription (but don't fail if it doesn't work - email might already be subscribed)
                    try:
                        sub_arn = ensure_email_subscribed(user_email, topic_arn)
                        if sub_arn:
                            logger.info('save_planting: Email %s subscription status: %s', user_email, sub_arn)
                            # Check if subscription is confirmed
                            if sub_arn == 'PendingConfirmation':
                                logger.warning('save_planting: Email %s subscription is pending confirmation - notification may not be delivered', user_email)
                            else:
                                logger.info('save_planting: Email %s is confirmed and subscribed', user_email)
                        else:
                            logger.warning('save_planting: Could not verify subscription for %s, but will still attempt to publish', user_email)
                    except Exception as e:
                        logger.warning('save_planting: Error checking subscription for %s: %s - will still attempt to publish', user_email, e)
                    
                    # Send notification email - publish to topic (will be delivered to all confirmed subscribers)
                    subject = f"Planting Added: {crop_name}"
                    message = f"""Hello {username or 'User'},

You've successfully added a new planting to your SmartHarvester account:

Crop: {crop_name}
Planting Date: {planting_date.strftime('%B %d, %Y')}
Batch ID: {batch_id}
{f'Notes: {notes}' if notes else ''}

Your planting has been saved and a care schedule has been generated. You can view your plantings and their care steps in your dashboard.

Happy gardening!
SmartHarvester Team"""
                    
                    try:
                        logger.info('🔔 SNS Notification: Attempting to publish to topic %s for email %s', topic_arn, user_email)
                        logger.debug('🔔 SNS Notification: Subject="%s", Message length=%d chars', subject, len(message))
                        result = publish_notification(subject, message)
                        if result:
                            message_id = result.get('MessageId', 'unknown')
                            logger.info('✅ SUCCESS: Sent SNS notification email for new planting to topic %s (MessageId: %s) - will be delivered to all subscribers including %s', topic_arn, message_id, user_email)
                        else:
                            logger.error('❌ FAILED: publish_notification returned None - SNS publish may have failed silently. Check AWS credentials and SNS topic permissions.')
                    except Exception as e:
                        logger.exception('❌ EXCEPTION: Error while publishing SNS notification: %s', e)
                        logger.error('❌ Exception details: type=%s, args=%s', type(e).__name__, str(e))
            else:
                logger.warning('⚠️ No email found for user (user_id=%s, username=%s) - skipping SNS notification', user_id, username)
                logger.debug('save_planting: Email lookup attempted from: cognito_payload, get_user_data_from_token, django_user')
        except Exception as e:
            logger.exception('❌ Error sending SNS notification for new planting: %s', e)
            # Don't fail the request if notification fails

        # Redirect to index after successful save - MUST return a response
        try:
            return redirect('index')
        except Exception as redirect_error:
            logger.exception('❌ Error during redirect to index: %s', redirect_error)
            # Return a simple response instead of crashing
            from django.http import HttpResponse
            try:
                return HttpResponse("Planting saved successfully. <a href='/'>Go to dashboard</a>", status=200)
            except Exception as response_error:
                logger.exception('❌ Error creating HttpResponse: %s', response_error)
                # Last resort - return minimal response
                from django.http import HttpResponse as HttpResponse2
                return HttpResponse2("OK", status=200)
    except Exception as e:
        logger.exception('❌ FATAL ERROR in save_planting: Unhandled exception caught at top level: %s', e)
        from django.http import HttpResponseServerError
        return HttpResponseServerError("An unexpected error occurred while saving the planting. Please try again.")

def edit_planting_view(request, planting_id):
    """Edit planting view - loads from DynamoDB or session"""
    # Check for authentication - same logic as other views
    user_id = None
    
    # Check for Cognito user first (from middleware)
    if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
        user_id = request.cognito_user_id
        logger.info('edit_planting_view: Using Cognito user_id from middleware: %s', user_id)
    else:
        # Try helper functions
        load_user_plantings = _get_helper('load_user_plantings')
        get_user_id_from_token = _get_helper('get_user_id_from_token', 'get_user_id_from_request')
        try:
            if get_user_id_from_token:
                user_id = get_user_id_from_token(request)
                logger.info('edit_planting_view: Using user_id from helper: %s', user_id)
        except Exception:
            logger.exception('Error getting user id in edit_planting_view')
    
    # Fallback to Django auth
    if not user_id and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        user_id = str(request.user.pk)
        logger.info('edit_planting_view: Using Django user_id: %s', user_id)
    
    # Require authentication
    if not user_id:
        # Final check: if there's a token in session, extract user_id from it
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            try:
                import jwt as pyjwt
                decoded = pyjwt.decode(id_token, options={"verify_signature": False})
                user_id = decoded.get('sub')
                logger.info('edit_planting_view: Extracted user_id from session token: %s', user_id)
            except Exception:
                logger.warning('edit_planting_view: No authenticated user found, redirecting to login')
                return redirect('cognito_login')
        else:
            logger.warning('edit_planting_view: No authenticated user found, redirecting to login')
            return redirect('cognito_login')
    
    load_user_plantings = _get_helper('load_user_plantings')

    user_plantings = []
    if user_id and load_user_plantings:
        try:
            user_plantings = load_user_plantings(user_id)
        except Exception as e:
            logger.exception('Error loading from DynamoDB: %s', e)

    if not user_plantings:
        user_plantings = request.session.get('user_plantings', [])

    if planting_id >= len(user_plantings):
        logger.error('Planting index %d out of range (total: %d)', planting_id, len(user_plantings))
        return redirect('index')

    try:
        planting_to_edit = dict(user_plantings[planting_id])
        planting_to_edit['id'] = planting_id

        # planting_date normalization for the form
        pd = planting_to_edit.get('planting_date', '')
        if isinstance(pd, date):
            planting_to_edit['planting_date_str'] = pd.isoformat()
        elif isinstance(pd, str):
            try:
                date.fromisoformat(pd)
                planting_to_edit['planting_date_str'] = pd
            except Exception:
                planting_to_edit['planting_date_str'] = str(pd)
        else:
            planting_to_edit['planting_date_str'] = str(pd) if pd else ''

        planting_to_edit.setdefault('crop_name', '')
        planting_to_edit.setdefault('batch_id', '')
        planting_to_edit.setdefault('notes', '')
        planting_to_edit.setdefault('image_url', '')

        logger.info('Loading planting for edit: id=%d, crop=%s, date=%s',
                    planting_id, planting_to_edit.get('crop_name'), planting_to_edit.get('planting_date_str'))
    except Exception as e:
        logger.exception('Error preparing planting for edit: %s', e)
        return redirect('index')

    plant_data = load_plant_data()
    # New structure: plant names are keys in the flat dict (e.g., {"Basil": {...}, "Cucumbers": {...}})
    if isinstance(plant_data, dict):
        # Extract plant names from keys (filter out non-dict values)
        plant_names = sorted([name for name in plant_data.keys() if isinstance(plant_data.get(name), dict)])
    else:
        # Fallback: empty list if structure is unexpected
        plant_names = []
        logger.warning('Unexpected plant_data structure in edit_planting_view')
    
    context = {
        'plant_names': plant_names,
        'planting': planting_to_edit,
        'is_editing': True
    }
    return render(request, 'tracker/edit.html', context)


def update_planting(request, planting_id):
    """
    Simple handler to update a planting item in DynamoDB.
    - POST: accepts crop_name, planting_date (ISO), batch_id, notes and optional image file 'image'.
      If an image is provided, it will be uploaded and image_url saved.
    - GET: redirects to index (you can extend to render an edit form if needed).
    """
    import logging
    from django.shortcuts import redirect
    from botocore.exceptions import ClientError
    from .dynamodb_helper import dynamo_resource, DYNAMO_PLANTINGS_TABLE
    from .s3_helper import upload_planting_image

    logger = logging.getLogger(__name__)

    # Only accept POST updates
    if request.method != "POST":
        return redirect("index")
    
    # Check for authentication - same logic as save_planting
    user_id = None
    username = None
    
    # Check for Cognito user first (from middleware)
    if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
        user_id = request.cognito_user_id
        if hasattr(request, 'cognito_payload') and request.cognito_payload:
            payload = request.cognito_payload
            username = payload.get('preferred_username') or payload.get('cognito:username') or payload.get('email')
        logger.info('update_planting: Using Cognito user_id from middleware: %s', user_id)
    else:
        # Try helper functions
        try:
            from .dynamodb_helper import get_user_id_from_token, get_user_data_from_token
            user_id = get_user_id_from_token(request)
            user_data = get_user_data_from_token(request)
            if user_data:
                username = user_data.get('username') or user_data.get('preferred_username') or user_data.get('email')
        except Exception:
            logger.exception("Error extracting user identity")
    
    # Fallback to Django auth
    if not user_id and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        username = getattr(request.user, 'username', None)
        user_id = f"django_{getattr(request.user, 'pk', '')}"
    
    # Require authentication
    if not user_id:
        # Final check: if there's a token in session, extract user_id from it
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            try:
                import jwt as pyjwt
                decoded = pyjwt.decode(id_token, options={"verify_signature": False})
                user_id = decoded.get('sub')
                if not username:
                    username = (
                        decoded.get('cognito:username') or
                        decoded.get('preferred_username') or
                        decoded.get('username') or
                        decoded.get('email')
                    )
                logger.info('update_planting: Extracted user_id from session token: %s', user_id)
            except Exception:
                logger.warning('update_planting: No authenticated user found, redirecting to login')
                return redirect('cognito_login')
        else:
            logger.warning('update_planting: No authenticated user found, redirecting to login')
            return redirect('cognito_login')

    table = dynamo_resource().Table(DYNAMO_PLANTINGS_TABLE)

    # Build update expression pieces dynamically
    update_parts = []
    expr_attr_names = {}
    expr_attr_values = {}

    def add_update(attr_name, value):
        placeholder_name = f"#{attr_name}"
        placeholder_value = f":{attr_name}"
        update_parts.append(f"{placeholder_name} = {placeholder_value}")
        expr_attr_names[placeholder_name] = attr_name
        expr_attr_values[placeholder_value] = value

    # Fields that can be updated via the form
    for field in ("crop_name", "planting_date", "batch_id", "notes"):
        v = request.POST.get(field)
        if v is not None:
            # normalize empty strings to None? keep as-is to allow clearing
            add_update(field, v)

    # Optional image upload handling
    if "image" in request.FILES and request.FILES["image"].name:
        try:
            # Use the authenticated user_id we already determined above
            upload_owner = user_id or username or "anonymous"
            image_url = upload_planting_image(request.FILES["image"], upload_owner)
            if image_url:
                add_update("image_url", image_url)
        except Exception:
            logger.exception("Failed to upload image for planting %s", planting_id)

    if not update_parts:
        # nothing to update
        return redirect("index")

    update_expr = "SET " + ", ".join(update_parts)

    try:
        table.update_item(
            Key={"planting_id": str(planting_id)},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
        )
        logger.info("✅ Updated planting %s: %s", planting_id, update_parts)
        logger.info("🔔 update_planting: user_id=%s, username=%s", user_id, username)
        
        # Get updated crop name for notification
        updated_crop_name = request.POST.get('crop_name', 'Unknown Crop')
        
        # Create in-app notification when planting is updated
        logger.info('🔔 Attempting to create in-app notification for updated planting: user_id=%s, crop_name=%s', user_id, updated_crop_name)
        try:
            from .dynamodb_helper import save_notification
            if user_id:
                notification_id = save_notification(
                    user_id=str(user_id).strip(),
                    notification_type='plant_edited',
                    title=f'Planting Updated: {updated_crop_name}',
                    message=f'You\'ve successfully updated {updated_crop_name}. Changes have been saved.',
                    planting_id=str(planting_id),
                    metadata={'crop_name': updated_crop_name},
                    request=request  # Pass request for session fallback
                )
                if notification_id:
                    logger.info('✅ Created in-app notification for updated planting: notification_id=%s, user_id=%s', notification_id, user_id)
                else:
                    logger.warning('⚠️ save_notification returned None for updated planting - notification not created')
            else:
                logger.warning('⚠️ No user_id available for updated planting - skipping in-app notification creation')
        except Exception as e:
            logger.exception('❌ Error creating in-app notification for updated planting: %s', e)
            # Don't fail the request if notification creation fails
        
        # Send SNS email notification when planting is updated
        try:
            from .sns_helper import publish_notification, ensure_email_subscribed, get_topic_arn
            from .dynamodb_helper import get_user_data_from_token
            
            # Get user's email - try multiple sources
            user_email = None
            email_source = None
            
            # Try Cognito payload first (most reliable)
            if hasattr(request, 'cognito_payload') and request.cognito_payload:
                user_email = request.cognito_payload.get('email')
                if user_email:
                    email_source = 'cognito_payload'
                    logger.info('update_planting: Found email from cognito_payload: %s', user_email)
            
            # Try helper function
            if not user_email:
                try:
                    user_data = get_user_data_from_token(request)
                    if user_data:
                        user_email = user_data.get('email')
                        if user_email:
                            email_source = 'get_user_data_from_token'
                            logger.info('update_planting: Found email from get_user_data_from_token: %s', user_email)
                except Exception as e:
                    logger.debug('update_planting: Error getting user data from token: %s', e)
            
            # Fallback to Django user email
            if not user_email and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
                user_email = getattr(request.user, 'email', None)
                if user_email:
                    email_source = 'django_user'
                    logger.info('update_planting: Found email from Django user: %s', user_email)
            
            # Final fallback: try to get email from DynamoDB user record
            if not user_email and username:
                try:
                    from .dynamodb_helper import dynamo_resource, DYNAMO_USERS_TABLE
                    from boto3.dynamodb.conditions import Attr
                    table = dynamo_resource().Table(DYNAMO_USERS_TABLE)
                    # Try to get user by username (PK) or user_id
                    try:
                        resp = table.get_item(Key={'username': username})
                        if 'Item' in resp:
                            user_email = resp['Item'].get('email')
                            if user_email:
                                email_source = 'dynamodb_users_table'
                                logger.info('update_planting: Found email from DynamoDB users table: %s', user_email)
                    except Exception:
                        pass
                    # If not found by username, try scanning by user_id
                    if not user_email and user_id:
                        try:
                            resp = table.scan(FilterExpression=Attr('user_id').eq(str(user_id)), Limit=1)
                            items = resp.get('Items', [])
                            if items:
                                user_email = items[0].get('email')
                                if user_email:
                                    email_source = 'dynamodb_users_table_scan'
                                    logger.info('update_planting: Found email from DynamoDB users table (scan): %s', user_email)
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug('update_planting: Error getting email from DynamoDB: %s', e)
            
            if user_email:
                logger.info('update_planting: Sending SNS notification to %s (source: %s)', user_email, email_source)
                
                # Ensure email is subscribed to SNS topic (checks if already subscribed)
                topic_arn = get_topic_arn()
                if not topic_arn:
                    logger.error('update_planting: SNS_TOPIC_ARN not configured - cannot send notification')
                else:
                    # Try to ensure subscription (but don't fail if it doesn't work - email might already be subscribed)
                    try:
                        sub_arn = ensure_email_subscribed(user_email, topic_arn)
                        if sub_arn:
                            logger.info('update_planting: Email %s subscription status: %s', user_email, sub_arn)
                            # Check if subscription is confirmed
                            if sub_arn == 'PendingConfirmation':
                                logger.warning('update_planting: Email %s subscription is pending confirmation - notification may not be delivered', user_email)
                            else:
                                logger.info('update_planting: Email %s is confirmed and subscribed', user_email)
                        else:
                            logger.warning('update_planting: Could not verify subscription for %s, but will still attempt to publish', user_email)
                    except Exception as e:
                        logger.warning('update_planting: Error checking subscription for %s: %s - will still attempt to publish', user_email, e)
                    
                    # Send notification email - publish to topic (will be delivered to all confirmed subscribers)
                    subject = f"Planting Updated: {updated_crop_name}"
                    message = f"""Hello {username or 'User'},

You've successfully updated a planting in your SmartHarvester account:

Crop: {updated_crop_name}
Planting ID: {planting_id}
{f'Batch ID: {request.POST.get("batch_id", "")}' if request.POST.get("batch_id") else ''}

The changes have been saved to your account. You can view the updated planting details in your dashboard.

Happy gardening!
SmartHarvester Team"""
                    
                    try:
                        result = publish_notification(subject, message)
                        if result:
                            message_id = result.get('MessageId', 'unknown')
                            logger.info('✅ Sent SNS notification email for updated planting to topic %s (MessageId: %s) - will be delivered to all subscribers including %s', topic_arn, message_id, user_email)
                        else:
                            logger.error('❌ Failed to send SNS notification email for updated planting - publish_notification returned None')
                    except Exception as e:
                        logger.exception('❌ Exception while publishing SNS notification: %s', e)
            else:
                logger.warning('⚠️ No email found for user (user_id=%s, username=%s) - skipping SNS notification', user_id, username)
                logger.debug('update_planting: Email lookup attempted from: cognito_payload, get_user_data_from_token, django_user')
        except Exception as e:
            logger.exception('❌ Error sending SNS notification for updated planting: %s', e)
            # Don't fail the request if notification fails
            
    except ClientError as e:
        logger.exception("DynamoDB update_item failed for planting %s: %s", planting_id, e)

    return redirect("index")

def delete_planting(request, planting_id):
    """Delete planting - Dynamo and session"""
    if request.method != 'POST':
        return redirect('index')

    # Check for authentication - same logic as other views
    user_id = None
    
    # Check for Cognito user first (from middleware)
    if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
        user_id = request.cognito_user_id
        logger.info('delete_planting: Using Cognito user_id from middleware: %s', user_id)
    else:
        # Try helper functions
        get_user_id_from_token = _get_helper('get_user_id_from_token', 'get_user_id_from_request')
        try:
            if get_user_id_from_token:
                user_id = get_user_id_from_token(request)
                logger.info('delete_planting: Using user_id from helper: %s', user_id)
        except Exception:
            logger.exception('Error getting user id in delete_planting')
    
    # Fallback to Django auth
    if not user_id and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        user_id = str(request.user.pk)
        logger.info('delete_planting: Using Django user_id: %s', user_id)
    
    # Require authentication
    if not user_id:
        # Final check: if there's a token in session, extract user_id from it
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            try:
                import jwt as pyjwt
                decoded = pyjwt.decode(id_token, options={"verify_signature": False})
                user_id = decoded.get('sub')
                logger.info('delete_planting: Extracted user_id from session token: %s', user_id)
            except Exception:
                logger.warning('delete_planting: No authenticated user found, redirecting to login')
                return redirect('cognito_login')
        else:
            logger.warning('delete_planting: No authenticated user found, redirecting to login')
            return redirect('cognito_login')

    load_user_plantings = _get_helper('load_user_plantings')
    delete_planting_from_dynamodb = _get_helper('delete_planting_from_dynamodb', 'delete_planting')
    delete_image_from_s3 = _get_helper('delete_image_from_s3')

    user_plantings = []
    if user_id and load_user_plantings:
        try:
            user_plantings = load_user_plantings(user_id)
        except Exception as e:
            logger.exception('Error loading from DynamoDB: %s', e)

    if not user_plantings:
        user_plantings = request.session.get('user_plantings', [])

    if planting_id >= len(user_plantings):
        logger.error('Planting index %d out of range (total: %d)', planting_id, len(user_plantings))
        return redirect('index')

    try:
        planting_to_delete = user_plantings[planting_id]
        actual_planting_id = planting_to_delete.get('planting_id')
        crop_name_to_delete = planting_to_delete.get('crop_name', 'Unknown Crop')
        image_url = planting_to_delete.get('image_url', '')

        if image_url and delete_image_from_s3:
            try:
                delete_image_from_s3(image_url)
                logger.info('Deleted image from S3: %s', image_url)
            except Exception:
                logger.exception('Failed to delete image from S3: %s', image_url)

        if user_id and actual_planting_id and delete_planting_from_dynamodb:
            try:
                deleted = delete_planting_from_dynamodb(actual_planting_id)
                if deleted:
                    logger.info('Deleted planting %s from DynamoDB', actual_planting_id)
                else:
                    logger.warning('Dynamo delete returned falsy; removing from session only')
            except Exception:
                logger.exception('Failed deleting planting from DynamoDB; proceeding to remove from session')

        # Create in-app notification when planting is deleted
        try:
            from .dynamodb_helper import save_notification
            if user_id:
                notification_id = save_notification(
                    user_id=str(user_id).strip(),
                    notification_type='plant_deleted',
                    title=f'Planting Deleted: {crop_name_to_delete}',
                    message=f'You\'ve successfully deleted {crop_name_to_delete}.',
                    planting_id=str(actual_planting_id) if actual_planting_id else None,
                    metadata={'crop_name': crop_name_to_delete},
                    request=request  # Pass request for session fallback
                )
                if notification_id:
                    logger.info('✅ Created in-app notification for deleted planting: %s', notification_id)
        except Exception as e:
            logger.exception('Error creating in-app notification for deleted planting: %s', e)
            # Don't fail the request if notification creation fails
        
        # Remove from session list
        user_plantings.pop(planting_id)
        request.session['user_plantings'] = user_plantings
        request.session.modified = True
        logger.info('Deleted planting at index %d from session', planting_id)
    except Exception:
        logger.exception('Exception while deleting planting')

    return redirect('index')


def cognito_login(request):
    """Redirect user to Cognito Hosted UI login."""
    # Validate required environment variables
    if not settings.COGNITO_DOMAIN:
        logger.error('COGNITO_DOMAIN is not configured')
        return HttpResponse(
            "Cognito domain not configured. Please set COGNITO_DOMAIN environment variable.\n"
            "Format: <prefix>.auth.<region>.amazoncognito.com",
            status=500,
            content_type='text/plain'
        )
    if not settings.COGNITO_CLIENT_ID:
        logger.error('COGNITO_CLIENT_ID is not configured')
        return HttpResponse("Cognito client ID not configured. Please set COGNITO_CLIENT_ID environment variable.", status=500)
    if not settings.COGNITO_REDIRECT_URI:
        logger.error('COGNITO_REDIRECT_URI is not configured')
        return HttpResponse("Cognito redirect URI not configured. Please set COGNITO_REDIRECT_URI environment variable.", status=500)
    
    # Validate domain format (basic check)
    domain = settings.COGNITO_DOMAIN
    if not (domain.endswith('.amazoncognito.com') or domain.endswith('.auth.us-east-1.amazoncognito.com') or 
            any(domain.endswith(f'.auth.{region}.amazoncognito.com') for region in ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2', 'eu-west-1', 'eu-central-1', 'ap-southeast-1', 'ap-southeast-2'])):
        logger.warning('COGNITO_DOMAIN format may be incorrect: %s. Expected format: <prefix>.auth.<region>.amazoncognito.com', domain)
        # Don't fail here, just warn - might be a custom domain
    
    from .cognito import build_authorize_url
    # Use the exact redirect_uri from settings to match Cognito configuration
    # This must match exactly what's configured in Cognito App Client settings
    redirect_uri = settings.COGNITO_REDIRECT_URI
    logger.info('Cognito login: Using redirect_uri from settings: %s', redirect_uri)
    logger.info('Cognito login: Using domain: %s', domain)
    
    try:
        url = build_authorize_url(redirect_uri=redirect_uri)
        logger.info('Cognito login: Redirecting to Cognito authorize URL: %s', url)
        return redirect(url)
    except ValueError as e:
        logger.exception('Configuration error building Cognito authorize URL: %s', e)
        return HttpResponse(f"Configuration error: {str(e)}", status=500)
    except Exception as e:
        logger.exception('Error building Cognito authorize URL: %s', e)
        # Check if it's a connection/DNS error
        error_msg = str(e)
        if 'NameResolutionError' in error_msg or 'Failed to resolve' in error_msg or 'Name or service not known' in error_msg:
            return HttpResponse(
                f"Cognito domain '{domain}' cannot be resolved. "
                "Please verify the COGNITO_DOMAIN is correct and exists in your Cognito User Pool.",
                status=500,
                content_type='text/plain'
            )
        return HttpResponse(f"Error redirecting to Cognito: {str(e)}", status=500)


def cognito_logout(request):
    """Logout user by clearing Cognito tokens and redirecting to login page."""
    request.session.pop('id_token', None)
    request.session.pop('access_token', None)
    request.session.pop('refresh_token', None)
    request.session.pop('cognito_tokens', None)
    logger.info('Cognito logout: Cleared tokens from session, redirecting to login')
    return redirect('login')


def cognito_callback(request):
    """Handle callback from Cognito Hosted UI, exchange code for tokens and save user to DynamoDB (best-effort)."""
    import requests
    from requests.auth import HTTPBasicAuth
    from django.db import OperationalError

    logger.info('Cognito callback received for path: %s', request.path)
    logger.info('Cognito callback query params: %s', request.GET.dict())

    # Validate required environment variables
    if not settings.COGNITO_DOMAIN:
        logger.error('COGNITO_DOMAIN is not configured')
        return HttpResponse("Cognito domain not configured. Please contact administrator.", status=500)
    if not settings.COGNITO_CLIENT_ID:
        logger.error('COGNITO_CLIENT_ID is not configured')
        return HttpResponse("Cognito client ID not configured. Please contact administrator.", status=500)
    if not settings.COGNITO_REDIRECT_URI:
        logger.error('COGNITO_REDIRECT_URI is not configured')
        return HttpResponse("Cognito redirect URI not configured. Please contact administrator.", status=500)

    error = request.GET.get('error')
    error_description = request.GET.get('error_description')
    if error:
        logger.error('Cognito callback error: %s - %s', error, error_description)
        from urllib.parse import quote
        return redirect(f'/?auth_error={quote(error_description or error)}')

    code = request.GET.get('code')
    if not code:
        logger.warning('Cognito callback: No code provided and no error - unexpected response')
        return HttpResponse("No code provided. Please try logging in again.", status=400)

    # Use the exact redirect_uri from settings to match what was used in authorize request
    # This must match exactly what's configured in Cognito App Client settings
    redirect_uri = settings.COGNITO_REDIRECT_URI
    logger.info('Cognito callback: Using redirect_uri from settings: %s', redirect_uri)

    # Build token URL using COGNITO_DOMAIN
    token_url = f"https://{settings.COGNITO_DOMAIN}/oauth2/token"
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    # Use HTTP Basic auth when client secret exists (OAuth2 standard)
    auth = None
    if settings.COGNITO_CLIENT_SECRET:
        auth = HTTPBasicAuth(settings.COGNITO_CLIENT_ID, settings.COGNITO_CLIENT_SECRET)
        # When using HTTP Basic auth, client_id should not be in the body
    else:
        # If no client secret, include client_id in body (for public clients)
        data['client_id'] = settings.COGNITO_CLIENT_ID

    try:
        logger.info('Cognito callback: Exchanging code for tokens at %s', token_url)
        response = requests.post(token_url, data=data, headers=headers, auth=auth, timeout=10)
    except requests.exceptions.ConnectionError as e:
        # Handle DNS/name resolution errors specifically
        error_msg = str(e)
        if 'NameResolutionError' in error_msg or 'Failed to resolve' in error_msg or 'Name or service not known' in error_msg:
            logger.error('Cognito domain resolution failed: %s. Domain: %s', error_msg, settings.COGNITO_DOMAIN)
            return HttpResponse(
                f"Cognito domain '{settings.COGNITO_DOMAIN}' cannot be resolved. "
                "Please verify:\n"
                "1. The COGNITO_DOMAIN environment variable is set correctly\n"
                "2. The domain exists in your Cognito User Pool (check AWS Console)\n"
                "3. The domain format is: <prefix>.auth.<region>.amazoncognito.com\n"
                "4. If using a custom domain, ensure DNS is configured correctly",
                status=500,
                content_type='text/plain'
            )
        logger.exception('Connection error calling Cognito token endpoint: %s', e)
        return HttpResponse(f"Connection error: {str(e)}", status=500)
    except requests.exceptions.RequestException as e:
        logger.exception('Error calling Cognito token endpoint: %s', e)
        return HttpResponse(f"Error fetching tokens: {str(e)}", status=500)

    if response.status_code != 200:
        error_text = response.text
        logger.error('Cognito token exchange failed: %s - %s', response.status_code, error_text)
        try:
            error_data = response.json()
            if error_data.get('error') == 'invalid_grant':
                return HttpResponse("Authorization code invalid or expired. Please try logging in again.", status=400)
        except Exception:
            pass
        return HttpResponse(f"Error fetching tokens: {error_text}", status=response.status_code)

    tokens = response.json()
    logger.info('Cognito callback: Tokens received successfully')

    try:
        request.session['id_token'] = tokens.get('id_token')
        request.session['access_token'] = tokens.get('access_token')
        if tokens.get('refresh_token'):
            request.session['refresh_token'] = tokens.get('refresh_token')
        request.session['cognito_tokens'] = {
            'id_token': tokens.get('id_token'),
            'access_token': tokens.get('access_token'),
            'refresh_token': tokens.get('refresh_token'),
        }
        request.session.modified = True
        logger.info('Cognito callback: Tokens saved to session')

        # Best-effort: decode id_token for logging and then persist via persist_cognito_user
        id_token = tokens.get('id_token')
        payload = {}
        if id_token:
            try:
                # Try jose first (if available), then PyJWT fallback
                try:
                    from jose import jwt as jose_jwt
                    payload = jose_jwt.decode(id_token, options={"verify_signature": False})
                except Exception:
                    try:
                        import jwt as pyjwt
                        payload = pyjwt.decode(id_token, options={"verify_signature": False})
                    except Exception as e:
                        logger.exception('Failed to decode id_token: %s', e)
                        payload = {}
                logger.info('Extracted user data from id_token keys: %s', list(payload.keys()))
            except Exception:
                logger.exception('Exception decoding id_token')

            # Load user from DynamoDB (Lambda trigger already saved it) and migrate session plantings
            try:
                user_exists, resolved_user_id = persist_cognito_user(request, id_token=id_token, claims=payload)
                if resolved_user_id:
                    request.session['user_id'] = resolved_user_id
                    request.session.modified = True
                    if user_exists:
                        logger.info('✅ User loaded from DynamoDB (Lambda trigger saved it): user_id=%s', resolved_user_id)
                    else:
                        logger.warning('⚠️ User not found in DynamoDB yet (Lambda trigger may not have run). Using token user_id: %s', resolved_user_id)
                else:
                    logger.warning('persist_cognito_user did not return user_id')
            except Exception:
                logger.exception('persist_cognito_user raised an exception')
        else:
            logger.warning('No id_token available in Cognito response; skipping user persist')
    except OperationalError as e:
        logger.exception('Database error saving session: %s', e)
        return HttpResponse("Authentication succeeded but session save failed.", status=503)
    except Exception as e:
        logger.exception('Error saving session: %s', e)
        return HttpResponse(f"Error saving session: {str(e)}", status=500)

    # Redirect to the page the user was trying to access, or home page if none
    # Check if there's a 'next_url' saved in session (e.g., from add_planting_view)
    next_url = request.session.pop('next_url', None)
    if next_url:
        # Use absolute URL to avoid protocol/port issues
        redirect_base = settings.COGNITO_REDIRECT_URI.rsplit('/auth/callback/', 1)[0]
        # Ensure next_url starts with / (it should already)
        if not next_url.startswith('/'):
            next_url = '/' + next_url
        redirect_url = redirect_base + next_url
        logger.info('Cognito callback: Redirecting to saved next_url: %s', redirect_url)
    else:
        # Default to home page - use absolute HTTPS URL to avoid protocol/port issues
        # Construct from COGNITO_REDIRECT_URI to ensure we use the correct base URL
        redirect_base = settings.COGNITO_REDIRECT_URI.rsplit('/auth/callback/', 1)[0]
        redirect_url = redirect_base + '/'
        logger.info('Cognito callback: Redirecting to home page: %s', redirect_url)
    return redirect(redirect_url)

def persist_cognito_user(request, id_token: str | None = None, claims: dict | None = None) -> tuple[bool, str | None]:
    """
    Load Cognito user from DynamoDB (Lambda trigger already saved it) and migrate session plantings.
    
    IMPORTANT: The Post Confirmation Lambda trigger automatically saves user data to DynamoDB
    when the user confirms their account. This function trusts that Lambda trigger and loads
    the user from DynamoDB instead of duplicating the save operation.
    
    - id_token: optional JWT string (if not provided, the helper will try request.session['id_token'])
    - claims: optional already-decoded claims dict (if provided, decoding is skipped)
    Returns (user_exists_in_dynamo, resolved_user_id)
    """
    import logging
    import uuid
    from .dynamodb_helper import get_user_data_from_token, get_user_id_from_token, save_planting_to_dynamodb, get_user_from_dynamodb
    logger = logging.getLogger(__name__)

    try:
        # Resolve claims and stable id from token
        if claims is None:
            claims = get_user_data_from_token(id_token or request.session.get("id_token")) or {}
        user_id_from_token = get_user_id_from_token(id_token or request.session.get("id_token")) or claims.get("sub")

        # Extract username using same priority as Lambda trigger
        # Lambda uses event.get("userName") which is typically cognito:username
        username = (
            claims.get("cognito:username") or      # Primary (matches Lambda's event.get("userName"))
            claims.get("preferred_username") or    # Secondary
            claims.get("username") or              # Tertiary
            claims.get("email")                     # Fallback
        )
        
        if not username:
            logger.warning("persist_cognito_user: Could not extract username from token claims")
            return False, None
        
        # TRUST LAMBDA TRIGGER: Load user from DynamoDB (Lambda already saved it)
        dynamodb_user = None
        if username:
            dynamodb_user = get_user_from_dynamodb(username)
        
        # If not found by username, try by user_id
        if not dynamodb_user and user_id_from_token:
            dynamodb_user = get_user_from_dynamodb(user_id_from_token)
        
        if dynamodb_user:
            # Lambda trigger already saved user - use DynamoDB data as source of truth
            from .dynamodb_helper import DYNAMO_USERS_PK
            resolved_user_id = dynamodb_user.get("user_id") or dynamodb_user.get("sub") or user_id_from_token
            resolved_username = dynamodb_user.get("username") or dynamodb_user.get(DYNAMO_USERS_PK) or username
            
            logger.info("✅ User found in DynamoDB (saved by Lambda trigger): username=%s, user_id=%s", 
                       resolved_username, resolved_user_id)
            
            # Migrate session plantings (if any) using DynamoDB user_id
            session_plantings = request.session.pop("user_plantings", []) or []
            migrated = 0
            for sp in session_plantings:
                try:
                    sp["user_id"] = resolved_user_id
                    sp["username"] = resolved_username
                    sp.setdefault("planting_id", sp.get("planting_id") or str(uuid.uuid4()))
                    pid = save_planting_to_dynamodb(sp)
                    if pid:
                        migrated += 1
                except Exception:
                    logger.exception("Failed to migrate planting %s", sp.get("planting_id"))
            if migrated:
                logger.info("✅ Migrated %d session plantings to DynamoDB for user_id=%s", migrated, resolved_user_id)
            
            request.session.modified = True
            return True, resolved_user_id
        else:
            # User not found in DynamoDB - Lambda trigger may not have run yet, or user just signed up
            logger.warning("⚠️ User not found in DynamoDB (username=%s, user_id=%s). "
                          "Lambda trigger may not have run yet or user is very new. "
                          "Will use token data as fallback.", username, user_id_from_token)
            
            # Fallback: Use token data (user might be very new and Lambda hasn't run yet)
            # Don't save to DynamoDB here - let Lambda handle it on next confirmation
            resolved_user_id = user_id_from_token or username
            logger.info("Using token data as fallback: user_id=%s", resolved_user_id)
            
            # Still migrate session plantings using token user_id
            session_plantings = request.session.pop("user_plantings", []) or []
            migrated = 0
            for sp in session_plantings:
                try:
                    sp["user_id"] = resolved_user_id
                    sp["username"] = username
                    sp.setdefault("planting_id", sp.get("planting_id") or str(uuid.uuid4()))
                    pid = save_planting_to_dynamodb(sp)
                    if pid:
                        migrated += 1
                except Exception:
                    logger.exception("Failed to migrate planting %s", sp.get("planting_id"))
            if migrated:
                logger.info("Migrated %d session plantings using token user_id=%s", migrated, resolved_user_id)
            
            request.session.modified = True
            return False, resolved_user_id  # Return False to indicate not found in DynamoDB yet
            
    except Exception:
        logger.exception("persist_cognito_user failed")
        return False, None

# API endpoint for returning user profile JSON (kept distinct from the login_required profile page)
def user_profile_api(request):
    if not hasattr(request, "user") or not getattr(request.user, "is_authenticated", False):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    return JsonResponse({
        "email": request.user.email,
        "sub": str(request.user.pk)
    })


def profile(request):
    """Handle profile view and profile updates. (web UI) - Works with Cognito and Django auth"""
    # TRUST LAMBDA TRIGGER: Load user from DynamoDB first (Lambda already saved it)
    user_data = {}
    user_id = None
    username = None
    
    # STEP 1: Extract user_id and username from middleware/tokens (for lookup)
    if hasattr(request, 'cognito_payload') and request.cognito_payload:
        payload = request.cognito_payload
        user_id = payload.get('sub')
        username = (
            payload.get('cognito:username') or
            payload.get('preferred_username') or
            payload.get('username') or
            payload.get('email')
        )
    elif hasattr(request, 'session') and request.session.get('id_token'):
        # Try to decode from session token
        get_user_data_from_token = _get_helper('get_user_data_from_token')
        if get_user_data_from_token:
            payload = get_user_data_from_token(request) or {}
            user_id = payload.get('sub')
            username = (
                payload.get('cognito:username') or
                payload.get('preferred_username') or
                payload.get('username') or
                payload.get('email')
            )
    # Fallback to Django auth
    elif hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        user = request.user
        user_id = str(user.pk)
        username = user.username
    
    # STEP 2: Load user from DynamoDB (Lambda trigger already saved it) - TRUST LAMBDA
    if user_id or username:
        try:
            from .dynamodb_helper import get_user_from_dynamodb
            dynamodb_user = None
            # Try loading by username first (Lambda uses username as PK), then user_id
            if username:
                dynamodb_user = get_user_from_dynamodb(username)
            if not dynamodb_user and user_id:
                dynamodb_user = get_user_from_dynamodb(user_id)
            
            if dynamodb_user:
                # Use DynamoDB user data as source of truth (Lambda trigger saved it)
                user_data = {
                    'username': dynamodb_user.get('username') or dynamodb_user.get('preferred_username') or username,
                    'email': dynamodb_user.get('email') or '',
                    'name': dynamodb_user.get('name') or dynamodb_user.get('username') or 'User',
                    'user_id': dynamodb_user.get('user_id') or dynamodb_user.get('sub') or user_id,
                    'first_name': dynamodb_user.get('given_name') or '',
                    'last_name': dynamodb_user.get('family_name') or '',
                }
                user_id = user_data['user_id']
                username = user_data['username']
                logger.info('✅ Profile: Loaded user from DynamoDB (Lambda trigger saved it): user_id=%s, email=%s', 
                           user_id, user_data.get('email'))
            else:
                # Not in DynamoDB yet - use token data as fallback
                logger.warning('⚠️ Profile: User not found in DynamoDB yet (Lambda trigger may not have run). Using token data.')
                if hasattr(request, 'cognito_payload') and request.cognito_payload:
                    payload = request.cognito_payload
                    user_data = {
                        'username': username,
                        'email': payload.get('email', ''),
                        'name': payload.get('name') or f"{payload.get('given_name', '')} {payload.get('family_name', '')}".strip(),
                        'user_id': user_id,
                        'first_name': payload.get('given_name', ''),
                        'last_name': payload.get('family_name', ''),
                    }
                elif hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
                    user = request.user
                    user_data = {
                        'username': user.username,
                        'email': getattr(user, 'email', ''),
                        'name': user.get_full_name() or user.username,
                        'user_id': str(user.pk),
                        'first_name': getattr(user, 'first_name', ''),
                        'last_name': getattr(user, 'last_name', ''),
                    }
        except Exception as e:
            logger.debug('Could not load user from DynamoDB (will use token data): %s', e)
            # Fallback to token/Django data if DynamoDB lookup fails
    
    # If no user found, redirect to login
    if not user_id:
        logger.warning('Profile: No user found, redirecting to login')
        return redirect('login')
    
    if request.method == 'POST':
        # Get email from form
        email = request.POST.get('email', '').strip()
        
        # For Cognito users, update DynamoDB user record and subscribe to SNS
        if hasattr(request, 'cognito_payload') or user_id:
            logger.info('Profile: Cognito user profile update requested')
            
            # Get username and user_id
            username_to_use = user_data.get('username') or user_id
            user_id_to_use = user_id or user_data.get('user_id')
            
            # Update user in DynamoDB if email changed
            if email and email != user_data.get('email'):
                from .dynamodb_helper import save_user_to_dynamodb
                update_data = {
                    'email': email,
                    'username': username_to_use,
                    'user_id': user_id_to_use,
                }
                # Preserve existing name if available
                if user_data.get('name'):
                    update_data['name'] = user_data.get('name')
                
                saved = save_user_to_dynamodb(user_id_to_use or username_to_use, update_data)
                if saved:
                    logger.info('Profile: Updated user email in DynamoDB: %s', email)
                
                # Subscribe email to SNS topic for notifications
                if email:
                    try:
                        from .sns_helper import subscribe_email_to_topic
                        subscribe_email_to_topic(email)
                        logger.info('Profile: Subscribed email %s to SNS topic', email)
                        
                        # Enable notifications preference
                        from .dynamodb_helper import update_user_notification_preference
                        update_user_notification_preference(username_to_use, True)
                        logger.info('Profile: Enabled notifications for user: %s', username_to_use)
                    except Exception as e:
                        logger.exception('Profile: Failed to subscribe email to SNS: %s', e)
            else:
                # Email not changed, but ensure user is subscribed if they have email
                email_to_check = email or user_data.get('email')
                if email_to_check:
                    try:
                        from .sns_helper import subscribe_email_to_topic
                        subscribe_email_to_topic(email_to_check)
                        logger.info('Profile: Ensured email %s is subscribed to SNS', email_to_check)
                    except Exception as e:
                        logger.debug('Profile: SNS subscription check failed: %s', e)
            
            return redirect('/')
        else:
            # Django auth user - update as before
            user = request.user
            username = request.POST.get('username')
            password = request.POST.get('password')

            if username and username != user.username:
                user.username = username
                user.save()
                logger.info('Profile updated: username changed to %s', username)

            if email and email != user.email:
                user.email = email
                user.save()
                logger.info('Profile updated: email changed to %s', email)
                
                # Subscribe email to SNS topic for notifications
                try:
                    from .sns_helper import subscribe_email_to_topic
                    subscribe_email_to_topic(email)
                    logger.info('Profile: Subscribed email %s to SNS topic', email)
                    
                    # Enable notifications preference
                    from .dynamodb_helper import update_user_notification_preference
                    update_user_notification_preference(username, True)
                    logger.info('Profile: Enabled notifications for Django user: %s', username)
                except Exception as e:
                    logger.exception('Profile: Failed to subscribe email to SNS: %s', e)

            if password:
                user.set_password(password)
                user.save()
                logger.info('Profile updated: password changed')
            return redirect('/')
    
    # Pass user data to template
    return render(request, 'profile.html', {'user': user_data, 'cognito_user': hasattr(request, 'cognito_payload')})


def signup(request):
    """User signup: create Django User, UserProfile and best-effort save to DynamoDB"""
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            try:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=form.cleaned_data['password1'],
                )
                logger.info('Django user created: username=%s, id=%s', username, user.id)

                UserProfile.objects.create(
                    user=user,
                    country=form.cleaned_data.get('country')
                )
                logger.info('UserProfile created for: %s', username)

                # Prepare user_data to persist to Dynamo (best-effort)
                user_data = {
                    'username': username,
                    'email': email,
                    'sub': f'django_{user.id}',
                    'name': username
                }

                save_user_to_dynamodb = _get_helper('save_user_to_dynamodb', 'create_or_update_user', 'save_user')
                if save_user_to_dynamodb:
                    try:
                        saved = save_user_to_dynamodb(user_data)
                        if saved:
                            logger.info('Saved user %s to DynamoDB', username)
                        else:
                            logger.warning('Dynamo helper returned falsy when saving user %s', username)
                    except Exception:
                        logger.exception('Exception while saving user to DynamoDB')
                else:
                    logger.warning('No dynamo helper available to save user data')

                # Authenticate and log the user in
                user = authenticate(username=username, password=form.cleaned_data['password1'])
                if user is not None:
                    login(request, user)
                    logger.info('User %s authenticated and logged in', username)
                else:
                    logger.error('Failed to authenticate user %s after signup', username)

                return redirect('/')
            except Exception as e:
                logger.exception('Error during signup: %s', e)
                form.add_error(None, f'An error occurred during signup: {str(e)}')
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})


def login_view(request):
    """
    Login view - supports Cognito redirect (preferred) and local Django auth fallback.
    """
    get_user_id_from_token = _get_helper('get_user_id_from_token', 'get_user_id_from_request')

    try:
        user_id = get_user_id_from_token(request) if get_user_id_from_token else None
    except Exception:
        user_id = None

    if user_id:
        logger.info('User already authenticated (user_id: %s), redirecting to home', user_id)
        return redirect('index')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        if username and password:
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                logger.info('User %s logged in via Django auth', username)
                return redirect('index')
            else:
                from django.contrib.auth.forms import AuthenticationForm
                form = AuthenticationForm()
                form.errors['__all__'] = form.error_messages['invalid_login']
                return render(request, 'registration/login.html', {'form': form})

    return render(request, 'registration/login.html')


def toggle_notifications(request):
    """
    API endpoint to toggle user's notification preferences.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method allowed'}, status=405)

    get_user_data_from_token = _get_helper('get_user_data_from_token', 'get_user_id_from_token')
    update_user_notification_preference = _get_helper('update_user_notification_preference', 'set_user_notification_preference', 'update_user_notifications')
    subscribe_email_to_topic = _get_helper('subscribe_email_to_topic', 'sns_subscribe_email')

    try:
        user_data = None
        if get_user_data_from_token:
            try:
                user_data = get_user_data_from_token(request)
            except Exception:
                try:
                    id_token = request.session.get('id_token')
                    user_data = get_user_data_from_token(id_token) if id_token else None
                except Exception:
                    user_data = None

        if not user_data and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
            user_data = {'username': request.user.username, 'email': request.user.email, 'sub': str(request.user.pk)}

        if not user_data:
            return JsonResponse({'error': 'User not authenticated'}, status=401)

        username = user_data.get('username') or user_data.get('preferred_username') or user_data.get('sub')
        email = user_data.get('email')

        # parse body
        try:
            body = json.loads(request.body) if request.body else request.POST
        except Exception:
            body = request.POST

        enabled = body.get('enabled', True)
        if isinstance(enabled, str):
            enabled = enabled.lower() == 'true'

        if update_user_notification_preference:
            ok = update_user_notification_preference(username, enabled)
            if not ok:
                return JsonResponse({'error': 'Failed to update notification preference'}, status=500)

        if enabled and email and subscribe_email_to_topic:
            try:
                subscribe_email_to_topic(email)
                logger.info('Subscribed %s to SNS topic', email)
            except Exception:
                logger.exception('Failed subscribing email to SNS topic')

        return JsonResponse({'success': True, 'notifications_enabled': enabled})
    except Exception as e:
        logger.exception('Error toggling notifications: %s', e)
        return JsonResponse({'error': str(e)}, status=500)


def get_notification_summaries(request):
    """
    API endpoint to get in-app notifications and upcoming harvest tasks for the logged-in user.
    Returns JSON with:
    - In-app notifications from DynamoDB (plant_added, plant_edited, plant_deleted, harvest_reminder, step_reminder)
    - Upcoming tasks from user's plantings in the next 7 days
    """
    from datetime import date, timedelta
    
    # Get user identity (same logic as other views)
    user_id = None
    username = None
    user_email = None
    
    # Check for Cognito user first (from middleware)
    if hasattr(request, 'cognito_user_id') and request.cognito_user_id:
        user_id = request.cognito_user_id
        if hasattr(request, 'cognito_payload') and request.cognito_payload:
            payload = request.cognito_payload
            username = (
                payload.get('cognito:username') or
                payload.get('preferred_username') or
                payload.get('username') or
                payload.get('email')
            )
            user_email = payload.get('email')
    else:
        # Try helper functions
        try:
            from .dynamodb_helper import get_user_id_from_token, get_user_data_from_token
            user_id = get_user_id_from_token(request)
            user_data = get_user_data_from_token(request)
            if user_data:
                username = (
                    user_data.get('cognito:username') or
                    user_data.get('preferred_username') or
                    user_data.get('username') or
                    user_data.get('email')
                )
                user_email = user_data.get('email')
        except Exception:
            pass
    
    # Fallback to session token
    if not user_id:
        id_token = request.session.get('id_token') or request.session.get('cognito_tokens', {}).get('id_token')
        if id_token:
            try:
                import jwt as pyjwt
                decoded = pyjwt.decode(id_token, options={"verify_signature": False})
                user_id = decoded.get('sub')
                username = (
                    decoded.get('cognito:username') or
                    decoded.get('preferred_username') or
                    decoded.get('username') or
                    decoded.get('email')
                )
                user_email = decoded.get('email')
            except Exception:
                pass
    
    # Require authentication
    if not user_id:
        return JsonResponse({'error': 'User not authenticated'}, status=401)
    
    # Log user_id being used for debugging
    logger.info('🔍 get_notification_summaries: Using user_id=%s, username=%s, email=%s', user_id, username, user_email)
    
    # Load in-app notifications (works locally with session storage)
    in_app_notifications = []
    try:
        from .dynamodb_helper import load_user_notifications
        logger.info('📥 Attempting to load notifications for user_id=%s', user_id)
        in_app_notifications = load_user_notifications(user_id, limit=50, unread_only=False, request=request)
        logger.info('✅ Loaded %d in-app notifications for user %s', len(in_app_notifications), user_id)
        if in_app_notifications:
            logger.info('📋 Sample notification: %s', in_app_notifications[0] if in_app_notifications else 'none')
        else:
            logger.info('ℹ️ No notifications found for user_id=%s', user_id)
    except Exception as e:
        logger.exception('❌ Error loading in-app notifications: %s', e)
        # Continue even if notifications can't be loaded
    
    # Load user's plantings for upcoming tasks
    try:
        from .dynamodb_helper import load_user_plantings
        plantings = load_user_plantings(user_id or username)
    except Exception as e:
        logger.exception('Error loading plantings for notification summaries: %s', e)
        plantings = []
    
    # Build upcoming task summaries (upcoming tasks in next 7 days)
    upcoming_task_summaries = []
    today = date.today()
    days_ahead = 7
    
    for planting in plantings:
        crop_name = planting.get('crop_name', 'Unknown Crop')
        planting_date_str = planting.get('planting_date', '')
        plan = planting.get('plan', [])
        planting_id = planting.get('planting_id')
        
        if not plan:
            continue
        
        # Check for upcoming tasks in the next 7 days
        for task in plan:
            task_due_date_str = task.get('due_date', '')
            if not task_due_date_str:
                continue
            
            try:
                task_due_date = date.fromisoformat(task_due_date_str) if isinstance(task_due_date_str, str) else task_due_date_str
                if isinstance(task_due_date, str):
                    task_due_date = date.fromisoformat(task_due_date_str)
                days_until = (task_due_date - today).days
                
                # Include tasks due in next 7 days (including today)
                if 0 <= days_until <= days_ahead:
                    task_name = task.get('task', 'Task')
                    summary = {
                        'crop_name': crop_name,
                        'task': task_name,
                        'due_date': task_due_date_str if isinstance(task_due_date_str, str) else task_due_date.isoformat(),
                        'days_until': days_until,
                        'planting_date': planting_date_str,
                        'batch_id': planting.get('batch_id', ''),
                        'notification_type': 'step_reminder',
                        'planting_id': str(planting_id) if planting_id else None,
                    }
                    upcoming_task_summaries.append(summary)
                    
                    # Create in-app notification for upcoming step if not already created today
                    try:
                        from .dynamodb_helper import save_notification
                        # Check if notification already exists for this task (avoid duplicates)
                        existing = [n for n in in_app_notifications 
                                   if n.get('notification_type') == 'step_reminder' 
                                   and n.get('crop_name') == crop_name 
                                   and n.get('due_date') == (task_due_date_str if isinstance(task_due_date_str, str) else task_due_date.isoformat())
                                   and n.get('task') == task_name]
                        if not existing:
                            notification_id = save_notification(
                                user_id=str(user_id).strip(),
                                notification_type='step_reminder',
                                title=f'{task_name} - {crop_name}',
                                message=f'{task_name} for {crop_name} is due {days_until} day(s) from now ({task_due_date.isoformat()}).',
                                planting_id=str(planting_id) if planting_id else None,
                                metadata={
                                    'crop_name': crop_name,
                                    'task': task_name,
                                    'due_date': task_due_date.isoformat(),
                                    'days_until': days_until
                                },
                                request=request  # Pass request for session fallback
                            )
                            if notification_id:
                                logger.info('✅ Created step reminder notification: %s', notification_id)
                    except Exception as e:
                        logger.exception('Error creating step reminder notification: %s', e)
            except (ValueError, TypeError) as e:
                logger.debug('Error parsing task due_date: %s', e)
                continue
        
        # Check for upcoming harvest dates (within 7 days)
        harvest_date = planting.get('harvest_date')
        if harvest_date:
            try:
                if isinstance(harvest_date, str):
                    harvest_date_obj = date.fromisoformat(harvest_date)
                else:
                    harvest_date_obj = harvest_date
                days_until_harvest = (harvest_date_obj - today).days
                
                # Include harvest dates within 7 days
                if 0 <= days_until_harvest <= days_ahead:
                    # Check if notification already exists for this harvest (avoid duplicates)
                    existing = [n for n in in_app_notifications 
                               if n.get('notification_type') == 'harvest_reminder' 
                               and n.get('crop_name') == crop_name 
                               and n.get('harvest_date') == harvest_date_obj.isoformat()]
                    if not existing:
                        try:
                            from .dynamodb_helper import save_notification
                            notification_id = save_notification(
                                user_id=str(user_id).strip(),
                                notification_type='harvest_reminder',
                                title=f'Harvest Reminder: {crop_name}',
                                message=f'{crop_name} is ready to harvest in {days_until_harvest} day(s) ({harvest_date_obj.isoformat()}).',
                                planting_id=str(planting_id) if planting_id else None,
                                metadata={
                                    'crop_name': crop_name,
                                    'harvest_date': harvest_date_obj.isoformat(),
                                    'days_until': days_until_harvest
                                },
                                request=request  # Pass request for session fallback
                            )
                            if notification_id:
                                logger.info('✅ Created harvest reminder notification: %s', notification_id)
                        except Exception as e:
                            logger.exception('Error creating harvest reminder notification: %s', e)
            except (ValueError, TypeError) as e:
                logger.debug('Error parsing harvest_date: %s', e)
                continue
    
    # Sort upcoming tasks by due_date (soonest first)
    upcoming_task_summaries.sort(key=lambda x: x.get('due_date', ''))
    
    # Reload notifications to include newly created ones
    try:
        from .dynamodb_helper import load_user_notifications
        in_app_notifications = load_user_notifications(user_id, limit=50, unread_only=False, request=request)
    except Exception:
        pass
    
    # Combine in-app notifications with upcoming task summaries
    # Convert in-app notifications to summary format for consistent display
    all_notifications = []
    
    # Add in-app notifications first (newest first)
    for notif in in_app_notifications:
        notif_type = notif.get('notification_type', '')
        created_at = notif.get('created_at', 0)
        if isinstance(created_at, (int, float)):
            # Convert timestamp to date string for display
            from datetime import datetime
            try:
                dt = datetime.fromtimestamp(created_at)
                created_at_str = dt.strftime('%Y-%m-%d %H:%M')
            except:
                created_at_str = str(created_at)
        else:
            created_at_str = str(created_at)
        
        all_notifications.append({
            'notification_id': notif.get('notification_id'),
            'type': notif_type,
            'title': notif.get('title', 'Notification'),
            'message': notif.get('message', ''),
            'created_at': created_at_str,
            'read': notif.get('read', False),
            'crop_name': notif.get('crop_name'),
            'planting_id': notif.get('planting_id'),
            'days_until': notif.get('days_until'),
            'due_date': notif.get('due_date'),
            'task': notif.get('task'),
        })
    
    # Add upcoming task summaries
    for summary in upcoming_task_summaries:
        all_notifications.append({
            'type': 'step_reminder',
            'title': f"{summary['task']} - {summary['crop_name']}",
            'message': f"{summary['task']} for {summary['crop_name']} is due {summary['days_until']} day(s) from now.",
            'created_at': summary['due_date'],
            'read': False,
            'crop_name': summary['crop_name'],
            'planting_id': summary.get('planting_id'),
            'days_until': summary['days_until'],
            'due_date': summary['due_date'],
            'task': summary['task'],
        })
    
    # Sort all notifications by date (newest/soonest first)
    all_notifications.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    # Build email summary text (this is what would be sent via email)
    email_summary = ""
    if upcoming_task_summaries:
        email_summary = f"Hello {username or user_email or 'User'},\n\n"
        email_summary += "Here are your upcoming harvest reminders:\n\n"
        
        for summary in upcoming_task_summaries:
            days_text = "today" if summary['days_until'] == 0 else f"in {summary['days_until']} day(s)"
            email_summary += f"• {summary['crop_name']}: {summary['task']} due {days_text} ({summary['due_date']})\n"
        
        email_summary += "\nThanks,\nSmartHarvester"
    
    logger.info('📊 get_notification_summaries: Returning %d notifications for user_id=%s', len(all_notifications), user_id)
    logger.info('📊 Breakdown: %d in-app notifications loaded, %d upcoming task summaries', len(in_app_notifications), len(upcoming_task_summaries))
    if in_app_notifications:
        logger.info('📋 First notification sample: type=%s, title=%s, created_at=%s', 
                   in_app_notifications[0].get('notification_type'), 
                   in_app_notifications[0].get('title'),
                   in_app_notifications[0].get('created_at'))
    
    unread_count = len([n for n in all_notifications if not n.get('read', False)])
    
    response_data = {
        'success': True,
        'email': user_email,
        'notifications': all_notifications,
        'summaries': upcoming_task_summaries,  # Keep for backward compatibility
        'email_summary': email_summary,
        'count': len(all_notifications),
        'unread_count': unread_count
    }
    
    logger.debug('📊 Response data keys: %s', list(response_data.keys()))
    logger.debug('📊 Total notifications: %d, Unread: %d', len(all_notifications), unread_count)
    if all_notifications:
        logger.debug('📊 Sample notifications: %s', [{'type': n.get('type'), 'title': n.get('title')} for n in all_notifications[:3]])
    
    return JsonResponse(response_data)