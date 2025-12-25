# -*- coding: utf-8 -*-
import datetime
import re
import time
import sys
import requests
import zlib
import gzip

BASE = "https://aao-eas.nuaa.edu.cn"
HOME_URL = f"{BASE}/eams/homeExt.action"
DEFAULT_TPL = f"{BASE}/eams/stdElectCourse!defaultPage.action?electionProfile.id={{pid}}"

# ===== 行为参数 =====
REQUEST_TIMEOUT = 5          # 每次请求超时（秒）
POST_INTERVAL = 0.7          # 提交间隔（秒），过快会触发“请不要过快点击”
BACKOFF_SECONDS = 3          # 命中限速提示后的退避（秒）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ID_PATTERNS = [
    re.compile(r"(?:\bprofileId\b|\belectionProfile\.id\b)\s*[:=]\s*['\"]?(\d+)"),
    re.compile(r"(?:\?|&)(?:profileId|electionProfile\.id)=(\d+)"),
]

def is_login_bounce(resp) -> bool:
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
    # 先尝试按 headers 的 Content-Encoding 自动解压；requests 通常会处理，这里再兜底
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

    # 优先用服务器声明的编码与 requests 的检测
    for enc in [getattr(resp, "encoding", None), getattr(resp, "apparent_encoding", None),
                "utf-8", "gb18030", "gbk", "gb2312", "latin1"]:
        if not enc:
            continue
        try:
            return raw.decode(enc, errors="ignore"), enc
        except Exception:
            continue
    # 兜底
    return raw.decode("utf-8", errors="ignore"), "utf-8"


def make_session(cookie_str: str, pid: str, printf) -> requests.Session:
    """
    请求主
    :param printf: Print function
    :param cookie_str: 曲奇
    :param pid: ID
    :return:
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Cookie": cookie_str.strip(),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": BASE,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    s.get(HOME_URL, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    referer = DEFAULT_TPL.format(pid=pid)
    s.get(referer, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    s.headers.update({
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    })
    rchk = s.get(f"{BASE}/eams/home.action", timeout=REQUEST_TIMEOUT, allow_redirects=True)
    if is_login_bounce(rchk):
        printf("错误(0X02): Cookie未生效或已过期, 请检查")
    return s

# ============ 拉取课程列表辅助 ============

def _extract_profile_ids(html: str):
    hits = []
    for pat in _ID_PATTERNS:
        hits += pat.findall(html)
    # 去重保序
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out

def _try_fetch_data(session: requests.Session, pid: str):
    """尝试两种参数名去拉 data.action；返回 (status, text, used_param)"""
    url1 = f"{BASE}/eams/stdElectCourse!data.action?electionProfile.id={pid}"
    r1 = session.get(url1, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    t1, _ = smart_read(r1)
    if r1.status_code == 200 and "id:" in t1 and "<html" not in t1.lower():
        return r1.status_code, t1, "electionProfile.id"

    url2 = f"{BASE}/eams/stdElectCourse!data.action?profileId={pid}"
    r2 = session.get(url2, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    t2, _ = smart_read(r2)
    return r2.status_code, t2, "profileId"

def course_info(session: requests.Session, pid: str, printf):
    """
    读取主网页
    :param printf:
    :param session:
    :param pid:
    :return: id_list n pid used
    """
    status, text, used = _try_fetch_data(session, pid)
    if status != 200 or "id:" not in text or "<html" in text.lower():
        warm = session.get(DEFAULT_TPL.format(pid=pid), timeout=REQUEST_TIMEOUT, allow_redirects=True)
        candidates = _extract_profile_ids(warm.text)
        if not candidates:
            dp = session.get(f"{BASE}/eams/stdElectCourse!defaultPage.action",
                             timeout=REQUEST_TIMEOUT, allow_redirects=True)
            candidates = _extract_profile_ids(dp.text)
        for cand in ([pid] + candidates):
            status, text, used = _try_fetch_data(session, cand)
            if status == 200 and "id:" in text and "<html" not in text.lower():
                pid = cand
                break

    if status != 200 or "id:" not in text or "<html" in text.lower():
        printf("="*30)
        printf("课程列表请求返回异常状态码：", status)
        printf(text[:300])
        sys.exit(1)
    print(text)
    # 解析课程
    find_id = re.compile(r"id:(\d+),")
    find_name = re.compile(r"name:'([^']*)',")
    find_teacher = re.compile(r"teachers:'([^']*)',")
    id_list = find_id.findall(text)
    name_list = []
    teacher_list = []
    for item in text.split("code:"):
        m = find_name.findall(item)
        t = find_teacher.findall(item)
        if m:
            name_list.append(m[0])
            teacher_list.append(t[0])
        else:
            break

    if not id_list:
        printf("Error0X03: 未解析到任何课程 ID，返回片段：", text[:300])
        sys.exit(1)

    n = min(len(id_list), len(name_list))
    printf("\n命中的选课档案ID:", pid, f"(参数名 {used})")
    printf("可选课程：")
    for i in range(n):
        printf(f"序号: {i:<3}  课程ID: {id_list[i]:<10}  课程名称: {name_list[i]}  教师名称: {teacher_list[i]<4}")


    return id_list, name_list, teacher_list, n, pid, used


# ============ 提交选课 ============

def grab_courses(open_at:str,
                 session: requests.Session,
                 lesson_ids,
                 pid: str,
                 used_param: str,
                 printf,
                 late_time:int=5):
    """
    提交主程序
    :param session:
    :param lesson_ids:
    :param pid:
    :param used_param:
    :return:
    """
    # open_at: str = "2025-9-16 16:00:00"

    dt = datetime.datetime.strptime(open_at, "%Y-%m-%d %H:%M:%S")
    ago = dt - datetime.timedelta(minutes=late_time)
    base_post = f"{BASE}/eams/stdElectCourse!batchOperator.action"
    if used_param == "profileId":
        post_urls = [f"{base_post}?profileId={pid}", f"{base_post}?electionProfile.id={pid}"]
    else:
        post_urls = [f"{base_post}?electionProfile.id={pid}", f"{base_post}?profileId={pid}"]

    forms = [{"optype": "true", "operator0": f"{cid}:true:0", "lesson0": cid} for cid in lesson_ids]

    # ——新增：两次提交的最小全局间隔，避免同一时间内多次提交——
    post_min_gap = 0.8  # 可按需调到 1.6～1.8 更稳
    last_post_ts = 0.0  # monotonic 时间戳

    printf("\n开始等待放闸时间……")
    while True:
        now = datetime.datetime.now()
        if now >= ago:
            for data in forms:
                sent_ok = False
                for url in post_urls:
                    # ——限速关键处：每次真正提交前，确保与上次提交至少间隔 POST_MIN_GAP——
                    gap = time.monotonic() - last_post_ts
                    if gap < post_min_gap:
                        time.sleep(post_min_gap - gap)

                    try:
                        resp = session.post(url, data=data, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                        # 记录“这次提交已经发生”
                        last_post_ts = time.monotonic()

                        # 被踢回统一认证，视为失败，换下一个 URL
                        if is_login_bounce(resp):
                            continue

                        body, enc = smart_read(resp)
                        chinese = re.findall(r"([\u4e00-\u9fa5]+)", body)
                        msg = "".join(chinese) or body[:180]
                        # 用当前时间打印更准确
                        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        printf(f"[{ts}] {resp.status_code} -> {msg}")

                        sent_ok = True
                        if ("请不要过快点击" in body) or (resp.status_code in (429, 503)):
                            time.sleep(BACKOFF_SECONDS)
                        break
                    except Exception:
                        # 提交异常也算一次尝试，已限速；继续下一个 URL
                        continue

                if not sent_ok:
                    printf("提交未成功：两个提交地址都被重定向或异常")
        else:
            remain = dt - now
            printf(f"抢课界面未开启，剩余：{remain}")

        # 维持你原有的外层节奏
        time.sleep(POST_INTERVAL)