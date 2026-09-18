# Relay Gateway

Relay is a small LLM gateway that sits between an application and model providers.
It gives the application one stable endpoint while the gateway handles the operational
work around model calls:

- limits traffic per client before it reaches a provider
- sends requests to a preferred provider
- retries through a fallback provider when the preferred provider fails
- records latency, routes, failures, and recent request events
- exposes those signals in a browser control room

This repository is a working local reference implementation. It is intentionally
small and dependency-free so the gateway behavior can be inspected and tested without
setting up a database, queue, or cloud deployment.

## Request flow

```text
Application
		|
		| POST /api/chat
		v
Relay gateway
		|
		| 1. Check client rate limit
		| 2. Call primary provider
		| 3. On provider failure, call fallback
		| 4. Record metrics and return one response
		v
OpenAI -> Anthropic -> Local fallback
```

The primary provider is OpenAI. Anthropic is used as the secondary provider when its
key is configured. If no Anthropic key is available, Relay returns a local response so
the routing and observability flows still work during development.

## What is implemented

### Rate limiting

`POST /api/chat` allows 8 requests per 60 seconds for each `X-Client-ID`. Requests
over the limit receive HTTP `429` and a `retryAfter` value. This prevents one client
from consuming the entire provider budget.

### Routing and fallback

Each accepted request goes to OpenAI first. Network errors, timeouts, and provider
HTTP errors trigger the fallback route. The response includes the provider and model
that actually handled the request, so callers do not need to know which route won.

### Observability

`GET /api/metrics` returns request totals, success rate, average latency, fallback
count, provider usage, and recent events. The dashboard polls this state when it loads
and updates it after every test request.

## Run locally

Requirements: Python 3.9 or newer. No package installation is required.

```bash
python3 server.py
```

Open the control room at <http://127.0.0.1:4173>.

The **Send test request** button calls the real local gateway endpoint. The dashboard
shows the active route, provider health, rate-limit events, fallback events, latency,
and recent request activity.

## Configuration

Create a local `.env` file. Do not commit it.

```env
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

`OPEN_AI_API_KEY` is also accepted for compatibility with the original local setup,
but `OPENAI_API_KEY` is the recommended name. If a provider key is missing, Relay
uses its local adapter instead of crashing.

## API examples

Send a request with a client identity:

```bash
curl -X POST http://127.0.0.1:4173/api/chat \
	-H 'Content-Type: application/json' \
	-H 'X-Client-ID: demo-app' \
	-d '{"prompt":"Explain what an LLM gateway does in one sentence."}'
```

Read gateway metrics:

```bash
curl http://127.0.0.1:4173/api/metrics
```

## Project files

- `server.py`: HTTP server, rate limiter, provider adapters, fallback routing, and metrics state
- `index.html`: control-room layout
- `style.css`: responsive dashboard styling
- `app.js`: dashboard API integration and interactions

## Production next steps

This is a local reference implementation, not a production deployment. A production
version should add a persistent/shared rate limiter such as Redis, structured logs,
authentication, request cancellation, provider-specific retry policies, secret
management, durable metrics, and health checks. Real provider keys should also be
rotated immediately if they are ever exposed in a terminal, screenshot, or repository.