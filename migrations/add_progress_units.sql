-- Migration: Add progress tracking units to status tables
-- Date: 2024-06-14
-- Purpose: Enable granular progress tracking for Celery tasks

-- Add columns to scraping_status table
ALTER TABLE scraping_status ADD COLUMN IF NOT EXISTS completed_units INTEGER DEFAULT 0;
ALTER TABLE scraping_status ADD COLUMN IF NOT EXISTS total_units INTEGER;

-- Add columns to file_upload_status table  
ALTER TABLE file_upload_status ADD COLUMN IF NOT EXISTS completed_units INTEGER DEFAULT 0;
ALTER TABLE file_upload_status ADD COLUMN IF NOT EXISTS total_units INTEGER; 