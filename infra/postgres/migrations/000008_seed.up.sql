-- Seed data: one demo org, one admin user, one demo server.
--
-- Password is argon2id hash of 'Admin1234!' — CHANGE THIS via the Admin API
-- before exposing the platform to any network.
--
-- The caimp_service role bypasses RLS so this seed can insert freely.

SET ROLE caimp_service;

-- Demo organisation
INSERT INTO organizations (id, name, plan)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Demo Org',
    'free'
) ON CONFLICT DO NOTHING;

-- Demo admin user — password is 'Admin1234!'
-- Hash generated via pgcrypto bcrypt (cost 12); compatible with passlib bcrypt.
INSERT INTO users (id, org_id, email, password_hash, role)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    'admin@caimp.local',
    crypt('Admin1234!', gen_salt('bf', 12)),
    'admin'
) ON CONFLICT DO NOTHING;

-- Self-monitoring server (used by the platform self-agent)
INSERT INTO organizations (id, name, plan)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    '_platform',
    'internal'
) ON CONFLICT DO NOTHING;

INSERT INTO servers (id, org_id, name, hostname, role)
VALUES (
    '00000000-0000-0000-0000-000000000010',
    '00000000-0000-0000-0000-000000000000',
    'caimp-host',
    'caimp-host',
    'platform'
) ON CONFLICT DO NOTHING;

-- Demo server in the demo org
INSERT INTO servers (id, org_id, name, hostname, role)
VALUES (
    '00000000-0000-0000-0000-000000000011',
    '00000000-0000-0000-0000-000000000001',
    'demo-server-01',
    'demo-server-01.local',
    'generic'
) ON CONFLICT DO NOTHING;

RESET ROLE;
