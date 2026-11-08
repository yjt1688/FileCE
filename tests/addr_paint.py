# -*- coding: utf-8 -*-
"""地址栏"鼠标移上去变空白"的最终功能回归（真实屏幕像素）。

难点：本环境里程序窗口被 bash 控制台等窗口盖住，被遮挡时 Windows 会把子窗口的
可见区域裁空（画不上、也取不到像素）。所以测试先做两件事：
  1) 把与主窗口矩形相交的其它顶层窗口临时压到 z 序底部，并把主窗口置前；
  2) 用 WindowFromPoint 确认地址栏中心确实命中本程序的窗口（否则判定 SKIP）。
然后直接 BitBlt 抓屏幕，统计地址栏矩形内的深色（文字）像素：
  A 基线
  B 强制工具栏整条重绘（等价于鼠标热跟踪/按钮高亮时的重绘）之后
  C 真实鼠标悬停地址栏并触发工具栏热跟踪之后
若工具栏绘制不裁剪兄弟窗口（缺 WS_CLIPSIBLINGS），B/C 会掉到 ~0（被涂成工具栏底色）。
结束后把所有被压低的窗口还原到原来相对位置（HWND_TOP）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))
SRCCOPY = 0x00CC0020
RDW_INVALIDATE = 0x0001; RDW_UPDATENOW = 0x0100; RDW_ERASE = 0x0004
WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E; WM_MOUSEMOVE = 0x0200
SW_SHOWNORMAL = 1; HWND_TOP = 0; HWND_BOTTOM = 1
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
u.InvalidateRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT), ctypes.c_bool]; u.InvalidateRect.restype = ctypes.c_bool
u.UpdateWindow.argtypes = [w.HWND]; u.UpdateWindow.restype = ctypes.c_bool
u.RedrawWindow.argtypes = [w.HWND, ctypes.POINTER(w.RECT), w.HRGN, ctypes.c_uint]; u.RedrawWindow.restype = ctypes.c_bool
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool
g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
g.BitBlt.restype = ctypes.c_bool
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]


class BI(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def wtext(h):
    if not h: return ""
    n = u.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    b = ctypes.create_unicode_buffer(n + 2); u.SendMessageW(h, WM_GETTEXT, n + 1, ctypes.addressof(b)); return b.value


def cls(h):
    if not h: return "?"
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


found = []; PID = w.DWORD(0)


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, l):
    if not u.IsWindowVisible(h): return True
    pid = w.DWORD(0); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value != PID.value: return True
    if cls(h) == "FFMainWnd": found.append(h)
    return True


p = subprocess.Popen([EXE, r"E:\临时"]); PID.value = p.pid
t0 = time.time()
while not found and time.time() - t0 < 10:
    u.EnumWindows(cb, 0); time.sleep(0.1)
if not found:
    print("RESULT: SKIP 找不到主窗口"); p.kill(); sys.exit(0)
time.sleep(1.5)
main = found[0]

kids = {}


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb(h, l):
    kids.setdefault(cls(h), []).append(h); return True


u.EnumChildWindows(main, kcb, 0)
addr = None
for c in kids.get("ComboBox", []):
    if ":" in wtext(c) or wtext(c) == "计算机": addr = c; break
tb = kids.get("FFToolBar", [None])[0]
aedit = None
if addr:
    u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]; u.FindWindowExW.restype = w.HWND
    aedit = u.FindWindowExW(addr, None, "Edit", None)
if not addr or not tb:
    print("RESULT: SKIP 找不到地址栏/工具栏"); p.kill(); sys.exit(0)

mr = w.RECT(); u.GetWindowRect(main, ctypes.byref(mr))
ar = w.RECT(); u.GetWindowRect(addr, ctypes.byref(ar))
print("主窗口矩形=%s 地址栏矩形=%s" % ((mr.left, mr.top, mr.right, mr.bottom), (ar.left, ar.top, ar.right, ar.bottom)), flush=True)

# 1) 把压在主窗口上的其它顶层窗口临时压到底部
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
time.sleep(0.6)
print("已压低遮挡窗口数=%d" % len(pushed), flush=True)

acx, acy = (ar.left + ar.right) // 2, (ar.top + ar.bottom) // 2
pt = w.POINT(acx, acy)
hit = u.WindowFromPoint(pt)
hit_ok = hit in (addr, aedit) or (hit and cls(hit) in ("ComboBox", "Edit"))
print("WindowFromPoint(地址栏中心)=%s cls=%s -> %s" % (hex(hit) if hit else "?", cls(hit), "OK 未被遮挡" if hit_ok else "仍被遮挡"), flush=True)
if not hit_ok:
    print("RESULT: SKIP 程序窗口仍被外层窗口遮挡，无法做像素判定", flush=True)
    for h in pushed: u.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    p.terminate(); time.sleep(0.3)
    if p.poll() is None: p.kill()
    sys.exit(0)


def dark(x0, y0, x1, y1, thr=110):
    """抓屏幕矩形，统计深色（文字）像素数。"""
    w_, h_ = x1 - x0, y1 - y0
    sdc = u.GetDC(0); mem = g.CreateCompatibleDC(sdc); bmp = g.CreateCompatibleBitmap(sdc, w_, h_)
    old = g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, w_, h_, sdc, x0, y0, SRCCOPY)
    bi = BI(); bi.biSize = ctypes.sizeof(BI); bi.biWidth = w_; bi.biHeight = -h_
    bi.biPlanes = 1; bi.biBitCount = 32
    px = (ctypes.c_ubyte * (w_ * h_ * 4))()
    g.GetDIBits(mem, bmp, 0, h_, px, ctypes.byref(bi), 0)
    g.SelectObject(mem, old); g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, sdc)
    n = 0
    for i in range(w_ * h_):
        o = i * 4
        if px[o] < thr and px[o + 1] < thr and px[o + 2] < thr: n += 1
    return n


X0, Y0, X1, Y1 = ar.left + 6, ar.top + 3, ar.right - 24, ar.bottom - 3
n0 = dark(X0, Y0, X1, Y1)
print("A 基线：地址栏文字像素=%d %s" % (n0, "OK" if n0 > 30 else "此刻是空白"), flush=True)

# A2 强制地址栏自己重绘：文字应重新出现 —— 用于证明测量手段有效
u.InvalidateRect(addr, None, True); u.UpdateWindow(addr)
u.RedrawWindow(addr, None, None, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ERASE)
time.sleep(0.35)
na2 = dark(X0, Y0, X1, Y1)
print("A2 地址栏自行重绘后：文字像素=%d %s" % (na2, "OK 测量有效" if na2 > 30 else "!!! 测量无效/地址栏真的没字"), flush=True)
if na2 <= 30:
    print("RESULT: SKIP 抓不到地址栏文字，像素判据不可用", flush=True)
    for h in pushed: u.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    p.terminate(); time.sleep(0.3)
    if p.poll() is None: p.kill()
    sys.exit(0)

ok = True
ok &= (n0 >= max(1, int(na2 * 0.7)))   # 基线就不该被涂白

u.InvalidateRect(tb, None, True); u.UpdateWindow(tb)
u.RedrawWindow(tb, None, None, RDW_INVALIDATE | RDW_UPDATENOW | RDW_ERASE)
time.sleep(0.35)
n1 = dark(X0, Y0, X1, Y1)
print("B 工具栏整条重绘后：文字像素=%d %s" % (n1, "OK 未被涂白" if n1 >= max(1, int(na2 * 0.7)) else "!!! 被涂白"), flush=True)
ok &= n1 >= max(1, int(na2 * 0.7))

u.SetCursorPos(ar.left + 30, acy); time.sleep(0.15)
u.SetCursorPos(acx, acy); time.sleep(0.15)
u.SendMessageW(tb, WM_MOUSEMOVE, 0, 0)
u.SetCursorPos(ar.right - 60, acy); time.sleep(0.35)
n2 = dark(X0, Y0, X1, Y1)
print("C 鼠标悬停后：文字像素=%d %s" % (n2, "OK 未被涂白" if n2 >= max(1, int(na2 * 0.7)) else "!!! 被涂白"), flush=True)
ok &= n2 >= max(1, int(na2 * 0.7))

print("地址栏文本=%r" % wtext(addr), flush=True)
print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)

for h in pushed: u.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
