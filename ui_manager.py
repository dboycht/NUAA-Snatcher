# -*- coding:utf-8 -*-
"""
:keyword NUAA QianKe
Fuck UI program
"""
from PySide6.QtWidgets import QApplication
from PySide6.QtUiTools import QUiLoader
from PySide6 import QtGui
import webbrowser
import datetime
import re
import time
import sys
import requests
import zlib
import gzip
from sys import exit
BASE = "https://aao-eas.nuaa.edu.cn"
HOME_URL = f"{BASE}/eams/homeExt.action"
DEFAULT_TPL = f"{BASE}/eams/stdElectCourse!defaultPage.action?electionProfile.id={{pid}}"
REQUEST_TIMEOUT = 5
POST_INTERVAL = 0.7
BACKOFF_SECONDS = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ID_PATTERNS = [
    re.compile(r"(?:\bprofileId\b|\belectionProfile\.id\b)\s*[:=]\s*['\"]?(\d+)"),
    re.compile(r"(?:\?|&)(?:profileId|electionProfile\.id)=(\d+)"),
]
def is_login_bounce(resp_) -> bool:
    try:
        url_l = resp_.url.lower()
    except Exception:
        url_l = ""
    text = ""
    try:
        text = resp_.text
    except Exception:
        pass
    return ("统一身份认证" in text) or ("authserver" in url_l)
def smart_read(resp_):
    raw = resp_.content or b""
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
def make_session(cookie_str: str, pid: str, printf) -> requests.Session:
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
def _extract_profile_ids(html: str):
    hits = []
    for pat in _ID_PATTERNS:
        hits += pat.findall(html)
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out
def _try_fetch_data(session: requests.Session, pid: str):
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
def grab_courses(open_at:str,
                 session: requests.Session,
                 lesson_ids,
                 pid: str,
                 used_param: str,
                 printf,
                 late_time:int=5):
    dt = datetime.datetime.strptime(open_at, "%Y-%m-%d %H:%M:%S")
    ago = dt - datetime.timedelta(minutes=late_time)
    base_post = f"{BASE}/eams/stdElectCourse!batchOperator.action"
    if used_param == "profileId":
        post_urls = [f"{base_post}?profileId={pid}", f"{base_post}?electionProfile.id={pid}"]
    else:
        post_urls = [f"{base_post}?electionProfile.id={pid}", f"{base_post}?profileId={pid}"]
    forms = [{"optype": "true", "operator0": f"{cid}:true:0", "lesson0": cid} for cid in lesson_ids]
    post_min_gap = 0.8
    last_post_ts = 0.0
    printf("\n开始等待放闸时间……")
    while True:
        now = datetime.datetime.now()
        if now >= ago:
            for data in forms:
                sent_ok = False
                for url in post_urls:
                    gap = time.monotonic() - last_post_ts
                    if gap < post_min_gap:
                        time.sleep(post_min_gap - gap)
                    try:
                        resp_ = session.post(url, data=data, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                        last_post_ts = time.monotonic()
                        if is_login_bounce(resp_):
                            continue
                        body, enc = smart_read(resp_)
                        chinese = re.findall(r"([\u4e00-\u9fa5]+)", body)
                        msg = "".join(chinese) or body[:180]
                        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        printf(f"[{ts}] {resp_.status_code} -> {msg}")
                        sent_ok = True
                        if ("请不要过快点击" in body) or (resp_.status_code in (429, 503)):
                            time.sleep(BACKOFF_SECONDS)
                        break
                    except Exception:
                        continue
                if not sent_ok:
                    printf("提交未成功：两个提交地址都被重定向或异常")
        else:
            remain = dt - now
            printf(f"抢课界面未开启，剩余：{remain}")
        time.sleep(POST_INTERVAL)
def resp():
    webbrowser.open("https://github.com/dboycht/NUAA-Snatcher")
def egg():
    webbrowser.open("https://www.bilibili.com/video/BV1GJ411x7h7")
class Stats(object):
    def __init__(self):
        self.ui = QUiLoader().load('./snatcher.ui')
        self.ui.setWindowIcon(QtGui.QIcon("icon.ico"))
        self.whether_load = False
        self.pid = ""
        self.cookie = ""
        self.session = None
        self.chose_list = []
        self.n = 0
        self.id_list = []
        self.name_list = []
        self.teacher_list = []
        self.used_p = ""
        self.ui.commandLinkButton.clicked.connect(self.go)
        self.ui.commandLinkButton_2.clicked.connect(self.load_base)
        self.ui.pushButton.clicked.connect(self.load_all)
        self.ui.pushButton_2.clicked.connect(self.load_list)
        self.ui.pushButton_3.clicked.connect(self.search)
        self.ui.pushButton_4.clicked.connect(self.add_list)
        self.ui.pushButton_5.clicked.connect(self.del_list)
        self.ui.actionExit.triggered.connect(exit)
        self.ui.action_2.triggered.connect(egg)
        self.ui.action.triggered.connect(resp)
    def printf(self, messages:str):
        self.ui.plainTextEdit.appendPlainText(messages)
        return True
    def load_base(self):
        self.pid = self.ui.textEdit.toPlainText().strip()[-4::]
        try:
            int(self.pid)
        except ValueError:
            self.printf("错误(0X01): URL输入错误, 请检查URL是否有ID信息")
            return False
        else:
            self.printf("="*30)
            self.cookie = self.ui.textEdit_2.toPlainText().strip()
            self.printf(f"加载URL-ID&Cookies\nID:{self.pid}\nCookie:{self.cookie}")
            self.session = make_session(self.cookie, self.pid, self.printf)
            (self.id_list,
             self.name_list,
             self.teacher_list,
             self.n, pid,
             self.used_p) = course_info(self.session, self.pid, self.printf)
        return True
    def add_list(self):
        if not self.n:
            self.printf("Error0X13: data无数据")
            return False
        try:
            want_index = int(self.ui.textEdit_5.toPlainText().strip())
        except ValueError:
            self.printf("Error0X09: 输入序列号有问题")
            return False
        else:
            if want_index>=self.n:
                self.printf("Error0X10: 输入序列号超出范围")
                return False
            if self.id_list[want_index] in self.chose_list:
                self.printf("Error0X11: 已经添加过该课程")
                return False
            self.chose_list.append(self.id_list[want_index])
            self.printf(f"id:{self.id_list[want_index]}已成功添加到队列")
            return True
    def del_list(self):
        if not self.n:
            self.printf("Error0X14: 选择列表无数据")
            return False
        try:
            want_index = int(self.ui.textEdit_5.toPlainText().strip())
        except ValueError:
            self.printf("Error0X09: 输入序列号有问题")
            return False
        else:
            if want_index >= self.n:
                self.printf("Error0X10: 输入序列号超出范围, 不在全部课程内")
                return False
            kill_id = self.id_list[want_index]
            try:
                kill_idx = self.chose_list.index(kill_id)
            except ValueError:
                self.printf("Error0X11: 在您的队列中未找到该序号")
                return False
            self.chose_list.pop(kill_idx)
            self.printf(f"队列中id:{self.id_list[want_index]}已成功删除")
            return True
    def go(self):
        time_str = self.ui.dateTimeEdit.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        delta = self.ui.spinBox.value()
        if self.whether_load or len(self.chose_list)==0 or not self.session:
            self.printf("="*30)
            self.printf("请检查是否正确配置或者任务队列是否有内容")
            return False
        self.load_list()
        grab_courses(time_str,
                     self.session,
                     self.chose_list,
                     self.pid,
                     self.used_p,
                     self.printf,
                     delta)
        return True
    def search(self):
        if self.n == 0:
            self.printf("Error0X16: 请检查是否正确加载数据")
            return False
        name_piece = self.ui.lineEdit.text().strip()
        for searcher in range(self.n):
            if name_piece in self.teacher_list[searcher]:
                self.ui.textEdit_4.setText(str(searcher))
                return True
        self.ui.textEdit_4.setText(str("未找到"))
        self.printf("没有找到喵, 请检查输入情况")
        return True
    def load_all(self):
        if self.n == 0 or self.id_list == [] or self.name_list==[] or self.teacher_list==[]:
            self.printf("Error0X06: 尚未加载网页数据")
            return False
        for i in range(self.n):
            self.printf("="*30)
            self.printf(f"序号: {i:<3}  "
                        f"课程ID: {self.id_list[i]:<10}  "
                        f"课程名称: {self.name_list[i]}  "
                        f"教师名称: {self.teacher_list[i] < 4}")
        return True
    def load_list(self):
        if not self.chose_list:
            self.printf("="*30)
            self.printf("Error0X08: 队列中无内容")
            return False
        for i in self.chose_list:
            idx = self.id_list.index(i)
            self.printf(f"序号: {idx:<3}  "
                        f"课程ID: {self.id_list[idx]:<10}  "
                        f"课程名称: {self.name_list[idx]}  "
                        f"教师名称: {self.teacher_list[idx] < 4}")
        return True
if __name__ == '__main__':
    app = QApplication([])
    stats = Stats()
    stats.ui.show()
    app.exec()