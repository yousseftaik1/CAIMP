module github.com/caimp/otelcol/processor/tenancyprocessor

go 1.22

require (
	go.opentelemetry.io/collector/component v0.104.0
	go.opentelemetry.io/collector/consumer v0.104.0
	go.opentelemetry.io/collector/pdata v1.11.0
	go.opentelemetry.io/collector/processor v0.104.0
	github.com/golang-jwt/jwt/v5 v5.2.1
	go.uber.org/zap v1.27.0
)
