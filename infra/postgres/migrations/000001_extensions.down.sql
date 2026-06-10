DROP EXTENSION IF EXISTS pgcrypto CASCADE;
DROP EXTENSION IF EXISTS vector CASCADE;
DROP EXTENSION IF EXISTS "uuid-ossp" CASCADE;
-- Do NOT drop timescaledb here — it would cascade-drop all hypertables.
