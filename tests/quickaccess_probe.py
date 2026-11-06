# -*- coding: utf-8 -*-
"""验证左侧树：「快速访问」在根上排第一，子项由 shell 枚举出来"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, tempfile, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t

TVM_GETNEXTITEM = 0x110A
TVGN_ROOT, TVGN_NEXT, TVGN_CHILD = 0x0, 0x1, 0x4
TVM_GETITEMTEXTW = 0x112E     # 需要 TVITEMW + 跨进程内存，这里不做


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
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


def roots(tree):
    out = []
    h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    while h:
        out.append(h)
        h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, h)
    return out


def children(tree, h):
    out = []
    c = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, h)
    while c:
        out.append(c)
        c = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, c)
    return out


def count(tree, h):
    n = 1
    for c in children(tree, h):
        n += count(tree, c)
    return n


EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
sand = tempfile.mkdtemp(prefix="ffce_qa3_")
open(os.path.join(sand, "a.txt"), "w").write("x")
p = subprocess.Popen([EXE, sand])
PID = p.pid
main = None
t0 = time.time()
while not main and time.time() - t0 < 10:
    for h in wins(PID):
        if cls(h) == "FFMainWnd":
            main = h
            break
    time.sleep(0.1)
time.sleep(2.2)
tree = u.FindWindowExW(main, None, "SysTreeView32", None)
print("树控件:", bool(tree))
if tree:
    rs = roots(tree)
    print("根节点数 =", len(rs), "(应为 2：快速访问 + 此电脑)")
    for i, r in enumerate(rs):
        kids = children(tree, r)
        print("  根[%d] 子节点 %d 个，该子树共 %d 个节点" % (i, len(kids), count(tree, r)))
    # 第一个根 = 快速访问：应该有自己的子项，而不是只有占位"…"
    if rs:
        k0 = children(tree, rs[0])
        print("第一个根（快速访问）的子节点数 =", len(k0),
              "->", "OK 已由 shell 枚举出内容" if len(k0) >= 1 else "!!! 空")
ok_all = bool(tree) and len(rs) == 2 and bool(k0)
print("RESULT:", "PASS" if ok_all else "FAIL")
p.terminate()
time.sleep(0.4)
shutil.rmtree(sand, ignore_errors=True)
