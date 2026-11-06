# -*- coding: utf-8 -*-
"""复现：隐藏/显示 工具栏条 与 地址栏条 后，下方区域出现"残影"（重复画出的按钮排）。

做法：
  1) 开"计算机"视图（列表内容固定为驱动器，上下移动时重绘量小）
  2) 把压在主窗口上的其它顶层窗口临时压到底层，BitBlt 抓屏幕
  3) 逐行扫描主窗口客户区，输出每一行的深色像素数，定位"成排出现"的深色行
     —— 按钮图形会表现为某几行深色像素骤增，正是残影特征
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


def cls(h):
    if not h: return "?"
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


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
if not found:
    print("RESULT: SKIP 找不到主窗口"); p.kill(); sys.exit(0)
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
cp = w.POINT((mr.left + mr.right) // 2, (mr.top + mr.bottom) // 2)
hit = u.WindowFromPoint(cp)
print("主窗口矩形=%s 中心命中=%s" % ((mr.left, mr.top, mr.right, mr.bottom), cls(hit)), flush=True)

X0, X1 = mr.left + 6, min(mr.right - 6, mr.left + 620)
Y0, Y1 = mr.top + 6, min(mr.bottom - 30, mr.top + 500)


def rowprofile(tag):
    w_, h_, px = snap(X0, Y0, X1, Y1)
    prof = []
    for y in range(h_):
        d = 0
        for x in range(w_):
            o = (y * w_ + x) * 4
            if px[o] < 110 and px[o + 1] < 110 and px[o + 2] < 110: d += 1
        prof.append(d)
    # 找"成排的深色行"：连续 >=3 行且每行深色像素 > 25
    runs = []
    s = None
    for y, d in enumerate(prof):
        if d > 25:
            if s is None: s = y
        else:
            if s is not None and y - s >= 3: runs.append((Y0 + s, Y0 + y - 1))
            s = None
    if s is not None and h_ - s >= 3: runs.append((Y0 + s, Y0 + h_ - 1))
    print("  %-22s 深色行带(屏幕y)=%s" % (tag, runs), flush=True)
    return runs


print("--- 逐行扫描（深色行带=该处有成排图形，正常只应在菜单/工具栏/标签栏行）---", flush=True)
print("窗口顶=%d 高=%d" % (mr.top, mr.bottom - mr.top), flush=True)
a = rowprofile("初始")
b = rowprofile("隐藏工具栏条")
c = rowprofile("再隐藏地址栏条")
d = rowprofile("两条都恢复")

print("--- 判定：恢复后不应在原有行带之外出现新的深色行带 ---", flush=True)
extra = [r for r in d if not any(abs(r[0] - q[0]) <= 3 for q in a)]
ok = not extra
print("恢复后新增行带=%s -> %s" % (extra, "OK" if ok else "!!! 出现残影"), flush=True)
print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)

for h in pushed: u.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
