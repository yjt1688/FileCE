# -*- coding: utf-8 -*-
"""验证：树节点展开后，自动刷新（目录监听）不会把它收起来"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]

TVM_GETCOUNT = 0x1104
TVM_GETNEXTITEM = 0x110A
TVM_EXPAND = 0x1102
TVE_EXPAND = 0x0002
TVE_COLLAPSE = 0x0001
TVGN_ROOT, TVGN_NEXT, TVGN_CHILD, TVGN_CARET = 0x0, 0x1, 0x4, 0x9


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


def count(tree):
    """跨进程 TVM_GETCOUNT 不可靠（一直返回 0），改成遍历计数"""
    def walk(h):
        n = 0
        while h:
            n += 1
            c = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, h)
            if c:
                n += walk(c)
            h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, h)
        return n
    return walk(u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0))


CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
sand = os.path.join(CWD, "build", "_exptest")
shutil.rmtree(sand, ignore_errors=True)
os.makedirs(os.path.join(sand, "alpha"), exist_ok=True)
os.makedirs(os.path.join(sand, "beta"), exist_ok=True)
for i in range(6):
    os.makedirs(os.path.join(sand, "alpha", "a%d" % i), exist_ok=True)

EXE = os.path.join(CWD, "build", "FileCE.exe")
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
time.sleep(1.8)
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
u.MoveWindow(main, 80, 40, 1000, 700, True)
time.sleep(0.8)

tree = u.FindWindowExW(main, None, "SysTreeView32", None)
n0 = count(tree)
caret = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CARET, 0)
print("初始节点数 =", n0, " 当前节点非空 =", bool(caret))

# 展开当前节点（= 测试目录），下面应出现 alpha/beta
u.SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, caret)
time.sleep(0.8)
n1 = count(tree)
print("展开后节点数 =", n1, "(应比初始多 2：alpha + beta)")

# 再展开 alpha（它下面有 6 个 a0..a5）
kids = []
c = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, caret)
while c:
    kids.append(c)
    c = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, c)
print("测试目录子节点数 =", len(kids))
if kids:
    u.SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, kids[0])
    time.sleep(0.8)
n2 = count(tree)
print("再展开第一层子目录后节点数 =", n2, "(再多 6)")

# 触发一次自动刷新：外部新建文件
with open(os.path.join(sand, "trigger.txt"), "w") as f:
    f.write("x")
print("已外部新建文件，等自动刷新…")
time.sleep(2.5)
n3 = count(tree)
print("刷新后节点数 =", n3)

ok = n3 >= n2
print("结果:", ("OK 展开状态保留了（%d -> %d）" % (n2, n3)) if ok
      else "!!! 刷新后收起来了（%d -> %d）" % (n2, n3))

p.terminate()
time.sleep(0.4)
shutil.rmtree(sand, ignore_errors=True)
print("RESULT:", "PASS" if ok else "FAIL")
