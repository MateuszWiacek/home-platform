-- Authentik PostgreSQL maintenance queries
--
-- Use these in order. The first sections are safe inspection queries.
-- Cleanup sections should be run only after a fresh backup.
--
-- For large VACUUM runs inside Docker, prefer:
--   VACUUM (ANALYZE, PARALLEL 0)
--
-- 1. Inspect expired channel/cache rows
SELECT 'expired_channels' AS metric, COUNT(*) AS value
FROM django_channels_postgres_message
WHERE expires < NOW();

SELECT 'expired_cache' AS metric, COUNT(*) AS value
FROM django_postgres_cache_cacheentry
WHERE expires < NOW();

-- 2. Inspect task queue state
SELECT state, COUNT(*)
FROM authentik_tasks_task
GROUP BY state
ORDER BY COUNT(*) DESC;

-- 3. Inspect the biggest queued actors
SELECT actor_name, COUNT(*)
FROM authentik_tasks_task
WHERE state = 'queued'
GROUP BY actor_name
ORDER BY COUNT(*) DESC
LIMIT 20;

-- 3a. Inspect age distribution for the main backlog actors
SELECT actor_name,
       MIN(mtime) AS oldest,
       MAX(mtime) AS newest,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE mtime < NOW() - INTERVAL '7 days') AS older_than_7d,
       COUNT(*) FILTER (WHERE mtime < NOW() - INTERVAL '14 days') AS older_than_14d,
       COUNT(*) FILTER (WHERE mtime < NOW() - INTERVAL '30 days') AS older_than_30d
FROM authentik_tasks_task
WHERE state = 'queued'
  AND actor_name IN (
    'authentik.providers.proxy.tasks.proxy_on_logout',
    'authentik.outposts.tasks.outpost_session_end',
    'authentik.core.tasks.clean_expired_models',
    'authentik.core.tasks.clean_temporary_users',
    'authentik.events.tasks.event_trigger_dispatch'
  )
GROUP BY actor_name
ORDER BY total DESC;

-- 4. Batch delete expired channel rows
WITH doomed AS (
  SELECT ctid
  FROM django_channels_postgres_message
  WHERE expires < NOW()
  LIMIT 50000
)
DELETE FROM django_channels_postgres_message
WHERE ctid IN (SELECT ctid FROM doomed);

-- 5. Delete expired cache rows
DELETE FROM django_postgres_cache_cacheentry
WHERE expires < NOW();

-- 6. Vacuum after cleanup
VACUUM (ANALYZE, PARALLEL 0) django_channels_postgres_message;
VACUUM (ANALYZE, PARALLEL 0) django_postgres_cache_cacheentry;

-- 7. Re-check queue state after cleanup
SELECT state, COUNT(*)
FROM authentik_tasks_task
GROUP BY state
ORDER BY COUNT(*) DESC;

-- 8. Optional: inspect old queued proxy/logout tasks before any manual purge
SELECT message_id, actor_name, mtime
FROM authentik_tasks_task
WHERE state = 'queued'
  AND actor_name IN (
    'authentik.providers.proxy.tasks.proxy_on_logout',
    'authentik.outposts.tasks.outpost_session_end'
  )
ORDER BY mtime ASC
LIMIT 100;

-- 9. Optional and risky: delete very old queued session/logout and cleanup tasks.
-- This is the safer first cut because these are duplicate session-end and cleanup jobs.
-- Delete matching tasklog rows first or PostgreSQL will block the task delete on FK.
-- Review the SELECTs above first. Keep this disabled unless you explicitly decide to purge.
--
-- DELETE FROM authentik_tasks_tasklog tl
-- USING authentik_tasks_task t
-- WHERE tl.task_id = t.message_id
--   AND t.state = 'queued'
--   AND t.actor_name IN (
--     'authentik.providers.proxy.tasks.proxy_on_logout',
--     'authentik.outposts.tasks.outpost_session_end',
--     'authentik.core.tasks.clean_expired_models',
--     'authentik.core.tasks.clean_temporary_users'
--   )
--   AND t.mtime < NOW() - INTERVAL '14 days';
--
-- DELETE FROM authentik_tasks_task
-- WHERE state = 'queued'
--   AND actor_name IN (
--     'authentik.providers.proxy.tasks.proxy_on_logout',
--     'authentik.outposts.tasks.outpost_session_end',
--     'authentik.core.tasks.clean_expired_models',
--     'authentik.core.tasks.clean_temporary_users'
--   )
--   AND mtime < NOW() - INTERVAL '14 days';

-- 10. Optional and riskier: old event dispatch backlog.
-- Leave this for phase 2 only if the queue is still not draining after the cleanup above.
--
-- DELETE FROM authentik_tasks_task
-- WHERE state = 'queued'
--   AND actor_name = 'authentik.events.tasks.event_trigger_dispatch'
--   AND mtime < NOW() - INTERVAL '30 days';
