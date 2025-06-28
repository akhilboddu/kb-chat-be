-- Migration: Create user_profiles table
-- Date: 2025-06-28
-- Description: Create user_profiles table for Google OAuth users and profile data storage

-- Create the user_profiles table
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    bio TEXT,
    avatar_url TEXT,
    payment_status TEXT DEFAULT 'TRIAL',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_payment_status ON user_profiles(payment_status);

-- Add RLS policy (if using Supabase Row Level Security)
-- Note: This may need to be adjusted based on your RLS setup
-- ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;

-- Add a comment to document the table
COMMENT ON TABLE user_profiles IS 'Stores profile data for users, especially Google OAuth users who may not be in Supabase Auth';
COMMENT ON COLUMN user_profiles.id IS 'User UUID (converted from Google OAuth ID using deterministic uuid5)';
COMMENT ON COLUMN user_profiles.email IS 'User email address';
COMMENT ON COLUMN user_profiles.display_name IS 'User display name';
COMMENT ON COLUMN user_profiles.bio IS 'User bio/description';
COMMENT ON COLUMN user_profiles.avatar_url IS 'User avatar/profile picture URL';
COMMENT ON COLUMN user_profiles.payment_status IS 'User subscription status: TRIAL, STARTER, PRO, ENTERPRISE';