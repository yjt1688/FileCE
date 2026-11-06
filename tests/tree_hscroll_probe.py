# -*- coding: utf-8 -*-
"""验证：深层目录定位后，树的水平滚动位置必须是 0
   GetScrollPos(tree, SB_HORZ) 跨进程可读，不需要写对方内存。"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.GetScrollPos.argtypes = [w.HWND, ctypes.c_int]
u.GetScrollPos.restype = ctypes.c_int
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]

CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")
SB_HORZ = 0
IDC_TREE = 1002          # 树控件 id（先探测，取不到就枚举类名）


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


def find_tree(main):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if cls(h) == "SysTreeView32":
            found.append(h)
        return True
    u.EnumChildWindows(main, cb, 0)
    return found[0] if found else None


# 造 7 层深层目录，每层名字都长，保证缩进远超树宽
base = os.path.join(CWD, "build", "_deeptree")
shutil.rmtree(base, ignore_errors=True)
cur = base
for i in range(7):
    cur = os.path.join(cur, "深层目录第%d级的很长的名字用来撑宽度" % (i + 1))
os.makedirs(cur, exist_ok=True)
open(os.path.join(cur, "a.txt"), "w").write("x")
print("目标深层路径长度:", len(cur), "层数: 7")

p = subprocess.Popen([EXE, cur])
ms = []
t0 = time.time()
while not ms and time.time() - t0 < 12:
    ms = mains_of(p.pid)
    time.sleep(0.1)
if not ms:
    print("启动失败")
    raise SystemExit(1)
main = ms[0]
time.sleep(2.5)
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
u.MoveWindow(main, 60, 30, 900, 620, True)
time.sleep(1.5)

tree = find_tree(main)
print("树控件:", tree)
if not tree:
    p.terminate()
    raise SystemExit(1)

h = u.GetScrollPos(tree, SB_HORZ)
print("首次定位后 水平滚动位置 =", h)

# 再刷新几次（F5 走 refresh 路径，也会 reveal）
CMD_REFRESH = 20004
for _ in range(3):
    u.PostMessageW(main, 0x0111, CMD_REFRESH, 0)
    time.sleep(1.0)
h2 = u.GetScrollPos(tree, SB_HORZ)
print("3 次刷新后 水平滚动位置 =", h2)

p.terminate()
time.sleep(0.4)
shutil.rmtree(base, ignore_errors=True)

ok = (h == 0 and h2 == 0)
print("\nRESULT:", "PASS 水平位置始终为 0（树没被横向滚走）" if ok
      else "FAIL 水平位置跑到 %d/%d" % (h, h2))
