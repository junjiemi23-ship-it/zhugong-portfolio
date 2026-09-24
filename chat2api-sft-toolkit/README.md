# chat2api-sft-toolkit · Turn idle Chat subscription quota into an SFT dataset

> Companion to the X thread: "Turn your idle Chat subscription quota into a free API"
> Thread link: https://x.com/jiemi232/status/2102592126412587502?s=46
> Companion thread 2 (pitfalls deep-dive): https://x.com/jiemi232/status/2102726759800328567?s=46

[中文版 → README.zh-CN.md](README.zh-CN.md)

## What is this

A small toolkit that answers one specific question: **besides chatting by hand, what else can your monthly Chat subscription quota become?**

The idea comes from the open-source project [Sun9220/chat2api](https://github.com/Sun9220/chat2api) (MIT): it reverse-engineers the web version of ChatGPT into an OpenAI-compatible API (`POST /v1/chat/completions`, local default `http://127.0.0.1:5005/v1`). The quota is still the quota inside your subscription — but it becomes **programmable quota**.

This toolkit handles the "second half": use a large model as the teacher, batch-generate high-quality Q&A pairs, clean them into a tidy instruction dataset, and fine-tune a local small model (Qwen / LLaMA family) — i.e. **distillation**. SFT learns "imitation", and data quality sets the ceiling: 500 clean examples beat 5,000 dirty ones.

## Who it's for

- Individual developers with a Plus / Pro subscription and quota to spare
- People who want to play with SFT / distillation on the cheap, without paying for data labeling
- People with a clear-eyed view of what a reverse-engineered API can and cannot do (read [docs/pitfalls.md](docs/pitfalls.md) first)

## Disclaimer (read first)

**The following is for research, personal development, and personal use only.** Reverse-engineered interfaces may violate terms of service, and account bans are a real risk. Do not use it for public services or commercial purposes; you are responsible for the consequences.

One more hard-won reminder (from real testing): these reverse-engineered channels have limited support for the `tools` parameter — in testing, no native `tool_calls` were ever produced, and the model even fabricated execution results in plain text. So it's good for **generation, evaluation, and data synthesis**; for agentic tool calling, use the official API. See [docs/pitfalls.md](docs/pitfalls.md).

## Lazy one-click prompt

Don't want to touch the terminal? Copy the block between the `---` markers in [prompts/lazy-oneclick.md](prompts/lazy-oneclick.md) and paste it to your agent (Cursor / opencode / codex / Claude). It automates the whole chain: deploy → token setup → batch generation → cleaning into an SFT dataset → sampling review. You only step in where marked: paste your token, pick the topic and count, and confirm the final sample. Red lines: personal research and study only — no commercial use, no public services.

## Quickstart

You need **your own chat2api deployment** (follow the [Sun9220/chat2api](https://github.com/Sun9220/chat2api) README; three options):

```bash
# Easiest: one-click Zeabur deploy; if you have a server:
docker run -d -p 5005:5005 lanqian528/chat2api:latest
# Local: pip install -r requirements.txt && python app.py
```

Then:

```bash
# 1. Prepare your prompt list (one per line); the example is a good starting point
cp examples/prompts_example.txt my_prompts.txt

# 2. Configure (everything via environment variables; CLI flags override, see --help)
export CHAT2API_BASE_URL=http://127.0.0.1:5005/v1
export CHAT2API_API_KEY=your_auth_code   # leave empty if AUTHORIZATION is not set
export CHAT2API_MODEL=gpt-4o-mini        # adjust to your deployment and login

# 3. Batch-generate (resumable: prompts already generated are skipped automatically)
python3 scripts/generate_dataset.py --prompts my_prompts.txt --out data/qa_raw.jsonl

# 4. Clean into SFT-ready data (dedupe, length filters, boilerplate removal, with stats)
python3 scripts/clean_dataset.py --in data/qa_raw.jsonl --out data/qa_sft.jsonl
```

`*.jsonl` under `data/` never enters the repo (see `.gitignore`); your data stays local.

Dependencies: Python standard library only, zero third-party packages.

## Project structure

```text
chat2api-sft-toolkit/
├── README.md               # This file (English)
├── README.zh-CN.md         # Chinese version
├── LICENSE                 # MIT
├── scripts/
│   ├── generate_dataset.py # Batch Q&A generation (resumable, exponential-backoff retries)
│   └── clean_dataset.py    # SFT data cleaning (dedupe, filters, stats)
├── docs/
│   ├── pitfalls.md         # Pitfall notes: tool_calls and the four wiring hurdles
│   ├── pitfalls-deep-dive.md # Deep-dive long-form: pit 0 + the four wiring hurdles (Chinese)
│   └── article.md          # Long-form version of the companion X thread (Chinese)
├── prompts/
│   └── lazy-oneclick.md    # One-click prompt: paste to your agent, runs the full chain
└── examples/
    └── prompts_example.txt # Example prompt list
```

## License

MIT (see [LICENSE](LICENSE)). chat2api itself is Sun9220/chat2api (MIT); this project is a data toolkit around it and contains no reverse-engineered server implementation.
