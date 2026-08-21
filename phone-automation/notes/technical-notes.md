# phone-automation · 技术要点笔记

> 本文记录 ADB 手机操控能力验证过程中的技术细节，供复用与扩展。全部为方法论层面内容，不含具体业务目标。

## 1. 连接管理

### 1.1 USB 有线（最稳定）
```bash
adb devices          # 查看已连接设备（应显示 device 状态）
adb -s <SERIAL> shell echo OK   # 指定设备执行命令
```

### 1.2 无线调试（首次配对）
```bash
# 手机开启「无线调试」→ 记下配对码 + IP:端口（配对端口）
adb pair <IP>:<配对端口> <配对码>    # 配对
adb connect <IP>:<连接端口>          # 连接（配对后自动建立 mDNS 通道）
```
实测注意：
- 无线调试在**热点切换 / 锁屏休眠 / WiFi 切换**时易掉线；
- 关键操作前必须复查 `adb devices`；
- USB 有线无此问题，为推荐方式。

## 2. 设备信息与状态读取

```bash
adb shell wm size                     # 分辨率（坐标换算基准，必须确认）
adb shell getprop ro.product.model    # 机型
adb shell "dumpsys window | grep mCurrentFocus"   # 当前前台窗口（验证页面状态）
adb shell "dumpsys activity top | grep ACTIVITY"  # 前台 Activity
adb shell "date +%s%3N"               # 设备毫秒时间戳（13 位数字）
```

**页面状态验证纪律**：任何导航/点击后，先 `dumpsys window` 确认前台正确再继续，不要假定操作成功。

## 3. 界面元素定位（三种方法对比）

| 方法 | 适用 | 局限 |
|---|---|---|
| `uiautomator dump` | 原生 View 页面 | WebView 只暴露根节点；页面有动画时可能失败 |
| 颜色检测（HSV 阈值） | 单色按钮、浅色背景 | 深色模式 / 大面积同色背景误判 |
| **人机协作识图（标注法）** | 一切可见元素 | 需人工标注一次（一次性成本） |

### 3.1 uiautomator dump（原生页面）
```bash
adb shell uiautomator dump --compressed /sdcard/ui.xml
adb pull /sdcard/ui.xml ./ui.xml
# 解析 XML 中 text/bounds 属性，取目标元素 bounds 中心
```

### 3.2 人机协作识图（标注法，原创）
见根目录 README「主公标注法」一节。要点：
- 截原始图 → 用户标注 → `cv2.absdiff` 差异 → 连通区域中心；
- 阈值经验：二值化 25，连通区域面积 > 800，宽 > 40px 高 > 25px 视为有效标记；
- 一次标注后，页面布局不变即可复用坐标。

## 4. 毫秒级触发（竞速场景）

### 4.1 问题
每次 `adb shell input tap` 都是 PC→手机一次往返（约 95ms）+ 设备端处理（50-100ms），逐条调用累计延迟大。

### 4.2 解法：设备端单命令等待+连点
```python
# Python 侧构造一条 shell 命令：
# 1) 设备端 while 循环等待到目标毫秒（date +%s%3N 数值比较）
# 2) for 循环连续 input tap N 次
body = f"while [ $(date +%s%3N) -lt {target_dev} ]; do :; done; " \
       f"for i in {' '.join(map(str, range(1, 21)))}; do input tap {x} {y}; done; echo DONE"
subprocess.run([ADB, "-s", SERIAL, "shell", body], timeout=90)
```
实测 20 次连点约 543ms 完成（每次 ~27ms），远优于逐条调用。

### 4.3 时间校准
```python
# 设备-电脑时间差（3 次取中位数，抗抖动）
vals = []
for _ in range(3):
    dev = int(adb("shell", "date", "+%s%3N").strip())
    vals.append(dev - int(time.time() * 1000))
    time.sleep(0.05)
vals.sort()
offset = vals[len(vals) // 2]
target_dev = target_pc + offset - ADVANCE_MS   # 提前量可调
```
注意：若存在"活动服务端时间"，应优先向服务端校准（±100ms 级），本地时钟仅作兜底。

## 5. 状态多帧监控

关键时间点连续截图，观察界面状态流转：
```python
time.sleep(0.5); shot("frame_0.5s.png")
time.sleep(0.5); shot("frame_1s.png")
time.sleep(1.0); shot("frame_2s.png")
```
用途：区分"前端 UI 响应时刻"与"后端处理完成时刻"；判断操作是否真正生效。

## 6. 关键认知

- **前端反应 ≠ 后端成功**：按钮变色/弹窗是本地 UI 行为，服务端是否接受操作需看最终状态变化；
- **成功判定标准**：以目标状态的**最终变化**为准（如按钮变为"已完成/已消耗"），不依据中间 UI 反馈；
- **降级策略**：坐标定位失败 2 次即停止自动尝试，请求人工协助或换方案，不无限重试。

## 7. 复用清单

- [x] `locate_button.py`：人机协作识图定位脚本（见仓库根目录说明）
- [x] 设备端毫秒触发模板（见本文第 4 节）
- [x] 页面状态验证纪律（`dumpsys window` 复查）
