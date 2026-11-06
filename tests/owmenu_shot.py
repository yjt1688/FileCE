# -*- coding: utf-8 -*-
"""诊断/取证：真实右键弹出"打开方式"子菜单后截屏保存，用于人工核对外观。"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SetForegroundWindow.argtypes = [w.HWND]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint] * 4 + [ctypes.c_void_p]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.GetSystemMetrics.argtypes = [ctypes.c_int]
u.GetForegroundWindow.restype = w.HWND
u.GetWindowThreadProcessId.restype = ctypes.c_ulong
u.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
u.BringWindowToTop.argtypes = [w.HWND]
u.SetFocus.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]

LDOWN, LUP, RDOWN, RUP = 0x0002, 0x0004, 0x0008, 0x0010
VK_DOWN, VK_UP, VK_RIGHT, VK_RETURN, VK_ESCAPE = 0x28, 0x26, 0x27, 0x0D, 0x1B
KEYUP = 0x0002
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DIR = r"C:\ffce\owmenu"
SHOT = os.path.join(HERE, "owmenu_shot.bmp")
STEP = sys.argv[1] if len(sys.argv) > 1 else "submenu"   # menu / submenu / enter


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def pid_of(h):
    p = ctypes.c_uint32(0); u.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value


def find_main(pid, timeout=15.0):
    out = []
    t0 = time.time()

    def cb(h, l):
        if cls(h) == "FFMainWnd" and pid_of(h) == pid and u.IsWindowVisible(h):
            out.append(h)
        return True
    while not out and time.time() - t0 < timeout:
        u.EnumWindows(HWNDCB(cb), 0); time.sleep(0.15)
    return out[0] if out else None


def click(x, y, right=False):
    u.SetCursorPos(x, y); time.sleep(0.08)
    u.mouse_event(RDOWN if right else LDOWN, 0, 0, 0, None); time.sleep(0.09)
    u.mouse_event(RUP if right else LUP, 0, 0, 0, None); time.sleep(0.5)


def raise_top(h):
    u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)   # HWND_TOPMOST


def force_focus(hwnd, tries=12):
    """键盘必须进到菜单里，所以先保证本程序是前台窗口（桌面上还开着浏览器）"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for _ in range(tries):
        if u.GetForegroundWindow() == hwnd:
            return True
        fg = u.GetForegroundWindow()
        tid_fg = u.GetWindowThreadProcessId(fg, None)
        tid_me = k32.GetCurrentThreadId()
        u.AttachThreadInput(tid_me, tid_fg, True)
        u.BringWindowToTop(hwnd); u.SetForegroundWindow(hwnd); u.SetFocus(hwnd)
        u.AttachThreadInput(tid_me, tid_fg, False)
        time.sleep(0.25)
    return u.GetForegroundWindow() == hwnd


def key(vk):
    u.keybd_event(vk, 0, 0, None); time.sleep(0.12)
    u.keybd_event(vk, 0, KEYUP, None); time.sleep(0.32)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def title(h):
    b = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, b, 512); return b.value


def top_windows_list():
    res = []

    def cb(h, l):
        if u.IsWindowVisible(h):
            res.append((h, cls(h), title(h), pid_of(h), True))
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    return res


def shot(path, rect):
    x, y, x2, y2 = rect
    W, H = x2 - x, y2 - y
    hdc = u.GetDC(0)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, W, H)
    g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, W, H, hdc, x, y, 0x00CC0020)  # SRCCOPY
    bi = BITMAPINFOHEADER(); bi.biSize = ctypes.sizeof(bi)
    bi.biWidth = W; bi.biHeight = -H; bi.biPlanes = 1; bi.biBitCount = 32
    buf = ctypes.create_string_buffer(W * H * 4)
    g.GetDIBits(mem, bmp, 0, H, buf, ctypes.byref(bi), 0)
    # 写 32bpp BMP（BGRA）
    import struct
    hdr = b"BM" + struct.pack("<IHHI", 14 + 40 + len(buf), 0, 0, 14 + 40)
    ih = struct.pack("<IiiHHIIiiII", 40, W, -H, 1, 32, 0, len(buf), 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(hdr); f.write(ih); f.write(buf.raw)
    g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, hdc)
    print("saved", path, W, "x", H)


shutil.rmtree(DIR, ignore_errors=True)
os.makedirs(DIR)
with open(os.path.join(DIR, "ow_menu_probe.txt"), "w", encoding="utf-8") as f:
    f.write("probe\n")

proc = subprocess.Popen([EXE, DIR])
try:
    main = find_main(proc.pid)
    if not main:
        print("no main"); sys.exit(1)
    time.sleep(1.0)
    u.SetForegroundWindow(main); time.sleep(0.4)
    lst = u.FindWindowExW(main, None, "SysListView32", None)
    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(0, 0); u.ClientToScreen(lst, ctypes.byref(org))
    rx, ry = org.x + 60, org.y + 34
    raise_top(main)
    force_focus(main)
    click(rx, ry)
    click(rx, ry, right=True)
    time.sleep(0.6)
    if STEP == "menu":
        pass
    else:
        key(VK_DOWN)
        for _ in range(4):
            if len([1 for h, c, t, p, v in top_windows_list() if c == "#32768"]) >= 2:
                break
            key(VK_RIGHT)
            if len([1 for h, c, t, p, v in top_windows_list() if c == "#32768"]) >= 2:
                break
            key(VK_DOWN)
        if STEP == "last":
            key(VK_UP)
            time.sleep(0.4)
        time.sleep(0.5)
    if STEP == "enter":
        key(VK_RETURN); time.sleep(3.0)
    sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    shot(SHOT, (0, 0, sw, sh))
    time.sleep(0.5)
finally:
    u.SetWindowPos(main, -2, 0, 0, 0, 0, 0x0002 | 0x0001)   # HWND_NOTOPMOST
    proc.terminate(); time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
