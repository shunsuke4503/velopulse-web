-- Run once in the Supabase SQL Editor after training_records and its RLS policies exist.
-- This creates a private bucket. Objects are stored under <authenticated-user-uuid>/<sha256>.fit.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('velopulse-fit-files', 'velopulse-fit-files', false, 52428800, array['application/octet-stream', 'application/fit'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;

drop policy if exists "VeloPulse users read own FIT files" on storage.objects;
create policy "VeloPulse users read own FIT files"
on storage.objects for select to authenticated
using (bucket_id = 'velopulse-fit-files' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "VeloPulse users upload own FIT files" on storage.objects;
create policy "VeloPulse users upload own FIT files"
on storage.objects for insert to authenticated
with check (bucket_id = 'velopulse-fit-files' and (storage.foldername(name))[1] = (select auth.uid())::text);

drop policy if exists "VeloPulse users delete own FIT files" on storage.objects;
create policy "VeloPulse users delete own FIT files"
on storage.objects for delete to authenticated
using (bucket_id = 'velopulse-fit-files' and (storage.foldername(name))[1] = (select auth.uid())::text);
