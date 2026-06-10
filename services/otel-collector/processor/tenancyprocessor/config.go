package tenancyprocessor

import "go.opentelemetry.io/collector/component"

// Config for the tenancy processor.
type Config struct {
	// JWTSecret is the shared HMAC secret used to verify agent JWTs.
	// Must match the JWT_SECRET used by the Admin API.
	JWTSecret string `mapstructure:"jwt_secret"`

	// CardinalityLimitPerOrg is the maximum number of unique metric names
	// allowed per organisation per minute. Batches exceeding this are dropped.
	CardinalityLimitPerOrg int `mapstructure:"cardinality_limit_per_org"`

	// RequireOrgID controls whether metrics without an org.id resource attribute
	// are dropped (true) or passed through with a warning (false, dev mode).
	RequireOrgID bool `mapstructure:"require_org_id"`
}

func createDefaultConfig() component.Config {
	return &Config{
		JWTSecret:              "",
		CardinalityLimitPerOrg: 10_000,
		RequireOrgID:           true,
	}
}
