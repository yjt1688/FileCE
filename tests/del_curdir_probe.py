# -*- coding: utf-8 -*-
"""验证：当前目录被删除后，列表自动退回父目录（不再卡在已删除的目录上）"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
for fn, rt, args in [
    ("GetClassNameW", None, [w.HWND, w.LPWSTR, ctypes.c_int]),
    ("EnumWindows", None, [ctypes.c_void_p, w.LPARAM]),
    ("GetWindowThreadProcessId", w.DWORD, [w.HWND, ctypes.POINTER(w.DWORD)]),
    ("GetDlgItem", w.HWND, [w.HWND, ctypes.c_int]),
    ("SendMessageW", ctypes.c_ssize_t, [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]),
    ("GetWindowTextW", ctypes.c_int, [w.HWND, w.LPWSTR, ctypes.c_int]),
    ("SetWindowPos", ctypes.c_bool, [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]),
    ("MoveWindow", ctypes.c_bool, [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]),
]:
    f = getattr(u, fn)
    f.argtypes = args
    if rt:
        f.restype = rt


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def title(h):
    b = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, b, 512)
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


EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "_deltest")
root = os.path.abspath(root)
shutil.rmtree(root, ignore_errors=True)
sub = os.path.join(root, "sub")
os.makedirs(sub)
os.makedirs(os.path.join(root, "other"))
open(os.path.join(sub, "inside.txt"), "w").write("x")

p = subprocess.Popen([EXE, sub])
PID = p.pid
main = None
t0 = time.time()
while not main and time.time() - t0 < 10:
    for h in wins(PID):
        if cls(h) == "FFMainWnd":
            main = h
            break
    time.sleep(0.1)
time.sleep(1.6)
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
u.MoveWindow(main, 80, 40, 1000, 700, True)
time.sleep(0.5)

lst = u.GetDlgItem(main, 1001)
n0 = u.SendMessageW(lst, 0x1004, 0, 0)
t0_txt = title(main)
print("当前目录 = sub（含 1 个文件），列表项数 =", n0, " 标题 =", t0_txt)

print("→ 外部删除 sub 目录（模拟当前目录被删）…")
shutil.rmtree(sub)
time.sleep(2.5)                       # watch 去抖 350ms + 导航刷新

n1 = u.SendMessageW(lst, 0x1004, 0, 0)
t1_txt = title(main)
print("删除后列表项数 =", n1, " 标题 =", t1_txt)
# 判定：标题必须已经从"...\sub"变成"...\_deltest"（退回父目录）
ok = ("_deltest" in t1_txt) and ("sub - FileCE" not in t1_txt)
print("结果:", "OK 已自动退回父目录" if ok else "!!! 仍卡在已删除的目录里")

p.terminate()
time.sleep(0.4)
shutil.rmtree(root, ignore_errors=True)
print("RESULT:", "PASS" if ok else "FAIL")
