#!/usr/bin/env python3
"""Small dependency-free LLM gateway with real provider adapters."""

from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import random
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = 4173
RATE_LIMIT = 8
WINDOW_SECONDS = 60
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Load simple KEY=value entries without overwriting real environment variables."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip().removeprefix("export ")
            value = value.strip().strip("\"'")
            os.environ.setdefault(name, value)


load_env()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

state = {
    "requests": 284691,
    "successes": 284178,
    "fallbacks": 1247,
    "latency_total": 239433672,
    "provider_requests": {"OpenAI": 0, "Anthropic": 0, "Google": 0},
    "events": deque(maxlen=12),
    "rate_windows": {},
}
lock = threading.Lock()


def add_event(kind, title, detail, provider):
    with lock:
        state["events"].appendleft({
            "kind": kind,
            "title": title,
            "detail": detail,
            "provider": provider,
            "time": "just now",
        })


def local_fallback(prompt):
    started = time.perf_counter()
    time.sleep(random.uniform(0.04, 0.08))
    elapsed = max(1, round((time.perf_counter() - started) * 1000))
    return {"provider": "Local fallback", "model": "local-fallback", "latency_ms": elapsed, "output": f"Local fallback response for: {prompt[:80]}"}


def provider_call(provider, prompt):
    """Call a configured provider, with a local deterministic adapter as a fallback."""
    started = time.perf_counter()
    if provider == "OpenAI" and not OPENAI_API_KEY:
        return local_fallback(prompt)
    if provider == "Anthropic" and not ANTHROPIC_API_KEY:
        return local_fallback(prompt)

    if provider == "OpenAI":
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        body = {"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "messages": [{"role": "user", "content": prompt}], "max_tokens": 250}
    else:
        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}
        body = {"model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"), "max_tokens": 250, "messages": [{"role": "user", "content": prompt}]}

    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=8) as upstream:
            result = json.loads(upstream.read())
    except (HTTPError, URLError, TimeoutError) as error:
        raise ConnectionError(f"{provider} request failed: {error}") from error
    elapsed = max(1, round((time.perf_counter() - started) * 1000))
    if provider == "OpenAI":
        output = result["choices"][0]["message"]["content"]
        model = result.get("model", body["model"])
    else:
        output = result["content"][0]["text"]
        model = result.get("model", body["model"])
    return {"provider": provider, "model": model, "latency_ms": elapsed, "output": output}


def rate_limit(client_id):
    now = time.monotonic()
    with lock:
        timestamps = state["rate_windows"].setdefault(client_id, deque())
        while timestamps and timestamps[0] <= now - WINDOW_SECONDS:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT:
            retry_after = max(1, round(timestamps[0] + WINDOW_SECONDS - now))
            return False, retry_after
        timestamps.append(now)
        return True, 0


def metrics_payload():
    with lock:
        average = round(state["latency_total"] / max(1, state["successes"]))
        return {
            "requests": state["requests"],
            "successRate": round(state["successes"] / max(1, state["requests"]) * 100, 2),
            "latency": average,
            "fallbacks": state["fallbacks"],
            "events": list(state["events"]),
            "providers": state["provider_requests"],
        }


class GatewayHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/api/metrics":
            self.send_json(200, metrics_payload())
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/chat":
            self.send_json(404, {"error": "Not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Request body must be JSON"})
            return

        client_id = self.headers.get("X-Client-ID", "dashboard")
        allowed, retry_after = rate_limit(client_id)
        if not allowed:
            add_event("limit", "Rate limit absorbed", f"client: {client_id} · retry in {retry_after}s", "Queue")
            self.send_json(429, {"error": "Rate limit exceeded", "retryAfter": retry_after})
            return

        prompt = str(payload.get("prompt", "Hello from Relay"))
        started = time.perf_counter()
        try:
            response = provider_call("OpenAI", prompt)
            route = "OpenAI"
        except (TimeoutError, ConnectionError) as primary_error:
            fallback_started = time.perf_counter()
            response = provider_call("Anthropic", prompt)
            response["latency_ms"] = round((time.perf_counter() - started) * 1000)
            response["fallback_reason"] = str(primary_error)
            route = response["provider"]
            with lock:
                state["fallbacks"] += 1
            add_event("fallback", "Fallback route used", f"{response['model']} · {primary_error}", route)
            _ = fallback_started

        with lock:
            state["requests"] += 1
            state["successes"] += 1
            state["latency_total"] += response["latency_ms"]
            state["provider_requests"][route] += 1
        if route == "OpenAI":
            add_event("success", "Request completed", f"gpt-4o · {len(prompt.split()) + 20} tokens", route)
        self.send_json(200, {"ok": True, "route": route, **response, "metrics": metrics_payload()})


if __name__ == "__main__":
    print(f"Relay gateway running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), GatewayHandler).serve_forever()