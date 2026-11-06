# -*- coding: utf-8 -*-
"""工具栏条 / 地址栏条 "整片空白" 专项回归。

现象：切换（或启动后）两条条带所在位置是一片白，按钮图标不见了。
判定手段（沿用已验证的做法）：
  1) 把与主窗口相交的其它顶层窗口临时压到 HWND_BOTTOM，主窗口置前；
  2) 直接 BitBlt 抓屏幕，统计条带里"按钮图标"区域的深色像素数。
     - 有图标：深色像素 >= 阈值
     - 空白条：深色像素 ~0（只剩底色）
三组：
  A 启动默认（两条都显示）
  B 查看菜单里 工具栏/地址栏 各关一次（应整条消失，下面上移）
  C 再各开一次（必须原样回来：可见 + 有图标）
C 是最关键的一组：只 MoveWindow 而漏了 ShowWindow(SW_SHOW) 的话，
条带会一直停在隐藏态，但布局仍给它留了高度 —— 屏幕上就是一条白。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))
SRCCOPY = 0x00CC0020
WM_COMMAND = 0x0111
CMD_TOGGLE_TOOLBAR = 20046; CMD_TOGGLE_ADDRBAR = 20047
SW_SHOWNORMAL = 1; HWND_TOP = 0; HWND_BOTTOM = 1
SWP_NOMOVE = 0x0002; SWP_NOSIZE = 0x0001; SWP_NOACTIVATE = 0x0010

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.IsIconic.argtypes = [w.HWND]; u.IsIconic.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetForegroundWindow.argtypes = [w.HWND]; u.SetForegroundWindow.restype = ctypes.c_bool
u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]; u.ShowWindow.restype = ctypes.c_bool
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool
g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC,
                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]; g.BitBlt.restype = ctypes.c_bool
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
                        ctypes.c_void_p, ctypes.c_uint]


class BI(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


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


p = subprocess.Popen([EXE, r"C:\Windows"]); PID.value = p.pid
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
bars = kids.get("FFToolBar", [])
tab = kids.get("FFTabBar", [None])[0]
if len(bars) < 2 or not tab:
    print("RESULT: SKIP 条带/标签栏不全"); p.kill(); sys.exit(0)


def rect_of(h):
    r = w.RECT(); u.GetWindowRect(h, ctypes.byref(r)); return r


by = sorted(bars, key=lambda h: rect_of(h).top)
tb, ab = by[0], by[1]

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
time.sleep(0.6)


def dark(x0, y0, x1, y1, thr=140):
    """抓屏幕矩形，统计非白（图标/文字）像素数。"""
    ww, hh = x1 - x0, y1 - y0
    if ww <= 0 or hh <= 0: return -1
    sdc = u.GetDC(0); mem = g.CreateCompatibleDC(sdc); bmp = g.CreateCompatibleBitmap(sdc, ww, hh)
    old = g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, ww, hh, sdc, x0, y0, SRCCOPY)
    bi = BI(); bi.biSize = ctypes.sizeof(BI); bi.biWidth = ww; bi.biHeight = -hh
    bi.biPlanes = 1; bi.biBitCount = 32
    px = (ctypes.c_ubyte * (ww * hh * 4))()
    g.GetDIBits(mem, bmp, 0, hh, px, ctypes.byref(bi), 0)
    g.SelectObject(mem, old); g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, sdc)
    n = 0
    for i in range(ww * hh):
        o = i * 4
        if px[o] < thr and px[o + 1] < thr and px[o + 2] < thr: n += 1
    return n


def probe(h, tag):
    """量一条：可见性 + 左侧按钮区（前 5 个按钮宽度）图标像素。"""
    r = rect_of(h)
    vis = bool(u.IsWindowVisible(h))
    x0, x1 = r.left + 2, r.left + 152
    y0, y1 = r.top + 3, r.bottom - 3
    n = dark(x0, y0, x1, y1)
    print("  %-8s 可见=%-5s 矩形=[%d,%d] 按钮区图标像素=%d -> %s"
          % (tag, vis, r.top, r.bottom, n,
             "有图标" if n >= 80 else ("空白!!!" if vis else "已隐藏(空位)")))
    return vis, n


ok = True
print("A 启动默认：")
v_tb0, n_tb0 = probe(tb, "工具栏条")
v_ab0, n_ab0 = probe(ab, "地址栏条")
ok &= v_tb0 and v_ab0 and n_tb0 >= 80 and n_ab0 >= 80


def toggle(cmd):
    u.SendMessageW(main, WM_COMMAND, cmd, 0); time.sleep(0.7)


print("B 两条都隐藏：")
toggle(CMD_TOGGLE_TOOLBAR); toggle(CMD_TOGGLE_ADDRBAR)
v_tb1, n_tb1 = probe(tb, "工具栏条")
v_ab1, n_ab1 = probe(ab, "地址栏条")
ok &= (not v_tb1) and (not v_ab1)

print("C 两条再显示（关键：必须真的回来，且不是白条）：")
toggle(CMD_TOGGLE_ADDRBAR); toggle(CMD_TOGGLE_TOOLBAR)
v_tb2, n_tb2 = probe(tb, "工具栏条")
v_ab2, n_ab2 = probe(ab, "地址栏条")
ok &= v_tb2 and v_ab2 and n_tb2 >= 80 and n_ab2 >= 80

tab_r = rect_of(tab)
print("标签栏 top=%d（两条都显示时应 >= 72）" % tab_r.top)
ok &= tab_r.top >= 72

# D 切回后 z 序：地址框仍要压在地址栏条之上（否则又变成"点不到/被涂白"）
kids2 = {}


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb2(h, l):
    kids2.setdefault(cls(h), []).append(h); return True


u.EnumChildWindows(main, kcb2, 0)
addrbox = None
for c in kids2.get("ComboBox", []):
    r = rect_of(c)
    if r.top >= rect_of(ab).top - 4 and r.bottom <= rect_of(ab).bottom + 4:
        addrbox = c; break
u.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.ChildWindowFromPointEx.argtypes = [w.HWND, w.POINT, ctypes.c_uint]
u.ChildWindowFromPointEx.restype = w.HWND
if addrbox:
    ar = rect_of(addrbox)
    pt = w.POINT((ar.left + ar.right) // 2, (ar.top + ar.bottom) // 2)
    u.ScreenToClient(main, ctypes.byref(pt))
    hit = u.ChildWindowFromPointEx(main, pt, 0)
    print("D 切回后地址框命中=%s -> %s" % (cls(hit), "OK" if cls(hit) == "ComboBox" else "!!! 被条带盖住"))
    ok &= cls(hit) == "ComboBox"
else:
    print("D 切回后找不到地址框 -> !!!"); ok = False

print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)
for h in pushed: u.SetWindowPos(h, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
