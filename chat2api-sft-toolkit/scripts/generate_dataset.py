#!/usr/bin/env python3
"""Batch Q&A generation through an OpenAI-compatible chat2api endpoint.

Reads prompts from a .txt file (one prompt per line) or a .jsonl file
(objects with a "prompt" field, or plain JSON strings), calls
POST {base_url}/chat/completions, and appends
{"prompt", "response", "model", "ts"} records to an output JSONL file.

Configuration -- everything via environment variables, each overridable
by a command-line flag:

    CHAT2API_BASE_URL   default: http://127.0.0.1:5005/v1
    CHAT2API_API_KEY    default: "" (your chat2api AUTHORIZATION code, if set)
    CHAT2API_MODEL      default: gpt-4o-mini (match your own deployment/login)

Resume support: prompts already present in the output file are skipped,
so re-running never duplicates work.

Requires YOUR OWN chat2api deployment (see README quickstart). Never fakes
a run: without a reachable endpoint this script fails loudly instead of
writing placeholder data. No credentials are hardcoded anywhere.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_BASE_URL = "http://127.0.0.1:5005/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def load_prompts(path):
    """Return a list of prompt strings from .txt or .jsonl."""
    prompts = []
    if path.endswith(".jsonl"):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                text = obj["prompt"] if isinstance(obj, dict) else str(obj)
                if text.strip():
                    prompts.append(text.strip())
    else:  # plain text, one prompt per line; '#' starts a comment
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    prompts.append(line)
    # de-duplicate while preserving order
    seen, uniq = set(), []
    for p in prompts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def load_done(out_path):
    """Return the set of prompts already answered in the output file."""
    done = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line).get("prompt", ""))
                except (json.JSONDecodeError, AttributeError):
                    continue
    return done


def chat_once(base_url, api_key, model, prompt, temperature, timeout,
                system=""):
    """One blocking chat-completions call. Raises on failure."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code}: {detail}")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"empty choices in response: {str(data)[:200]}")
    return (choices[0].get("message") or {}).get("content", "")


def generate_with_retry(base_url, api_key, model, prompt, temperature,
                        timeout, max_retries, system=""):
    """Call with exponential backoff. Returns (response, attempts)."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return chat_once(base_url, api_key, model, prompt,
                             temperature, timeout, system), attempt + 1
        except Exception as e:  # noqa: BLE001 - retry on any request failure
            last_err = e
            if attempt == max_retries:
                break
            wait = min(2 ** attempt, 60)
            log(f"  retry {attempt + 1}/{max_retries} in {wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError(f"failed after {max_retries + 1} attempts: {last_err}")


def main():
    ap = argparse.ArgumentParser(
        description="Batch-generate Q&A pairs via an OpenAI-compatible "
                    "chat2api endpoint. All config via env (see --help text).")
    ap.add_argument("--prompts", required=True,
                    help="input .txt (one prompt per line) or .jsonl file")
    ap.add_argument("--out", required=True, help="output JSONL file (appended)")
    ap.add_argument("--base-url",
                    default=os.environ.get("CHAT2API_BASE_URL", DEFAULT_BASE_URL),
                    help="chat2api base URL (env CHAT2API_BASE_URL)")
    ap.add_argument("--api-key",
                    default=os.environ.get("CHAT2API_API_KEY", ""),
                    help="chat2api AUTHORIZATION code (env CHAT2API_API_KEY)")
    ap.add_argument("--model",
                    default=os.environ.get("CHAT2API_MODEL", DEFAULT_MODEL),
                    help="model name, must match your deployment (env CHAT2API_MODEL)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--timeout", type=int, default=120,
                    help="per-request timeout in seconds")
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--system", default="",
                    help="optional system prompt prepended to every request")
    args = ap.parse_args()

    prompts = load_prompts(args.prompts)
    done = load_done(args.out)
    pending = [p for p in prompts if p not in done]
    log(f"prompts: {len(prompts)} total, {len(done)} already done, "
        f"{len(pending)} pending -> {args.out}")

    ok, failed = 0, 0
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as f:
        for i, prompt in enumerate(pending, 1):
            log(f"[{i}/{len(pending)}] generating...")
            try:
                response, _ = generate_with_retry(
                    args.base_url, args.api_key, args.model, prompt,
                    args.temperature, args.timeout, args.max_retries,
                    args.system)
                if not response.strip():
                    raise RuntimeError("empty response body")
                rec = {"prompt": prompt, "response": response.strip(),
                       "model": args.model,
                       "ts": datetime.now(timezone.utc).isoformat()}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                ok += 1
            except Exception as e:  # noqa: BLE001 - keep going, report at end
                log(f"  FAILED: {prompt[:60]!r}: {e}")
                failed += 1
    log(f"done: {ok} ok, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
