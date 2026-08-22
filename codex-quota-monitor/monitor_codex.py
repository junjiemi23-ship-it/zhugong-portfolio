#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_codex.py —— Codex 额度刷新监控系统（实施计划 Phase A）
依据：D:/AI交流/已解决-20260821-1957-Codex-给Work2-Codex额度刷新监控调研.md 第八节实施计划 v1
实现：Work2（国际版 WorkBuddy AI）

运行位置：腾讯云 CVM 7×24（主监控）/ 亦可本机 Windows 计划任务
依赖：Python 3.8+ 标准库，零第三方依赖（便于 CVM 直接部署）。注意：Windows 本机控制台默认 GBK，运行需 UTF-8 控制台或 Python 3.7+（脚本已在 main() 重配置 stdout/stderr 为 utf-8 兜底，见 12.3 节修复）

数据源（按优先级）：
  主信号  : @thsottiaux via xcancel 镜像（多实例故障转移）
  辅助校验: tibogpt.com 静态页（PROBABLY/YES/NO）
  社区旁证: Redlib 镜像（r/codex 等）
  媒体快讯: IT之家 RSS
判定状态机：观察 → 疑似 → 高度疑似 → 已确认
通知方式  ：SMTP 邮箱（QQ邮箱 465 SSL，主通道；Server酱 代码保留、默认关闭；dry_run 时仅打印）
事件日志  ：events.jsonl（每行一条 JSON）

用法：
  python monitor_codex.py --once        # 单次巡检（cron 每 10 分钟调用）
  python monitor_codex.py --serve       # 内部循环（自带 sleep，可选）
  python monitor_codex.py --replay       # 回放 2026-08-21 BANKED reset 事件，验证状态机+推送
  python monitor_codex.py --test-push    # 发一条测试推送（验证 SMTP 邮箱主通道）
  python monitor_codex.py --selftest     # 离线单测解析器/关键词/挑战检测
  python monitor_codex.py --confirm      # 主公确认当前事件 -> 补发 ✅
"""
import argparse, json, os, re, sys, time, datetime, hashlib, smtplib, urllib.request, urllib.error, urllib.parse
from html import unescape as html_unescape
from email.mime.text import MIMEText
from email.header import Header

# ---------- 路径（脚本同目录） ----------
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.yaml")
STATE_PATH = os.path.join(HERE, "state.json")
EVENT_LOG = os.path.join(HERE, "events.jsonl")

# ---------- 默认配置 ----------
DEFAULTS = {
    "serverchan_sendkey": "",            # 留空 = dry_run 仅打印；填上 = 真实推送
    # ---- 通知通道 ----
    "email_enabled": True,               # 主通道：SMTP 邮箱（QQ邮箱 465 SSL）
    "serverchan_enabled": False,         # Server酱 代码保留、默认关闭（将来可换回微信）
    "smtp_host": "smtp.qq.com",
    "smtp_port": 465,
    "smtp_user": "",                     # 主公QQ邮箱（发件）
    "smtp_pass": "",                     # QQ邮箱「设置→账户→开启POP3/SMTP→生成授权码」（非QQ密码）
    "to_email": "",                      # 主公手机邮箱App登录的收件邮箱
    "push_enabled": True,
    "dry_run": True,                      # 本机验证设 true；上 CVM 改 false
    # 主信号实例（多实例故障转移，按顺序尝试，被墙/失败自动跳过下一个）。
    # 实测（2026-08-21）：xcancel.com 稳定可用；nitter.tiekoetter.com 为公共备用，
    # 但偶被 Anubis 验证墙拦截（is_challenge 已识别并跳过），故作「尽力而为」备用。
    # 公共镜像普遍不稳 —— 长期最稳方案是自托管 xcancel/nitter 实例，填入此处即可。
    "xcancel_instances": ["https://xcancel.com/thsottiaux",
                           "https://nitter.tiekoetter.com/thsottiaux"],
    "tibogpt_url": "https://tibogpt.com",
    # 主信号源切换：xcancel（默认，完整推文）| tibogpt（CVM 被墙时零成本替代，只给 YES/PROBABLY 结论）
    "primary_source": "xcancel",
    # 社区旁证 / 媒体快证：本期（Phase A）仅保留配置占位，cycle() 未接入抓取逻辑，
    # 不参与主触发。未来接入需实现 fetch + 去噪，并把下面 enabled 改 true。
    "redlib_url": "https://redlib.catsarch.com/r/codex/search?q=codex%20reset",
    "redlib_enabled": False,
    "ithome_rss": "https://www.ithome.com/rss/",
    "ithome_enabled": False,
    # 白名单关键词：新推文命中即进入『疑似』；可加可减
    "keywords": ["banked reset", "credit every", "reset button",
                 "usage limit", "bear great news", "20m active users"],
    "exclude": ["sub2api"],               # 误报排除词（如 Tibo 谈 sub2api 风控时不误推）
    "check_interval_min": 10,
    "tibogpt_interval_min": 30,
    "redlib_interval_min": 360,
    "cooldown_hours": 24,                 # 同一事件 24h 冷却防重
    "http_timeout": 20,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

# ================= 配置加载（极简 YAML，零依赖） =================
def _strip_comment(line):
    """去注释：仅当 '#' 在行首或前一字符为空白、且不在引号内时才当注释。
    避免误删值里的 '#'（如 URL 锚点）。"""
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out)

def _split_list(s):
    """按逗号切分列表项，忽略引号/括号内的逗号。"""
    out, buf, depth, q = [], "", 0, None
    for ch in s:
        if q:
            buf += ch
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            buf += ch
        elif ch in "[{":
            depth += 1
            buf += ch
        elif ch in "]}":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf)
    return out

def _coerce(v):
    """值类型推断：去引号 → bool → int → float → 原串。"""
    v = v.strip()
    if len(v) >= 2 and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    if v.startswith("[") and v.endswith("]"):
        return [_coerce(x) for x in _split_list(v[1:-1])]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v

def load_config(path):
    """极简 YAML 解析（零依赖）。支持：内联列表 [a, b]、YAML 块列表（key: 换行 - a）、
    布尔、整数、浮点、引号字符串；# 仅当注释时去除。修复点：① 支持块列表；
    ② 注释/列表项引号/浮点健壮化（原实现只认内联 [] 且 # 一刀切会误删值内 #）。"""
    cfg = dict(DEFAULTS)
    if not os.path.exists(path):
        return cfg
    pending_key, pending_list = None, None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = _strip_comment(raw.rstrip())
            if not line.strip():
                continue
            if pending_list is not None:
                m = re.match(r"\s*-\s*(.*)$", line)
                if m:
                    pending_list.append(_coerce(m.group(1)))
                    continue
                cfg[pending_key] = pending_list   # 块列表结束，落盘后继续按普通行处理
                pending_key = pending_list = None
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v == "":
                pending_key, pending_list = k, []   # 可能是块列表开始
                continue
            if v.startswith("[") and v.endswith("]"):
                cfg[k] = [_coerce(x) for x in _split_list(v[1:-1])]
            else:
                cfg[k] = _coerce(v)
    if pending_list is not None:
        cfg[pending_key] = pending_list
    return cfg

# ================= HTTP 抓取 =================
def fetch(url, cfg):
    """返回 (html:str|None, err:str|None)。html=None 表示网络/读取失败。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": cfg["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=cfg["http_timeout"]) as r:
            data = r.read()
        try:
            return data.decode("utf-8"), None
        except Exception:
            return data.decode("latin-1"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)[:120]

def is_challenge(html):
    """判定是否被反爬验证墙拦截（xcancel/nitter 常见）。

    覆盖 Cloudflare「Verifying your browser / Just a moment」与 Anubis「Making sure
    you're not a bot」两类公共镜像验证墙——被墙页面若不当成失败跳过，会被误当成「已抓到
    推文」导致误 break / 污染 last_tweet_hash。"""
    if not html:
        return False
    low = html.lower()
    return any(s in low for s in ("verifying your browser", "checking your browser",
                                  "just a moment", "enable javascript and cookies",
                                  "making sure you're not a bot", "anubis",
                                  "are you a robot"))

# ================= 解析 =================
def parse_xcancel(html):
    """返回 (tweet_text, tweet_url) 或 (None, None)。
    兼容 xcancel/nitter 多结构：<article> / timeline-item / tweet-content / 兜底分段。"""
    if not html:
        return None, None
    link = None
    lm = re.search(r'href=["\'](/thsottiaux/status/\d+)["\']', html)
    if lm:
        link = "https://xcancel.com" + lm.group(1)
    # 结构 A：<article>
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
    if m:
        return (_extract_tweet(m.group(1)), link)
    # 结构 B：tweet-content / timeline-item 容器；链接可能在该块之前，改为整页取首条 status 链接
    # 关键：从起始标签的 '>' 之后切开，避免把 'class="tweet-content media-body" dir="auto">' 这类
    # 标签碎片残留在正文开头（xcancel 真实页面即如此）。
    i = html.lower().find('class="tweet-content')
    if i == -1:
        i = html.lower().find('class="timeline-item')
    if i != -1:
        link = _first_status_link(html)
        gt = html.find(">", i)
        start = (gt + 1) if gt != -1 else i
        return (_extract_tweet(html[start: start + 2500]), link)
    # 结构 C：兜底整页抽首段
    return (_extract_tweet(html[:3000]), link)

def _first_status_link(html):
    """从整页 HTML 抽取首条 @thsottiaux status 链接（结构 B / 兜底用）。"""
    if not html:
        return None
    m = re.search(r'/thsottiaux/status/(\d+)', html)
    if m:
        return "https://xcancel.com" + m.group(0)
    return None

def _extract_tweet(block):
    """从推文块里去标签抽取正文文本。"""
    if not block:
        return None
    txt = re.sub(r"<script.*?</script>", " ", block, flags=re.S | re.I)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
    # 兜底：若块开头仍残留类似 'class="tweet-content media-body" dir="auto">' 的未闭合标签碎片，先裁掉
    frag = re.match(r'^[^>]*>', txt)
    if frag:
        txt = txt[frag.end():]
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html_unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return (txt or None)

def parse_tibogpt(html):
    """返回 PROBABLY / YES / NO / None。"""
    if not html:
        return None
    m = re.search(r"CURRENT ANSWER\s*([A-Za-z]+)", html, re.I)
    if m:
        return m.group(1).upper()
    up = html.upper()
    if "PROBABLY" in up:
        return "PROBABLY"
    if "YES" in up:
        return "YES"
    if "NO" in up:
        return "NO"
    return None

def keyword_hit(text, cfg):
    low = text.lower()
    for kw in cfg["keywords"]:
        if kw.lower() in low:
            if any(e.lower() in low for e in cfg.get("exclude", [])):
                continue
            return kw
    return None

# ================= 状态 =================
def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"last_tweet_hash": None, "event": None, "fail_streak": 0}

def save_state(s):
    json.dump(s, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def log_event(d):
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

def fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def stable_hash(text):
    """跨进程稳定哈希（替代内置 hash()）。

    内置 hash() 受 PYTHONHASHSEED 随机种子影响，cron 每次启动新进程对【同一推文】算出的
    hash 可能不同 → 被误判成『新推文』，虽被 24h 冷却挡住重复推送，但会反复 fetch tibogpt、
    污染日志。改用 sha1 十六进制，结果跨进程一致。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

# ================= 推送（email SMTP 主通道 + Server酱 备用） =================
def _send_email(cfg, title, desp):
    """用标准库 smtplib 发送 UTF-8 纯文本邮件（QQ邮箱 465 SSL，零第三方依赖）。"""
    body = f"{desp}\n\n-- Codex 额度刷新监控 (monitor_codex.py)"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["to_email"]
    with smtplib.SMTP_SSL(str(cfg["smtp_host"]), int(cfg["smtp_port"]), timeout=15) as s:
        s.login(cfg["smtp_user"], cfg["smtp_pass"])
        s.sendmail(cfg["smtp_user"], [cfg["to_email"]], msg.as_string())

def push(cfg, title, desp, kind="suspect"):
    if not cfg.get("push_enabled", True):
        return False
    dry = cfg.get("dry_run", True)
    results = []
    any_channel = False

    # 1) 邮件主通道（QQ邮箱 465 SSL）
    if cfg.get("email_enabled", False):
        any_channel = True
        email_complete = bool(cfg.get("smtp_user") and cfg.get("smtp_pass") and cfg.get("to_email"))
        if dry or not email_complete:
            print(f"[DRY-RUN][EMAIL][{kind}] {title}\n收件: {cfg.get('to_email') or '(未填)'}\n{desp}\n{'='*40}")
            results.append("email-dry")
        else:
            try:
                _send_email(cfg, title, desp)
                print(f"[PUSH][EMAIL][{kind}] {title} -> {cfg.get('to_email')}")
                results.append("email-ok")
            except Exception as e:
                print(f"[PUSH-FAIL][EMAIL][{kind}] {e}")
                results.append("email-fail")

    # 2) Server酱 备用通道（默认关，代码保留）
    if cfg.get("serverchan_enabled", False):
        any_channel = True
        sct_key = cfg.get("serverchan_sendkey", "")
        if dry or not sct_key:
            print(f"[DRY-RUN][SCT][{kind}] {title}\n{desp}\n{'='*40}")
            results.append("sct-dry")
        else:
            try:
                url = "https://sctapi.qq.com/send?sendkey=" + urllib.parse.quote(sct_key)
                data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"User-Agent": cfg["user_agent"]})
                with urllib.request.urlopen(req, timeout=15) as r:
                    resp = r.read().decode("utf-8")
                ok = "success" in resp.lower()
                print(f"[PUSH][SCT][{kind}] {title} -> {resp.strip()}")
                results.append("sct-ok" if ok else "sct-fail")
            except Exception as e:
                print(f"[PUSH-FAIL][SCT][{kind}] {e}")
                results.append("sct-fail")

    # 3) 无可用通道（都关/都不完整）：兜底 dry-run 打印
    if not any_channel:
        print(f"[DRY-RUN][{kind}] {title}\n{desp}\n{'='*40}")
        return "dry-run"
    return results

# ================= 主巡检 =================
def cycle_tibogpt(cfg, state, now):
    """主信号源 = tibogpt.com 模式（CVM 被墙时的零成本替代，Codex 决策 A）。
    每轮轮询 tibogpt，翻转 YES/PROBABLY 即告警；无推文原文/链接属可接受降级。
    源不可达时沿用状态翻转降噪（signal_state up/down），不刷屏。"""
    html, err = fetch(cfg["tibogpt_url"], cfg)
    if html is None:
        state["fail_streak"] = state.get("fail_streak", 0) + 1
        if state["fail_streak"] >= 3 and state.get("signal_state", "up") != "down":
            push(cfg, "⚠️ 监控信号源失效",
                 f"tibogpt 连续 {state['fail_streak']} 轮抓取失败\n最后错误: {err}\n"
                 f"监控暂处盲区。已暂停重复告警，信号恢复时再通知一次。", kind="alert")
            state["signal_state"] = "down"
        save_state(state)
        return
    if state.get("signal_state", "up") == "down":
        push(cfg, "✅ 监控信号源已恢复", "tibogpt 重新可达，监控恢复。", kind="alert")
        state["signal_state"] = "up"
    state["fail_streak"] = 0
    tg = parse_tibogpt(html)
    prev_alerted = state.get("last_tibo") in ("PROBABLY", "YES")
    if tg in ("PROBABLY", "YES"):
        if prev_alerted:
            # 修复 a（Codex 决策 2026-08-22）：状态未翻转（上一次已是 PROBABLY/YES）
            # → 不重复推送，避免监控频率(3天) > 冷却(24h) 时每轮都发邮件刷屏。
            state["last_tibo"] = tg
            save_state(state)
            return
        # 翻转 NO/None → PROBABLY/YES：用 cooldown_hours(24h) 作防抖层，
        # 避免 YES/NO/YES 抖动在冷却期内误推（b：冷却保留不变，不放大到 96h 以免掩盖真实翻转）。
        ev = state.get("event")
        if ev and (now - ev.get("t", 0)) < cfg["cooldown_hours"] * 3600:
            # 防抖期内：视为抖动，抑制推送，且【不更新 last_tibo】（保留上次非告警态），
            # 使防抖期过后的真实翻转仍能触发推送（场景③ 期外推）。
            save_state(state)
            return
        level = "高度疑似" if tg == "YES" else "疑似"
        title = ("🔥 Codex 额度疑似刷新" if tg == "PROBABLY" else "🔥🔥 Codex 额度高度疑似刷新")
        desp = (f"来源: tibogpt.com（主信号模式）\n判定: {tg}\n时间: {fmt(now)}\n"
                f"说明: tibogpt 翻转为 {tg}，提示 Codex 额度可能已刷新。\n"
                f"注: 此模式无推文原文/链接（xcancel 在 CVM 被墙），以 tibogpt 结论为准。")
        pushed = push(cfg, title, desp, kind="suspect")
        state["event"] = {"kw": tg, "t": now, "level": level, "link": None, "pushed": bool(pushed)}
        log_event({"time": fmt(now), "source": "tibogpt", "verdict": tg, "state": level, "pushed": bool(pushed)})
    # 非 PROBABLY/YES（NO/None）或已判重处理：更新 last_tibo，不推（event 保留供防抖计时）
    state["last_tibo"] = tg
    save_state(state)

def cycle(cfg):
    state = load_state()
    now = time.time()
    # 主信号源可切换：xcancel（默认，完整推文）| tibogpt（CVM 被墙时零成本替代，只给结论）
    if cfg.get("primary_source", "xcancel") == "tibogpt":
        return cycle_tibogpt(cfg, state, now)

    # 注：redlib_url / ithome_rss 为「社区/媒体旁证」占位（见 DEFAULTS 的 *_enabled 开关），
    # 本期（Phase A）未接入 cycle() 抓取逻辑，不参与主触发；仅在真实事件来袭时作人工旁证参考。
    # 主信号 = xcancel 多实例；辅助校验 = tibogpt（下方步骤 4）。

    # 1) 主信号：xcancel 多实例故障转移
    tweet_text, tweet_link, src_err = None, None, None
    for inst in cfg["xcancel_instances"]:
        html, err = fetch(inst, cfg)
        if html is None:
            src_err = err
            continue
        if is_challenge(html):
            src_err = "challenge(验证墙)"
            continue
        t, link = parse_xcancel(html)
        if t:
            tweet_text, tweet_link = t, link
            break
        src_err = "no-article"

    if tweet_text is None:
        state["fail_streak"] = state.get("fail_streak", 0) + 1
        # 降噪（Codex 建议，2026-08-22）：信号源失效告警仅在『状态翻转』时发一次
        # （up→down），持续失效期间不再每轮刷屏（避免主公每 30 分钟收一封告警邮件）。
        # 用 state["signal_state"] 记录上一次状态（"up"/"down"）。
        if state["fail_streak"] >= 3 and state.get("signal_state", "up") != "down":
            push(cfg, "⚠️ 监控信号源失效",
                 f"xcancel 连续 {state['fail_streak']} 轮抓取失败\n最后错误: {src_err}\n"
                 f"监控暂处盲区。已暂停重复告警，信号恢复时再通知一次。\n"
                 f"请检查实例是否挂掉/被验证墙拦截，或切换信号源（见部署方案）。", kind="alert")
            state["signal_state"] = "down"
        save_state(state)
        return
    # 信号源恢复（down→up 翻转）：发一次恢复通知，避免盲区时误以为已恢复而无提示
    if state.get("signal_state", "up") == "down":
        push(cfg, "✅ 监控信号源已恢复",
             f"xcancel 重新抓到推文，监控恢复。\n最近一条: {tweet_text[:160]}", kind="alert")
        state["signal_state"] = "up"
    state["fail_streak"] = 0

    # 2) 是否新推文（stable_hash 跨进程一致，避免 cron 每次重启误判新推文）
    h = stable_hash(tweet_text)
    if h == state.get("last_tweet_hash"):
        save_state(state)
        return
    state["last_tweet_hash"] = h

    # 3) 关键词判定
    kw = keyword_hit(tweet_text, cfg)
    if not kw:
        save_state(state)
        return

    # 4) tibogpt 交叉 -> 高度疑似
    thtml, _ = fetch(cfg["tibogpt_url"], cfg)
    tg = parse_tibogpt(thtml) if thtml else None
    level = "高度疑似" if tg in ("PROBABLY", "YES") else "疑似"

    # 5) 冷却：同关键词 24h 内不重复推
    ev = state.get("event")
    cooldown = cfg["cooldown_hours"] * 3600
    if ev and ev.get("kw") == kw and (now - ev.get("t", 0)) < cooldown:
        save_state(state)
        return

    # 6) 推送（进疑似/高度疑似即推，保证第一时间）
    title = ("🔥 Codex 额度疑似刷新" if level == "疑似"
             else "🔥🔥 Codex 额度高度疑似刷新")
    desp = (f"来源: @thsottiaux (xcancel)\n命中关键词: {kw}\n"
            f"时间: {fmt(now)}\n链接: {tweet_link or '-'}\n"
            f"tibogpt: {tg or 'N/A'}\n\n摘要: {tweet_text[:400]}")
    pushed = push(cfg, title, desp, kind="suspect")
    state["event"] = {"kw": kw, "t": now, "level": level,
                      "tibogpt": tg, "link": tweet_link, "pushed": bool(pushed)}
    log_event({"time": fmt(now), "source": "tibo", "keyword": kw,
               "tibogpt": tg, "state": level, "pushed": bool(pushed)})
    save_state(state)

# ================= 回放验证 =================
def replay(cfg):
    tweet = ("It's me again. I come bearing great news. First of all, we have hit 20M "
             "active users for Codex some time this week. Second of all, this is cause "
             "for celebration and during the day we will credit every Codex and ChatGPT "
             "Work user with a BANKED reset that you can use at your own leisure.")
    link = "https://xcancel.com/thsottiaux/status/REPLAY"
    print("== REPLAY 2026-08-21 BANKED reset 真实事件 ==")
    print("推文:", tweet[:160], "...")
    kw = keyword_hit(tweet, cfg)
    print("白名单命中:", kw)
    tg = "PROBABLY"                     # 模拟 tibogpt 已翻转
    level = "高度疑似" if tg in ("PROBABLY", "YES") else "疑似"
    print("tibogpt 交叉:", tg, "->", level)
    title = "🔥🔥 Codex 额度高度疑似刷新 (REPLAY 回放验证)"
    desp = (f"来源: @thsottiaux (xcancel)\n命中关键词: {kw}\ntibogpt: {tg}\n"
            f"[回放验证] 真实事件 2026-08-21 BANKED reset，状态机 观察→疑似→高度疑似 触发推送")
    push(cfg, title, desp, kind="suspect")
    log_event({"time": fmt(time.time()), "source": "replay", "keyword": kw,
               "tibogpt": tg, "state": level, "pushed": True})
    print("REPLAY 完成 ✅ 状态机与推送链路验证通过")

# ================= 离线单测 =================
def selftest_tibogpt():
    """单测 cycle_tibogpt 的翻转判重 + cooldown 防抖（不联网、不写文件、不真发）。
    覆盖 Codex 决策三场景：① 状态不变跨冷却→不推；② NO→PROBABLY 推一次(后续不推)；
    ③ PROBABLY→NO→PROBABLY 防抖期内不推、防抖期外推。"""
    cfg = dict(DEFAULTS)
    captured = []
    orig = {n: globals()[n] for n in ("fetch", "push", "save_state", "log_event")}
    def fake_push(c, title, desp, kind="suspect"):
        captured.append(kind)
        return True
    def set_fetch(ans):
        globals()["fetch"] = lambda url, c: ("...CURRENT ANSWER " + ans + "...", None)
    globals()["push"] = fake_push
    globals()["save_state"] = lambda s: None
    globals()["log_event"] = lambda d: None
    ok = True
    try:
        # 场景1：状态不变跨冷却（PROBABLY 持续）→ 不推
        set_fetch("PROBABLY")
        st = {"last_tibo": "PROBABLY", "event": {"t": time.time() - 100000},
              "signal_state": "up", "fail_streak": 0}
        captured.clear()
        cycle_tibogpt(cfg, st, time.time())
        r1 = not captured
        print("  [1] 状态不变(PROBABLY)跨冷却:", "PASS" if r1 else "FAIL(误推)")
        ok = ok and r1

        # 场景2：NO→PROBABLY 推一次；持续 PROBABLY 不再推
        set_fetch("NO")
        st = {"last_tibo": "NO", "event": None, "signal_state": "up", "fail_streak": 0}
        cycle_tibogpt(cfg, st, time.time())          # NO：不推
        set_fetch("PROBABLY")
        captured.clear()
        cycle_tibogpt(cfg, st, time.time())          # 翻转 → 推
        r2 = len(captured) == 1
        captured.clear()
        cycle_tibogpt(cfg, st, time.time())          # 仍 PROBABLY → 不推
        r2b = not captured
        print("  [2] NO→PROBABLY 推一次/持续不推:", "PASS" if (r2 and r2b) else "FAIL")
        ok = ok and r2 and r2b

        # 场景3：PROBABLY→NO→PROBABLY 防抖期内外
        base = time.time()
        st = {"last_tibo": "PROBABLY", "event": {"t": base}, "signal_state": "up", "fail_streak": 0}
        set_fetch("NO")
        cycle_tibogpt(cfg, st, base + 1)             # NO：不推
        set_fetch("PROBABLY")
        captured.clear()
        cycle_tibogpt(cfg, st, base + 3600)          # +1h 防抖期内 → 不推
        r3in = not captured
        captured.clear()
        cycle_tibogpt(cfg, st, base + 25 * 3600)     # +25h 防抖期外 → 推
        r3out = len(captured) == 1
        print("  [3] PROBABLY→NO→PROBABLY 防抖内不推/外推:", "PASS" if (r3in and r3out) else "FAIL")
        ok = ok and r3in and r3out
    finally:
        for n, f in orig.items():
            globals()[n] = f
    print("TIBOGPT SELFTEST", "OK ✅" if ok else "FAIL ❌")
    return ok

def selftest(cfg):
    sample = ('<article class="tweet"><a href="/thsottiaux/status/123456">link</a>'
              '<div>We will credit every Codex user with a BANKED reset today!</div></article>')
    t, link = parse_xcancel(sample)
    print("解析样本推文:", (t or "")[:120])
    print("解析出链接  :", link)
    print("关键词命中  :", keyword_hit(t or "", cfg))
    print("tibogpt 解析:", parse_tibogpt("...CURRENT ANSWER PROBABLY..."))
    print("挑战页检测  :", is_challenge("<title>Verifying your browser</title>"))
    selftest_tibogpt()
    print("SELFTEST OK ✅")

# ================= 入口 =================
def main():
    # 防 Windows 中文控制台(GBK) 打印 emoji 崩溃：重配置 stdout/stderr 为 utf-8（errors=replace 兜底）。
    # 否则 print("SELFTEST OK ✅") 等会抛 UnicodeEncodeError: 'gbk' codec can't encode，退出码 1，
    # 导致本机计划任务静默失败。需 Python 3.7+（reconfigure 自 3.7 起）；本机建议 UTF-8 控制台。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Codex 额度刷新监控 (Phase A)")
    ap.add_argument("--once", action="store_true", help="单次巡检")
    ap.add_argument("--serve", action="store_true", help="内部循环（自带 sleep）")
    ap.add_argument("--replay", action="store_true", help="回放今日事件验证")
    ap.add_argument("--test-push", action="store_true", help="测试推送")
    ap.add_argument("--selftest", action="store_true", help="离线单测")
    ap.add_argument("--test-tibogpt", action="store_true", help="tibogpt 模式翻转判重单测")
    ap.add_argument("--confirm", action="store_true", help="主公确认->补发✅")
    args = ap.parse_args()
    cfg = load_config(CONFIG_PATH)

    if args.selftest:
        return selftest(cfg)
    if args.test_tibogpt:
        return selftest_tibogpt()
    if args.test_push:
        return push(cfg, "✅ 监控自检通过",
                    "Codex 额度监控脚本已就位。\n若你收到这条邮件，说明 SMTP 邮箱推送链路正常。",
                    kind="test")
    if args.replay:
        return replay(cfg)
    if args.confirm:
        st = load_state()
        ev = st.get("event")
        if ev:
            return push(cfg, "✅ 已确认 Codex 额度刷新",
                        f"主公确认。\n关键词: {ev['kw']}\n链接: {ev.get('link') or '-'}\n"
                        f"时间: {fmt(ev['t'])}", kind="confirm")
        print("无待确认事件")
        return
    if args.once:
        return cycle(cfg)
    if args.serve:
        print(f"[serve] 每 {cfg['check_interval_min']} 分钟一轮，Ctrl+C 退出")
        while True:
            try:
                cycle(cfg)
            except Exception as e:
                print(f"[cycle-error] {e}")
            time.sleep(cfg["check_interval_min"] * 60)
        return
    cycle(cfg)   # 默认单次

if __name__ == "__main__":
    main()
