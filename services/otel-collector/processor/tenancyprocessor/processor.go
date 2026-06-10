package tenancyprocessor

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/consumer"
	"go.opentelemetry.io/collector/pdata/pcommon"
	"go.opentelemetry.io/collector/pdata/pmetric"
	"go.uber.org/zap"
)

// ---------------------------------------------------------------------------
// Cardinality tracker
// ---------------------------------------------------------------------------

type orgWindow struct {
	mu      sync.Mutex
	names   map[string]struct{}
	resetAt time.Time
}

func (w *orgWindow) add(name string) int {
	w.mu.Lock()
	defer w.mu.Unlock()
	now := time.Now()
	if now.After(w.resetAt) {
		w.names   = make(map[string]struct{})
		w.resetAt = now.Add(time.Minute)
	}
	w.names[name] = struct{}{}
	return len(w.names)
}

// ---------------------------------------------------------------------------
// Processor
// ---------------------------------------------------------------------------

type tenancyProcessor struct {
	logger  *zap.Logger
	cfg     *Config
	next    consumer.Metrics
	windows sync.Map // orgID → *orgWindow
}

func newTenancyProcessor(
	logger *zap.Logger,
	cfg *Config,
	next consumer.Metrics,
) *tenancyProcessor {
	return &tenancyProcessor{logger: logger, cfg: cfg, next: next}
}

func (p *tenancyProcessor) Start(_ context.Context, _ component.Host) error { return nil }
func (p *tenancyProcessor) Shutdown(_ context.Context) error              { return nil }
func (p *tenancyProcessor) Capabilities() consumer.Capabilities {
	return consumer.Capabilities{MutatesData: true}
}

// ConsumeMetrics implements consumer.Metrics (and therefore processor.Metrics).
func (p *tenancyProcessor) ConsumeMetrics(ctx context.Context, md pmetric.Metrics) error {
	rms := md.ResourceMetrics()
	for i := rms.Len() - 1; i >= 0; i-- {
		rm := rms.At(i)
		attrs := rm.Resource().Attributes()

		// 1. Extract org_id from resource attributes
		orgIDVal, hasOrgID := attrs.Get("org.id")
		if !hasOrgID || orgIDVal.Str() == "" {
			if p.cfg.RequireOrgID {
				p.logger.Warn("Dropping resource metrics: missing org.id attribute")
				rms.RemoveIf(func(r pmetric.ResourceMetrics) bool {
					v, ok := r.Resource().Attributes().Get("org.id")
					return !ok || v.Str() == ""
				})
				continue
			}
			p.logger.Debug("Missing org.id — passing through (RequireOrgID=false)")
			continue
		}
		orgID := orgIDVal.Str()

		// 2. JWT validation (when secret is configured)
		if p.cfg.JWTSecret != "" {
			if err := p.validateJWT(attrs, orgID); err != nil {
				p.logger.Warn("JWT validation failed — dropping resource",
					zap.String("org_id", orgID), zap.Error(err))
				rms.RemoveIf(func(r pmetric.ResourceMetrics) bool {
					v, _ := r.Resource().Attributes().Get("org.id")
					return v.Str() == orgID
				})
				continue
			}
		}

		// 3. Cardinality check
		if exceeded := p.checkCardinality(orgID, rm); exceeded {
			p.logger.Warn("Cardinality limit exceeded — dropping batch",
				zap.String("org_id", orgID),
				zap.Int("limit", p.cfg.CardinalityLimitPerOrg))
			rms.RemoveIf(func(r pmetric.ResourceMetrics) bool {
				v, _ := r.Resource().Attributes().Get("org.id")
				return v.Str() == orgID
			})
			continue
		}

		// 4. Stamp caimp.org_id for downstream consumers
		attrs.PutStr("caimp.org_id", orgID)
	}

	if md.ResourceMetrics().Len() == 0 {
		return nil
	}
	return p.next.ConsumeMetrics(ctx, md)
}

// validateJWT checks the Bearer token in the "authorization" resource attribute.
func (p *tenancyProcessor) validateJWT(attrs pcommon.Map, expectedOrgID string) error {
	authVal, ok := attrs.Get("authorization")
	if !ok {
		return fmt.Errorf("missing authorization attribute")
	}
	tokenStr := strings.TrimPrefix(authVal.Str(), "Bearer ")
	if tokenStr == "" {
		return fmt.Errorf("empty Bearer token")
	}

	claims := jwt.MapClaims{}
	_, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return []byte(p.cfg.JWTSecret), nil
	})
	if err != nil {
		return fmt.Errorf("token parse: %w", err)
	}

	claimOrgID, _ := claims["org_id"].(string)
	if claimOrgID != expectedOrgID {
		return fmt.Errorf("org_id mismatch: token=%q resource=%q", claimOrgID, expectedOrgID)
	}
	return nil
}

// checkCardinality tracks unique metric names and returns true if the limit is exceeded.
func (p *tenancyProcessor) checkCardinality(orgID string, rm pmetric.ResourceMetrics) bool {
	raw, _ := p.windows.LoadOrStore(orgID, &orgWindow{
		names:   make(map[string]struct{}),
		resetAt: time.Now().Add(time.Minute),
	})
	win := raw.(*orgWindow)

	for i := 0; i < rm.ScopeMetrics().Len(); i++ {
		sm := rm.ScopeMetrics().At(i)
		for j := 0; j < sm.Metrics().Len(); j++ {
			name := sm.Metrics().At(j).Name()
			if count := win.add(name); count > p.cfg.CardinalityLimitPerOrg {
				return true
			}
		}
	}
	return false
}

// Compile-time interface check.
var _ consumer.Metrics = (*tenancyProcessor)(nil)
