-- ============================================================================
-- Vaulto rate alerts — the 15-minute tick.
--
-- Run this ONCE per Supabase project, in the SQL Editor, as the postgres user.
-- It is idempotent: re-running it replaces the job and rotates nothing.
--
-- WHY THIS EXISTS
-- The alert check used to be an APScheduler job inside the API process. Cloud
-- Run scales to zero, so between requests that process does not exist and the
-- ticks never happened — alerts silently stopped being delivered. The schedule
-- therefore lives here instead, in the database, which is running whether or not
-- any API instance is. Each tick is an HTTP request, which is also the one thing
-- that reliably wakes a scaled-to-zero service.
--
-- BEFORE YOU RUN IT, set these two:
--   :service_url   your Cloud Run URL, e.g. https://vaulto-api-xxxx.a.run.app
--   :cron_secret   the same value as CRON_SECRET on the Cloud Run service
-- Generate the secret with:  openssl rand -hex 32
-- ============================================================================

-- ── 1. Extensions ───────────────────────────────────────────────────────────
-- pg_cron runs the schedule; pg_net makes the outbound HTTP request. Both ship
-- with Supabase and just need enabling. They live in the `extensions` schema by
-- convention on Supabase.
create extension if not exists pg_cron;
create extension if not exists pg_net;


-- ── 2. Store the secret in Vault, not in the job ────────────────────────────
-- cron.job is readable by anyone who can read the schema, and the job's SQL body
-- is stored verbatim — pasting the secret into it publishes it to every database
-- user. Vault keeps it encrypted at rest and the job reads it by name at run
-- time.
--
-- Replace the first argument with your real secret.
select vault.create_secret(
  'REPLACE_WITH_YOUR_CRON_SECRET',
  'vaulto_cron_secret',
  'Bearer token for POST /internal/check-alerts on the Vaulto API'
);

-- Rotating it later (the name must already exist):
--   select vault.update_secret(
--     (select id from vault.secrets where name = 'vaulto_cron_secret'),
--     'THE_NEW_SECRET'
--   );
-- Update CRON_SECRET on Cloud Run in the same sitting: a tick that lands between
-- the two changes gets a 401, which costs one 15-minute cycle and nothing else.


-- ── 3. Schedule the tick ────────────────────────────────────────────────────
-- Replace the URL below with your Cloud Run service URL. Keep the path.
select cron.schedule(
  'vaulto-check-alerts',
  '*/15 * * * *',
  $job$
  select net.http_post(
    url := 'https://REPLACE-WITH-YOUR-SERVICE.a.run.app/internal/check-alerts',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'Authorization', 'Bearer ' || (
        select decrypted_secret
        from vault.decrypted_secrets
        where name = 'vaulto_cron_secret'
      )
    ),
    body := '{}'::jsonb,
    -- The endpoint runs the whole check before it answers, and a cold start plus
    -- a fan-out across every distinct alert corridor is not instant. pg_net's
    -- default is 5s, which would give up long before a real run finishes.
    --
    -- Giving up early does NOT cancel the run: the request has already been
    -- delivered and Cloud Run keeps processing it. All that is lost is the
    -- status recorded below, so set this comfortably above a normal run and
    -- below the 15-minute gap between ticks.
    timeout_milliseconds := 300000
  );
  $job$
);


-- ============================================================================
-- CHECKING ON IT
-- ============================================================================

-- Is the job registered, and when does it next run?
--   select jobid, jobname, schedule, active from cron.job
--   where jobname = 'vaulto-check-alerts';

-- Did the recent ticks fire? `status` here is pg_cron's view — whether the SQL
-- ran, not what the API answered.
--   select runid, status, return_message, start_time
--   from cron.job_run_details
--   where jobid = (select jobid from cron.job where jobname = 'vaulto-check-alerts')
--   order by start_time desc limit 10;

-- What did the API actually say? This is the one that tells you whether alerts
-- are working. 200 is a completed pass, 401 a secret mismatch, 409 a tick that
-- skipped because one was already running, 503 a missing CRON_SECRET on
-- Cloud Run, and an empty/errored row means pg_net stopped waiting (see the
-- timeout note above) or could not reach the service at all.
--   select id, status_code, content, created
--   from net._http_response order by created desc limit 10;

-- Fire one tick by hand, without waiting for the schedule:
--   select net.http_post(
--     url := 'https://REPLACE-WITH-YOUR-SERVICE.a.run.app/internal/check-alerts',
--     headers := jsonb_build_object(
--       'Content-Type', 'application/json',
--       'Authorization', 'Bearer ' || (
--         select decrypted_secret from vault.decrypted_secrets
--         where name = 'vaulto_cron_secret')
--     ),
--     body := '{}'::jsonb,
--     timeout_milliseconds := 300000
--   );
-- then read net._http_response as above. pg_net is asynchronous, so the row
-- appears a moment after the request returns its id.

-- Pause the tick (during maintenance, say):
--   select cron.alter_job(
--     (select jobid from cron.job where jobname = 'vaulto-check-alerts'),
--     active := false
--   );

-- Remove it entirely:
--   select cron.unschedule('vaulto-check-alerts');
