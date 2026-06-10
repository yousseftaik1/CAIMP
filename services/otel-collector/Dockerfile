FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git ca-certificates

ENV GOPROXY=https://goproxy.io,https://proxy.golang.org,direct
ENV GONOSUMDB=*
ENV GOFLAGS=-mod=mod

RUN go install go.opentelemetry.io/collector/cmd/builder@v0.104.0

WORKDIR /build

COPY processor/ ./processor/
COPY builder-config.yaml .

RUN cd processor/tenancyprocessor && go mod download

RUN builder --config=builder-config.yaml --skip-compilation=false

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
WORKDIR /
COPY --from=builder /build/output/caimp-otelcol /caimp-otelcol
EXPOSE 4317 4318 8888 13133
ENTRYPOINT ["/caimp-otelcol"]
CMD ["--config=/etc/otelcol/config.yaml"]
