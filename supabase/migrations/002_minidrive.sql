-- MiniDrive migration 002 — run once in Supabase Dashboard → SQL Editor
-- on a project created with the first version of schema.sql.
-- Adds: column visibility settings, synchronization history, username login,
-- and the auth_user_exists() check. Safe to run more than once.

-- Login by username (optional). Stored in lower case; "@" is never allowed,
-- so a login identifier containing "@" is always an email.
alter table public.users add column if not exists username text;
create unique index if not exists uq_users_username on public.users (username) where username is not null;
alter table public.users drop constraint if exists users_username_format;
alter table public.users add constraint users_username_format
    check (username is null or username ~ '^[a-z0-9_.-]{3,30}$');
create index if not exists idx_users_email on public.users (lower(email));

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


create index if not exists idx_synchronizations_user_started
    on public.synchronizations(user_id, started_at desc);

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

notify pgrst, 'reload schema';
