-- Migration: Add onboarding_status column to bots table
-- Date: 2025-06-27
-- Description: Add onboarding_status column to track bot configuration completion

-- Add the onboarding_status column with default value
ALTER TABLE bots 
ADD COLUMN onboarding_status TEXT DEFAULT 'pending';

-- Update existing bots to have 'completed' status if they are live
UPDATE bots 
SET onboarding_status = 'completed' 
WHERE is_live = true;

-- Add a comment to document the column
COMMENT ON COLUMN bots.onboarding_status IS 'Tracks bot onboarding completion status: pending, completed';