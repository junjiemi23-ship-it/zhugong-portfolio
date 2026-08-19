# Clash Verge Rev 规则分流配置指南（Windows）

> 场景：需要「国内站直连 + 海外站走代理」共存（日常 Chrome 查资料 + Google/Codex 等海外服务）
> 适用：Windows 11 / Chrome 151，Clash Verge Rev v2.5.2
> 整理：WorkBuddy（2026-08-19，基于本机完整实战）

---

## 📌 作品简介（30 秒看懂）

**解决什么问题**：代理客户端（nano 等）以 TUN 模式全局接管整机流量，所有网站（含国内 B站/抖音/知乎）都走海外数据中心 IP，导致 Google 判定"数据中心 IP + 自动化"弹反爬验证页，Chrome 日常查询通道失效。

**怎么意识到这个问题**：Chrome 通道打不开，抓取 Google 验证页里的出口 IP 查到是 Zenlayer 美国数据中心 IP，确认整机流量被全局 TUN 接管。

**怎么解决**：换用 Clash Verge Rev（规则模式）→ 国内域名直连真实 IP、海外域名走代理 → 节点选 TCP（vless）避坑（TUIC/UDP 节点在本机网络环境下延迟正常但 outbound 全断）→ 系统代理/TUN 开启。最终国内站直连无风控、Google 200 OK 0.4s 秒开。

---

## 一、为什么需要规则分流

**问题**：部分代理客户端（如 nano）以 TUN 模式全局接管整机流量，所有流量（含国内站）都走海外数据中心 IP → Google 判定"数据中心 IP + 自动化" → 弹「系统检测到异常流量」反爬验证页。

**方案**：换用支持**规则模式**的客户端（Clash Verge Rev / mihomo 系），实现：
- 国内域名 → 直连真实国内 IP（快、无风控）
- 海外域名 → 走代理节点（Google/ChatGPT/GitHub 等）

---

## 二、安装 Clash Verge Rev

1. GitHub 搜 `clash-verge-rev` → Releases → 下载 `Clash.Verge_<版本>_x64-setup.exe`（Windows x64）
2. 安装到 `C:\Program Files\Clash Verge`
3. **若主窗口空白**（WebView2 渲染失败）：
   - 退出程序 → 删除 `%LOCALAPPDATA%\io.github.clash-verge-rev.clash-verge-rev\EBWebView` 缓存目录 → 重启
   - 或下载 `_fixed_webview2` 版安装包（自带 WebView2）
4. 启动后托盘图标 → 呼出主窗口

---

## 三、导入订阅

1. 登录你的机场面板（如 NanoCloud 等通用代理服务商面板），找到「订阅链接」→ 点「复制」
   - ⚠️ 订阅链接 = 账号凭证，**不要发到聊天/群/任何 AI**
2. Clash Verge → 左侧「订阅 / Profiles」→「新建 / 导入」→ 粘贴链接 → 保存
3. 自动拉取节点列表（状态栏显示节点数、流量、到期时间）

---

## 四、配置分流（关键步骤）

1. **先退出旧的代理客户端**（nano 等）——避免两个 TUN 抢占路由冲突，导致整机断网
2. 左侧「代理」页 → 代理组展开 → **手动选择 TCP 协议节点**（vless / vmess / ss）：
   - ⚠️ **TUIC / hysteria2（UDP/QUIC 协议）节点在本机网络环境下实测：延迟测试正常（如 113ms）但 outbound 全部超时**（Google/YouTube/GitHub 12s 超时）——不同网络环境表现可能不同，建议优先选 TCP 节点
3. 左侧「首页」→ 网络设置：
   - 模式选「**规则 / Rule**」（默认：国内直连 + 海外代理，无需自写规则）
   - 开启「**系统代理 / System Proxy**」或「**TUN 虚拟网卡模式**」
   - 切换瞬间会断网 5-30 秒，属正常
4. 验证：浏览器无痕窗口访问 `https://www.google.com` → 正常打开、无验证页 = 成功

---

## 五、验证命令

```bash
# 1. 国内域名应直连（显示国内 IP）
curl -s https://api.ipify.org
# 期望：国内（如 114.x 北京联通）

# 2. 海外域名经代理（Clash 默认混合端口 7897）
curl -sx http://127.0.0.1:7897 https://api.ipify.org
# 期望：海外节点 IP

# 3. Google 连通性（Windows 写法；Git Bash 用户可写 -o /dev/null）
curl -sx http://127.0.0.1:7897 -o NUL -w "%{http_code} %{time_total}s" https://www.google.com
# 期望：200 1s内
```

---

## 六、日常使用

| 事项 | 操作 |
|---|---|
| 翻墙/查海外 | 保持 Clash 系统代理开启，Chrome 正常用 |
| 充值/续费 | 机场面板（浏览器打开官网）→ 购买订阅，续费后 Clash 自动同步流量 |
| 节点选择 | 固定用 TCP（vless/vmess）节点；TUIC/hysteria2 留给 UDP 友好环境 |
| ⚠️ 节点可用性 | **延迟正常 ≠ 可用**：切换节点后先跑一遍第五节验证命令做连通性检查，再正式使用 |
| Google 反爬根治 | 选「住宅 / 家宽 / 原生 IP」出口节点（数据中心 IP 下验证页会反复出现） |
| 重启电脑后 | Clash 开启「开机自启」；Chrome 的「启用远程调试」开关需重新勾选一次 |

---

## 七、踩坑记录（本次实战）

1. **nano 客户端不支持规则分流**（仅全局/自动两档，自动也不区分国内外 GeoIP）→ 换 Clash 系
2. **TUIC 节点延迟正常但 outbound 全断（本机网络环境实测）** → UDP 被干扰，换 TCP 节点立即通
3. **Clash 主窗口空白** → 清 EBWebView 缓存目录重启即可
4. **系统 WebView2 "已安装"但 Clash 不工作** → 实际是渲染缓存问题，不是缺 WebView2
5. **订阅链接 ≈ 密码** → 任何时候不复制到聊天/文件

---

*本指南由 WorkBuddy 整理，经 Codex 审核（2026-08-19）*
