-- Database roles for LOCAL DEVELOPMENT AND CI ONLY.
--
-- Runs once, as the superuser, when the Compose database volume is first
-- created (Postgres image: /docker-entrypoint-initdb.d), and as an explicit
-- step in CI. The passwords below are public, throwaway values; the app's
-- config refuses to start in production with any of them. Production roles
-- and passwords are created by the deployment runbook (M9).
--
-- Two roles, least privilege:
--   leadops_migrator  owns the database and schema; only Alembic uses it.
--   leadops_app       what the API and worker use: read and write rows,
--                     never create, alter, or drop anything.

CREATE ROLE leadops_migrator LOGIN PASSWORD 'leadops_migrator_dev';
CREATE ROLE leadops_app LOGIN PASSWORD 'leadops_app_dev';

-- The database owner also owns the public schema (PostgreSQL 15+), so the
-- migrator can create tables there.
ALTER DATABASE leadops OWNER TO leadops_migrator;

-- Nobody else may connect or create objects by default.
REVOKE ALL ON DATABASE leadops FROM PUBLIC;
GRANT CONNECT ON DATABASE leadops TO leadops_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO leadops_app;

-- Every table and sequence the migrator creates from now on is automatically
-- usable (but not alterable) by the app role. Without this, each migration
-- would need its own GRANT statements and one forgotten grant would break
-- production.
ALTER DEFAULT PRIVILEGES FOR ROLE leadops_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO leadops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE leadops_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO leadops_app;
