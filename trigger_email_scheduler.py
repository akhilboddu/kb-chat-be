#!/usr/bin/env python3

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.worker.celery_app import celery_app
from app.tasks.email_scheduler import send_scheduled_followup_emails

if __name__ == "__main__":
    print("Manually triggering email scheduler...")
    
    # Submit the task
    result = send_scheduled_followup_emails.delay()
    
    print(f"Task submitted with ID: {result.id}")
    print("Task status:", result.status)
    
    # Wait for result (optional)
    try:
        task_result = result.get(timeout=60)  # Wait up to 60 seconds
        print("Task completed with result:", task_result)
    except Exception as e:
        print(f"Task failed or timed out: {e}")
        print("Check Celery logs for details")
    
    print("\nTo monitor all tasks:")
    print("celery -A app.worker.celery_app inspect active")
    print("celery -A app.worker.celery_app inspect scheduled")
