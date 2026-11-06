# -*- coding: utf-8 -*-
"""左侧目录树：外部删除子目录后必须自动刷新（节点消失）

用户实测："左边的树目录 删除目录以后不刷新"。树是惰性展开的，只有展开过的
分支里才有子节点；删除发生在别的进程里，所以必须靠目录监听 + 局部重建。

★测试目录必须用"非隐藏"路径：树的填充逻辑跳过隐藏/系统目录，
  而 %TEMP% 在隐藏的 AppData 下面 —— 用临时目录测会得到"树里没这个节点"的假象。
★每删一个目录节点，节点总数会少 2：目录本身 + 它那个"可展开"占位子节点。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, tempfile, shutil

u = ctypes.WinDLL("user32")
for fn, rt, args in [
    ("GetClassNameW", None, [w.HWND, w.LPWSTR, ctypes.c_int]),
    ("EnumWindows", None, [ctypes.c_void_p, w.LPARAM]),
    ("GetWindowThreadProcessId", w.DWORD, [w.HWND, ctypes.POINTER(w.DWORD)]),
    ("GetDlgItem", w.HWND, [w.HWND, ctypes.c_int]),
    ("SendMessageW", ctypes.c_ssize_t, [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]),
    ("SetWindowPos", ctypes.c_bool, [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]),
    ("MoveWindow", ctypes.c_bool, [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]),
]:
    f = getattr(u, fn)
    f.argtypes = args
    if rt:
        f.restype = rt

TVM_GETCOUNT = 0x1105
TVM_GETNEXTITEM = 0x110A
TVM_EXPAND = 0x1102
TVGN_CARET, TVGN_CHILD = 9, 4
TVE_EXPAND = 2


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


EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
# ★必须用"非隐藏"路径：树的填充逻辑会跳过隐藏/系统目录，
#   而 %TEMP% 在隐藏的 AppData 下面 —— 用临时目录测树会得到"树里没有这个节点"的假象。
sand = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "_treetest")
sand = os.path.abspath(sand)
shutil.rmtree(sand, ignore_errors=True)
os.makedirs(sand)
for n in ("sub1", "sub2", "sub3"):
    os.makedirs(os.path.join(sand, n))
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
time.sleep(1.5)
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
u.MoveWindow(main, 80, 40, 1000, 700, True)
time.sleep(0.6)

tree = u.GetDlgItem(main, 1002)
print("树控件:", hex(tree or 0))
caret = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CARET, 0)
print("当前节点:", hex(caret or 0))
n_before_expand = u.SendMessageW(tree, TVM_GETCOUNT, 0, 0)
print("展开前节点总数:", n_before_expand)

# 展开当前节点 → 树里出现 sub1/sub2/sub3
u.SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, caret)
time.sleep(0.8)
n0 = u.SendMessageW(tree, TVM_GETCOUNT, 0, 0)
print("展开后节点总数:", n0, "(应比展开前多 3)")

# 外部删掉一个子目录
shutil.rmtree(os.path.join(sand, "sub1"))
print("已在外部删除 sub1，等待自动刷新…")
t0 = time.time()
n1 = n0
while time.time() - t0 < 5:
    n1 = u.SendMessageW(tree, TVM_GETCOUNT, 0, 0)
    if n1 == n0 - 1:
        break
    time.sleep(0.1)
print("刷新后节点总数:", n1)
ok = n1 < n0
print("结果:", ("OK 树自动刷新了（%d -> %d）" % (n0, n1)) if ok else "!!! 树没刷新")

# 再删一个，验证可重复
shutil.rmtree(os.path.join(sand, "sub2"))
t0 = time.time()
n2 = n1
while time.time() - t0 < 5:
    n2 = u.SendMessageW(tree, TVM_GETCOUNT, 0, 0)
    if n2 == n1 - 1:
        break
    time.sleep(0.1)
ok2 = n2 < n1
print("第二次删除后节点总数:", n2, "->", "OK" if ok2 else "!!! 没刷新")
ok = ok and ok2

p.terminate()
time.sleep(0.4)
shutil.rmtree(sand, ignore_errors=True)
print("RESULT: %s" % ("PASS" if ok else "FAIL"))
import sys
sys.exit(0 if ok else 1)
