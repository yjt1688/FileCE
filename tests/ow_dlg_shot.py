# -*- coding: utf-8 -*-
"""截取"打开方式"对话框（FFOpenWithDlg）的区域，用于核对外观是否与 Win10 一致。
用法: python tests/ow_dlg_shot.py
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys, struct

u = ctypes.WinDLL("user32", use_last_error=True)
g = ctypes.WinDLL("gdi32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetWindowThreadProcessId.restype = ctypes.c_ulong
u.SetForegroundWindow.argtypes = [w.HWND]
u.GetForegroundWindow.restype = w.HWND
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint] * 4 + [ctypes.c_void_p]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
u.BringWindowToTop.argtypes = [w.HWND]
u.SetFocus.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]

LDOWN, LUP, RDOWN, RUP = 0x0002, 0x0004, 0x0008, 0x0010
VK_DOWN, VK_UP, VK_RIGHT, VK_RETURN = 0x28, 0x26, 0x27, 0x0D
KEYUP = 0x0002
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DIR = r"C:\ffce\owdlg"
SHOT = os.path.join(HERE, "ow_dlg.bmp")
EXT = sys.argv[1] if len(sys.argv) > 1 else ".txt"


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def title(h):
    b = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, b, 512); return b.value


def pid_of(h):
    p = ctypes.c_uint32(0); u.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value


def tops():
    res = []
    def cb(h, l):
        if u.IsWindowVisible(h):
            res.append((h, cls(h), title(h), pid_of(h)))
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    return res


def menus(pid):
    return [x for x in tops() if x[1] == "#32768" and x[3] == pid]


def rect(h):
    rc = w.RECT(); u.GetWindowRect(h, ctypes.byref(rc))
    return (rc.left, rc.top, rc.right, rc.bottom)


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


def key(vk):
    u.keybd_event(vk, 0, 0, None); time.sleep(0.12)
    u.keybd_event(vk, 0, KEYUP, None); time.sleep(0.30)


def raise_top(h):
    u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)


def force_focus(hwnd, tries=12):
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


class BIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def shot(path, r):
    x, y, x2, y2 = r
    W, H = x2 - x, y2 - y
    hdc = u.GetDC(0); mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, W, H); g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, W, H, hdc, x, y, 0x00CC0020)
    bi = BIH(); bi.biSize = ctypes.sizeof(bi); bi.biWidth = W; bi.biHeight = -H
    bi.biPlanes = 1; bi.biBitCount = 32
    buf = ctypes.create_string_buffer(W * H * 4)
    g.GetDIBits(mem, bmp, 0, H, buf, ctypes.byref(bi), 0)
    hdr = b"BM" + struct.pack("<IHHI", 14 + 40 + len(buf), 0, 0, 14 + 40)
    ih = struct.pack("<IiiHHIIiiII", 40, W, -H, 1, 32, 0, len(buf), 0, 0, 0, 0)
    open(path, "wb").write(hdr + ih + buf.raw)
    g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, hdc)
    print("saved", path, W, "x", H)


shutil.rmtree(DIR, ignore_errors=True)
os.makedirs(DIR)
fname = "dlg_probe" + EXT
open(os.path.join(DIR, fname), "w", encoding="utf-8").write("probe\n")

proc = subprocess.Popen([EXE, DIR])
main = None
try:
    main = find_main(proc.pid)
    if not main:
        print("no main"); sys.exit(1)
    time.sleep(1.0)
    raise_top(main); force_focus(main); time.sleep(0.4)
    lst = u.FindWindowExW(main, None, "SysListView32", None)
    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(0, 0); u.ClientToScreen(lst, ctypes.byref(org))
    rx, ry = org.x + 60, org.y + 34
    click(rx, ry)
    click(rx, ry, right=True)
    time.sleep(0.6)
    key(VK_DOWN)
    for _ in range(4):
        if len(menus(proc.pid)) >= 2:
            break
        key(VK_RIGHT)
        if len(menus(proc.pid)) >= 2:
            break
        key(VK_DOWN)
    key(VK_UP)           # 最后一项 = 选择其他应用
    time.sleep(0.4)
    before = set(h for h, _, _, _ in tops())
    key(VK_RETURN)
    time.sleep(2.0)
    dlg = [x for x in tops() if x[0] not in before and x[1] == "FFOpenWithDlg"]
    print("FFOpenWithDlg:", dlg)
    if dlg:
        h = dlg[0][0]
        print("  rect:", rect(h))
        lstid = u.GetDlgItem(h, 5301)
        if lstid:
            n = u.SendMessageW(lstid, 0x018B, 0, 0)   # LB_GETCOUNT
            print("  列表项数:", n)
            cur = u.SendMessageW(lstid, 0x0188, 0, 0)  # LB_GETCURSEL
            print("  当前选中行:", cur)
            for i in range(n):
                data = u.SendMessageW(lstid, 0x0199, i, 0)  # LB_GETITEMDATA
                print("    row%d itemdata=%s" % (i, data))
            rr = w.RECT(); u.GetWindowRect(lstid, ctypes.byref(rr))
            print("  列表 rect:", (rr.left, rr.top, rr.right, rr.bottom))
        ck = u.GetDlgItem(h, 5302)
        if ck:
            b = ctypes.create_unicode_buffer(256); u.GetWindowTextW(ck, b, 256)
            print("  复选框:", repr(b.value))
        r = rect(h)
        pad = 8
        shot(SHOT, (r[0]-pad, r[1]-pad, r[2]+pad, r[3]+pad))
    print("FileCE alive:", proc.poll() is None)
finally:
    if main:
        u.SetWindowPos(main, -2, 0, 0, 0, 0, 0x0002 | 0x0001)
    proc.terminate(); time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
    shutil.rmtree(DIR, ignore_errors=True)