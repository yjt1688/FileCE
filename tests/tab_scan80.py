# -*- coding: utf-8 -*-
"""阈值 80 扫描：64 算暗、96 不算 —— 用来验证非活动标签文字色是否真的变深"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HANDLE]; g.SelectObject.restype = w.HANDLE
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

CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")
CMD_TAB_NEW = 20040
THRESH = 80                     # 关键：64 算暗、96 不算


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def mains_of(pid):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        q = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(q))
        if q.value == pid and cls(h) == "FFMainWnd":
            out.append(h)
        return True
    u.EnumWindows(cb, 0)
    return out


def child_class(parent, name):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if cls(h) == name:
            out.append(h)
        return True
    u.EnumChildWindows(parent, cb, 0)
    return out[0] if out else None


def scan(n):
    work = os.path.join(CWD, "build", "_s80_%d" % n)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    open(os.path.join(work, "d0.txt"), "w").write("x")

    p = subprocess.Popen([EXE, work])
    ms = []
    t0 = time.time()
    while not ms and time.time() - t0 < 10:
        ms = mains_of(p.pid)
        time.sleep(0.1)
    if not ms:
        p.terminate()
        return None
    main = ms[0]
    time.sleep(2.0)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 1044, 640, True)
    time.sleep(0.9)
    for _ in range(n - 1):
        u.PostMessageW(main, 0x0111, CMD_TAB_NEW, 0)
        time.sleep(0.85)
    time.sleep(1.2)

    tb = child_class(main, "FFTabBar")
    rc = w.RECT()
    u.GetClientRect(tb, ctypes.byref(rc))
    ww, hh = rc.right, rc.bottom
    hdc = u.GetDC(tb)
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
    u.ReleaseDC(tb, hdc)
    raw = buf.raw
    p.terminate()
    time.sleep(0.4)
    shutil.rmtree(work, ignore_errors=True)

    cells = []
    for x0 in range(0, min(ww, 900), 40):
        d = 0
        for x in range(x0, min(x0 + 40, ww)):
            for y in range(hh):
                o = (y * ww + x) * 4
                if raw[o] < THRESH and raw[o + 1] < THRESH and raw[o + 2] < THRESH:
                    d += 1
        cells.append("X" if d > 5 else ".")
    return "".join(cells)


print("阈值 %d（RGB(64) 算暗、RGB(96) 不算）" % THRESH)
print("每档 40px：X=有深色内容\n")
for n in (3, 5, 6):
    p = scan(n)
    print("  %d 个标签: %s" % (n, p if p else "抓不到窗口"))
