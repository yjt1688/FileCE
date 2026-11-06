# -*- coding: utf-8 -*-
"""验证（按参考实现，全部交给 shell）：
   A 同目录复制粘贴 → 自动生成「xxx - 副本」，**不弹框**
   B 跨目录同名     → 弹系统的覆盖确认框
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.IsWindowVisible.argtypes = [w.HWND]

CMD_COPY, CMD_PASTE = 20007, 20009
WM_COMMAND = 0x0111


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def txt(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, b, 256)
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


CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")


def open_app(path):
    p = subprocess.Popen([EXE, path])
    main = None
    t0 = time.time()
    while not main and time.time() - t0 < 10:
        for h in wins(p.pid):
            if cls(h) == "FFMainWnd":
                main = h
                break
        time.sleep(0.1)
    time.sleep(1.6)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 900, 650, True)
    time.sleep(0.6)
    return p, main


def click_first(main):
    lst = u.GetDlgItem(main, 1001)
    r = w.RECT()
    u.GetWindowRect(lst, ctypes.byref(r))
    u.SetCursorPos(r.left + 90, r.top + 46)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)


def dialogs(pid):
    return [txt(h) for h in wins(pid) if u.IsWindowVisible(h) and cls(h) == "#32770"]


# ---------------- A 同目录 ----------------
print("A 同目录复制粘贴（应自动出「副本」，不弹框）")
base = os.path.join(CWD, "build", "_sa")
shutil.rmtree(base, ignore_errors=True)
os.makedirs(base)
open(os.path.join(base, "doc.txt"), "w").write("CONTENT")
p, main = open_app(base)
click_first(main)
u.PostMessageW(main, WM_COMMAND, CMD_COPY, 0)
time.sleep(0.6)
u.PostMessageW(main, WM_COMMAND, CMD_PASTE, 0)
time.sleep(3.0)
d1 = dialogs(p.pid)
files = sorted(os.listdir(base))
print("   弹框:", d1 if d1 else "（无）")
print("   目录:", files)
has_copy = any(("副本" in f) or ("Copy" in f) or ("copy" in f) or ("(" in f) for f in files)
okA = (not d1) and has_copy
print("   ->", "PASS" if okA else "FAIL")
p.terminate(); time.sleep(0.4)
shutil.rmtree(base, ignore_errors=True)

# ---------------- B 跨目录同名 ----------------
print("\nB 跨目录同名（应弹系统覆盖确认）")
base = os.path.join(CWD, "build", "_cb")
shutil.rmtree(base, ignore_errors=True)
A, B = os.path.join(base, "A"), os.path.join(base, "B")
os.makedirs(A); os.makedirs(B)
open(os.path.join(A, "same.txt"), "w").write("FROM-A")
open(os.path.join(B, "same.txt"), "w").write("FROM-B")

p, main = open_app(A)
click_first(main)
u.PostMessageW(main, WM_COMMAND, CMD_COPY, 0)
time.sleep(0.7)
p.terminate(); time.sleep(0.4)

p, main = open_app(B)
u.PostMessageW(main, WM_COMMAND, CMD_PASTE, 0)
d2 = []
t0 = time.time()
while time.time() - t0 < 4:
    d2 = dialogs(p.pid)
    if d2:
        break
    time.sleep(0.2)
print("   弹框:", d2 if d2 else "（无）")
okB = bool(d2)
print("   ->", "PASS 系统确认框出现了" if okB else "FAIL 没有确认框")
# 关掉框
for h in wins(p.pid):
    if u.IsWindowVisible(h) and cls(h) == "#32770":
        u.PostMessageW(h, 0x0010, 0, 0)
time.sleep(0.5)
p.terminate(); time.sleep(0.4)
shutil.rmtree(base, ignore_errors=True)

print("\nRESULT:", "PASS" if (okA and okB) else "FAIL")
