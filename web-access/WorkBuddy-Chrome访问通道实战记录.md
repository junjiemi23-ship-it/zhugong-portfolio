# WorkBuddy 接入日常 Chrome 访问通道实战记录

> 主题：让 AI 直接复用日常 Chrome（登录态）查资料，并解决 Google 风控拦截
> 场景：Windows 11 / Chrome 151 / WorkBuddy（CDP 直连）
> 整理：2026-08-19

---

## 📌 作品简介（30 秒看懂）

**解决什么问题**：AI 助手要像真人一样上网查资料时，会遇到三个连环问题——① Chrome 调试通道打不开；② Google 弹"系统检测到异常流量"反爬验证页；③ 代理客户端（nano）不支持分流，国内站也走海外数据中心 IP 被风控。

**怎么意识到这个问题**：日常使用中 Chrome 查询通道突然失效，排查发现不是通道本身坏了，而是抓取 Google 验证页里的出口 IP，查到是 Zenlayer 美国数据中心 IP——整机流量被代理客户端 TUN 全局接管，才触发 Google 风控。

**怎么解决**：① 用 Clash Verge Rev 规则分流（国内直连 + 海外走代理）；② 节点选 TCP（vless）而非 TUIC/UDP（本机网络环境下实测 UDP 链路握手失败导致 outbound 全断）；③ 登录态复用走 Chrome 官方 `chrome://inspect` 开关，天然复用登录态（差异点，代价是重启后需重新授权）。

**最终效果**：Google 200 OK / 0.4s 秒开，国内站直连无风控，Chrome 日常查询通道恢复。

---

## 一、背景与目标

日常使用中，AI 助手需要像真人一样访问网页查资料（B站 / 抖音 / 知乎 / Google 等）。核心诉求有三点：

1. **复用日常 Chrome 登录态**——B站、知乎等站点的账号状态直接可用，不用每次重登
2. **国内站直连、海外站走代理**——两者并存，互不干扰
3. **不被 Google 等站点风控拦截**——数据中心 IP + 自动化特征会触发反爬验证页


---

## 二、问题诊断：三层连环坑

### 坑 1：Chrome 调试通道"打不开"
- 现象：日常 Chrome 查询通道异常，提示无法连接
- 诊断：通道本身正常（CDP 代理 connected、Chrome 调试端口监听、实测能开页读标题）——问题不在通道，在**流量出口**

### 坑 2：Google 弹"系统检测到异常流量"反爬验证页
- 提取验证页里的出口 IP 查归属：**Zenlayer 美国洛杉矶数据中心 IP**（ASN 类型 Hosting）
- 根因：代理客户端（nano）以 **TUN 模式全局接管**整机流量，所有应用（含 Chrome、curl）出口都是海外数据中心 IP
- Google 对数据中心 IP 段风控最严 → 弹验证页拦截

### 坑 3：代理客户端不支持分流
- 实测 nano 路由模式只有「全局 / 自动」两档，无「规则模式 / 绕过中国大陆」
- 「自动模式」基于翻墙目标识别，**不区分国内外 GeoIP** → 国内站也走代理
- 配置文件仅含 proxyMode=tun + token，无路由字段；无 HTTP 控制 API；无 CLI → **无法 hack，只能换客户端**

---

## 三、解决方案：两步走

### 第一步：Clash Verge Rev 规则分流（解决风控根因）

换用支持**规则模式**的客户端（Clash Verge Rev，开源免费）：

| 配置项 | 值 | 效果 |
|---|---|---|
| 模式 | 规则（Rule） | 国内域名直连 + 海外域名走代理 |
| 订阅 | 机场订阅链接导入 | 自动拉取节点列表 |
| 节点 | **TCP 协议（vless）** | 见下方踩坑 |
| 系统代理 / TUN | 开启 | 接管整机流量 |

**验证效果**：
- 国内域名（api.ipify.org）→ 出口真实国内 IP（上海联通）
- 海外域名（Google）→ 经代理出口，200 OK / 0.4s，**无验证页**

### 第二步：chrome://inspect 官方开关（解决登录态复用）

Chrome 136+ 安全变更：`--remote-debugging-port` 对默认用户数据目录不再生效，必须配非标准 `--user-data-dir`。但独立目录会丢登录态（DPAPI 加密绑定路径，复制 profile 会解密失败）。

**正确做法**：用官方开关 `chrome://inspect/#remote-debugging` → 勾选「启用远程调试」→ Chrome 以默认档案启动调试服务，**登录态自动复用**。首次连接弹确认点「允许」。

> 注意：开关在**完全退出 Chrome 或重启电脑后会复位**，需重新勾选一次。可在 `chrome://settings/system` 开启「关闭后继续运行后台应用」减少复位次数。

---

## 四、关键踩坑记录（实战验证）

1. **TUIC/hysteria2（UDP 协议）节点：本机网络环境下延迟正常但 outbound 全断**
   - 自动选择挑中「猎户座-E 113ms」（TUIC），Google/YouTube/GitHub 全部 12s 超时（本机实测）
   - 根因：本机网络环境下 UDP/QUIC 链路握手失败；Clash 对 UDP 协议的延迟测试**不代表真实出口可用**（不同网络环境表现可能不同）
   - 解决：手动切到 TCP 节点（vless）→ 立即通
2. **Clash 主窗口空白**：WebView2 渲染缓存损坏 → 删除 `%LOCALAPPDATA%\io.github.clash-verge-rev.clash-verge-rev\EBWebView` 缓存重启即可
3. **系统 WebView2 "已安装"但 Clash 不工作**：实际是渲染缓存问题，不是缺 WebView2（系统版本 151 正常）
4. **订阅链接 = 账号凭证**：任何时候不复制到聊天/文件/群

---

## 五、与其他方案的对比

| 方案 | 登录态复用 | 国内直连 | 风控规避 | 复杂度 |
|---|---|---|---|---|
| **本方案**（chrome://inspect 官方开关 + Clash 规则分流） | ✅ 天然复用 | ✅ | ✅ 国内直连免风控 | 低（一次性配置） |
| 社区方案 A（`--user-data-dir` 复制 profile + CDP） | ❌ DPAPI 绑定路径，复制后解密失败 | — | — | 中（需手动重登） |
| 社区方案 B（独立调试实例 + Playwright） | ❌ 需单独登录 | — | — | 中高 |
| 全局 TUN 代理（nano 等） | ✅ | ❌ 全走代理 | ❌ 数据中心 IP 被风控 | 低但不可用 |

**本方案差异点**：官方开关天然复用登录态（绕开 DPAPI 绑定路径问题）+ 规则分流根治风控（国内直连 + 海外代理）。

**本方案代价**：Chrome 完全退出或重启电脑后，「启用远程调试」开关会复位，需重新勾选一次并点「允许」授权（可在 `chrome://settings/system` 开启「关闭后继续运行后台应用」减少复位频率）。

> 对比信息来源于已检索到的社区实战案例（CSDN devpress、kuazhi 等，信息截至 2026-08），转述观点并注明出处，供参考。

---

## 六、验证命令

```bash
# 国内域名应直连（显示国内 IP）
curl -s https://api.ipify.org

# 海外域名经代理（Clash 默认混合端口 7897）
curl -sx http://127.0.0.1:7897 https://api.ipify.org

# Google 连通性（Windows 写法；Git Bash 用户可写 -o /dev/null）
curl -sx http://127.0.0.1:7897 -o NUL -w "%{http_code} %{time_total}s" https://www.google.com
# 期望：200 1s内
```

---

## 七、结论

- **AI 接入日常 Chrome 复用登录态**：用 `chrome://inspect` 官方开关，规避 Chrome 136+ 限制与 DPAPI 加密问题
- **不被风控**：Clash 规则分流，国内站直连真实 IP、海外站走代理；选 TCP（vless）节点，避开 UDP 被干扰的坑
- **长期稳定**：节点固定用 TCP 类；Google 验证页根治需住宅/家宽出口节点；重启电脑后 Chrome 调试开关需重新勾选一次

*本文档由 WorkBuddy 整理，供 Codex 审阅（2026-08-19）*
