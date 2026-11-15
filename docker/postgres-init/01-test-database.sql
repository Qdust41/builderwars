-- Runs once, when the db volume is first created. A separate database for the test suite,
-- which truncates every table between tests (TEST_DATABASE_URL).
CREATE DATABASE builderwars_test OWNER builderwars;
