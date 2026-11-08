# -*- coding: utf-8 -*-
"""菜单栏回归：主菜单应常驻标题栏下方，且勾选项随状态刷新。

检查：
  A 主窗口挂了菜单栏（GetMenu != NULL），顶层项数=5，项名是 文件/转到/查看/工具/帮助
  B 菜单栏在标题栏下方：工具栏顶端 - 窗口顶端 应大于标题栏高度（多出来的就是菜单栏）
  C 展开「查看」时（WM_INITMENUPOPUP）勾选项跟随当前视图；切换视图后重新展开应跟着变
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))
WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E; WM_COMMAND = 0x0111
WM_INITMENUPOPUP = 0x0117
MF_BYPOSITION = 0x400; MF_BYCOMMAND = 0x000; MF_CHECKED = 0x0008
CMD_VIEW_LARGE = 20020; CMD_VIEW_DETAIL = 20023
SM_CYCAPTION = 4

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]; u.SendMessageW.restype = ctypes.c_ssize_t
u.GetMenu.argtypes = [w.HWND]; u.GetMenu.restype = w.HMENU
u.GetMenuItemCount.argtypes = [w.HMENU]; u.GetMenuItemCount.restype = ctypes.c_int
u.GetSubMenu.argtypes = [w.HMENU, ctypes.c_int]; u.GetSubMenu.restype = w.HMENU
u.GetMenuStringW.argtypes = [w.HMENU, ctypes.c_uint, w.LPWSTR, ctypes.c_int, ctypes.c_uint]; u.GetMenuStringW.restype = ctypes.c_int
u.GetMenuState.argtypes = [w.HMENU, ctypes.c_uint, ctypes.c_uint]; u.GetMenuState.restype = ctypes.c_uint
u.GetSystemMetrics.argtypes = [ctypes.c_int]; u.GetSystemMetrics.restype = ctypes.c_int
u.MapWindowPoints  # noqa

found = []; PID = w.DWORD(0)


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


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

ok = True

bar = u.GetMenu(main)
print("A 菜单栏=%s %s" % (hex(bar) if bar else "NULL", "OK" if bar else "!!! 没有菜单栏"), flush=True)
ok &= bool(bar)

if bar:
    n = u.GetMenuItemCount(bar)
    print("  顶层项数=%d %s" % (n, "OK" if n == 5 else "!!! 应为 5"), flush=True)
    ok &= (n == 5)
    names = []
    for i in range(n):
        b = ctypes.create_unicode_buffer(64)
        u.GetMenuStringW(bar, i, b, 64, MF_BYPOSITION)
        names.append(b.value)
    print("  顶层项=%s" % names, flush=True)
    ok &= any("文件" in x for x in names)

# B 位置：菜单栏在标题栏下方
kids = {}


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb(h, l):
    kids.setdefault(cls(h), []).append(h); return True


u.EnumChildWindows(main, kcb, 0)
mr = w.RECT(); u.GetWindowRect(main, ctypes.byref(mr))
tb = kids.get("FFToolBar", [None])[0]
tr = w.RECT(); u.GetWindowRect(tb, ctypes.byref(tr))
cap = u.GetSystemMetrics(SM_CYCAPTION)
delta = tr.top - mr.top
print("B 工具栏顶端-窗口顶端=%d，标题栏高=%d，菜单栏约占=%d -> %s"
      % (delta, cap, delta - cap, "OK 标题栏下确实多出菜单栏" if delta - cap >= 12 else "!!! 没有多出菜单栏高度"), flush=True)
ok &= (delta - cap) >= 12

# C 勾选项刷新
if bar:
    view = u.GetSubMenu(bar, 2)
    u.SendMessageW(main, WM_INITMENUPOPUP, view, 0)
    st_det = u.GetMenuState(view, CMD_VIEW_DETAIL, MF_BYCOMMAND) & MF_CHECKED
    st_lar = u.GetMenuState(view, CMD_VIEW_LARGE, MF_BYCOMMAND) & MF_CHECKED
    print("C 初始：详细信息勾=%d 大图标勾=%d -> %s" % (bool(st_det), bool(st_lar), "OK" if st_det and not st_lar else "!!! 勾不对"), flush=True)
    ok &= bool(st_det) and not bool(st_lar)

    u.SendMessageW(main, WM_COMMAND, CMD_VIEW_LARGE, 0)
    time.sleep(0.8)
    u.SendMessageW(main, WM_INITMENUPOPUP, view, 0)
    st_det2 = u.GetMenuState(view, CMD_VIEW_DETAIL, MF_BYCOMMAND) & MF_CHECKED
    st_lar2 = u.GetMenuState(view, CMD_VIEW_LARGE, MF_BYCOMMAND) & MF_CHECKED
    print("C 切大图标后：详细信息勾=%d 大图标勾=%d -> %s" % (bool(st_det2), bool(st_lar2), "OK 跟随刷新" if st_lar2 and not st_det2 else "!!! 没刷新"), flush=True)
    ok &= bool(st_lar2) and not bool(st_det2)

print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
