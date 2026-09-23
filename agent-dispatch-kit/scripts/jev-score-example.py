#!/usr/bin/env python3
"""Sanitized example: independent second-model scoring for agent task acceptance.

This is a PATTERN, not production code. It shows how a dispatcher can ask an
independent model to score a worker agent's report before making the final
accept/reject call.

- The API key comes from the DISPATCH_SCORER_API_KEY environment variable.
  If it is not set, the script refuses to run. It never lives in source.
- Any OpenAI-compatible chat-completions endpoint works; configure it with
  DISPATCH_SCORER_BASE_URL and DISPATCH_SCORER_MODEL.
- Standard library only: no dependencies to install.
"""

import json
import os
import sys
import urllib.request

SCORER_SYSTEM = (
    "You are an independent acceptance scorer. Read the acceptance criteria "
    "and the worker agent's report, then reply with JSON only, no other text: "
    '{"completion": <0.0-1.0>, "quality": <0-10>, '
    '"outcome": "success|partial|failed", "reasons": ["..."]}'
)


def score(criteria: str, report: str) -> dict:
    api_key = os.environ.get("DISPATCH_SCORER_API_KEY")
    if not api_key:
        sys.exit("Refusing to run: set DISPATCH_SCORER_API_KEY first.")
    base_url = os.environ.get(
        "DISPATCH_SCORER_BASE_URL", "https://api.example.com/v1"
    ).rstrip("/")
    body = {
        "model": os.environ.get("DISPATCH_SCORER_MODEL", "your-scorer-model"),
        "messages": [
            {"role": "system", "content": SCORER_SYSTEM},
            {
                "role": "user",
                "content": f"Acceptance criteria:\n{criteria}\n\nWorker report:\n{report}",
            },
        ],
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return json.loads(data["choices"][0]["message"]["content"])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: jev-score-example.py <criteria_file> <report_file>")
    with open(sys.argv[1]) as f:
        criteria_text = f.read()
    with open(sys.argv[2]) as f:
        report_text = f.read()
    print(json.dumps(score(criteria_text, report_text), indent=2, ensure_ascii=False))
