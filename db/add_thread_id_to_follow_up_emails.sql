-- Migration: Add thread_id field to follow_up_emails table
-- This allows tracking Gmail thread IDs for proper email threading

-- Add thread_id column to follow_up_emails table
ALTER TABLE follow_up_emails 
ADD COLUMN IF NOT EXISTS thread_id TEXT;

-- Add index for thread_id for better query performance
CREATE INDEX IF NOT EXISTS idx_follow_up_emails_thread_id ON follow_up_emails(thread_id);

-- Add comment for documentation
COMMENT ON COLUMN follow_up_emails.thread_id IS 'Gmail thread ID for email threading - allows all follow-ups to be in the same conversation thread'; 