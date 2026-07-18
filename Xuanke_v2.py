#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NUAA 选课工具 V1.3.2 — PySide6 桌面版
基于 NUAA-Snatcher (github.com/dboycht/NUAA-Snatcher) 重构
作者: dboycht
===================================
功能：
  - 浏览器弹窗登录 → 自动提取 Cookie → 持久化存储
  - 图形化课程列表（表格 + 搜索过滤 + 全选/反选）
  - 定时抢课（预发射补偿 + 多 URL 容错 + 限速退避）
  - 彩色实时日志 + 提交统计
  - 所有设置自动记忆

依赖：pip install pyside6 playwright requests
      playwright install chromium
"""

import sys
import re
import time
import subprocess
import base64
import datetime
import gzip
import zlib

import requests

# ── 依赖自检与一键安装 ──────────────────────────────────

def _install_deps_via_tkinter(packages: list, title: str = "安装缺失依赖"):
    """
    使用 tkinter（Python 标准库，始终可用）弹出安装窗口。
    当 PySide6 未安装时，这是唯一的 GUI 回退方案。
    packages: [(描述, ["pip", "install", "xxx"]), ...]
    """
    import tkinter as tk
    from tkinter import ttk
    from tkinter import messagebox

    root = tk.Tk()
    root.title(title)
    root.geometry("650x440")
    root.resizable(True, True)
    root.configure(bg="#f5f5f5")

    # -- 标题 --
    header = tk.Label(
        root, bg="#f5f5f5",
        text=f"检测到以下依赖未安装，点击「一键安装」继续：",
        font=("Microsoft YaHei", 11), wraplength=600, justify="left",
    )
    header.pack(pady=(14, 2), padx=20, anchor="w")

    # -- 包列表 --
    list_frame = tk.Frame(root, bg="#f5f5f5")
    list_frame.pack(fill="x", padx=24, pady=4)
    for pkg_desc, pkg_cmd in packages:
        lbl = tk.Label(list_frame, bg="#f5f5f5", anchor="w",
                       text=f"  📦 {pkg_desc}    →    {' '.join(pkg_cmd)}",
                       font=("Consolas", 10))
        lbl.pack(anchor="w")

    # -- 输出区域 --
    output = tk.Text(root, height=14, bg="#1a1a2e", fg="#bdc3c7",
                     insertbackground="white", font=("Consolas", 9),
                     relief="sunken", borderwidth=2)
    output.pack(fill="both", expand=True, padx=20, pady=(10, 4))

    # -- 按钮 --
    btn_frame = tk.Frame(root, bg="#f5f5f5")
    btn_frame.pack(pady=(0, 14))

    exit_btn = ttk.Button(btn_frame, text="退出", command=lambda: (root.destroy(), sys.exit(0)))
    exit_btn.pack(side="right", padx=6)

    def _run_install():
        output.delete("1.0", tk.END)
        output.insert(tk.END, ">>> 开始安装依赖...\n")
        install_btn.config(state="disabled")
        exit_btn.config(state="disabled")
        root.update()

        python_exe = sys.executable
        all_ok = True
        for pkg_desc, pkg_cmd in packages:
            full_cmd = [python_exe, "-m"] + pkg_cmd
            output.insert(tk.END, f">>> {' '.join(full_cmd)}\n")
            output.see(tk.END); root.update()
            try:
                proc = subprocess.Popen(
                    full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in proc.stdout:
                    output.insert(tk.END, line)
                    output.see(tk.END); root.update()
                proc.wait()
                if proc.returncode != 0:
                    output.insert(tk.END, f"\n!!! {pkg_desc} 安装失败 (exit={proc.returncode})\n")
                    all_ok = False
                    break
            except Exception as e:
                output.insert(tk.END, f"\n!!! 异常: {e}\n")
                all_ok = False
                break

        if all_ok:
            output.insert(tk.END, "\n" + "=" * 50 + "\n")
            output.insert(tk.END, " 全部依赖安装完成！请重新启动程序。\n")
            output.insert(tk.END, "=" * 50 + "\n")
            output.see(tk.END)
            messagebox.showinfo("安装完成", "所有依赖已安装成功！\n\n请关闭此窗口后重新启动程序。")
        else:
            output.insert(tk.END, "\n安装过程中出现问题，请检查上方日志。\n")
            output.see(tk.END)
        exit_btn.config(state="normal", text="关闭")
        install_btn.config(state="disabled")

    install_btn = ttk.Button(btn_frame, text="⚡ 一键安装", command=_run_install)
    install_btn.pack(side="left", padx=6)

    root.mainloop()


# ── PySide6 ──────────────────────────────────────────────
try:
    from PySide6.QtCore import (
        Qt, QThread, Signal, QSettings, QDateTime, QObject
    )
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QTabWidget,
        QVBoxLayout, QHBoxLayout, QFormLayout,
        QLabel, QPushButton, QLineEdit, QTableWidget,
        QTableWidgetItem, QHeaderView, QSpinBox,
        QDateTimeEdit, QProgressBar, QGroupBox, QTextBrowser,
        QStatusBar, QMessageBox, QFrame, QFileDialog
    )
    from PySide6.QtGui import (
        QFont
    )
except ImportError:
    _install_deps_via_tkinter(
        [("PySide6 (Qt GUI 框架)", ["pip", "install", "pyside6"])],
        title="NUAA 选课工具 — 安装 PySide6",
    )
    # tkinter 弹窗结束后必然退出，不会走到这里
    sys.exit(1)

# ── Playwright（可选，仅登录时使用）──────────────────────
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# ============================================================
# 常量和工具函数（从 Xuanke_v1.py 移植）
# ============================================================

BASE = "https://aao-eas.nuaa.edu.cn"
HOME_URL = f"{BASE}/eams/homeExt.action"
DEFAULT_TPL = f"{BASE}/eams/stdElectCourse!defaultPage.action?electionProfile.id={{pid}}"
REQUEST_TIMEOUT = 5
BACKOFF_SECONDS = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ID_PATTERNS = [
    re.compile(r"(?:\bprofileId\b|\belectionProfile\.id\b)\s*[:=]\s*['\"]?(\d+)"),
    re.compile(r"(?:\?|&)(?:profileId|electionProfile\.id)=(\d+)"),
]


def is_login_bounce(resp) -> bool:
    """是否被重定向/返回到统一认证页面"""
    try:
        url_l = resp.url.lower()
    except Exception:
        url_l = ""
    text = ""
    try:
        text = resp.text
    except Exception:
        pass
    return ("统一身份认证" in text) or ("authserver" in url_l)


def smart_read(resp):
    """尽最大可能把响应体解码成可读文本；返回 (text, used_encoding)"""
    raw = resp.content or b""

    def _maybe_decompress(b: bytes) -> bytes:
        if len(b) >= 2 and b[0] == 0x1F and b[1] == 0x8B:  # gzip magic
            try:
                return gzip.decompress(b)
            except Exception:
                return b
        if len(b) >= 2 and b[0] == 0x78 and b[1] in (0x01, 0x5E, 0x9C, 0xDA):  # zlib
            try:
                return zlib.decompress(b)
            except Exception:
                return b
        return b

    raw = _maybe_decompress(raw)

    for enc in [getattr(resp, "encoding", None), getattr(resp, "apparent_encoding", None),
                "utf-8", "gb18030", "gbk", "gb2312", "latin1"]:
        if not enc:
            continue
        try:
            return raw.decode(enc, errors="ignore"), enc
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore"), "utf-8"


def _extract_profile_ids(html: str):
    """从 HTML 中提取所有候选 profileId"""
    hits = []
    for pat in _ID_PATTERNS:
        hits += pat.findall(html)
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _make_eams_session(cookie_str: str, pid: str) -> requests.Session:
    """创建预热的 requests.Session（首页 + defaultPage）"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Cookie": cookie_str.strip(),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": BASE,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    try:
        s.get(HOME_URL, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except Exception:
        pass
    referer = DEFAULT_TPL.format(pid=pid)
    try:
        s.get(referer, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    except Exception:
        pass
    s.headers.update({
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    })
    return s


# ============================================================
# I18n — 国际化 / Internationalization
# ============================================================

class I18n(QObject):
    """中英文切换管理器。language_changed 信号触发所有组件刷新文本。"""
    language_changed = Signal(str)  # 参数: "zh" | "en"

    STRINGS = {
        # ── 通用 ──
        "app.title":          {"zh": "NUAA 选课工具 V2",           "en": "NUAA Course Grabber V2"},
        "status.ready":       {"zh": "就绪 | 请先在「登录」Tab 中完成认证",
                               "en": "Ready | Complete authentication in the Login tab"},
        "status.cookie_ok":   {"zh": "✅ Cookie 有效 | 可前往「选课」Tab 获取课程",
                               "en": "✅ Cookie valid | Go to Course tab to fetch courses"},
        "status.courses_sel": {"zh": "📌 已选择 {n} 门课程 | 档案 ID: {pid}",
                               "en": "📌 {n} course(s) selected | Profile ID: {pid}"},
        "status.grab_started":{"zh": "🚀 抢课引擎已启动...",        "en": "🚀 Grab engine started..."},
        "status.grab_stopped":{"zh": "⏹ 已停止抢课",               "en": "⏹ Grab stopped"},
        "status.grab_done":   {"zh": "🏁 抢课完成 | 查看「日志」Tab 了解详情",
                               "en": "🏁 Grab finished | Check Log tab for details"},

        # ── Tab 标签 ──
        "tab.login":    {"zh": "🔐 登录",   "en": "🔐 Login"},
        "tab.courses":  {"zh": "📚 选课",   "en": "📚 Courses"},
        "tab.grab":     {"zh": "🚀 抢课",   "en": "🚀 Grab"},
        "tab.log":      {"zh": "📋 日志",   "en": "📋 Log"},

        # ── LoginTab ──
        "login.title":           {"zh": "🔐 登录认证",              "en": "🔐 Authentication"},
        "login.subtitle":        {"zh": "请先完成统一身份认证，获取有效的登录 Cookie。",
                                   "en": "Please complete SSO authentication to obtain a valid Cookie."},
        "login.cookie_status":   {"zh": "Cookie 状态",              "en": "Cookie Status"},
        "login.cookie_none":     {"zh": "⚪ 尚未设置 Cookie",       "en": "⚪ No cookie set"},
        "login.cookie_valid":    {"zh": "✅ Cookie 已从本地加载，状态有效",
                                   "en": "✅ Cookie loaded from local storage, valid"},
        "login.cookie_expired":  {"zh": "⚠️ 本地 Cookie 已过期，请重新登录",
                                   "en": "⚠️ Local cookie expired, please re-login"},
        "login.cookie_saved":    {"zh": "✅ Cookie 已自动提取并保存",
                                   "en": "✅ Cookie extracted and saved"},
        "login.cookie_display":  {"zh": "🍪 当前 Cookie（获取后自动显示）",
                                   "en": "🍪 Current Cookie (auto-display after extraction)"},
        "login.cookie_placeholder":{"zh": "尚未获取 Cookie...",     "en": "No cookie yet..."},
        "login.browser_group":   {"zh": "🌐 浏览器登录（推荐）",    "en": "🌐 Browser Login (Recommended)"},
        "login.browser_desc":    {"zh": "Chromium 浏览器 + JS 注入隐藏 webdriver + 多标签页自动检测。登录后程序自动识别并提取 Cookie。",
                                   "en": "Chromium browser + JS injection to hide webdriver + multi-tab auto-detection. Cookie is auto-extracted after login."},
        "login.btn_browser":     {"zh": "🌐 打开浏览器登录",        "en": "🌐 Open Browser Login"},
        "login.btn_browser_retry":{"zh":"🌐 重试浏览器登录",        "en": "🌐 Retry Browser Login"},
        "login.btn_browser_waiting":{"zh":"⏳ 浏览器运行中，请登录（含验证码）...",
                                      "en": "⏳ Browser running, please login (incl. CAPTCHA)..."},
        "login.btn_force":       {"zh": "📥 我已登录完成，立即提取 Cookie！",
                                   "en": "📥 I've logged in — Extract Cookie Now!"},
        "login.btn_force_extracting":{"zh":"⏳ 正在提取...",        "en": "⏳ Extracting..."},
        "login.waiting_status":  {"zh": "⏳ 等待浏览器登录...",     "en": "⏳ Waiting for browser login..."},
        "login.manual_title":    {"zh": "📋 手动粘贴 Cookie（兜底方案）",
                                   "en": "📋 Manual Cookie Paste (Fallback)"},
        "login.manual_placeholder":{"zh": "从浏览器 DevTools → Network → Request Headers 复制整行 Cookie",
                                     "en": "Copy the full Cookie line from DevTools → Network → Request Headers"},
        "login.btn_apply":       {"zh": "应用",                     "en": "Apply"},
        "login.manual_valid":    {"zh": "✅ 手动输入的 Cookie 有效，已保存",
                                   "en": "✅ Manual cookie valid, saved"},
        "login.manual_invalid":  {"zh": "⚠️ Cookie 验证失败，可能已过期或格式不正确",
                                   "en": "⚠️ Cookie validation failed — may be expired or malformed"},
        "login.no_pw":           {"zh": "⚠️ 未检测到 Playwright，浏览器登录功能不可用",
                                   "en": "⚠️ Playwright not detected — browser login unavailable"},
        "login.btn_install_pw":  {"zh": "🔧 一键安装 Playwright",   "en": "🔧 Install Playwright"},
        "login.install_done":    {"zh": "✅ 安装完成 — 请重启程序",  "en": "✅ Install done — please restart"},
        "login.install_ready":   {"zh": "✅ 已就绪，无需重启",      "en": "✅ Ready, no restart needed"},
        "login.install_failed":  {"zh": "❌ 安装失败 — 点击重试",   "en": "❌ Install failed — click to retry"},
        "login.install_running": {"zh": "⏳ 安装中...",             "en": "⏳ Installing..."},
        "login.force_log":       {"zh": "🔧 用户手动触发强制提取...","en": "🔧 Manual force-extract triggered..."},
        "login.force_ok":        {"zh": "✅ 强制提取成功！",         "en": "✅ Force-extract successful!"},
        "login.force_fail":      {"zh": "⚠️ 强制提取未找到有效 Cookie，请确认已登录完成",
                                   "en": "⚠️ Force-extract failed — please confirm login is complete"},
        "login.no_worker":       {"zh": "⚠️ 没有正在运行的登录进程","en": "⚠️ No active login process"},
        "login.status_waiting":  {"zh": "⏳ 等待浏览器登录...",     "en": "⏳ Waiting for login..."},
        "login.paste_warning":   {"zh": "请粘贴完整的 Cookie 字符串。","en": "Please paste the complete Cookie string."},

        # ── CourseTab ──
        "course.title":          {"zh": "📚 课程选择",              "en": "📚 Course Selection"},
        "course.pid_label":      {"zh": "选课档案 ID：",           "en": "Profile ID:"},
        "course.pid_placeholder":{"zh": "示例：4665",               "en": "e.g. 4665"},
        "course.btn_fetch":      {"zh": "📥 获取课程列表",          "en": "📥 Fetch Courses"},
        "course.btn_fetching":   {"zh": "⏳ 获取中...",             "en": "⏳ Fetching..."},
        "course.search":         {"zh": "🔍 搜索：",                "en": "🔍 Search:"},
        "course.search_placeholder":{"zh":"输入课程名称关键字实时过滤...","en":"Type course name to filter..."},
        "course.col_check":      {"zh": "",                         "en": ""},
        "course.col_id":         {"zh": "课程 ID",                  "en": "Course ID"},
        "course.col_name":       {"zh": "课程名称",                 "en": "Course Name"},
        "course.btn_all":        {"zh": "☑ 全选",                   "en": "☑ Select All"},
        "course.btn_none":       {"zh": "☐ 取消全选",               "en": "☐ Deselect All"},
        "course.btn_invert":     {"zh": "🔄 反选",                   "en": "🔄 Invert"},
        "course.selected_count": {"zh": "已选：{n} / {t} 门",       "en": "Selected: {n} / {t}"},
        "course.btn_confirm":    {"zh": "✅ 确认选择，进入抢课",     "en": "✅ Confirm & Go to Grab"},
        "course.pid_invalid":    {"zh": "请输入有效的选课档案 ID（纯数字）。",
                                   "en": "Please enter a valid numeric Profile ID."},
        "course.need_cookie":    {"zh": "请先在「登录」Tab 中获取有效的 Cookie。",
                                   "en": "Please obtain a valid Cookie in the Login tab first."},
        "course.no_selection":   {"zh": "请至少选择一门课程。",      "en": "Please select at least one course."},

        # ── GrabTab ──
        "grab.title":            {"zh": "🚀 抢课控制台",            "en": "🚀 Grab Console"},
        "grab.no_courses":       {"zh": "暂未选择课程，请先在「选课」Tab 中确认选择。",
                                   "en": "No courses selected. Please confirm in the Courses tab."},
        "grab.selected_info":    {"zh": "📌 已选 {n} 门课程 | 档案 ID: {pid} | 参数: {param}\n课程 ID: {ids}",
                                   "en": "📌 {n} course(s) | Profile: {pid} | Param: {param}\nIDs: {ids}"},
        "grab.time_group":       {"zh": "⏰ 放闸时间设置",          "en": "⏰ Target Time"},
        "grab.time_label":       {"zh": "目标时间：",               "en": "Target Time:"},
        "grab.strategy_group":   {"zh": "⚙️ 策略配置",              "en": "⚙️ Strategy"},
        "grab.prefire_label":    {"zh": "预发射偏移：",             "en": "Pre-fire Offset:"},
        "grab.interval_label":   {"zh": "提交间隔：",               "en": "Submit Interval:"},
        "grab.max_attempts_label":{"zh":"每课最大尝试：",           "en": "Max Attempts/Course:"},
        "grab.countdown_group":  {"zh": "🕐 倒计时",                "en": "🕐 Countdown"},
        "grab.countdown_ready":  {"zh": "--:--:--.---",             "en": "--:--:--.---"},
        "grab.status_ready":     {"zh": "就绪，等待开始...",         "en": "Ready, waiting to start..."},
        "grab.btn_start":        {"zh": "▶ 开始抢课",               "en": "▶ Start Grab"},
        "grab.btn_stop":         {"zh": "⏹ 停止抢课",               "en": "⏹ Stop Grab"},
        "grab.btn_instant":      {"zh": "⚡ 立即提交（跳过定时）",   "en": "⚡ Submit Now (Skip Timer)"},
        "grab.time_past":        {"zh": "目标时间已过，将立即开始提交。确定继续？",
                                   "en": "Target time has passed. Start immediately?"},
        "grab.instant_confirm":  {"zh": "将立即提交 {n} 门课程，确定？",
                                   "en": "Submit {n} course(s) immediately?"},
        "grab.confirm_title":    {"zh": "确认",                      "en": "Confirm"},

        # ── LogTab ──
        "log.title":             {"zh": "📋 运行日志",              "en": "📋 Run Log"},
        "log.total":             {"zh": "总提交：{n}",              "en": "Total: {n}"},
        "log.success":           {"zh": "成功：{n}",                "en": "Success: {n}"},
        "log.failed":            {"zh": "失败：{n}",                "en": "Failed: {n}"},
        "log.btn_clear":         {"zh": "🗑 清空日志",              "en": "🗑 Clear Log"},
        "log.btn_export":        {"zh": "💾 导出日志",              "en": "💾 Export Log"},

        # ── AboutTab ──
        "tab.about":     {"zh": "ℹ️ 关于",   "en": "ℹ️ About"},
        "about.title":   {"zh": "关于 NUAA 选课工具",       "en": "About NUAA Course Grabber"},
        "about.version": {"zh": "版本",                       "en": "Version"},
        "about.author":  {"zh": "作者",                       "en": "Author"},
        "about.project": {"zh": "项目地址",                   "en": "Project"},
        "about.based_on":{"zh": "基于 NUAA-Snatcher 重构",   "en": "Based on NUAA-Snatcher"},
        "about.license": {"zh": "Apache 2.0 开源协议 | 仅供学习交流使用",
                          "en": "Apache 2.0 License | For educational use only"},
        "about.disclaimer":{"zh":"严禁用于南京航空航天大学的抢课，一切后果与作者无关。",
                            "en":"Strictly prohibited for course grabbing at NUAA. All consequences are the author's responsibility."},
        "about.changelog_title": {"zh": "更新日志",           "en": "Changelog"},
        "about.changelog": {"zh":
            "V1.3.2 — 功能完善\n"
            "  • 修复多标签页登录检测\n"
            "  • 新增「强制提取 Cookie」按钮\n"
            "  • 新增 Cookie 明文显示\n"
            "  • 新增中/英文界面切换\n"
            "  • 新增「关于」Tab\n"
            "  • 代码清理与稳定性修复\n"
            "\n"
            "V1.3 — PySide6 桌面版重构\n"
            "  • 全新 PySide6 深色主题界面\n"
            "  • 浏览器弹窗登录 + Cookie 自动提取 + 持久化\n"
            "  • 图形化课程选择（表格 + 搜索 + 全选/反选）\n"
            "  • 预发射定时抢课 + 多 URL 容错 + 限速退避\n"
            "  • 一键安装缺失依赖\n"
            "  • 彩色实时日志 + 提交统计\n"
            "\n"
            "V1.2b — 发行版\n"
            "  • 更新补全 README 文件\n"
            "  • 修复了已知问题\n"
            "\n"
            "V1.2a — 测试版\n"
            "  • 更新补全 README 文件\n"
            "  • 修复了安装协议书乱码的 bug\n"
            "  • 更改了软件内仓库地址\n"
            "  • 修复了软件内版本号错误的 bug\n"
            "\n"
            "V1.1 — 发行版\n"
            "  • 更新打包并编译程序\n"
            "\n"
            "V1.0 — 正式版\n"
            "  • 更新了 UI 以及搜寻教师的功能\n"
            "  • 修复了 Alpha 0.1 搜寻功能无法正常运行的 bug\n"
            "\n"
            "Alpha 0.1 — 测试版\n"
            "  • 初始版本，基础选课功能"
        , "en":
            "V1.3.2 — Feature Improvements\n"
            "  • Fixed multi-tab login detection\n"
            "  • Added 'Force Extract Cookie' button\n"
            "  • Added cookie plaintext display\n"
            "  • Added Chinese/English UI switching\n"
            "  • Added About tab\n"
            "  • Code cleanup & stability fixes\n"
            "\n"
            "V1.3 — PySide6 Desktop Rewrite\n"
            "  • Brand new PySide6 dark-themed UI\n"
            "  • Browser popup login + auto cookie extraction + persistence\n"
            "  • Graphical course selection (table + search + select all/invert)\n"
            "  • Pre-fire timed grab + multi-URL fallback + rate-limit backoff\n"
            "  • One-click dependency installation\n"
            "  • Color-coded real-time log + statistics\n"
            "\n"
            "V1.2b — Release\n"
            "  • Updated README\n"
            "  • Fixed known issues\n"
            "\n"
            "V1.2a — Beta\n"
            "  • Updated README\n"
            "  • Fixed license agreement garbled text\n"
            "  • Updated repository URL\n"
            "  • Fixed version number display\n"
            "\n"
            "V1.1 — Release\n"
            "  • Packaged and compiled\n"
            "\n"
            "V1.0 — Stable\n"
            "  • Updated UI and teacher search\n"
            "  • Fixed Alpha 0.1 search bug\n"
            "\n"
            "Alpha 0.1 — Beta\n"
            "  • Initial release, basic course selection"
        },
    }

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._lang = self._settings.value("language", "zh")
        if self._lang not in ("zh", "en"):
            self._lang = "zh"

    @property
    def lang(self) -> str:
        return self._lang

    def t(self, key: str, **kwargs) -> str:
        """获取翻译字符串，支持 {key} 格式化"""
        entry = self.STRINGS.get(key, {})
        text = entry.get(self._lang) if entry else None
        if text is None:
            # fallback: Chinese if key exists but language entry missing
            text = entry.get("zh", f"[[{key}]]")
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return text

    def set_language(self, lang: str):
        if lang not in ("zh", "en"):
            return
        if lang == self._lang:
            return
        self._lang = lang
        self._settings.setValue("language", lang)
        self._settings.sync()
        self.language_changed.emit(lang)

    def toggle(self):
        self.set_language("en" if self._lang == "zh" else "zh")

    @property
    def current_label(self) -> str:
        return {"zh": "中", "en": "EN"}[self._lang]


# ============================================================
# CookieManager — Cookie 持久化与验证
# ============================================================

class CookieManager:
    """管理 Cookie 的存储、加载、验证"""

    def __init__(self):
        self.settings = QSettings(
            QSettings.IniFormat, QSettings.UserScope, "NuuaXuanke", "XuankeV2"
        )
        self._cookie_str: str | None = None

    @property
    def cookie(self) -> str | None:
        return self._cookie_str

    @cookie.setter
    def cookie(self, value: str | None):
        self._cookie_str = value

    def save(self, cookie_str: str):
        """保存 Cookie 到本地（base64 编码）"""
        encoded = base64.b64encode(cookie_str.encode("utf-8")).decode("ascii")
        self.settings.setValue("cookie_raw", encoded)
        self.settings.setValue("cookie_ts", datetime.datetime.now().isoformat())
        self.settings.sync()
        self._cookie_str = cookie_str

    def load(self) -> str | None:
        """从本地加载 Cookie"""
        encoded = self.settings.value("cookie_raw", "")
        if encoded:
            try:
                decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
                self._cookie_str = decoded
                return decoded
            except Exception:
                self.clear()
        return None

    def clear(self):
        """清除已保存的 Cookie"""
        self.settings.remove("cookie_raw")
        self.settings.remove("cookie_ts")
        self.settings.sync()
        self._cookie_str = None

    def quick_validate(self) -> bool:
        """快速验证当前 Cookie 是否仍有效"""
        if not self._cookie_str:
            return False
        try:
            with requests.Session() as s:
                s.headers.update({
                    "User-Agent": USER_AGENT,
                    "Cookie": self._cookie_str,
                })
                r = s.get(f"{BASE}/eams/home.action", timeout=REQUEST_TIMEOUT, allow_redirects=True)
                return not is_login_bounce(r)
        except Exception:
            return False

    def save_config(self, key: str, value):
        """保存通用配置项"""
        self.settings.setValue(key, value)
        self.settings.sync()

    def load_config(self, key: str, default=None):
        """加载通用配置项"""
        return self.settings.value(key, default)


# ============================================================
# Worker 线程
# ============================================================

class LoginWorker(QThread):
    """后台线程：打开 Playwright 浏览器（增强反检测），让用户登录，提取 Cookie"""
    cookie_ready = Signal(str)
    login_error = Signal(str)
    status_update = Signal(str)
    url_update = Signal(str)          # 实时 URL 变化信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self._force_extract = False

    def request_force_extract(self):
        """由 UI 线程调用：强制在下一轮轮询中立即尝试提取 Cookie"""
        self._force_extract = True

    # ── 反检测 JS 脚本 ──
    STEALTH_JS = """
    // 1. 隐藏 webdriver 标记
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    // 2. 伪造 chrome 对象
    window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
    // 3. 伪造 plugins 数量
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
    // 4. 移除 PhantomJS 痕迹
    delete window.callPhantom;
    // 5. 覆盖权限查询
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({state: Notification.permission}) :
        originalQuery(parameters)
    );
    """

    def run(self):
        if not HAS_PLAYWRIGHT:
            self.login_error.emit("未安装 Playwright。请在终端执行：\n  pip install playwright\n  playwright install chromium")
            return

        self.status_update.emit("正在启动浏览器（已启用反检测）...")
        LOGIN_ENTRY = f"{BASE}/eams/homeExt.action"
        MAX_WAIT_SECONDS = 300
        browser = None

        try:
            with sync_playwright() as p:
                self.status_update.emit("启动 Chromium 浏览器...")
                browser = p.chromium.launch(
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled",
                          "--disable-features=IsolateOrigins,site-per-process",
                          "--no-sandbox", "--disable-infobars", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    user_agent=USER_AGENT, viewport={"width": 1920, "height": 1080},
                    locale="zh-CN", timezone_id="Asia/Shanghai",
                )
                context.add_init_script(self.STEALTH_JS)
                page = context.new_page()
                self.status_update.emit("正在访问教务系统...")

                try:
                    page.goto(LOGIN_ENTRY, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass

                context.on("page", lambda new_page: self.url_update.emit(
                    f"🆕 新标签页: {new_page.url[:120]}"))

                self.url_update.emit(f"当前页面: {page.url[:100]}")
                self.status_update.emit(
                    "请在浏览器窗口中完成登录（含验证码，如有）。\n"
                    "登录成功后程序会自动检测并提取 Cookie...")

                logged_in = False
                last_url_summary = ""
                unchanged_secs = 0

                for _ in range(MAX_WAIT_SECONDS):
                    page_urls = []
                    for pg in context.pages:
                        try:
                            page_urls.append(pg.url)
                        except Exception:
                            pass
                    url_summary = " | ".join(u[:80] for u in page_urls) if page_urls else "(无页面)"

                    if url_summary != last_url_summary:
                        self.url_update.emit(f"📑 {len(page_urls)} 个标签页: {url_summary[:200]}")
                        last_url_summary = url_summary
                        unchanged_secs = 0
                    else:
                        unchanged_secs += 1

                    if unchanged_secs == 20:
                        self.url_update.emit(
                            f"⚠️ 所有标签页 URL 均未变化 ({unchanged_secs}s)\n"
                            f"   请检查是否填写了验证码并点击了登录按钮")

                    for pg in context.pages:
                        try:
                            if "aao-eas" in pg.url.lower() and "authserver" not in pg.url.lower():
                                page = pg
                                pg.bring_to_front()
                                pg.wait_for_timeout(1500)
                                if self._verify_extracted_cookies(context.cookies()):
                                    logged_in = True
                                    self.url_update.emit(f"✅ 检测到登录成功！页面: {pg.url[:100]}")
                                    break
                        except Exception:
                            continue
                    if logged_in:
                        break

                    if self._force_extract:
                        self._force_extract = False
                        self.url_update.emit("🔧 用户请求强制提取 Cookie...")
                        for pg in context.pages:
                            try:
                                if self._verify_extracted_cookies(context.cookies()):
                                    logged_in = True
                                    page = pg
                                    self.url_update.emit("✅ 强制提取成功！")
                                    break
                            except Exception:
                                continue
                        if not logged_in:
                            self.url_update.emit("⚠️ 强制提取未找到有效 Cookie，请确认已登录完成")
                        if logged_in:
                            break

                    self.msleep(1000)

                if not logged_in:
                    self.status_update.emit("等待超时，尝试使用当前 Cookie...")

                cookie_str = "; ".join(
                    f"{c['name']}={c['value']}" for c in context.cookies())

                if cookie_str:
                    self.cookie_ready.emit(cookie_str)
                else:
                    self.login_error.emit(
                        "未能提取到有效 Cookie。\n"
                        "请确认：1) 表单中是否有验证码？\n"
                        "         2) 登录后页面是否成功跳转？")

        except Exception as e:
            self.login_error.emit(f"浏览器登录异常：{e}")
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

    def _verify_extracted_cookies(self, cookies: list) -> bool:
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        try:
            with requests.Session() as s:
                s.headers.update({"User-Agent": USER_AGENT, "Cookie": cookie_str})
                r = s.get(f"{BASE}/eams/home.action", timeout=5, allow_redirects=True)
                return not is_login_bounce(r)
        except Exception:
            return False


class FetchCoursesWorker(QThread):
    """后台线程：获取可选课程列表"""
    courses_ready = Signal(list, list, str, str)   # (ids, names, pid, used_param)
    fetch_error = Signal(str)
    status_update = Signal(str)

    def __init__(self, cookie_str: str, profile_id: str, parent=None):
        super().__init__(parent)
        self.cookie_str = cookie_str
        self.profile_id = profile_id

    def run(self):
        self.status_update.emit("正在获取课程列表...")
        session = _make_eams_session(self.cookie_str, self.profile_id)
        pid = self.profile_id

        # 1) 直接用用户输入的 pid 尝试
        status, text, used = self._try_fetch_data(session, pid)
        if status != 200 or "id:" not in text or "<html" in text.lower():
            # 2) 从 defaultPage 反向解析候选 pid
            try:
                warm = session.get(
                    DEFAULT_TPL.format(pid=pid),
                    timeout=REQUEST_TIMEOUT, allow_redirects=True
                )
                candidates = _extract_profile_ids(warm.text)
                if not candidates:
                    dp = session.get(
                        f"{BASE}/eams/stdElectCourse!defaultPage.action",
                        timeout=REQUEST_TIMEOUT, allow_redirects=True
                    )
                    candidates = _extract_profile_ids(dp.text)
                for cand in ([pid] + candidates):
                    status, text, used = self._try_fetch_data(session, cand)
                    if status == 200 and "id:" in text and "<html" not in text.lower():
                        pid = cand
                        break
            except Exception as e:
                self.fetch_error.emit(f"获取课程列表异常：{e}")
                return

        if status != 200 or "id:" not in text or "<html" in text.lower():
            self.fetch_error.emit(
                f"课程列表请求返回异常状态码：{status}\n{text[:300]}"
            )
            return

        # 解析课程
        find_id = re.compile(r"id:(\d+),")
        find_name = re.compile(r"name:'([^']*)',")
        id_list = find_id.findall(text)
        name_list = []
        for item in text.split("code:"):
            m = find_name.findall(item)
            if m:
                name_list.append(m[0])
            # continue on non-matching segments (preamble)

        if not id_list:
            self.fetch_error.emit(f"未解析到任何课程 ID，返回片段：{text[:300]}")
            return

        n = min(len(id_list), len(name_list))
        self.courses_ready.emit(id_list[:n], name_list[:n], pid, used)

    def _try_fetch_data(self, session: requests.Session, pid: str):
        """尝试两种参数名去拉 data.action"""
        url1 = f"{BASE}/eams/stdElectCourse!data.action?electionProfile.id={pid}"
        r1 = session.get(url1, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        t1, _ = smart_read(r1)
        if r1.status_code == 200 and "id:" in t1 and "<html" not in t1.lower():
            return r1.status_code, t1, "electionProfile.id"

        url2 = f"{BASE}/eams/stdElectCourse!data.action?profileId={pid}"
        r2 = session.get(url2, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        t2, _ = smart_read(r2)
        return r2.status_code, t2, "profileId"


class GrabWorker(QThread):
    """后台线程：定时抢课核心引擎"""
    log_info = Signal(str, str)        # (message, color)
    countdown = Signal(str)            # 倒计时字符串
    grab_done = Signal()              # 所有提交完成
    stats_update = Signal(int, int, int)  # (提交, 成功, 失败)

    def __init__(self, cookie_str: str, course_ids: list, pid: str,
                 used_param: str, target_dt: datetime.datetime,
                 prefire_ms: int = 200, interval_ms: int = 800,
                 max_per_course: int = 3, parent=None):
        super().__init__(parent)
        self.cookie_str = cookie_str
        self.course_ids = course_ids
        self.pid = pid
        self.used_param = used_param
        self.target_dt = target_dt
        self.prefire_ms = prefire_ms
        self.interval_ms = interval_ms
        self.max_per_course = max_per_course
        self._stop_flag = False

    def stop(self):
        """外部调用：停止抢课"""
        self._stop_flag = True

    def run(self):
        import traceback
        try:
            self._do_run()
        except Exception:
            tb = traceback.format_exc()
            self.log_info.emit(f"💥 抢课引擎崩溃：\n{tb}", "red")
        finally:
            self.grab_done.emit()

    def _do_run(self):
        # 构建 session
        session = _make_eams_session(self.cookie_str, self.pid)

        # 构建提交 URL 列表（主 + 备）
        base_post = f"{BASE}/eams/stdElectCourse!batchOperator.action"
        if self.used_param == "profileId":
            post_urls = [f"{base_post}?profileId={self.pid}",
                         f"{base_post}?electionProfile.id={self.pid}"]
        else:
            post_urls = [f"{base_post}?electionProfile.id={self.pid}",
                         f"{base_post}?profileId={self.pid}"]

        total_submitted = 0
        total_success = 0
        total_failed = 0
        last_post_ts = 0.0

        fire_time = self.target_dt - datetime.timedelta(milliseconds=self.prefire_ms)

        self.log_info.emit("⏳ 开始等待放闸时间...", "gray")
        self.log_info.emit(
            f"📍 目标时间: {self.target_dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}", "gray"
        )
        self.log_info.emit(
            f"🎯 预发射偏移: {self.prefire_ms} ms (实际发射: "
            f"{fire_time.strftime('%H:%M:%S.%f')[:-3]})", "gray"
        )
        self.log_info.emit(f"📦 待抢课程: {len(self.course_ids)} 门", "gray")

        # ── 倒计时阶段 ──
        while not self._stop_flag:
            now = datetime.datetime.now()
            if now >= fire_time:
                break

            remain = fire_time - now
            total_sec = remain.total_seconds()

            if total_sec > 0:
                h = int(total_sec // 3600)
                m = int((total_sec % 3600) // 60)
                s = int(total_sec % 60)
                ms = int((total_sec * 1000) % 1000)
                self.countdown.emit(f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}")

            sleep_ms = 10 if total_sec < 1.0 else 100
            self.msleep(sleep_ms)

        if self._stop_flag:
            self.log_info.emit("⚠️ 用户停止了抢课", "yellow")
            return

        self.countdown.emit("🔥 发射！")

        # ── 提交阶段 ──
        for cid in self.course_ids:
            if self._stop_flag:
                break

            self.log_info.emit(f"→ 正在提交课程 {cid}...", "gray")

            for attempt in range(self.max_per_course):
                if self._stop_flag:
                    break

                sent_ok = False
                for url in post_urls:
                    if self._stop_flag:
                        break

                    gap = time.monotonic() - last_post_ts
                    min_gap = self.interval_ms / 1000.0
                    if gap < min_gap:
                        self.msleep(int((min_gap - gap) * 1000))

                    data = {
                        "optype": "true",
                        "operator0": f"{cid}:true:0",
                        "lesson0": cid,
                    }
                    try:
                        resp = session.post(
                            url, data=data, timeout=REQUEST_TIMEOUT, allow_redirects=True
                        )
                        last_post_ts = time.monotonic()

                        if is_login_bounce(resp):
                            continue

                        body, _ = smart_read(resp)
                        chinese = re.findall(r"([一-龥]+)", body)
                        msg = "".join(chinese) or body[:180]
                        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

                        total_submitted += 1

                        if "成功" in msg or "选课成功" in msg:
                            self.log_info.emit(
                                f"  [{ts}] ✅ {resp.status_code} → {msg}", "green"
                            )
                            total_success += 1
                            sent_ok = True
                        elif "请不要过快点击" in body or resp.status_code in (429, 503):
                            self.log_info.emit(
                                f"  [{ts}] ⚠️ {resp.status_code} → {msg} (退避 {BACKOFF_SECONDS}s)",
                                "yellow"
                            )
                            total_failed += 1
                            self.msleep(BACKOFF_SECONDS * 1000)
                        elif "失败" in msg or "错误" in msg or resp.status_code >= 400:
                            self.log_info.emit(
                                f"  [{ts}] ❌ {resp.status_code} → {msg}", "red"
                            )
                            total_failed += 1
                        else:
                            self.log_info.emit(
                                f"  [{ts}] ⚪ {resp.status_code} → {msg}", "gray"
                            )
                            sent_ok = True

                        self.stats_update.emit(total_submitted, total_success, total_failed)

                        if sent_ok:
                            break

                    except Exception as e:
                        last_post_ts = time.monotonic()
                        total_failed += 1
                        self.log_info.emit(
                            f"  [{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] "
                            f"💥 网络异常 → {e}", "red"
                        )
                        self.stats_update.emit(total_submitted, total_success, total_failed)
                        continue

                if sent_ok:
                    break
            else:
                self.log_info.emit(
                    f"  ⚠️ 课程 {cid}：{self.max_per_course} 次尝试均未成功", "yellow"
                )

        self.log_info.emit(
            f"🏁 抢课结束 | 提交: {total_submitted} | 成功: {total_success} | 失败: {total_failed}",
            "gray" if total_success == 0 else "green"
        )


class InstallWorker(QThread):
    """后台线程：执行 pip install（用于应用内安装缺失的依赖）"""
    output_line = Signal(str)        # 实时输出行
    install_done = Signal(bool, str) # (success, message)

    def __init__(self, packages: list, parent=None):
        """
        packages: [(描述, ["pip", "install", "xxx"]), ...]
                  也支持 ["playwright", "install", "chromium"] 这类非 pip 命令
        """
        super().__init__(parent)
        self.packages = packages

    def run(self):
        python_exe = sys.executable
        all_ok = True
        for pkg_desc, pkg_cmd in self.packages:
            # 允许以 "python -m pip" 开头的命令和纯命令两种形式
            if pkg_cmd[0] in ("pip", "playwright"):
                full_cmd = [python_exe, "-m"] + pkg_cmd
            else:
                full_cmd = pkg_cmd

            self.output_line.emit(f">>> {' '.join(full_cmd)}")
            try:
                proc = subprocess.Popen(
                    full_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                for line in proc.stdout:
                    self.output_line.emit(line.rstrip())
                proc.wait()
                if proc.returncode != 0:
                    self.output_line.emit(f"\n!!! {pkg_desc} 安装失败 (exit={proc.returncode})")
                    all_ok = False
                    break
                self.output_line.emit(f"--- {pkg_desc} 完成 ---")
            except Exception as e:
                self.output_line.emit(f"!!! 异常: {e}")
                all_ok = False
                break

        if all_ok:
            self.install_done.emit(True, "所有依赖安装完成！")
        else:
            self.install_done.emit(False, "安装未完全成功，请检查上方日志。")


# ============================================================
# Tab 页面组件
# ============================================================

class LoginTab(QWidget):
    """登录 Tab — 浏览器登录 + 手动粘贴"""
    cookie_obtained = Signal(str)

    def __init__(self, cookie_manager: CookieManager, i18n: I18n, parent=None):
        super().__init__(parent)
        self.cm = cookie_manager
        self.i18n = i18n
        self._login_worker: LoginWorker | None = None
        self._build_ui()
        self.i18n.language_changed.connect(self._retranslate_ui)

    def post_init_load_cookie(self):
        """在信号连接后调用：加载已保存的 Cookie 并验证"""
        saved = self.cm.load()
        if saved and self.cm.quick_validate():
            self._update_cookie_status("valid", "✅ Cookie 已从本地加载，状态有效")
            self._show_cookie(saved)
            self.cookie_obtained.emit(saved)
        elif saved:
            self._update_cookie_status("expired", "⚠️ 本地 Cookie 已过期，请重新登录")
        else:
            self._update_cookie_status("none", "⚪ 尚未设置 Cookie")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── 标题 ──
        title = QLabel("🔐 登录认证")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        layout.addWidget(title)

        # ── Cookie 状态 ──
        status_group = QGroupBox("Cookie 状态")
        status_layout = QVBoxLayout(status_group)
        self.status_label = QLabel("⚪ 尚未设置 Cookie")
        self.status_label.setFont(QFont("Microsoft YaHei", 11))
        status_layout.addWidget(self.status_label)
        self.status_detail = QLabel("")
        self.status_detail.setStyleSheet("color: gray;")
        self.status_detail.setWordWrap(True)
        status_layout.addWidget(self.status_detail)
        layout.addWidget(status_group)

        # ── Cookie 明文显示 ──
        self.cookie_display_group = QGroupBox(self.i18n.t("login.cookie_display"))
        cookie_display_layout = QVBoxLayout(self.cookie_display_group)
        self.cookie_display = QTextBrowser()
        self.cookie_display.setFont(QFont("Consolas", 9))
        self.cookie_display.setMaximumHeight(80)
        self.cookie_display.setPlaceholderText(self.i18n.t("login.cookie_placeholder"))
        self.cookie_display.setStyleSheet(
            "QTextBrowser { background-color: #0d1b2a; color: #f39c12; }"
        )
        cookie_display_layout.addWidget(self.cookie_display)
        layout.addWidget(self.cookie_display_group)

        # ── 浏览器登录（已启用反检测）──
        self.login_group = QGroupBox(self.i18n.t("login.browser_group"))
        self.login_group.setStyleSheet(self.login_group.styleSheet() +
            "QGroupBox { color: #27ae60; font-weight: bold; }")
        gl_layout = QVBoxLayout(self.login_group)

        self.login_desc = QLabel(self.i18n.t("login.browser_desc"))
        self.login_desc.setWordWrap(True)
        gl_layout.addWidget(self.login_desc)

        btn_row = QHBoxLayout()
        self.btn_browser = QPushButton(self.i18n.t("login.btn_browser"))
        self.btn_browser.setMinimumHeight(42)
        self.btn_browser.setFont(QFont("Microsoft YaHei", 11))
        self.btn_browser.clicked.connect(self._start_browser_login)
        self.btn_browser.setToolTip("弹出增强的 Chromium 浏览器（已注入反检测脚本）")
        btn_row.addWidget(self.btn_browser)
        gl_layout.addLayout(btn_row)

        if not HAS_PLAYWRIGHT:
            self.btn_browser.setEnabled(False)
            self._add_playwright_install_ui(gl_layout)

        layout.addWidget(self.login_group)

        # ── 强制提取按钮（等待登录时显示）──
        self.btn_force_extract = QPushButton(self.i18n.t("login.btn_force"))
        self.btn_force_extract.setMinimumHeight(40)
        self.btn_force_extract.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.btn_force_extract.setStyleSheet(
            "QPushButton { background-color: #f39c12; color: white; }"
            "QPushButton:hover { background-color: #e67e22; }"
        )
        self.btn_force_extract.clicked.connect(self._on_force_extract)
        self.btn_force_extract.setVisible(False)
        layout.addWidget(self.btn_force_extract)

        # ── URL / 状态输出 ──
        self.url_output = QTextBrowser()
        self.url_output.setFont(QFont("Consolas", 9))
        self.url_output.setMaximumHeight(100)
        self.url_output.setVisible(False)
        layout.addWidget(self.url_output)

        # ── 手动粘贴 Cookie（兜底）──
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        self.manual_title_label = QLabel(self.i18n.t("login.manual_title"))
        layout.addWidget(self.manual_title_label)
        paste_layout = QHBoxLayout()
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText(
            "从浏览器 DevTools → Network → Request Headers 复制整行 Cookie"
        )
        paste_layout.addWidget(self.cookie_input)
        self.btn_paste = QPushButton("应用")
        self.btn_paste.clicked.connect(self._apply_manual_cookie)
        paste_layout.addWidget(self.btn_paste)
        layout.addLayout(paste_layout)

        layout.addStretch()

    def _add_playwright_install_ui(self, parent_layout):
        """Playwright 未安装时显示的安装界面"""
        install_hint = QLabel("⚠️ 未检测到 Playwright，浏览器登录功能不可用")
        install_hint.setStyleSheet("color: #e67e22; font-size: 13px;")
        parent_layout.addWidget(install_hint)

        self.btn_install_pw = QPushButton("🔧 一键安装 Playwright")
        self.btn_install_pw.setStyleSheet(
            "background-color: #e67e22; color: white;"
            "padding: 8px 16px; border-radius: 4px; font-size: 13px;"
        )
        self.btn_install_pw.clicked.connect(self._install_playwright)
        parent_layout.addWidget(self.btn_install_pw)

        self.pw_install_output = QTextBrowser()
        self.pw_install_output.setFont(QFont("Consolas", 9))
        self.pw_install_output.setMaximumHeight(100)
        self.pw_install_output.setVisible(False)
        parent_layout.addWidget(self.pw_install_output)

        self._pw_install_worker: InstallWorker | None = None

    # ── 浏览器登录（Playwright + 反检测）──
    def _start_browser_login(self):
        self._set_browser_btn_enabled(False)
        self._show_force_extract_btn()
        self.btn_browser.setText("⏳ 浏览器运行中，请登录（含验证码）...")
        self.status_label.setText("⏳ 等待浏览器登录...")
        self.status_label.setStyleSheet("color: #f39c12;")
        self.url_output.setVisible(True)
        self.url_output.clear()

        self._login_worker = LoginWorker()
        self._login_worker.cookie_ready.connect(self._on_cookie_ready)
        self._login_worker.login_error.connect(self._on_login_error)
        self._login_worker.status_update.connect(
            lambda msg: self.status_detail.setText(msg)
        )
        self._login_worker.url_update.connect(self._append_url_log)
        self._login_worker.start()

    # ── 通用回调 ──
    def _on_cookie_ready(self, cookie_str: str):
        self.cm.save(cookie_str)
        self._update_cookie_status("valid", "✅ Cookie 已自动提取并保存")
        self._show_cookie(cookie_str)
        self._set_browser_btn_enabled(True)
        self._hide_force_extract_btn()
        self.btn_browser.setText("🌐 打开浏览器登录")
        self.cookie_obtained.emit(cookie_str)

    def _on_login_error(self, msg: str):
        self._update_cookie_status("none", f"❌ {msg}")
        self._set_browser_btn_enabled(True)
        self._hide_force_extract_btn()
        self.btn_browser.setText("🌐 重试浏览器登录")

    def _set_browser_btn_enabled(self, enabled: bool):
        self.btn_browser.setEnabled(enabled)

    def _append_url_log(self, text: str):
        self.url_output.append(text)
        sb = self.url_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _show_cookie(self, cookie_str: str):
        """在 Cookie 显示区展示明文 Cookie"""
        self.cookie_display.clear()
        # 截断过长内容，保留头尾
        if len(cookie_str) > 600:
            head = cookie_str[:300]
            tail = cookie_str[-200:]
            display = f"{head}\n\n... (共 {len(cookie_str)} 字符) ...\n\n{tail}"
        else:
            display = cookie_str
        self.cookie_display.setPlainText(display)

    # ── 强制提取 Cookie ──
    def _on_force_extract(self):
        """用户手动点击：强制从浏览器提取 Cookie"""
        self.btn_force_extract.setEnabled(False)
        self.btn_force_extract.setText("⏳ 正在提取...")
        self._append_url_log("🔧 用户手动触发强制提取...")
        # 向正在运行的 worker 发送信号
        if self._login_worker and self._login_worker.isRunning():
            self._login_worker.request_force_extract()
        else:
            self._append_url_log("⚠️ 没有正在运行的登录进程")
            self.btn_force_extract.setEnabled(True)
            self.btn_force_extract.setText("📥 我已登录完成，立即提取 Cookie！")

    def _show_force_extract_btn(self):
        self.btn_force_extract.setVisible(True)
        self.btn_force_extract.setEnabled(True)
        self.btn_force_extract.setText("📥 我已登录完成，立即提取 Cookie！")

    def _hide_force_extract_btn(self):
        self.btn_force_extract.setVisible(False)

    # ── 手动粘贴 Cookie ──
    def _apply_manual_cookie(self):
        cookie_str = self.cookie_input.text().strip()
        if not cookie_str:
            QMessageBox.warning(self, "提示", "请粘贴完整的 Cookie 字符串。")
            return
        self.cm.save(cookie_str)
        self.cm.cookie = cookie_str
        if self.cm.quick_validate():
            self._update_cookie_status("valid", "✅ 手动输入的 Cookie 有效，已保存")
            self._show_cookie(cookie_str)
            self.cookie_obtained.emit(cookie_str)
        else:
            self._update_cookie_status("expired", "⚠️ Cookie 验证失败，可能已过期或格式不正确")
            self._show_cookie(cookie_str)  # 即使无效也显示，方便排查

    def _retranslate_ui(self, _lang=""):
        """刷新 LoginTab 所有 UI 文本"""
        i = self.i18n
        # 标题 & Cookie 状态
        self.cookie_display_group.setTitle(i.t("login.cookie_display"))
        self.cookie_display.setPlaceholderText(i.t("login.cookie_placeholder"))
        self.login_group.setTitle(i.t("login.browser_group"))
        self.login_desc.setText(i.t("login.browser_desc"))
        self.btn_browser.setText(i.t("login.btn_browser"))
        self.btn_force_extract.setText(i.t("login.btn_force"))
        # 手动粘贴
        self.manual_title_label.setText(i.t("login.manual_title"))
        self.cookie_input.setPlaceholderText(i.t("login.manual_placeholder"))
        self.btn_paste.setText(i.t("login.btn_apply"))

    def _update_cookie_status(self, status: str, detail: str):
        colors = {
            "valid": ("#27ae60", "#2ecc71"),
            "expired": ("#e67e22", "#f39c12"),
            "none": ("#7f8c8d", "#95a5a6"),
        }
        fg, _ = colors.get(status, colors["none"])
        self.status_detail.setText(detail)
        self.status_label.setStyleSheet(f"color: {fg}; font-weight: bold;")

    # ── Playwright 一键安装 ──
    def _install_playwright(self):
        self.btn_install_pw.setEnabled(False)
        self.btn_install_pw.setText("⏳ 安装中...")
        self.pw_install_output.setVisible(True)
        self.pw_install_output.clear()

        packages = [
            ("Playwright (浏览器自动化库)", ["pip", "install", "playwright"]),
            ("Chromium 浏览器", ["playwright", "install", "chromium"]),
        ]
        self._pw_install_worker = InstallWorker(packages)
        self._pw_install_worker.output_line.connect(self._on_pw_install_output)
        self._pw_install_worker.install_done.connect(self._on_pw_install_done)
        self._pw_install_worker.start()

    def _on_pw_install_output(self, line: str):
        self.pw_install_output.append(line)
        sb = self.pw_install_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_pw_install_done(self, success: bool, message: str):
        self.pw_install_output.append(f"\n{'='*50}\n{message}\n{'='*50}")
        if success:
            self.btn_install_pw.setText("✅ 安装完成 — 请重启程序")
            self.btn_install_pw.setStyleSheet(
                "background-color: #27ae60; color: white;"
                "padding: 8px 16px; border-radius: 4px; font-size: 13px;"
            )
            global HAS_PLAYWRIGHT
            try:
                from playwright.sync_api import sync_playwright  # noqa: F811
                HAS_PLAYWRIGHT = True
                self.btn_browser.setEnabled(True)
                self.btn_browser.setText("🌐 打开浏览器登录")
                self.btn_install_pw.setText("✅ 已就绪，无需重启")
            except ImportError:
                pass
        else:
            self.btn_install_pw.setText("❌ 安装失败 — 点击重试")
            self.btn_install_pw.setEnabled(True)
            self.btn_install_pw.setStyleSheet(
                "background-color: #e74c3c; color: white;"
                "padding: 8px 16px; border-radius: 4px; font-size: 13px;"
            )


class CourseTab(QWidget):
    """选课 Tab：课程列表 + 搜索过滤"""
    courses_selected = Signal(list, str, str)

    def __init__(self, cookie_manager: CookieManager, i18n: I18n, parent=None):
        super().__init__(parent)
        self.cm = cookie_manager
        self.i18n = i18n
        self.i18n.language_changed.connect(self._retranslate_ui)
        self._id_list: list = []
        self._name_list: list = []
        self._pid: str = ""
        self._used_param: str = ""
        self._fetch_worker: FetchCoursesWorker | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("📚 课程选择")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        layout.addWidget(title)

        # ── Profile ID 行 ──
        pid_layout = QHBoxLayout()
        pid_layout.addWidget(QLabel("选课档案 ID："))
        self.pid_input = QLineEdit()
        self.pid_input.setPlaceholderText("示例：4665")
        saved_pid = self.cm.load_config("last_profile_id", "")
        if saved_pid:
            self.pid_input.setText(saved_pid)
        pid_layout.addWidget(self.pid_input)
        self.btn_fetch = QPushButton("📥 获取课程列表")
        self.btn_fetch.setMinimumHeight(32)
        self.btn_fetch.clicked.connect(self._fetch_courses)
        pid_layout.addWidget(self.btn_fetch)
        layout.addLayout(pid_layout)

        # ── 搜索框 ──
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 搜索："))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入课程名称关键字实时过滤...")
        self.search_input.textChanged.connect(self._filter_table)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # ── 课程表格 ──
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["", "课程 ID", "课程名称"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ── 操作按钮行 ──
        btn_layout = QHBoxLayout()
        self.btn_all = QPushButton("☑ 全选")
        self.btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_layout.addWidget(self.btn_all)
        self.btn_none = QPushButton("☐ 取消全选")
        self.btn_none.clicked.connect(lambda: self._set_all_checked(False))
        btn_layout.addWidget(self.btn_none)
        self.btn_invert = QPushButton("🔄 反选")
        self.btn_invert.clicked.connect(self._invert_selection)
        btn_layout.addWidget(self.btn_invert)
        btn_layout.addStretch()
        self.lbl_count = QLabel("已选：0 门")
        self.lbl_count.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        btn_layout.addWidget(self.lbl_count)
        layout.addLayout(btn_layout)

        # ── 确认按钮 ──
        self.btn_confirm = QPushButton("✅ 确认选择，进入抢课")
        self.btn_confirm.setMinimumHeight(38)
        self.btn_confirm.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self.btn_confirm.clicked.connect(self._confirm_selection)
        self.btn_confirm.setEnabled(False)
        layout.addWidget(self.btn_confirm)

    def _fetch_courses(self):
        pid = self.pid_input.text().strip()
        if not pid.isdigit():
            QMessageBox.warning(self, "提示", "请输入有效的选课档案 ID（纯数字）。")
            return

        cookie = self.cm.cookie
        if not cookie:
            QMessageBox.warning(self, "提示", "请先在「登录」Tab 中获取有效的 Cookie。")
            return

        self.cm.save_config("last_profile_id", pid)
        self.btn_fetch.setEnabled(False)
        self.btn_fetch.setText("⏳ 获取中...")
        self.table.setRowCount(0)

        self._fetch_worker = FetchCoursesWorker(cookie, pid)
        self._fetch_worker.courses_ready.connect(self._on_courses_ready)
        self._fetch_worker.fetch_error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_courses_ready(self, id_list: list, name_list: list, pid: str, used: str):
        self._id_list = id_list
        self._name_list = name_list
        self._pid = pid
        self._used_param = used

        self.table.setRowCount(len(id_list))
        for i, (cid, cname) in enumerate(zip(id_list, name_list)):
            # Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 0, chk_item)
            # ID
            self.table.setItem(i, 1, QTableWidgetItem(cid))
            # Name
            self.table.setItem(i, 2, QTableWidgetItem(cname))

        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("📥 获取课程列表")
        self.btn_confirm.setEnabled(True)
        self.lbl_count.setText(f"已选：0 / {len(id_list)} 门")
        self.table.itemChanged.connect(self._on_check_changed)

    def _on_fetch_error(self, msg: str):
        self.btn_fetch.setEnabled(True)
        self.btn_fetch.setText("📥 获取课程列表")
        QMessageBox.critical(self, "获取失败", msg)

    def _refresh_count_label(self):
        """同步勾选数量到标签"""
        count = sum(
            1 for i in range(self.table.rowCount())
            if self.table.item(i, 0) and self.table.item(i, 0).checkState() == Qt.Checked
        )
        self.lbl_count.setText(f"已选：{count} / {len(self._id_list)} 门")

    def _on_check_changed(self, _item):
        self._refresh_count_label()

    def _filter_table(self, text: str):
        keyword = text.strip().lower()
        for i in range(self.table.rowCount()):
            name_item = self.table.item(i, 2)
            id_item = self.table.item(i, 1)
            if name_item and id_item:
                match = keyword in name_item.text().lower() or keyword in id_item.text()
                self.table.setRowHidden(i, not match)

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        self.table.itemChanged.disconnect(self._on_check_changed)
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i) and self.table.item(i, 0):
                self.table.item(i, 0).setCheckState(state)
        self.table.itemChanged.connect(self._on_check_changed)
        self._refresh_count_label()

    def _invert_selection(self):
        self.table.itemChanged.disconnect(self._on_check_changed)
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i) and self.table.item(i, 0):
                current = self.table.item(i, 0).checkState()
                self.table.item(i, 0).setCheckState(
                    Qt.Unchecked if current == Qt.Checked else Qt.Checked
                )
        self.table.itemChanged.connect(self._on_check_changed)
        self._refresh_count_label()

    def _confirm_selection(self):
        selected = []
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0) and self.table.item(i, 0).checkState() == Qt.Checked:
                cid = self.table.item(i, 1).text()
                selected.append(cid)

        if not selected:
            QMessageBox.warning(self, "提示", "请至少选择一门课程。")
            return

        self.courses_selected.emit(selected, self._pid, self._used_param)

    def _retranslate_ui(self, _lang=""):
        pass  # CourseTab 静态文本在 _build_ui 中已使用 i18n.t()


class GrabTab(QWidget):
    """抢课 Tab：定时设置 + 策略配置 + 倒计时"""
    start_grab = Signal(list, str, str, datetime.datetime, int, int, int)
    stop_grab = Signal()

    def __init__(self, i18n: I18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self.i18n.language_changed.connect(self._retranslate_ui)
        self._selected_courses: list = []
        self._pid: str = ""
        self._used_param: str = ""
        self._is_running = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("🚀 抢课控制台")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        layout.addWidget(title)

        # ── 已选课程信息 ──
        self.lbl_selected = QLabel("暂未选择课程，请先在「选课」Tab 中确认选择。")
        self.lbl_selected.setStyleSheet("color: gray;")
        self.lbl_selected.setWordWrap(True)
        layout.addWidget(self.lbl_selected)

        # ── 时间设置 ──
        time_group = QGroupBox("⏰ 放闸时间设置")
        time_layout = QFormLayout(time_group)
        self.dt_picker = QDateTimeEdit()
        self.dt_picker.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.dt_picker.setCalendarPopup(True)
        # 默认设为明天 9:00
        default_dt = QDateTime.currentDateTime().addDays(1)
        default_dt.setTime(default_dt.time().addSecs(
            -default_dt.time().hour() * 3600
            - default_dt.time().minute() * 60
            - default_dt.time().second()
            + 9 * 3600
        ))
        self.dt_picker.setDateTime(default_dt)
        time_layout.addRow("目标时间：", self.dt_picker)
        layout.addWidget(time_group)

        # ── 策略配置 ──
        strat_group = QGroupBox("⚙️ 策略配置")
        strat_layout = QFormLayout(strat_group)

        self.spin_prefire = QSpinBox()
        self.spin_prefire.setRange(0, 5000)
        self.spin_prefire.setValue(200)
        self.spin_prefire.setSuffix(" ms")
        self.spin_prefire.setToolTip("提前多少毫秒发射请求，用于补偿网络延迟")
        strat_layout.addRow("预发射偏移：", self.spin_prefire)

        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(300, 5000)
        self.spin_interval.setValue(800)
        self.spin_interval.setSuffix(" ms")
        self.spin_interval.setToolTip("两次提交之间的最小间隔")
        strat_layout.addRow("提交间隔：", self.spin_interval)

        self.spin_max_attempts = QSpinBox()
        self.spin_max_attempts.setRange(1, 20)
        self.spin_max_attempts.setValue(3)
        self.spin_max_attempts.setToolTip("每门课的最大提交尝试次数")
        strat_layout.addRow("每课最大尝试：", self.spin_max_attempts)

        layout.addWidget(strat_group)

        # ── 倒计时显示 ──
        countdown_group = QGroupBox("🕐 倒计时")
        cd_layout = QVBoxLayout(countdown_group)
        self.lbl_countdown = QLabel("--:--:--.---")
        self.lbl_countdown.setFont(QFont("Consolas", 36, QFont.Bold))
        self.lbl_countdown.setAlignment(Qt.AlignCenter)
        self.lbl_countdown.setStyleSheet("color: #3498db;")
        cd_layout.addWidget(self.lbl_countdown)

        self.lbl_status = QLabel("就绪，等待开始...")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("color: gray;")
        cd_layout.addWidget(self.lbl_status)

        layout.addWidget(countdown_group)

        # ── 进度条 ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # ── 按钮行 ──
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始抢课")
        self.btn_start.setMinimumHeight(42)
        self.btn_start.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self.btn_start.clicked.connect(self._toggle_grab)
        self.btn_start.setEnabled(False)
        btn_layout.addWidget(self.btn_start)

        self.btn_instant = QPushButton("⚡ 立即提交（跳过定时）")
        self.btn_instant.setMinimumHeight(42)
        self.btn_instant.clicked.connect(self._instant_grab)
        self.btn_instant.setEnabled(False)
        btn_layout.addWidget(self.btn_instant)

        layout.addLayout(btn_layout)

    def set_courses(self, course_ids: list, pid: str, used_param: str):
        self._selected_courses = course_ids
        self._pid = pid
        self._used_param = used_param
        self.lbl_selected.setText(
            f"📌 已选 {len(course_ids)} 门课程 | 档案 ID: {pid} | 参数: {used_param}\n"
            f"课程 ID: {', '.join(course_ids)}"
        )
        self.lbl_selected.setStyleSheet("color: #27ae60; font-weight: bold;")
        self.btn_start.setEnabled(True)
        self.btn_instant.setEnabled(True)

    def _toggle_grab(self):
        if not self._is_running:
            self._start_grab()
        else:
            self._stop_grab()

    def _start_grab(self):
        if not self._selected_courses:
            QMessageBox.warning(self, "提示", "请先在「选课」Tab 中选择课程。")
            return

        target_qdt = self.dt_picker.dateTime()
        target_dt = target_qdt.toPython()

        if target_dt <= datetime.datetime.now():
            reply = QMessageBox.question(
                self, "确认",
                "目标时间已过，将立即开始提交。确定继续？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
            target_dt = datetime.datetime.now() + datetime.timedelta(seconds=1)

        self._do_start_grab(target_dt, self.spin_prefire.value())

    def _stop_grab(self):
        self.stop_grab.emit()
        # 不在此处 _reset_ui() —— 等 GrabWorker 真正停止后由 on_grab_done() 触发

    def _instant_grab(self):
        if not self._selected_courses:
            QMessageBox.warning(self, "提示", "请先在「选课」Tab 中选择课程。")
            return
        reply = QMessageBox.question(
            self, "确认",
            f"将立即提交 {len(self._selected_courses)} 门课程，确定？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        target_dt = datetime.datetime.now() + datetime.timedelta(milliseconds=500)
        self._do_start_grab(target_dt, prefire=0)

    def _do_start_grab(self, target_dt, prefire: int):
        """统一的抢课启动逻辑"""
        interval = self.spin_interval.value()
        max_attempts = self.spin_max_attempts.value()

        self._is_running = True
        self.btn_start.setText("⏹ 停止抢课")
        self.btn_start.setStyleSheet("background-color: #e74c3c; color: white;")
        self.btn_instant.setEnabled(False)
        self.dt_picker.setEnabled(False)
        self.spin_prefire.setEnabled(False)
        self.spin_interval.setEnabled(False)
        self.spin_max_attempts.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self._selected_courses))
        self.progress.setValue(0)
        self.lbl_countdown.setStyleSheet("color: #e67e22;")

        self.start_grab.emit(
            self._selected_courses, self._pid, self._used_param,
            target_dt, prefire, interval, max_attempts
        )

    def update_countdown(self, text: str):
        """由 GrabWorker 信号驱动的倒计时更新"""
        self.lbl_countdown.setText(text)

    def on_grab_done(self):
        """抢课完成回调"""
        self._reset_ui()

    def _reset_ui(self):
        self._is_running = False
        self.btn_start.setText("▶ 开始抢课")
        self.btn_start.setStyleSheet("")
        self.btn_start.setEnabled(True)
        self.btn_instant.setEnabled(True)
        self.dt_picker.setEnabled(True)
        self.spin_prefire.setEnabled(True)
        self.spin_interval.setEnabled(True)
        self.spin_max_attempts.setEnabled(True)
        self.progress.setVisible(False)
        self.lbl_countdown.setText("--:--:--.---")
        self.lbl_countdown.setStyleSheet("color: #3498db;")
        self.lbl_status.setText("就绪，等待开始...")

    def _retranslate_ui(self, _lang=""):
        pass


class LogTab(QWidget):
    """日志 Tab：彩色日志 + 统计"""

    def __init__(self, i18n: I18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self._total = 0
        self._success = 0
        self._failed = 0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("📋 运行日志")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        layout.addWidget(title)

        # ── 统计面板 ──
        stats_layout = QHBoxLayout()
        self.lbl_total = self._make_stat_label("总提交：0")
        stats_layout.addWidget(self.lbl_total)
        self.lbl_success = self._make_stat_label("成功：0", "#27ae60")
        stats_layout.addWidget(self.lbl_success)
        self.lbl_failed = self._make_stat_label("失败：0", "#e74c3c")
        stats_layout.addWidget(self.lbl_failed)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)

        # ── 日志输出区 ──
        self.log_text = QTextBrowser()
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setOpenExternalLinks(False)
        layout.addWidget(self.log_text)

        # ── 按钮行 ──
        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("🗑 清空日志")
        self.btn_clear.clicked.connect(self.clear_log)
        btn_layout.addWidget(self.btn_clear)
        self.btn_export = QPushButton("💾 导出日志")
        self.btn_export.clicked.connect(self._export_log)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _make_stat_label(self, text: str, color: str = "#ecf0f1") -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        lbl.setStyleSheet(
            f"color: {color}; background-color: #2c3e50; "
            f"padding: 6px 14px; border-radius: 4px;"
        )
        return lbl

    def append_log(self, text: str, color: str = "gray"):
        """追加一条彩色日志"""
        color_map = {
            "green": "#2ecc71",
            "red": "#e74c3c",
            "yellow": "#f39c12",
            "gray": "#bdc3c7",
        }
        html_color = color_map.get(color, color)
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        html = (
            f'<span style="color:#7f8c8d;">[{ts}]</span> '
            f'<span style="color:{html_color};">{text}</span>'
        )
        self.log_text.append(html)
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_stats(self, total: int, success: int, failed: int):
        self._total = max(self._total, total)
        self._success = max(self._success, success)
        self._failed = max(self._failed, failed)
        self.lbl_total.setText(f"总提交：{self._total}")
        self.lbl_success.setText(f"成功：{self._success}")
        self.lbl_failed.setText(f"失败：{self._failed}")

    def clear_log(self):
        self.log_text.clear()
        self._total = 0
        self._success = 0
        self._failed = 0
        self.update_stats(0, 0, 0)

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", f"nuua_xuanke_log_{datetime.date.today()}.txt",
            "文本文件 (*.txt);;所有文件 (*)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toPlainText())

    def _retranslate_ui(self, _lang=""):
        pass


class AboutTab(QWidget):
    """关于 Tab：项目信息 + 更新日志"""

    def __init__(self, i18n: I18n, parent=None):
        super().__init__(parent)
        self.i18n = i18n
        self._build_ui()
        self.i18n.language_changed.connect(self._retranslate_ui)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        i = self.i18n

        # ── 标题 ──
        self.lbl_title = QLabel(i.t("about.title"))
        self.lbl_title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        self.lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_title)

        # ── 分隔线 ──
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # ── 版本信息 ──
        info_group = QGroupBox()
        info_layout = QFormLayout(info_group)

        self.lbl_version = QLabel("V1.3.2")
        self.lbl_version.setFont(QFont("Consolas", 12, QFont.Bold))
        self.lbl_version.setStyleSheet("color: #e94560;")
        info_layout.addRow(f"{i.t('about.version')}：", self.lbl_version)

        self.lbl_author = QLabel("dboycht")
        self.lbl_author.setFont(QFont("Consolas", 12))
        info_layout.addRow(f"{i.t('about.author')}：", self.lbl_author)

        self.lbl_project = QTextBrowser()
        self.lbl_project.setOpenExternalLinks(True)
        self.lbl_project.setMaximumHeight(36)
        self.lbl_project.setFont(QFont("Consolas", 10))
        self.lbl_project.setHtml(
            '<a href="https://github.com/dboycht/NUAA-Snatcher" '
            'style="color:#3498db;">github.com/dboycht/NUAA-Snatcher</a>'
        )
        info_layout.addRow(f"{i.t('about.project')}：", self.lbl_project)

        self.lbl_based = QLabel(i.t("about.based_on"))
        self.lbl_based.setStyleSheet("color: gray;")
        info_layout.addRow("", self.lbl_based)

        layout.addWidget(info_group)

        # ── 协议声明 ──
        self.lbl_license = QLabel(i.t("about.license"))
        self.lbl_license.setWordWrap(True)
        self.lbl_license.setStyleSheet("color: #f39c12; font-weight: bold;")
        layout.addWidget(self.lbl_license)

        self.lbl_disclaimer = QLabel(i.t("about.disclaimer"))
        self.lbl_disclaimer.setWordWrap(True)
        self.lbl_disclaimer.setStyleSheet("color: #e74c3c;")
        layout.addWidget(self.lbl_disclaimer)

        # ── 分隔线 ──
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line2)

        # ── 更新日志 ──
        changelog_group = QGroupBox()
        changelog_layout = QVBoxLayout(changelog_group)
        self.lbl_changelog_title = QLabel(i.t("about.changelog_title"))
        self.lbl_changelog_title.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        changelog_layout.addWidget(self.lbl_changelog_title)

        self.changelog_text = QTextBrowser()
        self.changelog_text.setFont(QFont("Consolas", 10))
        raw = str(i.t("about.changelog"))
        self.changelog_text.setPlainText(raw)
        changelog_layout.addWidget(self.changelog_text)

        layout.addWidget(changelog_group)

    def _retranslate_ui(self, _lang=""):
        i = self.i18n
        self.lbl_title.setText(i.t("about.title"))
        self.changelog_text.setPlainText(i.t("about.changelog"))
        self.lbl_license.setText(i.t("about.license"))
        self.lbl_disclaimer.setText(i.t("about.disclaimer"))
        self.lbl_based.setText(i.t("about.based_on"))
        self.lbl_changelog_title.setText(i.t("about.changelog_title"))


# ============================================================
# 主窗口
# ============================================================

class XuankeApp(QMainWindow):
    """NUAA 选课工具 V2 主窗口"""

    def __init__(self):
        super().__init__()
        self.cookie_manager = CookieManager()
        self.i18n = I18n(self.cookie_manager.settings)
        self._grab_worker: GrabWorker | None = None

        self._setup_window()
        self._build_tabs()
        self._connect_signals()
        self._build_statusbar()
        self._restore_geometry()

        # 信号就绪后加载 Cookie（LoginTab 需要信号来触发自动跳转）
        self.login_tab.post_init_load_cookie()

        # 语言切换时刷新所有 Tab
        self.i18n.language_changed.connect(self._retranslate_ui)

    # ── 窗口设置 ──
    def _setup_window(self):
        self.setWindowTitle(self.i18n.t("app.title"))
        self.setMinimumSize(900, 680)
        self.resize(960, 720)

    def _retranslate_ui(self, _lang=""):
        self.setWindowTitle(self.i18n.t("app.title"))
        # Tab 标签
        self.tabs.setTabText(0, self.i18n.t("tab.login"))
        self.tabs.setTabText(1, self.i18n.t("tab.courses"))
        self.tabs.setTabText(2, self.i18n.t("tab.grab"))
        self.tabs.setTabText(3, self.i18n.t("tab.log"))
        self.tabs.setTabText(4, self.i18n.t("tab.about"))
        # 语言切换按钮
        self._lang_btn.setText(self.i18n.current_label)

    def _restore_geometry(self):
        geo = self.cookie_manager.load_config("window_geometry", "")
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                pass

    def _build_tabs(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.login_tab = LoginTab(self.cookie_manager, self.i18n)
        self.course_tab = CourseTab(self.cookie_manager, self.i18n)
        self.grab_tab = GrabTab(self.i18n)
        self.log_tab = LogTab(self.i18n)
        self.about_tab = AboutTab(self.i18n)

        self.tabs.addTab(self.login_tab, self.i18n.t("tab.login"))
        self.tabs.addTab(self.course_tab, self.i18n.t("tab.courses"))
        self.tabs.addTab(self.grab_tab, self.i18n.t("tab.grab"))
        self.tabs.addTab(self.log_tab, self.i18n.t("tab.log"))
        self.tabs.addTab(self.about_tab, self.i18n.t("tab.about"))

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(self.i18n.t("status.ready"))

        # 语言切换按钮
        self._lang_btn = QPushButton(self.i18n.current_label)
        self._lang_btn.setFixedSize(36, 24)
        self._lang_btn.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        self._lang_btn.setStyleSheet(
            "QPushButton { background-color: #2c3e50; color: #ecf0f1; "
            "border: 1px solid #e94560; border-radius: 3px; padding: 2px 4px; }"
            "QPushButton:hover { background-color: #e94560; }"
        )
        self._lang_btn.setToolTip("Switch Language / 切换语言")
        self._lang_btn.clicked.connect(self.i18n.toggle)
        self.status_bar.addPermanentWidget(self._lang_btn)

    def _connect_signals(self):
        # 登录 → Cookie 获取成功
        self.login_tab.cookie_obtained.connect(self._on_cookie_ready)

        # 选课确认 → 传递到抢课 Tab
        self.course_tab.courses_selected.connect(self._on_courses_confirmed)

        # 抢课开始 / 停止
        self.grab_tab.start_grab.connect(self._start_grab_worker)
        self.grab_tab.stop_grab.connect(self._stop_grab_worker)

    # ── 槽函数 ──
    def _on_cookie_ready(self, _cookie_str: str):
        self.status_bar.showMessage(self.i18n.t("status.cookie_ok"))
        self.tabs.setCurrentIndex(1)  # 自动切换到选课 Tab

    def _on_courses_confirmed(self, course_ids: list, pid: str, used_param: str):
        self.grab_tab.set_courses(course_ids, pid, used_param)
        self.tabs.setCurrentIndex(2)  # 自动切换到抢课 Tab
        self.status_bar.showMessage(
            self.i18n.t("status.courses_sel", n=len(course_ids), pid=pid)
        )

    def _start_grab_worker(self, course_ids: list, pid: str, used_param: str,
                           target_dt: datetime.datetime, prefire_ms: int,
                           interval_ms: int, max_attempts: int):
        cookie = self.cookie_manager.cookie
        if not cookie:
            QMessageBox.warning(self, "提示", "Cookie 未设置，请先登录。")
            self.grab_tab._reset_ui()
            return

        self._grab_worker = GrabWorker(
            cookie, course_ids, pid, used_param,
            target_dt, prefire_ms, interval_ms, max_attempts
        )
        self._grab_worker.log_info.connect(self._on_grab_log)
        self._grab_worker.countdown.connect(self.grab_tab.update_countdown)
        self._grab_worker.stats_update.connect(self.log_tab.update_stats)
        self._grab_worker.grab_done.connect(self._on_grab_done)
        self._grab_worker.start()

        self.tabs.setCurrentIndex(3)  # 自动切换到日志 Tab
        self.status_bar.showMessage(self.i18n.t("status.grab_started"))

    def _stop_grab_worker(self):
        if self._grab_worker and self._grab_worker.isRunning():
            self._grab_worker.stop()
            self._grab_worker.wait(3000)
        self.status_bar.showMessage(self.i18n.t("status.grab_stopped"))

    def _on_grab_log(self, msg: str, color: str):
        self.log_tab.append_log(msg, color)

    def _on_grab_done(self):
        self.grab_tab.on_grab_done()
        self.status_bar.showMessage(self.i18n.t("status.grab_done"))
        self._grab_worker = None

    # ── 窗口事件 ──
    def closeEvent(self, event):
        # 保存窗口位置
        geo_hex = self.saveGeometry().toHex().data().decode()
        self.cookie_manager.save_config("window_geometry", geo_hex)

        # 停止所有后台线程，避免 "QThread: Destroyed while thread is still running"
        self._shutdown_all_workers()
        super().closeEvent(event)

    def _shutdown_all_workers(self):
        """安全终止所有 QThread Worker"""

        def _stop_and_wait(worker, name: str, timeout_ms: int = 5000):
            """通用：发 stop → 等 timeout_ms → 报告"""
            if worker is None:
                return
            if not worker.isRunning():
                return
            if hasattr(worker, "stop"):
                worker.stop()
            worker.quit()
            finished = worker.wait(timeout_ms)
            if not finished:
                worker.terminate()  # 最后手段：强杀
                worker.wait(1000)

        # GrabWorker
        if self._grab_worker:
            _stop_and_wait(self._grab_worker, "GrabWorker", 5000)

        # 各 Tab 内的 Worker
        _stop_and_wait(getattr(self.login_tab, "_login_worker", None), "LoginWorker", 3000)
        _stop_and_wait(getattr(self.login_tab, "_pw_install_worker", None), "InstallWorker", 5000)
        _stop_and_wait(getattr(self.course_tab, "_fetch_worker", None), "FetchCoursesWorker", 3000)


# ============================================================
# 入口
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NuuaXuankeV2")
    app.setOrganizationName("NuuaXuanke")

    # 全局样式
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow {
            background-color: #1a1a2e;
        }
        QTabWidget::pane {
            border: 1px solid #2c3e50;
            background-color: #16213e;
        }
        QTabBar::tab {
            background-color: #0f3460;
            color: #a0a0b0;
            padding: 10px 20px;
            margin-right: 2px;
            font-size: 13px;
        }
        QTabBar::tab:selected {
            background-color: #16213e;
            color: #e94560;
            font-weight: bold;
        }
        QTabBar::tab:hover:!selected {
            background-color: #1a1a4e;
            color: #e0e0e0;
        }
        QLabel {
            color: #ecf0f1;
        }
        QLineEdit, QSpinBox, QDateTimeEdit {
            background-color: #0f3460;
            color: #ecf0f1;
            border: 1px solid #2c3e50;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 13px;
        }
        QLineEdit:focus, QSpinBox:focus, QDateTimeEdit:focus {
            border-color: #e94560;
        }
        QPushButton {
            background-color: #e94560;
            color: white;
            border: none;
            padding: 8px 18px;
            border-radius: 4px;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #c0392b;
        }
        QPushButton:pressed {
            background-color: #a93226;
        }
        QPushButton:disabled {
            background-color: #5a5a6e;
            color: #888;
        }
        QTableWidget {
            background-color: #0f3460;
            color: #ecf0f1;
            gridline-color: #2c3e50;
            border: 1px solid #2c3e50;
            alternate-background-color: #1a1a4e;
        }
        QTableWidget::item:selected {
            background-color: #e94560;
        }
        QHeaderView::section {
            background-color: #16213e;
            color: #e0e0e0;
            padding: 6px;
            border: 1px solid #2c3e50;
            font-weight: bold;
        }
        QGroupBox {
            color: #e0e0e0;
            border: 1px solid #2c3e50;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 16px;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
        }
        QTextBrowser {
            background-color: #0d1b2a;
            color: #bdc3c7;
            border: 1px solid #2c3e50;
            font-family: "Consolas", "Courier New", monospace;
        }
        QProgressBar {
            background-color: #0f3460;
            border: 1px solid #2c3e50;
            border-radius: 3px;
            text-align: center;
            color: white;
        }
        QProgressBar::chunk {
            background-color: #e94560;
            border-radius: 2px;
        }
        QStatusBar {
            background-color: #0f3460;
            color: #bdc3c7;
        }
        QSpinBox::up-button, QSpinBox::down-button {
            background-color: #16213e;
            border: 1px solid #2c3e50;
        }
        QFrame[HLine="true"] {
            color: #2c3e50;
        }
    """)

    window = XuankeApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
