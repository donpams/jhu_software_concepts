-- Test database role: the pytest suite TRUNCATEs applicants before every test
-- and creates the table if it is missing, so it needs a little more than the
-- app role - but only inside the throwaway gradcafe_test database.
--     createdb gradcafe_test
--     psql -d gradcafe_test -v test_password=change-me -f db/create_test_user.sql
\set ON_ERROR_STOP on
CREATE ROLE gradcafe_test LOGIN PASSWORD :'test_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE gradcafe_test TO gradcafe_test;
GRANT USAGE, CREATE ON SCHEMA public TO gradcafe_test;
ALTER DEFAULT PRIVILEGES FOR ROLE gradcafe_test IN SCHEMA public GRANT ALL ON TABLES TO gradcafe_test;
