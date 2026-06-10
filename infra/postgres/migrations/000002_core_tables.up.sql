-- Core application tables.
-- All multi-tenant tables carry org_id; RLS policies are applied in migration 000007.

CREATE TABLE organizations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'free',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('admin', 'devops', 'viewer')),
    mfa_secret      TEXT,
    mfa_enabled     BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (email)
);

CREATE INDEX idx_users_org_id ON users (org_id);

CREATE TABLE servers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    hostname        TEXT NOT NULL,
    ip_address      INET,
    role            TEXT NOT NULL DEFAULT 'generic',
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('online', 'degraded', 'offline', 'pending')),
    last_heartbeat  TIMESTAMPTZ,
    agent_version   TEXT,
    labels          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, hostname)
);

CREATE INDEX idx_servers_org_id ON servers (org_id);
CREATE INDEX idx_servers_status  ON servers (org_id, status);

-- CA configuration — one root CA per platform (org_id = nil means global CA)
CREATE TABLE ca_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cert_pem        TEXT NOT NULL,
    encrypted_key   BYTEA NOT NULL,   -- AES-256-GCM encrypted, key = CA_KEY_PASSPHRASE
    algorithm       TEXT NOT NULL DEFAULT 'ecdsa-p256',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL
);

-- Agent certificates issued by the platform CA
CREATE TABLE agent_certs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    server_id       UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    cert_pem        TEXT NOT NULL,
    serial_number   TEXT NOT NULL UNIQUE,
    fingerprint     TEXT NOT NULL,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ
);

CREATE INDEX idx_agent_certs_server  ON agent_certs (server_id);
CREATE INDEX idx_agent_certs_org     ON agent_certs (org_id);
CREATE INDEX idx_agent_certs_serial  ON agent_certs (serial_number);

-- Revoked agents — checked by OTel Collector on every mTLS connection
CREATE TABLE revoked_agents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    server_id   UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    reason      TEXT,
    revoked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_by  UUID REFERENCES users(id)
);

CREATE INDEX idx_revoked_agents_server ON revoked_agents (server_id);
CREATE INDEX idx_revoked_agents_org    ON revoked_agents (org_id);

-- One-time enrollment tokens (stored in Redis normally; this table is backup)
CREATE TABLE enrollment_tokens (
    token       TEXT PRIMARY KEY,
    server_id   UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ
);

-- Alert rules defined by users
CREATE TABLE alert_rules (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id                  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                    TEXT NOT NULL,
    rule_type               TEXT NOT NULL CHECK (rule_type IN ('threshold', 'ai_enriched')),
    condition_json          JSONB NOT NULL,
    notification_channels   JSONB NOT NULL DEFAULT '[]',
    cooldown_minutes        INTEGER NOT NULL DEFAULT 15,
    enabled                 BOOLEAN NOT NULL DEFAULT true,
    created_by              UUID REFERENCES users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_alert_rules_org ON alert_rules (org_id);

-- Fired notifications
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    server_id       UUID REFERENCES servers(id),
    alert_rule_id   UUID REFERENCES alert_rules(id),
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message         TEXT NOT NULL,
    channel         TEXT NOT NULL,
    extra_json      JSONB,
    fired_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_notifications_org        ON notifications (org_id, fired_at DESC);
CREATE INDEX idx_notifications_server     ON notifications (server_id, fired_at DESC);

-- AI-generated explanations for anomaly incidents
CREATE TABLE ai_explanations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    server_id           UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    incident_id         TEXT NOT NULL,
    anomaly_type        TEXT NOT NULL,
    severity            TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    explanation         TEXT NOT NULL,
    root_cause          TEXT,
    recommended_action  TEXT,
    confidence          TEXT NOT NULL CHECK (confidence IN ('low', 'medium', 'high')),
    model               TEXT NOT NULL,
    prompt_hash         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_explanations_org      ON ai_explanations (org_id, created_at DESC);
CREATE INDEX idx_ai_explanations_server   ON ai_explanations (server_id, created_at DESC);
CREATE INDEX idx_ai_explanations_incident ON ai_explanations (incident_id);

-- Immutable audit log
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID REFERENCES organizations(id) ON DELETE SET NULL,
    actor_id        UUID REFERENCES users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    target_type     TEXT,
    target_id       TEXT,
    details_json    JSONB,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_log_org    ON audit_log (org_id, created_at DESC);
CREATE INDEX idx_audit_log_actor  ON audit_log (actor_id, created_at DESC);

-- Refresh token blacklist (complement to Redis for durability)
CREATE TABLE refresh_token_blacklist (
    jti         TEXT PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_rtb_user ON refresh_token_blacklist (user_id);
