# -*- coding: utf-8 -*-
"""验证标签文字真的画出来了（像素统计，不靠猜）。
   TEXT 颜色 RGB(32,32,32)，背景 RGB(238,238,238) → 数暗像素即可。"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")
k = ctypes.WinDLL("kernel32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.GetDC.argtypes = [w.HWND]
u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
g.CreateCompatibleDC.argtypes = [w.HDC]
g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HANDLE]
g.SelectObject.restype = w.HANDLE
g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD]
g.DeleteObject.argtypes = [w.HANDLE]
g.DeleteDC.argtypes = [w.HDC]

CMD_TAB_NEW = 20040
WM_COMMAND = 0x0111
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "build", "FileCE.exe")
WORK = os.path.join(ROOT, "build", "_texttest")


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
                ("biSizeImage", w.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", w.DWORD),
                ("biClrImportant", w.DWORD)]


g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p,
                        ctypes.POINTER(BMIH), w.UINT]
g.GetDIBits.restype = ctypes.c_int


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def wins(pid):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        q = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(q))
        if q.value == pid:
            out.append(h)
        return True

    u.EnumWindows(cb, 0)
    return out


def find_child(parent, name):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if cls(h) == name:
            found.append(h)
        return True
    u.EnumChildWindows(parent, cb, 0)
    return found[0] if found else None


def count_dark(tabbar):
    """统计标签栏里暗像素数量（文字/图标都是深色）"""
    rc = w.RECT()
    u.GetClientRect(tabbar, ctypes.byref(rc))
    ww, hh = rc.right, rc.bottom
    if ww <= 0 or hh <= 0:
        return (0, 0, 0)
    hdc = u.GetDC(tabbar)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, ww, hh)
    g.SelectObject(mdc, bmp)
    g.BitBlt(mdc, 0, 0, ww, hh, hdc, 0, 0, 0x00CC0020)   # SRCCOPY

    bi = BMIH()
    bi.biSize = ctypes.sizeof(BMIH)
    bi.biWidth = ww
    bi.biHeight = -hh
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(ww * hh * 4)
    g.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    raw = buf.raw

    # 文字区：跳过左侧图标带（约前 32px）和右侧关闭按钮带（约 20px）
    x0, x1 = 32, max(33, ww - 20)
    dark_text = 0
    dark_all = 0
    maxx = 0
    for y in range(hh):
        row = y * ww * 4
        for x in range(ww):
            o = row + x * 4
            b, gg, r = raw[o], raw[o + 1], raw[o + 2]
            if r < 120 and gg < 120 and b < 120:
                dark_all += 1
                if x >= maxx:
                    maxx = x
                if x0 <= x < x1:
                    dark_text += 1
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(tabbar, hdc)
    return (dark_all, dark_text, ww, maxx)


def run(label, tabs):
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for i in range(5):
        open(os.path.join(WORK, "文档%d.txt" % i), "w").write("x")

    p = subprocess.Popen([EXE, WORK])
    main = None
    t0 = time.time()
    while not main and time.time() - t0 < 10:
        for h in wins(p.pid):
            if cls(h) == "FFMainWnd":
                main = h
                break
        time.sleep(0.1)
    time.sleep(2.0)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 1000, 620, True)
    time.sleep(0.8)

    for _ in range(tabs - 1):
        u.PostMessageW(main, WM_COMMAND, CMD_TAB_NEW, 0)
        time.sleep(0.9)
    time.sleep(0.8)

    tb = find_child(main, "FFTabBar")
    if not tb:
        print("  [%s] 没找到 FFTabBar" % label)
        p.terminate()
        return None
    total, text, ww, maxx = count_dark(tb)
    p.terminate()
    time.sleep(0.4)
    verdict = "有文字" if text > 40 else "!!文字区几乎空白"
    print("  [%s] 请求 %d 个标签, 栏宽 %dpx, 暗像素: 全部=%d 文字区=%d, 最右x=%d -> %s"
          % (label, tabs, ww, total, text, maxx, verdict))
    return text


print("检查标签上的文字是否真的画出来了（文字区暗像素应明显 > 0）\n")
r1 = run("单标签", 1)
r2 = run("三标签", 3)
shutil.rmtree(WORK, ignore_errors=True)

print()
if r1 is None or r2 is None:
    print("RESULT: FAIL 探针没跑起来")
else:
    ok = r1 > 40 and r2 > 40
    print("单标签文字区暗像素=%d, 三标签=%d" % (r1, r2))
    print("\nRESULT:", "PASS 文字正常画出" if ok else "FAIL 文字仍空白")
