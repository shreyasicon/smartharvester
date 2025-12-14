"""
Django management command to send harvest reminder notifications via SNS.

Usage:
    python manage.py send_harvest_reminders --days 3
    python manage.py send_harvest_reminders --days 3 --dry-run
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from tracker.dynamodb_helper import load_user_plantings
from tracker.sns_helper import send_harvest_reminder, subscribe_email_to_topic
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send harvest reminder notifications to users for plantings due in N days'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=3,
            help='Number of days in advance to send reminders (default: 3)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually sending notifications (test mode)',
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.SUCCESS(f'Starting harvest reminder check (days={days}, dry_run={dry_run})'))
        
        try:
            # Get DynamoDB resource
            from tracker.dynamodb_helper import dynamo_resource, DYNAMO_USERS_TABLE
            table = dynamo_resource().Table(DYNAMO_USERS_TABLE)
            users_response = table.scan()
            users = users_response.get('Items', [])
            
            self.stdout.write(f'Found {len(users)} users in DynamoDB')
            
            reminders_sent = 0
            total_plantings_checked = 0
            
            # Calculate target date
            target_date = date.today() + timedelta(days=days)
            
            for user_item in users:
                try:
                    # Extract user info from DynamoDB item (using resource format, not client format)
                    username = user_item.get('username', '')
                    email = user_item.get('email', '')
                    user_id = user_item.get('user_id', '') or username
                    
                    if not email:
                        self.stdout.write(self.style.WARNING(f'  Skipping user {username}: no email'))
                        continue
                    
                    # Check if notifications are enabled (default to True if not set)
                    notifications_enabled = user_item.get('notifications_enabled', True)
                    
                    if not notifications_enabled:
                        self.stdout.write(self.style.WARNING(f'  Skipping user {username}: notifications disabled'))
                        continue
                    
                    # Load user's plantings
                    plantings = load_user_plantings(user_id)
                    if not plantings:
                        continue
                    
                    self.stdout.write(f'\n  Checking plantings for {username} ({email})...')
                    
                    # Check each planting for upcoming tasks
                    for planting in plantings:
                        total_plantings_checked += 1
                        plan = planting.get('plan', [])
                        
                        if not plan:
                            continue
                        
                        # Check if any task is due on target_date
                        upcoming_tasks = []
                        for task in plan:
                            task_due_date_str = task.get('due_date', '')
                            if not task_due_date_str:
                                continue
                            
                            try:
                                task_due_date = date.fromisoformat(task_due_date_str)
                                if task_due_date == target_date:
                                    upcoming_tasks.append(task)
                            except (ValueError, TypeError):
                                continue
                        
                        if upcoming_tasks:
                            crop_name = planting.get('crop_name', 'your crop')
                            planting_date = planting.get('planting_date', 'N/A')
                            
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'    ✓ {crop_name} has {len(upcoming_tasks)} task(s) due on {target_date}'
                                )
                            )
                            
                            if not dry_run:
                                # Prepare planting info for notification
                                planting_info = {
                                    'crop_name': crop_name,
                                    'planting_date': planting_date,
                                    'due_date': target_date.isoformat(),
                                    'tasks': [task.get('task', 'Task') for task in upcoming_tasks],
                                }
                                
                                # Ensure email is subscribed to SNS topic
                                subscribe_email_to_topic(email)
                                
                                # Send reminder
                                message_id = send_harvest_reminder(email, planting_info)
                                if message_id:
                                    reminders_sent += 1
                                    self.stdout.write(
                                        self.style.SUCCESS(f'      ✓ Reminder sent (MessageId: {message_id})')
                                    )
                                else:
                                    self.stdout.write(
                                        self.style.ERROR(f'      ✗ Failed to send reminder')
                                    )
                            else:
                                self.stdout.write(f'      [DRY RUN] Would send reminder to {email}')
                                reminders_sent += 1
                
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Error processing user {username}: {e}'))
                    logger.exception(f'Error processing user {username}: {e}')
            
            self.stdout.write(self.style.SUCCESS(f'\n✓ Processed {len(users)} users'))
            self.stdout.write(self.style.SUCCESS(f'✓ Checked {total_plantings_checked} plantings'))
            self.stdout.write(self.style.SUCCESS(f'✓ Sent {reminders_sent} reminder(s)'))
            
            if dry_run:
                self.stdout.write(self.style.WARNING('  [DRY RUN MODE - No notifications were actually sent]'))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
            logger.exception(f'Error in send_harvest_reminders: {e}')
            raise

