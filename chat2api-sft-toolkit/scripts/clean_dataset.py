#!/usr/bin/env python3
"""Clean a generated Q&A JSONL file into an SFT-ready dataset.

Steps:
  1. de-duplicate by normalized prompt (keep first occurrence)
  2. drop records with empty prompt/response
  3. length filters: response must be within [min-resp-len, max-resp-len],
     prompt must not exceed --max-prompt-len
  4. drop boilerplate / refusal-style responses (heuristic regex list)

Prints a stats breakdown so you can see what was removed and why.
JSONL in, JSONL out. Stdlib only.
"""

import argparse
import json
import re
import sys

# Heuristic boilerplate patterns (Chinese + English). These catch refusals
# and "as an AI" style filler that pollute SFT data. Edit to taste.
BOILERPLATE = [
    r"作为.{0,8}AI", r"AI\s*语言模型", r"作为一个语言模型",
    r"我无法(回答|帮助|提供)", r"很抱歉.*无法", r"无法满足",
    r"as an ai language model", r"\bi['’]m an ai\b", r"\bi am an ai\b",
    r"\bi cannot\b", r"\bi can't (help|comply)\b",
]
BOILERPLATE_RE = re.compile("|".join(BOILERPLATE), re.IGNORECASE)


def norm_prompt(text):
    return " ".join(text.split()).lower()


def clean(records, min_resp_len, max_resp_len, max_prompt_len):
    kept, stats = [], {"dup": 0, "empty": 0, "too_short": 0,
                       "too_long": 0, "prompt_too_long": 0, "boilerplate": 0}
    seen = set()
    for rec in records:
        prompt = (rec.get("prompt") or "").strip()
        response = (rec.get("response") or "").strip()
        if not prompt or not response:
            stats["empty"] += 1
            continue
        key = norm_prompt(prompt)
        if key in seen:
            stats["dup"] += 1
            continue
        if len(prompt) > max_prompt_len:
            stats["prompt_too_long"] += 1
            continue
        if len(response) < min_resp_len:
            stats["too_short"] += 1
            continue
        if len(response) > max_resp_len:
            stats["too_long"] += 1
            continue
        if BOILERPLATE_RE.search(response):
            stats["boilerplate"] += 1
            continue
        seen.add(key)
        kept.append({"prompt": prompt, "response": response,
                     "model": rec.get("model", ""), "ts": rec.get("ts", "")})
    return kept, stats


def main():
    ap = argparse.ArgumentParser(
        description="De-duplicate and filter a Q&A JSONL into SFT-ready data.")
    ap.add_argument("--in", dest="inp", required=True, help="input JSONL")
    ap.add_argument("--out", required=True, help="output JSONL")
    ap.add_argument("--min-resp-len", type=int, default=20,
                    help="drop responses shorter than this (chars)")
    ap.add_argument("--max-resp-len", type=int, default=8000,
                    help="drop responses longer than this (chars)")
    ap.add_argument("--max-prompt-len", type=int, default=2000,
                    help="drop prompts longer than this (chars)")
    args = ap.parse_args()

    records = []
    with open(args.inp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    kept, stats = clean(records, args.min_resp_len,
                        args.max_resp_len, args.max_prompt_len)

    with open(args.out, "w", encoding="utf-8") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    dropped = sum(stats.values())
    print(f"input:  {len(records)}")
    print(f"kept:   {len(kept)}")
    print(f"dropped: {dropped}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if kept:
        avg_p = sum(len(r["prompt"]) for r in kept) / len(kept)
        avg_r = sum(len(r["response"]) for r in kept) / len(kept)
        print(f"avg prompt chars: {avg_p:.0f}, avg response chars: {avg_r:.0f}")


if __name__ == "__main__":
    main()
