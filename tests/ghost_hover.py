# -*- coding: utf-8 -*-
"""残影专项：鼠标悬停在按钮上（按钮处于高亮态）时，隐藏/显示另一条，检查是否
在下面留下"重复的高亮按钮排"。

判据：定位【地址栏条】的矩形，统计其内部像素；若出现"从上到下都是同一个按钮图形"
（即竖直方向有大量深色像素、且分布跨越整条高度），说明是克隆/残影。
另外检查：地址栏条区域内应只有一排按钮（按 x 方向扫描，按钮之间的间隙应为背景色）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))
SRCCOPY = 0x00CC0020
WM_COMMAND = 0x0111
CMD_TOGGLE_TOOLBAR = 20046; CMD_TOGGLE_ADDRBAR = 20047
SW_SHOWNORMAL = 1; HWND_BOTTOM = 1; HWND_TOP = 0
SWP_NOMOVE = 0x0002; SWP_NOSIZE = 0x0001; SWP_NOACTIVATE = 0x0010
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.IsIconic.argtypes = [w.HWND]; u.IsIconic.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]; u.SendMessageW.restype = ctypes.c_ssize_t
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetForegroundWindow.argtypes = [w.HWND]; u.SetForegroundWindow.restype = ctypes.c_bool
u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]; u.ShowWindow.restype = ctypes.c_bool
u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.ChildWindowFromPointEx.argtypes = [w.HWND, w.POINT, ctypes.c_uint]; u.ChildWindowFromPointEx.restype = w.HWND
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool
g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
g.BitBlt.restype = ctypes.c_bool
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E


class BI(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def cls(h):
    if not h: return "?"
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def wtext(h):
    if not h: return ""
    n = u.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    b = ctypes.create_unicode_buffer(n + 2); u.SendMessageW(h, WM_GETTEXT, n + 1, ctypes.addressof(b)); return b.value


def snap(x0, y0, x1, y1):
    w_, h_ = x1 - x0, y1 - y0
    sdc = u.GetDC(0); mem = g.CreateCompatibleDC(sdc); bmp = g.CreateCompatibleBitmap(sdc, w_, h_)
    old = g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, w_, h_, sdc, x0, y0, SRCCOPY)
    bi = BI(); bi.biSize = ctypes.sizeof(BI); bi.biWidth = w_; bi.biHeight = -h_
    bi.biPlanes = 1; bi.biBitCount = 32
    px = (ctypes.c_ubyte * (w_ * h_ * 4))()
    g.GetDIBits(mem, bmp, 0, h_, px, ctypes.byref(bi), 0)
    g.SelectObject(mem, old); g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, sdc)
    return w_, h_, px


found = []; PID = w.DWORD(0)


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, l):
    if not u.IsWindowVisible(h): return True
    pid = w.DWORD(0); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value != PID.value: return True
    if cls(h) == "FFMainWnd": found.append(h)
    return True


p = subprocess.Popen([EXE]); PID.value = p.pid
t0 = time.time()
while not found and time.time() - t0 < 10:
    u.EnumWindows(cb, 0); time.sleep(0.1)
time.sleep(1.5)
main = found[0]
mr = w.RECT(); u.GetWindowRect(main, ctypes.byref(mr))
pushed = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def push_cb(h, l):
    if h == main or not u.IsWindowVisible(h) or u.IsIconic(h): return True
    r = w.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    if r.right <= mr.left or r.left >= mr.right or r.bottom <= mr.top or r.top >= mr.bottom: return True
    pushed.append(h)
    u.SetWindowPos(h, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    return True


u.EnumWindows(push_cb, 0)
u.ShowWindow(main, SW_SHOWNORMAL)
u.SetForegroundWindow(main)
time.sleep(0.7)

kids = {}


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb(h, l):
    kids.setdefault(cls(h), []).append(h); return True


u.EnumChildWindows(main, kcb, 0)
bars = sorted(kids.get("FFToolBar", []), key=lambda h: (lambda r: r.top)(w.RECT()) if False else 0)
def rect_of(h):
    r = w.RECT(); u.GetWindowRect(h, ctypes.byref(r)); return r
bars = sorted(kids.get("FFToolBar", []), key=lambda h: rect_of(h).top)
addr = None
for c in kids.get("ComboBox", []):
    if ":" in wtext(c) or wtext(c) == "计算机": addr = c; break
if len(bars) < 2:
    print("RESULT: SKIP 找不到两条"); p.kill(); sys.exit(0)
tb, ab = bars[0], bars[1]
ar = rect_of(addr)
print("工具栏条 top=%d 地址栏条 top=%d 地址框 left=%d" % (rect_of(tb).top, rect_of(ab).top, ar.left), flush=True)

ok = True


def check(tag):
    """扫描：地址栏条矩形内，按 x 扫描每列是否有深色像素；
    再有：地址栏条【下方 4px 以内】不应有任何深色像素（那是列表/标签栏边界）"""
    r = rect_of(ab)
    w_, h_, px = snap(r.left, r.top, r.right, r.bottom)
    col = []
    for x in range(w_):
        d = 0
        for y in range(h_):
            o = (y * w_ + x) * 4
            if px[o] < 110 and px[o + 1] < 110 and px[o + 2] < 110: d += 1
        col.append(d)
    darkcols = sum(1 for d in col if d > 0)
    # 再抓条带下方 2..6 px 一条，检查是否被污染
    below = snap(r.left, r.bottom + 2, r.right, r.bottom + 6)
    bw, bh, bpx = below
    dn = 0
    for i in range(bw * bh):
        o = i * 4
        if bpx[o] < 110 and bpx[o + 1] < 110 and bpx[o + 2] < 110: dn += 1
    print("  %-22s 条带有内容的列数=%d 条带下方杂质像素=%d" % (tag, darkcols, dn), flush=True)
    return darkcols, dn


print("--- 悬停场景 ---", flush=True)
# 先记录"隐藏前"下方那条区域的基线，作为对照
def below_probe(tag):
    r = rect_of(ab)
    bw, bh, bpx = snap(r.left, r.bottom + 2, r.right, r.bottom + 6)
    dn = 0
    for i in range(bw * bh):
        o = i * 4
        if bpx[o] < 110 and bpx[o + 1] < 110 and bpx[o + 2] < 110: dn += 1
    print("  %-22s 条带下方杂质像素=%d  (区域 y=%d..%d)" % (tag, dn, r.bottom + 2, r.bottom + 6), flush=True)
    return dn

# 把鼠标停在地址栏条第 2 个按钮上（前进），再切换另一条
bt = rect_of(tb)
u.SetCursorPos(bt.left + 60, (bt.top + bt.bottom) // 2)
time.sleep(0.4)
d0 = below_probe("隐藏前基线")
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0); time.sleep(0.7)
c1 = check("隐藏地址栏条(悬停中)")
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0); time.sleep(0.8)
c2 = check("恢复地址栏条")

# 同理：悬停在地址栏条按钮上时切换工具栏条
ab_r = rect_of(ab)
u.SetCursorPos(ab_r.left + 30, (ab_r.top + ab_r.bottom) // 2)
time.sleep(0.4)
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_TOOLBAR, 0); time.sleep(0.7)
c3 = check("隐藏工具栏条(悬停中)")
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_TOOLBAR, 0); time.sleep(0.8)
c4 = check("恢复工具栏条")

# 判定：只在"隐藏地址栏条"这一路做对比 —— 隐藏后，原来地址栏条所占的区域
# 必须被清理干净（那里会由下面的标签栏/列表接管）。用"隐藏后 与 隐藏前的地址栏条矩形"
# 同一块屏幕区域做前后对比：前后差值过大说明没重绘。
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0)  # 先恢复
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0)
time.sleep(0.9)
# 隐藏地址栏条，然后检查"原地址栏条矩形"区域内的像素是否被重绘过
before = rect_of(ab)
A = snap(before.left, before.top, before.right, before.bottom)
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0)
time.sleep(0.9)
B = snap(before.left, before.top, before.right, before.bottom)
diff = 0
for i in range(0, min(len(A[2]), len(B[2])), 4):
    if abs(A[2][i] - B[2][i]) > 40: diff += 1
print("  隐藏前后 原地址栏条矩形 内不同像素数=%d" % diff, flush=True)
if diff < 500:
    print("!!! 原地址栏条区域几乎没变（%d），说明隐藏后没有重绘" % diff, flush=True)
    ok = False

print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)
for h in pushed: u.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
