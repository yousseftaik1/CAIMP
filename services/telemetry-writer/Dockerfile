FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git ca-certificates

WORKDIR /src

ENV GOPROXY=https://goproxy.cn,https://proxy.golang.org,direct
ENV GONOSUMDB=*
ENV GOFLAGS=-mod=mod

# Clone pgservicefile to the path referenced by the replace directive in go.mod.
# Must happen before COPY so the directory exists when go build resolves modules.
RUN git clone --depth 1 https://github.com/jackc/pgservicefile.git /pgservicefile

COPY . .
WORKDIR /src/services/telemetry-writer
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -o /telemetry-writer ./cmd/main.go

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /telemetry-writer /usr/local/bin/telemetry-writer
EXPOSE 4318 9091
ENTRYPOINT ["/usr/local/bin/telemetry-writer"]
