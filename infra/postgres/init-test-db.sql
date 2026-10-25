-- Runs once, when the PostgreSQL volume is first created.
-- A separate database for the automated tests (they recreate its schema).
CREATE DATABASE netribeat_test OWNER netribeat;
