# Email Scheduler Setup Guide

This guide explains how to set up and use the automated email scheduler for follow-up emails.

## Overview

The email scheduler uses Celery Beat to automatically send scheduled follow-up emails using your existing Gmail API endpoint (`/api/gmail/{bot_id}/send-email`).

## Components

1. **Email Scheduler Task** (`app/tasks/email_scheduler.py`)
   - Checks for pending emails every 5 minutes
   - Sends emails via your Gmail API
   - Updates email status in database
   - Handles errors and retries

2. **Celery Beat Scheduler**
   - Runs scheduled tasks automatically
   - Configures task intervals

3. **Email Worker**
   - Processes email tasks in background
   - Handles async email sending

## Setup

### 1. Environment Variables

Make sure these are set in your environment:

```bash
# API Configuration
API_BASE_URL=http://localhost:8000  # Your FastAPI server URL

# Supabase Configuration (already configured)
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# Gmail API Configuration (for your existing endpoint)
# These should already be configured for your Gmail API
```

### 2. Start the Email Scheduler

#### Option A: Using the updated start script
```bash
./start.sh
```

This will automatically start:
- Email worker (`celery -A app.worker.celery_app worker -Q email`)
- Celery Beat scheduler (`celery -A app.worker.celery_app beat`)

#### Option B: Manual startup
```bash
# Start email worker
celery -A app.worker.celery_app worker -Q email --pool=threads --concurrency=2 --loglevel=info

# Start Celery Beat scheduler (in another terminal)
celery -A app.worker.celery_app beat --loglevel=info
```

### 3. Monitor with Flower
```bash
celery -A app.worker.celery_app flower --port=5555
```

Visit http://localhost:5555 to monitor tasks.

## How It Works

### 1. Email Scheduling
When a conversation is closed, it's automatically added to the follow-up queue with:
- Default due date: 12 hours from now
- AI-generated email content
- Status: "pending"

### 2. Email Processing
Every 5 minutes, the scheduler:
1. Queries for pending emails due to be sent
2. Calls your Gmail API endpoint for each email
3. Updates email status to "sent" or "failed"
4. Increments follow-up count in queue

### 3. Email Content
The scheduler uses the AI-generated email content from your follow-up queue, including:
- Personalized subject and message
- Customer name replacement
- AI-generated key points and urgency levels

## Testing

### 1. Manual Trigger
```bash
python trigger_email_scheduler.py
```

### 2. Check Task Status
```bash
# Check active tasks
celery -A app.worker.celery_app inspect active

# Check scheduled tasks
celery -A app.worker.celery_app inspect scheduled

# Check registered tasks
celery -A app.worker.celery_app inspect registered
```

### 3. Monitor Logs
```bash
# Check worker logs
tail -f celery_email_worker.log

# Check beat scheduler logs
tail -f celery_beat.log
```

## Configuration

### Task Schedule
The scheduler runs:
- **Email sending**: Every 5 minutes
- **Failed email cleanup**: Daily at 2 AM

You can modify these in `app/tasks/email_scheduler.py`:

```python
celery_app.conf.beat_schedule.update({
    'send-scheduled-emails': {
        'task': 'app.tasks.email_scheduler.send_scheduled_followup_emails',
        'schedule': 300.0,  # Every 5 minutes (300 seconds)
    },
    'cleanup-failed-emails': {
        'task': 'app.tasks.email_scheduler.cleanup_failed_emails',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
})
```

### Email Provider
The scheduler uses your existing Gmail API endpoint. If you want to change the email provider, modify the `send_email_via_gmail_api` function in `app/tasks/email_scheduler.py`.

## Troubleshooting

### Common Issues

1. **Emails not sending**
   - Check if email worker is running: `ps aux | grep celery`
   - Check worker logs for errors
   - Verify Gmail API credentials

2. **Tasks not scheduled**
   - Check if Celery Beat is running: `ps aux | grep beat`
   - Check beat logs for errors
   - Verify task registration

3. **Database connection issues**
   - Check Supabase credentials
   - Verify database tables exist

### Debug Commands

```bash
# Check all Celery processes
ps aux | grep celery

# Check task queue
celery -A app.worker.celery_app inspect active

# Check worker status
celery -A app.worker.celery_app inspect stats

# Purge all tasks (emergency)
celery -A app.worker.celery_app purge
```

## Database Schema

The scheduler uses these tables:
- `follow_up_queue`: Queue items with due dates
- `follow_up_emails`: Individual email records with status

### Email Status Values
- `pending`: Scheduled but not sent yet
- `sent`: Successfully sent
- `failed`: Failed to send
- `delivered`: Delivered to recipient
- `opened`: Opened by recipient
- `clicked`: Clicked by recipient

## Production Deployment

For production, consider:

1. **Process Management**
   - Use Supervisor or systemd to keep workers running
   - Set up automatic restarts

2. **Monitoring**
   - Set up alerts for failed emails
   - Monitor worker health

3. **Scaling**
   - Run multiple email workers for high volume
   - Use Redis cluster for high availability

4. **Logging**
   - Centralized logging (ELK stack, etc.)
   - Structured logging for better debugging

## API Integration

The scheduler integrates with your existing APIs:

- **Gmail API**: `/api/gmail/{bot_id}/send-email`
- **Follow-up API**: `/api/followup/queue/{bot_id}`

No additional API endpoints are needed - the scheduler uses your existing infrastructure.
