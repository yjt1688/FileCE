# -*- coding: utf-8 -*-
"""拖入（WM_DROPFILES）端到端回归，对应 handle_drop_files 的四条语义：
1) 拖入即复制：把别处的文件拖进正在浏览的目录 → 复制到当前目录并刷新列表；
2) 拖到当前目录不动作：源目录 == 当前目录 → 一个字节都不复制（无 副本/(2) 重名文件）；
3) 在"此电脑"视图拖入一个文件 → 导航到该文件所在目录（不复制）；
4) 在"此电脑"视图拖入一个目录 → 直接进入该目录。

投递手段分两种，互相补位：
- 合成 HDROP：测试进程 GlobalAlloc 出 DROPFILES + 宽字符路径表，
  PostMessageW(WM_DROPFILES, hglobal, 0) —— 与 shell 投递的真实消息同构
  （DragQueryFileW/DragFinish 照常工作，句柄跨进程有效）。
  分别投到"列表窗口"（覆盖 列表→主窗口 转发链）和"主窗口"（直达路径）。
- 真实鼠标自拖自放：同一实例里把列表文件拖回自己列表的空白处 ——
  走完整 OLE DoDragDrop → shell 默认放落目标（DragAcceptFiles）→ WM_DROPFILES
  链路，正是"拖到当前目录不动作"的真实入口。
  （从资源管理器拖入的接收端链路与自拖完全相同，源端行为 FileCE 管不着，
  跨实例真实拖放已由 drag_out_probe.py 覆盖。）

用法: python tests/drag_in_probe.py
"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os, shutil

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
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

GMEM_MOVEABLE, GMEM_ZEROINIT, GMEM_SHARE = 0x0002, 0x0040, 0x2000
WM_DROPFILES = 0x0233
LVM_GETITEMCOUNT = 0x1004


class DROPFILES(ctypes.Structure):
    _fields_ = [("pFiles", w.DWORD), ("pt", w.POINT), ("fNC", w.BOOL), ("fWide", w.BOOL)]


k.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]; k.GlobalAlloc.restype = ctypes.c_void_p
k.GlobalLock.argtypes = [ctypes.c_void_p]; k.GlobalLock.restype = ctypes.c_void_p
k.GlobalUnlock.argtypes = [ctypes.c_void_p]


def make_hdrop(paths):
    """按 shell 的 CF_HDROP 布局造一个 HDROP：DROPFILES 头 + 宽字符路径表（双 0 结尾）。"""
    size = ctypes.sizeof(DROPFILES) + 2
    for p in paths:
        size += (len(p) + 1) * 2
    h = k.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT | GMEM_SHARE, size)
    if not h:
        raise RuntimeError("GlobalAlloc failed")
    ptr = k.GlobalLock(h)
    if not ptr:
        raise RuntimeError("GlobalLock failed")
    df = DROPFILES.from_address(ptr)
    df.pFiles = ctypes.sizeof(DROPFILES)
    df.fWide = True
    off = ctypes.sizeof(DROPFILES)
    for p in paths:
        blob = p.encode("utf-16-le") + b"\x00\x00"
        ctypes.memmove(ptr + off, blob, len(blob))
        off += len(blob)
    k.GlobalUnlock(h)
    return h


def drop(hwnd, paths):
    """模拟把 paths 拖放到 hwnd 上（与 shell 投递的真实 WM_DROPFILES 同构）。"""
    h = make_hdrop(paths)
    if not u.PostMessageW(hwnd, WM_DROPFILES, h, 0):
        raise RuntimeError("PostMessageW(WM_DROPFILES) failed")


HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
TMP = os.environ.get("TEMP", r"C:\Windows\Temp")
SRC = os.path.join(TMP, "ffce_drop_src")
SUB = os.path.join(SRC, "subdir")
DST = os.path.join(TMP, "ffce_drop_dst")

HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def find_main(pid, timeout=15.0):
    time.sleep(1.0)                      # 等主窗口建出
    out = []
    t0 = time.time()

    def cb(h, l):
        c = ctypes.create_unicode_buffer(96)
        u.GetClassNameW(h, c, 96)
        if c.value != "FFMainWnd":
            return True
        p = ctypes.c_uint32(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            out.append(h)
        return True
    while not out and time.time() - t0 < timeout:
        u.EnumWindows(HWNDCB(cb), 0)
        time.sleep(0.15)
    return out[0] if out else None


def child_of(hwnd, cls):
    return u.FindWindowExW(hwnd, None, cls, None)


def child_list(hwnd):
    out = []

    def cb(c, l):
        n = ctypes.create_unicode_buffer(96)
        u.GetClassNameW(c, n, 96)
        if n.value == "SysListView32":
            out.append(c)
        return True
    u.EnumChildWindows(hwnd, HWNDCB(cb), 0)
    return out[0] if out else None


def list_count(main):
    l = child_list(main)
    return u.SendMessageW(l, LVM_GETITEMCOUNT, 0, 0) if l else -1


def addr_path(main):
    """地址栏编辑框里的完整当前路径（面包屑覆盖层不影响 WM_GETTEXT）。"""
    combo = child_of(main, "COMBOBOX")
    if not combo:
        return ""
    edit = u.FindWindowExW(combo, None, "Edit", None)
    if not edit:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    u.SendMessageW(edit, 0x000D, 512, ctypes.cast(buf, ctypes.c_void_p).value)  # WM_GETTEXT
    return buf.value


def title_of(hwnd):
    b = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, b, 512)
    return b.value


def title_path(hwnd):
    t = title_of(hwnd)
    return t.split(" - FileCE")[0].strip() if " - FileCE" in t else t


def wait_until(fn, timeout=6.0, step=0.15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(step)
    return bool(fn())


def stop(p):
    p.terminate()
    time.sleep(0.2)
    if p.poll() is None:
        p.kill()


fails = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not ok:
        fails.append(name)


def write(p, content):
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


# ---- 准备 ----
for d in (SRC, SUB, DST):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
write(os.path.join(SRC, "alpha.txt"), "alpha-content")
write(os.path.join(SRC, "beta.txt"), "beta-content")
write(os.path.join(SRC, "gamma.txt"), "gamma-content")
SUBMARK = "sub-file"
write(os.path.join(SUB, "in_sub.txt"), SUBMARK)

print("=" * 60)
print("A组 拖入即复制（浏览 DST，先投列表窗口=真实落点，再投主窗口）")
print("=" * 60)
pa = subprocess.Popen([EXE, DST])
ha = find_main(pa.pid)
try:
    check("A: 主窗口出现", bool(ha))
    if not ha:
        stop(pa); sys.exit(1)
    check("A: 初始列表为空", list_count(ha) == 0, "count=%d" % list_count(ha))

    drop(child_list(ha), [os.path.join(SRC, "alpha.txt"), os.path.join(SRC, "beta.txt")])
    ok = wait_until(lambda: os.path.exists(os.path.join(DST, "alpha.txt"))
                    and os.path.exists(os.path.join(DST, "beta.txt")))
    check("A1: 投到列表窗口 → 两个文件都复制进来", ok)
    ok2 = wait_until(lambda: list_count(ha) == 2, timeout=4.0)
    check("A1: 列表自动刷新到 2 项", ok2, "count=%d" % list_count(ha))
    if ok:
        check("A1: 复制内容一致",
              open(os.path.join(DST, "alpha.txt"), encoding="utf-8").read() == "alpha-content"
              and open(os.path.join(DST, "beta.txt"), encoding="utf-8").read() == "beta-content")

    drop(ha, [os.path.join(SRC, "gamma.txt")])   # 第二个文件投主窗口（直达路径）
    ok3 = wait_until(lambda: os.path.exists(os.path.join(DST, "gamma.txt")))
    check("A2: 投到主窗口也复制", ok3)
    check("A2: 列表刷新到 3 项", wait_until(lambda: list_count(ha) == 3, timeout=4.0),
          "count=%d" % list_count(ha))
    check("A: 进程未崩溃", pa.poll() is None)
finally:
    stop(pa)

print()
print("=" * 60)
print("B组/E组 拖到当前目录不动作（浏览 SRC；B=合成 HDROP，E=真实鼠标自拖自放）")
print("=" * 60)
SRC_ITEMS = ["alpha.txt", "beta.txt", "gamma.txt", "subdir"]   # SRC 原有内容
pb = subprocess.Popen([EXE, SRC])
hb = find_main(pb.pid)
try:
    check("B: 主窗口出现", bool(hb))
    if not hb:
        stop(pb); sys.exit(1)

    drop(child_list(hb), [os.path.join(SRC, "alpha.txt")])
    time.sleep(1.5)
    check("B: 同目录文件拖给自己 → 无 副本/(2) 重名文件",
          sorted(os.listdir(SRC)) == SRC_ITEMS, str(sorted(os.listdir(SRC))))
    check("B: 列表条目数不变(4)", list_count(hb) == 4, "count=%d" % list_count(hb))
    check("B: 进程未崩溃", pb.poll() is None)

    # E: 真实鼠标把第一行文件拖到本列表空白处（自拖自放，完整 OLE 链路）
    u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.BOOL]
    u.MoveWindow(hb, 10, 40, 620, 420, 1)
    u.SetForegroundWindow.argtypes = [w.HWND]
    u.SetForegroundWindow(hb)
    time.sleep(0.8)
    l = child_list(hb)
    rc = w.RECT()
    u.GetClientRect(l, ctypes.byref(rc))
    p1 = w.POINT(rc.left + 45, rc.top + 40); u.ClientToScreen(l, ctypes.byref(p1))
    p2 = w.POINT(rc.left + (rc.right - rc.left) // 2, rc.top + 220); u.ClientToScreen(l, ctypes.byref(p2))

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                    ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ctypes.POINTER(w.ULONG))]

    class _IU(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("u", _IU)]

    def mouse(flags):
        inp = INPUT(0, _IU(MOUSEINPUT(0, 0, 0, flags, 0, None)))
        u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    u.SetCursorPos(p1.x, p1.y); time.sleep(0.25)
    mouse(0x0002); time.sleep(0.35)          # LEFTDOWN，等列表完成选中
    for i in range(1, 13):                    # 12 步移到列表空白处
        u.SetCursorPos(p1.x + (p2.x - p1.x) * i // 12, p1.y + (p2.y - p1.y) * i // 12)
        time.sleep(0.04)
    time.sleep(0.25)
    mouse(0x0004); time.sleep(1.5)           # LEFTUP，等 WM_DROPFILES 处理完

    check("E: 真实自拖自放 → 仍无副本文件", sorted(os.listdir(SRC)) == SRC_ITEMS,
          str(sorted(os.listdir(SRC))))
    check("E: 列表条目数不变(4)", list_count(hb) == 4, "count=%d" % list_count(hb))
    check("E: 进程未崩溃", pb.poll() is None)
finally:
    stop(pb)

print()
print("=" * 60)
print("C组 此电脑视图拖入文件 → 导航到文件所在目录（不复制）")
print("=" * 60)
pc = subprocess.Popen([EXE])                 # 无参数启动 = 此电脑（当前目录为空）
hc = find_main(pc.pid)
try:
    check("C: 主窗口出现", bool(hc))
    if not hc:
        stop(pc); sys.exit(1)
    check("C: 起始视图是此电脑", addr_path(hc) in ("", "此电脑"), "addr=%r" % addr_path(hc))

    drop(hc, [os.path.join(SRC, "alpha.txt")])
    ok = wait_until(lambda: addr_path(hc).lower() == SRC.lower())
    check("C: 拖入文件 → 导航到其所在目录", ok, "addr=%r" % addr_path(hc))
    check("C: 标题显示该目录名", title_path(hc) == "ffce_drop_src", title_path(hc))
    check("C: 文件没有被复制到别处", sorted(os.listdir(SRC)) == SRC_ITEMS)
    check("C: 进程未崩溃", pc.poll() is None)
finally:
    stop(pc)

print()
print("=" * 60)
print("D组 此电脑视图拖入目录 → 直接进入该目录（独立干净进程，起始=此电脑）")
print("=" * 60)
pd = subprocess.Popen([EXE])
hd = find_main(pd.pid)
try:
    check("D: 主窗口出现", bool(hd))
    if not hd:
        stop(pd); sys.exit(1)
    drop(hd, [SUB])
    ok = wait_until(lambda: addr_path(hd).lower() == SUB.lower())
    check("D: 拖入目录 → 直接进入该目录", ok, "addr=%r" % addr_path(hd))
    check("D: 列表显示目录内容(1 项)", wait_until(lambda: list_count(hd) == 1, timeout=4.0),
          "count=%d" % list_count(hd))
    check("D: 进程未崩溃", pd.poll() is None)
finally:
    stop(pd)
    time.sleep(0.5)
    shutil.rmtree(SRC, ignore_errors=True)
    shutil.rmtree(DST, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails))
    sys.exit(1)
print("全部通过")
