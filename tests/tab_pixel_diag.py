# -*- coding: utf-8 -*-
"""扫标签栏每一列的暗像素分布，定位"哪些标签没画文字"。
   同时打印标签边界（靠竖线/背景变化推断）。"""
import ctypes, ctypes.wintypes as w, subprocess, time, os

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")

u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
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


def find_windows():
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if cls(h) == "FFMainWnd":
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


def grab(hwnd):
    rc = w.RECT()
    u.GetClientRect(hwnd, ctypes.byref(rc))
    ww, hh = rc.right, rc.bottom
    hdc = u.GetDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, ww, hh)
    g.SelectObject(mdc, bmp)
    g.BitBlt(mdc, 0, 0, ww, hh, hdc, 0, 0, 0x00CC0020)
    bi = BMIH()
    bi.biSize = ctypes.sizeof(BMIH)
    bi.biWidth = ww
    bi.biHeight = -hh
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(ww * hh * 4)
    g.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    u.ReleaseDC(hwnd, hdc)
    return (buf.raw, ww, hh)


mains = find_windows()
print("找到 %d 个 FileCE 主窗口" % len(mains))
if not mains:
    raise SystemExit("请先把程序打开")

for main in mains:
    tb = find_child(main, "FFTabBar")
    if not tb:
        continue
    pid = w.DWORD(0)
    u.GetWindowThreadProcessId(main, ctypes.byref(pid))
    raw, ww, hh = grab(tb)
    print("\n=== 主窗口 %s (PID %d) 标签栏 %dx%d ===" % (hex(main), pid.value, ww, hh))

    # 每列暗像素数（文字/图标/竖线都算），按 4px 一档聚合输出
    col = []
    for x in range(ww):
        n = 0
        for y in range(hh):
            o = (y * ww + x) * 4
            b, gg, r = raw[o], raw[o + 1], raw[o + 2]
            if r < 120 and gg < 120 and b < 120:
                n += 1
        col.append(n)

    # 找出有内容的列区间（连续 >0 的段）
    segs = []
    s = None
    for x, n in enumerate(col):
        if n > 0 and s is None:
            s = x
        elif n == 0 and s is not None:
            if x - s >= 3:
                segs.append((s, x - 1, sum(col[s:x])))
            s = None
    if s is not None:
        segs.append((s, ww - 1, sum(col[s:])))

    print("有内容的横向区间（左-右, 暗像素总数）:")
    for a, b, t in segs:
        print("   %4d - %4d   %5d" % (a, b, t))

    # 按 40px 一档画直方图，直观看出哪里空
    print("\n列分布（每 20px 一档，数字=暗像素数）:")
    for x0 in range(0, min(ww, 700), 20):
        tot = sum(col[x0:x0 + 20])
        bar = "#" * min(40, tot)
        print("   x=%3d..%3d  %4d %s" % (x0, x0 + 19, tot, bar))
