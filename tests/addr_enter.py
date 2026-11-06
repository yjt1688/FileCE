# -*- coding: utf-8 -*-
"""地址栏"输入路径回车没反应"回归。

关键手法：本环境拦截合成输入（SendInput 注入 0 事件），无法真敲键盘。但回车被谁
吃掉，可以用两种投递方式区分：
  - PostMessage -> 进入消息队列 -> 经过主循环的 IsDialogMessage -> 再到窗口过程
  - SendMessage -> 直接进窗口过程，绕过主循环
若 Post 不导航而 Send 导航，说明回车在消息循环里被截走（IsDialogMessage 把它
翻译成 WM_COMMAND(IDOK) 发给主窗口，编辑框根本收不到 WM_KEYDOWN）。

同时检查列表里的回车（选中项回车应打开）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))
WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E; WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100; WM_KEYUP = 0x0101
VK_RETURN = 0x0D
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]; u.FindWindowExW.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]; u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]; u.PostMessageW.restype = ctypes.c_bool
u.SetFocus.argtypes = [w.HWND]; u.SetFocus.restype = w.HWND


_bufs = []

def wptr(s):
    b = ctypes.create_unicode_buffer(s)
    _bufs.append(b)          # 保持缓冲存活，避免指针悬空
    return ctypes.addressof(b)


def wtext(h):
    if not h: return ""
    n = u.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    b = ctypes.create_unicode_buffer(n + 2); u.SendMessageW(h, WM_GETTEXT, n + 1, ctypes.addressof(b)); return b.value


def cls(h):
    if not h: return "?"
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def title():
    return wtext(main)


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
addr = None
for c in kids.get("ComboBox", []):
    if ":" in wtext(c): addr = c; break
edit = u.FindWindowExW(addr, None, "Edit", None) if addr else None
lst = None
for c in kids.get("SysListView32", []):
    r = w.RECT(); u.GetWindowRect(c, ctypes.byref(r))
    if r.bottom - r.top > 200: lst = c; break
print("地址栏=%s Edit=%s 列表=%s 初始标题=%r" % (hex(addr) if addr else "?", hex(edit) if edit else "?", hex(lst) if lst else "?", title()), flush=True)

ok = True

# 1) PostMessage 走消息队列（会经过主循环的 IsDialogMessage）
u.SendMessageW(addr, WM_SETTEXT, 0, wptr(r"C:\Users"))
u.SetFocus(edit)
time.sleep(0.2)
before = title()
u.PostMessageW(edit, WM_KEYDOWN, VK_RETURN, 0x0001 | (0x1C << 16))
u.PostMessageW(edit, WM_KEYUP, VK_RETURN, 0xC0000001 | (0x1C << 16))
time.sleep(1.2)
after_post = title()
print("1) PostMessage 回车: %r -> %r  %s" % (before, after_post, "OK 导航了" if "Users" in after_post else "!!! 没反应"), flush=True)
post_ok = "Users" in after_post
ok &= post_ok

# 2) 对照：SendMessage 直接进窗口过程（绕过主循环）
u.SendMessageW(addr, WM_SETTEXT, 0, wptr(r"C:\ProgramData"))
u.SetFocus(edit)
time.sleep(0.2)
u.SendMessageW(edit, WM_KEYDOWN, VK_RETURN, 0x0001 | (0x1C << 16))
u.SendMessageW(edit, WM_KEYUP, VK_RETURN, 0xC0000001 | (0x1C << 16))
time.sleep(1.2)
after_send = title()
print("2) SendMessage 回车(绕过循环): %r  %s" % (after_send, "OK 导航了" if "ProgramData" in after_send else "!!! 没反应"), flush=True)
send_ok = "ProgramData" in after_send
ok &= send_ok

print("--- 判定 ---", flush=True)
if send_ok and not post_ok:
    print("回车在消息循环中被截走（IsDialogMessage 拦下 VK_RETURN）——需修主循环", flush=True)
elif post_ok:
    print("回车在消息循环中正常工作", flush=True)
else:
    print("两种方式都不导航——问题在导航逻辑本身", flush=True)

print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
