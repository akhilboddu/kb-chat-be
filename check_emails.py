#!/usr/bin/env python3

import os
from supabase import create_client

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(supabase_url, supabase_key)

# Check pending emails
response = supabase.table("follow_up_emails").select("*, follow_up_queue!inner(*)").eq("delivery_status", "pending").execute()

print(f"Pending emails: {len(response.data)}")

for email in response.data[:5]:
    queue_count = email["follow_up_queue"]["follow_up_count"]
    print(f"Email {email['id']}: {email['subject']} -> {email['recipient_email']} (Queue count: {queue_count})")

# Check sent emails
sent_response = supabase.table("follow_up_emails").select("*, follow_up_queue!inner(*)").eq("delivery_status", "sent").order("created_at", desc=True).limit(5).execute()

print(f"\nRecent sent emails: {len(sent_response.data)}")

for email in sent_response.data:
    queue_count = email["follow_up_queue"]["follow_up_count"]
    print(f"Email {email['id']}: {email['subject']} -> {email['recipient_email']} (Queue count: {queue_count})") 