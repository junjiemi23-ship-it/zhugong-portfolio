# aihot-welfare：把 AIHOT 从"新闻监控"改成"福利雷达"

作者：Junjie Mi（本目录补丁内容 © 2026 Junjie Mi，MIT 协议）

基于 MIT 开源项目 AIHOT（https://github.com/KKKKhazix/AIHOT）的一套定制补丁：
让它的精选评分认识"福利/促销"，并给出一套零成本部署接线。

## 原项目是什么

AIHOT：采集 → 判重 → 模型双次打分 → 中文摘要 → 事件聚簇 → 日报/周报，带 admin 后台（预算熔断、token 用量都看得见）。

## 我改了什么

1. **新增福利评分维度 `promo_welfare`**（详见 `welfare-scoring-patch.md` 改动 1）
   - 内容类型：免费额度、折扣、赠送、试用延长、邀请奖励等读者能直接领取的优惠
   - 权重 `sig 2 / nov 1 / cred 3 / reson 2 / act 2`：证据强度优先——没官方来源、没明确领取方式/门槛/截止时间的"福利"，`cred ≤ 3` 且总分 ≤ 40，直接压住；过期、名额已满、多数人地区不符的，`act ≤ 3`
   - 真实可领的福利按真实价值正常打分，不因"只是促销"被压低
2. **零成本模型接线**（改动 2 + `.env.example`）
   - 打分、摘要走 OpenAI 兼容的 API key 接入，免费额度完全够用
   - embeddings、X 信源、公众号等付费项留空，照样跑
3. **低配部署记录**（改动 3）
   - 1G 内存 VPS + swap，Docker 一把梭；首次 backfill 调用量大，先开 3–5 个信源试跑，admin 后台预算熔断先设好

## 怎么用

1. 克隆原项目：`git clone https://github.com/KKKKhazix/AIHOT`
2. 按 `welfare-scoring-patch.md` 改 `industry/prompts/selection-score.md`
3. 复制 `.env.example` 为 `.env`，填上你自己的 OpenAI 兼容 API key（只放在你自己服务器上，不要公开）
4. `docker compose up -d`

## 定位

AIHOT 只做上游粗筛和聚簇；终审是我的 AI 助手：福利优先判断 → 爆火潜力判断 → 官方来源核验，再按固定节奏推送。
一句话：AI 监控 AI，人只负责拍板。

## 文件

- `welfare-scoring-patch.md` — 三处改动的完整说明（评分 prompt / env 接线 / 部署注意）
- `.env.example` — OpenAI 兼容 API key 接线模板

## 协议与来源

- 本目录补丁内容 © 2026 Junjie Mi，MIT 协议（见仓库根目录 LICENSE）
- 基于 MIT 开源项目 AIHOT（https://github.com/KKKKhazix/AIHOT）
