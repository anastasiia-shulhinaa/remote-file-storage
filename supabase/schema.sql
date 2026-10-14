-- Nastusha — database schema, indexes, RLS and Storage bucket.
-- Run once in Supabase Dashboard → SQL Editor.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

create table if not exists public.users (
    id uuid primary key references auth.users(id) on delete cascade,
    email text not null,
    display_name text not null,
    created_at timestamptz not null default now()
);

-- Login by username (optional). Stored in lower case; "@" is never allowed,
-- so a login identifier containing "@" is always an email.
alter table public.users add column if not exists username text;
create unique index if not exists uq_users_username on public.users (username) where username is not null;
alter table public.users drop constraint if exists users_username_format;
alter table public.users add constraint users_username_format
    check (username is null or username ~ '^[a-z0-9_.-]{3,30}$');
create index if not exists idx_users_email on public.users (lower(email));

create table if not exists public.folders (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null
        references public.users(id)
        on delete cascade,

    parent_folder_id uuid
        references public.folders(id)
        on delete cascade,

    name text not null,
    created_at timestamptz not null default now(),

    -- no two sibling folders with the same name (root: parent is null)
    constraint uq_folders_sibling_name
        unique nulls not distinct (user_id, parent_folder_id, name)
);

create table if not exists public.files (
    id uuid primary key default gen_random_uuid(),

    folder_id uuid not null
        references public.folders(id)
        on delete cascade,

    name text not null,
    extension text not null,
    size bigint not null,
    storage_path text not null unique,

    created_at timestamptz not null default now(),
    modified_at timestamptz not null default now(),

    uploaded_by uuid not null
        references public.users(id),

    modified_by uuid not null
        references public.users(id),

    -- uploading a file with an existing name replaces it
    constraint uq_files_folder_name unique (folder_id, name)
);

-- Optional metadata columns shown in the clients. "Name" is always visible,
-- so it has no column here.
create table if not exists public.column_visibility_settings (
    user_id uuid primary key
        references public.users(id)
        on delete cascade,

    size boolean not null default true,
    created_at boolean not null default true,
    modified_at boolean not null default true,
    uploaded_by boolean not null default true,
    modified_by boolean not null default true
);

-- Persistent summary of a synchronization run. The plan and its individual
-- file changes are transient and are not stored.
create table if not exists public.synchronizations (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null
        references public.users(id)
        on delete cascade,

    remote_folder_id uuid
        references public.folders(id)
        on delete set null,

    client text not null default 'api'
        check (client in ('desktop', 'web', 'api')),
    mode text not null
        check (mode in ('two_way', 'mirror_local', 'mirror_remote')),
    status text not null default 'PENDING'
        check (status in ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),

    planned_changes integer not null default 0,
    uploaded integer not null default 0,
    downloaded integer not null default 0,
    deleted_local integer not null default 0,
    deleted_remote integer not null default 0,
    unchanged integer not null default 0,
    failed integer not null default 0,
    error text,

    started_at timestamptz not null default now(),
    finished_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

create index if not exists idx_synchronizations_user_started
    on public.synchronizations(user_id, started_at desc);

create index if not exists idx_files_folder_id on public.files(folder_id);
create index if not exists idx_files_extension on public.files(extension);
create index if not exists idx_files_created_at on public.files(created_at);
create index if not exists idx_files_modified_at on public.files(modified_at);
create index if not exists idx_folders_user_id on public.folders(user_id);
create index if not exists idx_folders_parent_folder_id on public.folders(parent_folder_id);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- The backend uses the server-side key (bypasses RLS) and checks ownership
-- itself. These policies are defense in depth for direct access with a user JWT.
-- ---------------------------------------------------------------------------

alter table public.users enable row level security;
alter table public.folders enable row level security;
alter table public.files enable row level security;
alter table public.column_visibility_settings enable row level security;
alter table public.synchronizations enable row level security;

drop policy if exists "column settings: own row" on public.column_visibility_settings;
create policy "column settings: own row" on public.column_visibility_settings
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists "synchronizations: own rows" on public.synchronizations;
create policy "synchronizations: own rows" on public.synchronizations
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists "users: own row" on public.users;
create policy "users: own row" on public.users
    for all to authenticated
    using (id = auth.uid())
    with check (id = auth.uid());

drop policy if exists "folders: own folders" on public.folders;
create policy "folders: own folders" on public.folders
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists "files: files in own folders" on public.files;
create policy "files: files in own folders" on public.files
    for all to authenticated
    using (exists (
        select 1 from public.folders f
        where f.id = files.folder_id and f.user_id = auth.uid()
    ))
    with check (exists (
        select 1 from public.folders f
        where f.id = files.folder_id and f.user_id = auth.uid()
    ));

-- ---------------------------------------------------------------------------
-- Storage: private bucket "files", objects stored as
-- <user_id>/<folder_id>/<file_id>/<filename>
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public)
values ('files', 'files', false)
on conflict (id) do nothing;

drop policy if exists "files bucket: own objects" on storage.objects;
create policy "files bucket: own objects" on storage.objects
    for all to authenticated
    using (
        bucket_id = 'files'
        and (storage.foldername(name))[1] = auth.uid()::text
    )
    with check (
        bucket_id = 'files'
        and (storage.foldername(name))[1] = auth.uid()::text
    );


-- ---------------------------------------------------------------------------
-- Synchronization cancellation / rollback, device (same as migrations/003)
-- ---------------------------------------------------------------------------

-- 1. extended session state machine
alter table public.synchronizations drop constraint if exists synchronizations_status_check;
alter table public.synchronizations add constraint synchronizations_status_check
    check (status in ('PENDING', 'RUNNING', 'CANCEL_REQUESTED', 'ROLLING_BACK',
                      'CANCELLED', 'ROLLBACK_FAILED', 'COMPLETED', 'FAILED'));

-- last activity (lease: an untouched PENDING/RUNNING session is treated as abandoned).
-- Existing rows get their real last activity, not the time of this migration.
alter table public.synchronizations add column if not exists updated_at timestamptz;
update public.synchronizations
    set updated_at = coalesce(finished_at, started_at)
    where updated_at is null;
alter table public.synchronizations alter column updated_at set default now();
alter table public.synchronizations alter column updated_at set not null;

-- what the rollback restored / could not restore
alter table public.synchronizations add column if not exists rollback_report jsonb;

-- the computer (desktop: host name) or browser (web: "Edge · Windows") that ran the sync
alter table public.synchronizations add column if not exists device text;

-- sessions left PENDING/RUNNING by older versions can never be resumed or rolled back:
-- close them, otherwise they would keep their folders locked
update public.synchronizations
    set status = 'FAILED',
        error = coalesce(error, 'interrupted'),
        finished_at = coalesce(finished_at, now())
    where status in ('PENDING', 'RUNNING')
      and updated_at < now() - interval '10 minutes';

-- at most one active session per user and target folder (overlapping folders are checked by the API)
create unique index if not exists uq_synchronizations_active_target
    on public.synchronizations (user_id, remote_folder_id)
    where status in ('PENDING', 'RUNNING', 'CANCEL_REQUESTED', 'ROLLING_BACK');

-- 2. journal of remote changes made during a synchronization (write-ahead, for rollback)
create table if not exists public.sync_operations (
    id uuid primary key,
    seq bigint generated always as identity,

    synchronization_id uuid not null
        references public.synchronizations(id)
        on delete cascade,

    user_id uuid not null
        references public.users(id)
        on delete cascade,

    kind text not null
        check (kind in ('CREATE_REMOTE_FILE', 'OVERWRITE_REMOTE_FILE',
                        'DELETE_REMOTE_FILE', 'CREATE_REMOTE_FOLDER')),
    relative_path text,
    file_id uuid,
    folder_id uuid,
    -- the file row before the change (restored on rollback)
    snapshot jsonb,
    -- copy of the old bytes in Storage: <user_id>/.sync-backups/<sync_id>/<operation_id>
    backup_path text,
    status text not null default 'PENDING'
        check (status in ('PENDING', 'APPLIED', 'ROLLING_BACK', 'ROLLED_BACK',
                          'ROLLBACK_FAILED', 'COMMITTED')),
    error text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_sync_operations_sync_seq
    on public.sync_operations (synchronization_id, seq);

alter table public.sync_operations enable row level security;

drop policy if exists "sync operations: own rows" on public.sync_operations;
create policy "sync operations: own rows" on public.sync_operations
    for all to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());


-- ---------------------------------------------------------------------------
-- Login UX: "user not found" vs "wrong password".
-- Supabase Auth answers both with "invalid_credentials". This function lets the
-- backend (service role only) check reliably whether an account exists.
-- ---------------------------------------------------------------------------

create or replace function public.auth_user_exists(p_email text)
returns boolean
language sql
security definer
set search_path = ''
as $$
    select exists (select 1 from auth.users where lower(email) = lower(p_email));
$$;

revoke all on function public.auth_user_exists(text) from public, anon, authenticated;
grant execute on function public.auth_user_exists(text) to service_role;

-- make the new tables/columns visible to the REST API immediately
notify pgrst, 'reload schema';
