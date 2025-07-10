#!/usr/bin/env python3

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.tasks.email_scheduler import test_email_scheduler

if __name__ == "__main__":
    print("Testing email scheduler...")
    result = test_email_scheduler()
    print(f"Task submitted: {result.id}")
    print("Check Celery logs for results")
    print("You can monitor the task with: celery -A app.worker.celery_app inspect active")
