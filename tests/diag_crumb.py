# -*- coding: utf-8 -*-
"""诊断面包屑：1) WindowFromPoint 判定覆盖层是否真的在最上层（真实点击能否到达）；
2) 用真实鼠标点击面包屑中段，看地址栏路径是否跳到祖先目录。"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys

u = ctypes.WinDLL("user32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.SetForegroundWindow.argtypes = [w.HWND]; u.SetForegroundWindow.restype = ctypes.c_bool
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DEEP = r"C:\ffce\a\b\c\d"
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def title(h):
    b = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, b, 512); return b.value


def find_main(pid, timeout=15.0):
    out = []
    t0 = time.time()
    def cb(h, l):
        if cls(h) != "FFMainWnd": return True
        p = ctypes.c_uint32(0); u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h): out.append(h)
        return True
    while not out and time.time() - t0 < timeout:
        u.EnumWindows(HWNDCB(cb), 0); time.sleep(0.15)
    return out[0] if out else None


def addr_path(main):
    combo = u.FindWindowExW(main, None, "COMBOBOX", None)
    if not combo: return ""
    edit = u.FindWindowExW(combo, None, "Edit", None)
    if not edit: return ""
    buf = ctypes.create_unicode_buffer(512)
    u.SendMessageW(edit, 0x000D, 512, ctypes.cast(buf, ctypes.c_void_p).value)
    return buf.value


def real_click(x, y):
    u.SetCursorPos(x, y)
    time.sleep(0.05)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.08)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.5)


shutil.rmtree(DEEP, ignore_errors=True)
os.makedirs(DEEP)
proc = subprocess.Popen([EXE, DEEP])
try:
    main = find_main(proc.pid)
    print("main:", main, title(main))
    for _ in range(40):
        if u.IsWindowVisible(main): break
        time.sleep(0.1)
    time.sleep(0.6)
    crumb = u.FindWindowExW(main, None, "FFCrumb", None)
    print("crumb:", crumb, "visible:", u.IsWindowVisible(crumb) if crumb else None)

    rc = w.RECT(); u.GetClientRect(crumb, ctypes.byref(rc))
    pt0 = w.POINT(rc.left, rc.top); u.ClientToScreen(crumb, ctypes.byref(pt0))
    W = rc.right - rc.left; H = rc.bottom - rc.top
    print("crumb client rect:", rc.left, rc.top, rc.right, rc.bottom, "size", W, H)

    # 1) WindowFromPoint 扫描面包屑各 x，看顶层窗口是不是 FFCrumb
    print("\n[WindowFromPoint 扫描] (期望命中 FFCrumb)")
    for fx in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85):
        x = pt0.x + int(W * fx); y = pt0.y + H // 2
        h = u.WindowFromPoint(w.POINT(x, y))
        print("  x=%d -> top=%s (%s)" % (x, cls(h), h))

    # 2) 真实点击中段，看路径是否变化
    u.SetForegroundWindow(main); time.sleep(0.3)
    print("\n[真实鼠标点击中段]")
    before = os.path.normcase(addr_path(main))
    print("  点击前:", before)
    # 点偏右一段（靠近末端，但非最末）期望跳到祖先
    for fx in (0.45, 0.6, 0.3):
        x = pt0.x + int(W * fx); y = pt0.y + H // 2
        real_click(x, y)
        after = os.path.normcase(addr_path(main))
        print("  click fx=%.2f -> %s" % (fx, after))
        if after != before:
            print("  => 真实点击触发了导航！")
            break
    else:
        print("  => 真实点击未改变路径（覆盖层没收到点击 / 点到非导航段）")

finally:
    proc.terminate(); time.sleep(0.2)
    if proc.poll() is None: proc.kill()
    shutil.rmtree(DEEP, ignore_errors=True)
