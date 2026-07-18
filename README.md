# NUAA 选课工具 V1.3 / NUAA Course Grabber V1.3

> 🏗️ 基于 [NUAA-Snatcher](https://github.com/dboycht/NUAA-Snatcher) 重构 | 作者 [dboycht](https://github.com/dboycht)
> Based on [NUAA-Snatcher](https://github.com/dboycht/NUAA-Snatcher) | Author [dboycht](https://github.com/dboycht)

南京航空航天大学教务系统自动选课桌面应用。
A desktop app for automating course registration on the NUAA educational administration system.

## 语言 / Language

应用支持**中文 / English** 切换。点击状态栏右下角的 `中` / `EN` 按钮即可切换。
The app supports **Chinese / English** switching. Click the `中` / `EN` button at the bottom-right of the status bar.

语言偏好会自动保存，下次启动时自动加载。
Language preference is saved automatically and loaded on next launch.

---

## 功能 / Features

- **浏览器弹窗登录** — 一键打开 Chromium 窗口，完成统一认证后自动提取 Cookie
- **Browser popup login** — Opens a Chromium window, auto-extracts cookie after SSO login
- **Cookie 持久化** — 加密存储到本地，下次启动自动加载验证
- **Cookie persistence** — Encrypted local storage with auto-validation on restart
- **图形化选课** — 表格展示课程列表，支持搜索过滤、全选/反选
- **Graphical course selection** — Table view with search/filter, select all/invert
- **定时抢课** — 预发射补偿 + 多 URL 容错 + 限速退避
- **Timed grab** — Pre-fire compensation + multi-URL fallback + rate-limit backoff
- **实时日志** — 彩色分类显示提交结果，自动统计
- **Real-time log** — Color-coded results with auto statistics
- **一键安装依赖** — 缺失 PySide6/Playwright 时 GUI 内一键安装
- **One-click dependency install** — Install missing packages from within the app

---

## 安装 / Installation

```bash
pip install pyside6 playwright requests
playwright install chromium
```

> 如果启动时检测到 PySide6 未安装，程序会自动弹出安装窗口。
> If PySide6 is not detected at startup, the app will auto-launch an install window.

## 启动 / Launch

```bash
python Xuanke_v2.py
```

---

## 使用流程 / Usage

### 1. 登录认证 / Authentication

- 点击 **「打开浏览器登录 / Open Browser Login」**，弹出 Chromium 浏览器窗口
- 在浏览器中完成统一身份认证登录（含验证码，如有）
- 登录成功后程序自动检测并提取 Cookie
- 如果自动检测没反应，点击 **「强制提取 / Extract Now」** 手动触发
- Cookie 会在界面中明文显示，方便确认
- 也可以通过 **「手动粘贴 Cookie」** 兜底（从浏览器 DevTools 复制）

---

- Click **Open Browser Login**, a Chromium window will pop up
- Complete the SSO login in the browser (including CAPTCHA if present)
- The app auto-detects login success and extracts cookies
- If auto-detection doesn't trigger, click **Extract Cookie Now** to force extraction
- The cookie is displayed in plain text for verification
- You can also use **Manual Cookie Paste** as a fallback

### 2. 选择课程 / Course Selection

- 输入选课档案 ID（网址末尾的数字，如 `4665`）
- 点击 **「获取课程列表 / Fetch Courses」**
- 表格中勾选要抢的课程，支持搜索过滤
- 点击 **「确认选择，进入抢课 / Confirm & Go to Grab」**

---

- Enter the Profile ID (the number at the end of the URL, e.g. `4665`)
- Click **Fetch Courses**
- Check the courses you want, use the search bar to filter
- Click **Confirm & Go to Grab**

### 3. 开始抢课 / Start Grab

- 设置放闸时间（精确到秒）
- 调整策略参数：
  - **预发射偏移 / Pre-fire Offset**：提前多少毫秒发送请求（建议 200ms）
  - **提交间隔 / Submit Interval**：两次提交之间的最小间隔（建议 ≥ 800ms）
  - **每课最大尝试 / Max Attempts**：单门课的最大提交次数
- 点击 **「开始抢课 / Start Grab」** 进入倒计时
- 或点击 **「立即提交 / Submit Now」** 跳过定时直接抢

---

- Set the target time (precise to seconds)
- Adjust strategy parameters:
  - **Pre-fire Offset**: How many ms early to send requests (recommended: 200ms)
  - **Submit Interval**: Minimum gap between submissions (recommended: ≥ 800ms)
  - **Max Attempts/Course**: Max tries per course
- Click **Start Grab** to begin countdown
- Or click **Submit Now** to skip the timer

### 4. 查看结果 / Results

- 「日志 / Log」Tab 实时显示每条提交结果
- 🟢 绿色/Green = 成功/Success
- 🔴 红色/Red = 失败/Failure
- 🟡 黄色/Yellow = 限速/Rate-limited
- ⚪ 灰色/Gray = 信息/Info
- 支持导出日志到文本文件 / Export log to text file

---

## 反爬策略 / Anti-Detection

| 检测点 / Detection Point | 措施 / Countermeasure |
|--------------------------|----------------------|
| `navigator.webdriver` | JS 注入隐藏 / JS injection to hide |
| `window.chrome` | 伪造 runtime 对象 / Fake runtime object |
| `navigator.plugins` | 注入非空数组 / Inject non-empty array |
| Blink automation flag | `--disable-blink-features=AutomationControlled` |
| Multi-tab redirects | 遍历 `context.pages` 监控所有标签页 |

---

## 技术架构 / Architecture

```
Xuanke_v2.py (~1900 lines)
├── I18n                    中英文切换 / Language switching (QObject + Signal)
├── CookieManager           持久化存储 / Persistent storage (QSettings + base64)
├── LoginWorker             Playwright 浏览器登录 / Browser login (QThread)
├── FetchCoursesWorker      课程列表拉取 / Course list fetch (QThread)
├── GrabWorker              抢课引擎 / Grab engine (QThread + pre-fire)
├── InstallWorker           pip 安装 / pip install (QThread)
├── LoginTab                登录界面 / Login UI
├── CourseTab               选课界面 / Course selection UI
├── GrabTab                 抢课控制台 / Grab console
├── LogTab                  彩色日志 + 统计 / Colored log + stats
└── XuankeApp               主窗口 / Main window
```

---

## 配置存储 / Configuration

所有设置保存在 `%APPDATA%/NuuaXuanke/XuankeV2.ini`：
All settings stored in `%APPDATA%/NuuaXuanke/XuankeV2.ini`:

- Cookie（base64 编码 / base64 encoded）
- 语言偏好 / Language preference
- 上次使用的 profile ID / Last used profile ID
- 窗口位置和大小 / Window geometry

---

## 注意事项 / Notes

- 首次使用需安装 Playwright 的 Chromium 浏览器（约 150MB）
- First run requires Playwright Chromium download (~150MB)
- Cookie 有效期取决于教务系统配置，过期后需重新登录
- Cookie validity depends on the server; re-login when expired
- 提交间隔不要设置过低，否则会触发服务器限速（建议 ≥ 800ms）
- Don't set submit interval too low (recommended: ≥ 800ms)
- 预发射偏移根据网络情况调整（校园网建议 100-300ms）
- Adjust pre-fire offset based on network (campus network: 100-300ms)
- 登录页面如有验证码，需手动输入
- Manual CAPTCHA entry may be required during login

## License

仅供学习交流使用。For educational use only.

---

## 更新日志 / Changelog

### V1.3 — PySide6 桌面版重构
- 全新 PySide6 深色主题界面
- 浏览器弹窗登录 + Cookie 自动提取 + 持久化
- 图形化课程选择（表格 + 搜索 + 全选/反选）
- 预发射定时抢课 + 多 URL 容错 + 限速退避
- 中/英文界面切换
- 一键安装缺失依赖
- 彩色实时日志 + 提交统计

### V1.2b — 发行版
- 更新补全 README 文件
- 修复了已知问题

### V1.2a — 测试版
- 更新补全 README 文件
- 修复了安装协议书乱码的 bug
- 更改了软件内仓库地址
- 修复了软件内版本号错误的 bug

### V1.1 — 发行版
- 更新打包并编译程序

### V1.0 — 正式版
- 更新了 UI 以及搜寻教师的功能
- 修复了 Alpha 0.1 搜寻功能无法正常运行的 bug

### Alpha 0.1 — 测试版
- 初始版本，基础选课功能
