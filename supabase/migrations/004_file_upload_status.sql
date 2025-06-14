-- Migration: Add file_upload_status table for tracking background file upload progress
-- Created: 2025-01-13

create table if not exists public.file_upload_status (
  kb_id text not null primary key,
  status text,                 -- processing | completed | completed_with_errors | failed
  total_files int,
  processed_files int,
  failed_files int,
  message text,
  progress_data jsonb,         -- { stage, details, percent }
  updated_at timestamptz default now()
);

-- Add index for faster queries
create index if not exists idx_file_upload_status_kb_id on public.file_upload_status(kb_id);

-- Add updated_at trigger to automatically update timestamp
create or replace function update_updated_at_column()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger update_file_upload_status_updated_at
before update on public.file_upload_status
for each row
execute function update_updated_at_column(); 