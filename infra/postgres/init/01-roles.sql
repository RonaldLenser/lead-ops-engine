-- Database roles and databases for LOCAL DEVELOPMENT AND CI ONLY.
--
-- Runs once, as the superuser, when the Compose database volume is first
-- created (Postgres image: /docker-entrypoint-initdb.d), and as an explicit
-- step in CI. The passwords below are public, throwaway values; the app's
-- config refuses to start in production with any of them. Production roles
-- and passwords are created by the deployment runbook (M9).
--
-- Two roles, least privilege:
--   leadops_migrator  owns the databases and schemas; only Alembic uses it.
--   leadops_app       what the API and worker use: read and write rows,
--                     never create, alter, or drop anything.
--
-- Two databases:
--   leadops       the development database the Compose API uses
--   leadops_test  the ONLY database integration tests may reset. The test
--                 suite refuses to run destructive operations against any
--                 database whose name does not end in _test.
--
-- Expects to be connected to the `leadops` database (POSTGRES_DB).

CREATE ROLE leadops_migrator LOGIN PASSWORD 'leadops_migrator_dev';
CREATE ROLE leadops_app LOGIN PASSWORD 'leadops_app_dev';

CREATE DATABASE leadops_test;

\set dbname leadops
\ir lib/grants.sql

\connect leadops_test
\set dbname leadops_test
\ir lib/grants.sql
