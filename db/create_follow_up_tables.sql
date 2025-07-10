-- Create follow_up_queue table for managing automated follow-up tasks
CREATE TABLE IF NOT EXISTS follow_up_queue (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    customer_phone TEXT,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'overdue', 'cancelled')),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
    due_date TIMESTAMPTZ,
    follow_up_count INTEGER NOT NULL DEFAULT 0,
    max_follow_ups INTEGER NOT NULL DEFAULT 3,
    lead_score INTEGER CHECK (lead_score >= 0 AND lead_score <= 100),
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Add indexes for better query performance
    CONSTRAINT follow_up_queue_bot_id_idx UNIQUE (bot_id, conversation_id)
);

-- Create follow_up_emails table to track all sent follow-up emails
CREATE TABLE IF NOT EXISTS follow_up_emails (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    follow_up_queue_id UUID NOT NULL REFERENCES follow_up_queue(id) ON DELETE CASCADE,
    email_type TEXT NOT NULL CHECK (email_type IN ('initial', 'follow_up_1', 'follow_up_2', 'follow_up_3', 'custom')),
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    recipient_name TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivery_status TEXT NOT NULL DEFAULT 'sent' CHECK (delivery_status IN ('sent', 'delivered', 'bounced', 'failed', 'opened', 'clicked')),
    opened_at TIMESTAMPTZ,
    clicked_at TIMESTAMPTZ,
    bounce_reason TEXT,
    email_provider TEXT, -- gmail, deskforce, etc.
    email_provider_id TEXT, -- external email provider's message ID
    metadata JSONB DEFAULT '{}', -- additional metadata like headers, etc.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_follow_up_queue_bot_id ON follow_up_queue(bot_id);
CREATE INDEX IF NOT EXISTS idx_follow_up_queue_status ON follow_up_queue(status);
CREATE INDEX IF NOT EXISTS idx_follow_up_queue_priority ON follow_up_queue(priority);
CREATE INDEX IF NOT EXISTS idx_follow_up_queue_due_date ON follow_up_queue(due_date);
CREATE INDEX IF NOT EXISTS idx_follow_up_queue_created_at ON follow_up_queue(created_at);
CREATE INDEX IF NOT EXISTS idx_follow_up_queue_customer_email ON follow_up_queue(customer_email);

-- Indexes for follow_up_emails table
CREATE INDEX IF NOT EXISTS idx_follow_up_emails_queue_id ON follow_up_emails(follow_up_queue_id);
CREATE INDEX IF NOT EXISTS idx_follow_up_emails_sent_at ON follow_up_emails(sent_at);
CREATE INDEX IF NOT EXISTS idx_follow_up_emails_delivery_status ON follow_up_emails(delivery_status);
CREATE INDEX IF NOT EXISTS idx_follow_up_emails_recipient_email ON follow_up_emails(recipient_email);
CREATE INDEX IF NOT EXISTS idx_follow_up_emails_email_provider ON follow_up_emails(email_provider);

-- Create a function to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at for follow_up_queue
CREATE TRIGGER update_follow_up_queue_updated_at 
    BEFORE UPDATE ON follow_up_queue 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Create trigger to automatically update updated_at for follow_up_emails
CREATE TRIGGER update_follow_up_emails_updated_at 
    BEFORE UPDATE ON follow_up_emails 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Create a function to check if follow-up count exceeds max_follow_ups
CREATE OR REPLACE FUNCTION check_follow_up_count()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.follow_up_count > NEW.max_follow_ups THEN
        RAISE EXCEPTION 'Follow-up count cannot exceed max_follow_ups';
    END IF;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to check follow-up count
CREATE TRIGGER check_follow_up_count_trigger
    BEFORE INSERT OR UPDATE ON follow_up_queue
    FOR EACH ROW
    EXECUTE FUNCTION check_follow_up_count();

-- Create a function to automatically update follow_up_count when emails are sent
CREATE OR REPLACE FUNCTION update_follow_up_count_on_email()
RETURNS TRIGGER AS $$
BEGIN
    -- Increment follow_up_count in follow_up_queue when a new email is inserted
    UPDATE follow_up_queue 
    SET follow_up_count = follow_up_count + 1,
        updated_at = NOW()
    WHERE id = NEW.follow_up_queue_id;
    
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to update follow_up_count when emails are sent
CREATE TRIGGER update_follow_up_count_trigger
    AFTER INSERT ON follow_up_emails
    FOR EACH ROW
    EXECUTE FUNCTION update_follow_up_count_on_email();

-- Create a function to automatically mark items as overdue
CREATE OR REPLACE FUNCTION mark_overdue_follow_ups()
RETURNS void AS $$
BEGIN
    UPDATE follow_up_queue 
    SET status = 'overdue', updated_at = NOW()
    WHERE due_date < NOW() 
    AND status IN ('pending', 'in_progress')
    AND follow_up_count < max_follow_ups;
END;
$$ language 'plpgsql';

-- Create a view for easy querying of overdue items
CREATE OR REPLACE VIEW overdue_follow_ups AS
SELECT 
    fq.*,
    b.name as bot_name,
    b.user_id
FROM follow_up_queue fq
JOIN bots b ON fq.bot_id = b.id
WHERE fq.due_date < NOW() 
AND fq.status IN ('pending', 'in_progress')
AND fq.follow_up_count < fq.max_follow_ups;

-- Create a view for follow-up statistics
CREATE OR REPLACE VIEW follow_up_stats AS
SELECT 
    bot_id,
    COUNT(*) as total_items,
    COUNT(*) FILTER (WHERE status = 'pending') as pending_items,
    COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress_items,
    COUNT(*) FILTER (WHERE status = 'completed') as completed_items,
    COUNT(*) FILTER (WHERE status = 'overdue') as overdue_items,
    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled_items,
    AVG(lead_score) as avg_lead_score,
    AVG(follow_up_count) as avg_follow_up_count
FROM follow_up_queue
GROUP BY bot_id;

-- Create a view for email statistics
CREATE OR REPLACE VIEW follow_up_email_stats AS
SELECT 
    fq.bot_id,
    COUNT(fe.id) as total_emails_sent,
    COUNT(fe.id) FILTER (WHERE fe.delivery_status = 'delivered') as delivered_emails,
    COUNT(fe.id) FILTER (WHERE fe.delivery_status = 'opened') as opened_emails,
    COUNT(fe.id) FILTER (WHERE fe.delivery_status = 'clicked') as clicked_emails,
    COUNT(fe.id) FILTER (WHERE fe.delivery_status = 'bounced') as bounced_emails,
    COUNT(fe.id) FILTER (WHERE fe.delivery_status = 'failed') as failed_emails,
    AVG(EXTRACT(EPOCH FROM (fe.opened_at - fe.sent_at))/3600) as avg_hours_to_open,
    AVG(EXTRACT(EPOCH FROM (fe.clicked_at - fe.sent_at))/3600) as avg_hours_to_click
FROM follow_up_queue fq
LEFT JOIN follow_up_emails fe ON fq.id = fe.follow_up_queue_id
GROUP BY fq.bot_id;

-- Enable Row Level Security (RLS)
ALTER TABLE follow_up_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE follow_up_emails ENABLE ROW LEVEL SECURITY;

-- Create RLS policies for follow_up_queue
-- Policy to allow users to see only their own bot's follow-up items
CREATE POLICY "Users can view their own bot's follow-up items" ON follow_up_queue
    FOR SELECT USING (
        bot_id IN (
            SELECT id FROM bots WHERE user_id = auth.uid()
        )
    );

-- Policy to allow users to insert follow-up items for their own bots
CREATE POLICY "Users can insert follow-up items for their own bots" ON follow_up_queue
    FOR INSERT WITH CHECK (
        bot_id IN (
            SELECT id FROM bots WHERE user_id = auth.uid()
        )
    );

-- Policy to allow users to update follow-up items for their own bots
CREATE POLICY "Users can update follow-up items for their own bots" ON follow_up_queue
    FOR UPDATE USING (
        bot_id IN (
            SELECT id FROM bots WHERE user_id = auth.uid()
        )
    );

-- Policy to allow users to delete follow-up items for their own bots
CREATE POLICY "Users can delete follow-up items for their own bots" ON follow_up_queue
    FOR DELETE USING (
        bot_id IN (
            SELECT id FROM bots WHERE user_id = auth.uid()
        )
    );

-- Create RLS policies for follow_up_emails
-- Policy to allow users to see emails for their own bot's follow-up items
CREATE POLICY "Users can view emails for their own bot's follow-up items" ON follow_up_emails
    FOR SELECT USING (
        follow_up_queue_id IN (
            SELECT fq.id FROM follow_up_queue fq
            JOIN bots b ON fq.bot_id = b.id
            WHERE b.user_id = auth.uid()
        )
    );

-- Policy to allow users to insert emails for their own bot's follow-up items
CREATE POLICY "Users can insert emails for their own bot's follow-up items" ON follow_up_emails
    FOR INSERT WITH CHECK (
        follow_up_queue_id IN (
            SELECT fq.id FROM follow_up_queue fq
            JOIN bots b ON fq.bot_id = b.id
            WHERE b.user_id = auth.uid()
        )
    );

-- Policy to allow users to update emails for their own bot's follow-up items
CREATE POLICY "Users can update emails for their own bot's follow-up items" ON follow_up_emails
    FOR UPDATE USING (
        follow_up_queue_id IN (
            SELECT fq.id FROM follow_up_queue fq
            JOIN bots b ON fq.bot_id = b.id
            WHERE b.user_id = auth.uid()
        )
    );

-- Policy to allow users to delete emails for their own bot's follow-up items
CREATE POLICY "Users can delete emails for their own bot's follow-up items" ON follow_up_emails
    FOR DELETE USING (
        follow_up_queue_id IN (
            SELECT fq.id FROM follow_up_queue fq
            JOIN bots b ON fq.bot_id = b.id
            WHERE b.user_id = auth.uid()
        )
    );

-- Grant necessary permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON follow_up_queue TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON follow_up_emails TO authenticated;
GRANT SELECT ON overdue_follow_ups TO authenticated;
GRANT SELECT ON follow_up_stats TO authenticated;
GRANT SELECT ON follow_up_email_stats TO authenticated;

-- Add comments for documentation
COMMENT ON TABLE follow_up_queue IS 'Stores follow-up tasks for automated customer follow-up campaigns';
COMMENT ON COLUMN follow_up_queue.bot_id IS 'Reference to the bot that owns this follow-up task';
COMMENT ON COLUMN follow_up_queue.conversation_id IS 'Unique identifier for the conversation that needs follow-up';
COMMENT ON COLUMN follow_up_queue.customer_name IS 'Name of the customer for follow-up';
COMMENT ON COLUMN follow_up_queue.customer_email IS 'Email address of the customer for follow-up';
COMMENT ON COLUMN follow_up_queue.customer_phone IS 'Phone number of the customer (optional)';
COMMENT ON COLUMN follow_up_queue.subject IS 'Subject line for the follow-up message';
COMMENT ON COLUMN follow_up_queue.message IS 'Content of the follow-up message';
COMMENT ON COLUMN follow_up_queue.status IS 'Current status of the follow-up task';
COMMENT ON COLUMN follow_up_queue.priority IS 'Priority level of the follow-up task';
COMMENT ON COLUMN follow_up_queue.due_date IS 'When the follow-up should be sent';
COMMENT ON COLUMN follow_up_queue.follow_up_count IS 'Number of follow-ups already sent';
COMMENT ON COLUMN follow_up_queue.max_follow_ups IS 'Maximum number of follow-ups to send';
COMMENT ON COLUMN follow_up_queue.lead_score IS 'Lead score (0-100) for prioritization';
COMMENT ON COLUMN follow_up_queue.tags IS 'Array of tags for categorization';

COMMENT ON TABLE follow_up_emails IS 'Stores all sent follow-up emails with delivery tracking';
COMMENT ON COLUMN follow_up_emails.follow_up_queue_id IS 'Reference to the follow-up task this email belongs to';
COMMENT ON COLUMN follow_up_emails.email_type IS 'Type of email (initial, follow_up_1, follow_up_2, etc.)';
COMMENT ON COLUMN follow_up_emails.subject IS 'Subject line of the sent email';
COMMENT ON COLUMN follow_up_emails.message IS 'Content of the sent email';
COMMENT ON COLUMN follow_up_emails.recipient_email IS 'Email address of the recipient';
COMMENT ON COLUMN follow_up_emails.recipient_name IS 'Name of the recipient';
COMMENT ON COLUMN follow_up_emails.sent_at IS 'When the email was sent';
COMMENT ON COLUMN follow_up_emails.delivery_status IS 'Current delivery status of the email';
COMMENT ON COLUMN follow_up_emails.opened_at IS 'When the email was opened (if tracked)';
COMMENT ON COLUMN follow_up_emails.clicked_at IS 'When the email was clicked (if tracked)';
COMMENT ON COLUMN follow_up_emails.bounce_reason IS 'Reason for bounce if email bounced';
COMMENT ON COLUMN follow_up_emails.email_provider IS 'Email service provider used (gmail, deskforce, etc.)';
COMMENT ON COLUMN follow_up_emails.email_provider_id IS 'External email provider message ID';
COMMENT ON COLUMN follow_up_emails.metadata IS 'Additional metadata like headers, tracking info, etc.'; 