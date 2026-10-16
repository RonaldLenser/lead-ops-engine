-- Ownership and privileges for one database. Included by ../01-roles.sql
-- once per database, with the psql variable :dbname set and a connection
-- to that database already open. Not run on its own: the Postgres image
-- only executes files directly inside /docker-entrypoint-initdb.d.

-- The database owner also owns the public schema (PostgreSQL 15+), so the
-- migrator can create tables there.
ALTER DATABASE :"dbname" OWNER TO leadops_migrator;

-- Nobody else may connect or create objects by default.
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO leadops_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO leadops_app;

-- Every table and sequence the migrator creates from now on is automatically
-- usable (but not alterable) by the app role. Individual migrations can
-- still take privileges away (for example, audit_events is append-only).
ALTER DEFAULT PRIVILEGES FOR ROLE leadops_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO leadops_app;
ALTER DEFAULT PRIVILEGES FOR ROLE leadops_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO leadops_app;
