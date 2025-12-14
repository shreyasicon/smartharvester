"""
Built-in plan calculator for generating planting care plans.
Works with data.json to calculate care schedules for plants.
"""
from datetime import date, timedelta
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


def calculate_plan(crop_name: str, planting_date: date, plant_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Calculate a care plan for a given crop based on planting date.
    
    Args:
        crop_name: Name of the crop (e.g., "Cucumbers")
        planting_date: Date when the crop was planted
        plant_data: Dictionary containing plant data from data.json (new flat structure)
        
    Returns:
        List of dictionaries with 'task' and 'due_date' keys
    """
    plan = []
    
    if not plant_data:
        logger.warning('calculate_plan: Invalid plant_data structure')
        return plan
    
    # Support both new structure (flat object with plant names as keys) and old structure (with 'plants' array)
    plant_info = None
    
    # Try new structure first: plant_data is a dict with plant names as keys (e.g., {"Basil": {...}, "Cucumbers": {...}})
    if isinstance(plant_data, dict):
        # Normalize crop_name: strip whitespace
        crop_name = crop_name.strip()
        
        # Check exact match first
        if crop_name in plant_data:
            plant_info = plant_data[crop_name]
            logger.debug('calculate_plan: Found exact match for "%s"', crop_name)
        # Try title case (e.g., "basil" -> "Basil", "BELL PEPPERS" -> "Bell Peppers")
        elif crop_name.title() in plant_data:
            plant_info = plant_data[crop_name.title()]
            logger.debug('calculate_plan: Found title case match for "%s" -> "%s"', crop_name, crop_name.title())
        # Try case-insensitive match
        else:
            crop_name_lower = crop_name.lower().strip()
            for key, value in plant_data.items():
                if isinstance(value, dict) and key.lower() == crop_name_lower:
                    plant_info = value
                    logger.debug('calculate_plan: Found case-insensitive match for "%s" -> "%s"', crop_name, key)
                    break
        
        # If still not found, try fuzzy matching (handle singular/plural variations)
        if not plant_info:
            crop_name_lower = crop_name.lower().strip()
            for key, value in plant_data.items():
                if not isinstance(value, dict):
                    continue
                key_lower = key.lower()
                # Try exact lowercase match
                if key_lower == crop_name_lower:
                    plant_info = value
                    logger.debug('calculate_plan: Found fuzzy match (exact lowercase) for "%s" -> "%s"', crop_name, key)
                    break
                # Try singular/plural variations (e.g., "Tomato" vs "Tomatoes")
                if crop_name_lower.rstrip('s') == key_lower.rstrip('s'):
                    plant_info = value
                    logger.debug('calculate_plan: Found fuzzy match (singular/plural) for "%s" -> "%s"', crop_name, key)
                    break
                # Try partial match (e.g., "Bell Pepper" matches "Bell Peppers")
                if crop_name_lower in key_lower or key_lower in crop_name_lower:
                    plant_info = value
                    logger.debug('calculate_plan: Found fuzzy match (partial) for "%s" -> "%s"', crop_name, key)
                    break
        
        # If not found and 'plants' key exists, try old structure
        if not plant_info and 'plants' in plant_data:
            for plant in plant_data['plants']:
                if plant.get('name', '').lower() == crop_name.lower():
                    plant_info = plant
                    logger.debug('calculate_plan: Found match in old structure for "%s"', crop_name)
                    break
    
    if not plant_info:
        logger.warning('calculate_plan: Plant "%s" not found in plant_data. Available plants: %s', 
                      crop_name, list(plant_data.keys())[:10] if isinstance(plant_data, dict) else 'N/A')
        return plan
    
    # Get care schedule
    care_schedule = plant_info.get('care_schedule', [])
    if not care_schedule:
        logger.warning('calculate_plan: No care_schedule found for "%s"', crop_name)
        return plan
    
    # Build plan with calculated dates
    for task_item in care_schedule:
        task_title = task_item.get('task_title', '')
        days_after = task_item.get('days_after_planting')
        
        # Skip tasks without days_after_planting (ongoing tasks are handled separately)
        if days_after is None or days_after == '':
            continue
        
        try:
            days = int(days_after)
            due_date = planting_date + timedelta(days=days)
            
            plan.append({
                'task': task_title,
                'due_date': due_date
            })
        except (ValueError, TypeError):
            logger.warning('calculate_plan: Invalid days_after_planting for task "%s"', task_title)
            continue
    
    # Sort by due_date
    plan.sort(key=lambda x: x.get('due_date', date.today()))
    
    logger.info('calculate_plan: Generated %d tasks for "%s"', len(plan), crop_name)
    return plan

