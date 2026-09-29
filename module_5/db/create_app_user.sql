-- Least-privilege database account for the Grad Cafe analytics app (Module 5).
-- Run once as the database owner / superuser, e.g.:
--     psql -d gradcafe -v app_password=change-me -f db/create_app_user.sql
--
-- The application only ever:
--   * SELECTs from applicants (analysis page, /api/applicants, query scripts)
--   * INSERTs into applicants (Pull Data adds new rows; ON CONFLICT DO NOTHING)
-- It never UPDATEs, DELETEs, creates or alters objects, so the role gets none
-- of those rights and is explicitly NOT a superuser, cannot create databases
-- or roles, and does not own the table.  Schema creation (load_data.create_table)
-- is an administrative step done by the owner before the app user is used.

\set ON_ERROR_STOP on

-- 1. Role: login only, no elevated attributes, small connection budget.
--    (Run once; re-running fails on "role already exists", which is harmless.)
CREATE ROLE gradcafe_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION CONNECTION LIMIT 5;

-- 2. Start from nothing: remove the default PUBLIC privileges on the schema.
REVOKE ALL ON SCHEMA public FROM gradcafe_app;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM gradcafe_app;

-- 3. Grant exactly what the app needs.
GRANT CONNECT ON DATABASE gradcafe TO gradcafe_app;
GRANT USAGE ON SCHEMA public TO gradcafe_app;          -- see the table, cannot CREATE in the schema
GRANT SELECT, INSERT ON TABLE applicants TO gradcafe_app;

-- 4. (Optional) make the account read-only instead, if Pull Data is not used:
-- REVOKE INSERT ON TABLE applicants FROM gradcafe_app;

-- Verify:
--   \du gradcafe_app
--   SELECT grantee, privilege_type FROM information_schema.role_table_grants
--    WHERE grantee = 'gradcafe_app';
