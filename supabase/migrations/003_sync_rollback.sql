-- MiniDrive migration 003 — synchronization sessions: cancellation / rollback, device name.
-- Run once in Supabase Dashboard → SQL Editor (after 002_minidrive.sql). Safe to run more than once.

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

notify pgrst, 'reload schema';
