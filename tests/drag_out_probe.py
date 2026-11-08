# -*- coding: utf-8 -*-
"""拖放端到端回归：
1) 实例 A 浏览 src 目录，实例 B 浏览 dst 目录（不同目录）；
2) 用真实鼠标事件把 A 列表里的文件拖到 B 列表上松开；
3) 验证 B 目录里出现该文件（放开鼠标就复制，无确认框），且两实例都不崩溃。

用法: python tests/drag_out_probe.py
"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os, shutil

u = ctypes.WinDLL("user32", use_last_error=True)

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
TMP = os.environ.get("TEMP", r"C:\Windows\Temp")
SRC = os.path.join(TMP, "ffce_drag_src")
DST = os.path.join(TMP, "ffce_drag_dst")
MARK = u"拖放测试文件.txt"

HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def find_main(pid, timeout=15.0):
    out = []
    t0 = time.time()

    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        c = ctypes.create_unicode_buffer(96)
        u.GetClassNameW(h, c, 96)
        if c.value != "FFMainWnd":
            return True
        p = ctypes.c_uint32(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            out.append(h)
        return True
    while not out and time.time() - t0 < timeout:
        u.EnumWindows(HWNDCB(cb), 0)
        time.sleep(0.15)
    return out[0] if out else None


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


def client_center(hwnd, dx=None, dy=None):
    rc = w.RECT()
    u.GetClientRect(hwnd, ctypes.byref(rc))
    pt = w.POINT(dx if dx is not None else (rc.right - rc.left) // 2,
                 dy if dy is not None else (rc.bottom - rc.top) // 2)
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                ("dwFlags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.POINTER(w.ULONG))]


class _INPUTU(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", w.DWORD), ("u", _INPUTU)]


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
INPUT_MOUSE = 0


def send_mouse(flags):
    mi = MOUSEINPUT(0, 0, 0, flags, 0, None)
    inp = INPUT(INPUT_MOUSE, _INPUTU(mi))
    u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def drag(from_xy, to_xy, steps=14):
    """真实鼠标按下→分步移动→松开。分步移动要跨过列表的拖动阈值。"""
    u.SetCursorPos(*from_xy)
    time.sleep(0.25)
    send_mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.30)                       # 按下后先让列表完成选中
    for i in range(1, steps + 1):
        x = from_xy[0] + (to_xy[0] - from_xy[0]) * i // steps
        y = from_xy[1] + (to_xy[1] - from_xy[1]) * i // steps
        u.SetCursorPos(x, y)
        time.sleep(0.04)
    time.sleep(0.25)
    send_mouse(MOUSEEVENTF_LEFTUP)
    time.sleep(0.10)


fails = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not ok:
        fails.append(name)


# ---- 准备目录 ----
for d in (SRC, DST):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
with open(os.path.join(SRC, "drag1.txt"), "w", encoding="utf-8") as f:
    f.write("drag-drop e2e marker")
# 列表按名称排序，drag1.txt 恒为第一行（拖的就是它）；再放一个文件验证拖完源文件还在
shutil.copy(os.path.join(SRC, "drag1.txt"), os.path.join(SRC, "zzz2.bin"))

a = subprocess.Popen([EXE, SRC])
b = subprocess.Popen([EXE, DST])
ha = find_main(a.pid)
hb = find_main(b.pid)
try:
    check("实例A主窗口", bool(ha))
    check("实例B主窗口", bool(hb))
    if not (ha and hb):
        sys.exit(1)

    # 两个实例默认都开在 (52,52) 完全重叠，鼠标会点到最上面的那个。
    # 先把窗口错开：A 在上半屏、B 在下半屏，再取真实坐标。
    u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.BOOL]
    u.MoveWindow(ha, 10, 40, 620, 420, 1)
    u.MoveWindow(hb, 10, 480, 620, 420, 1)
    u.SetForegroundWindow.argtypes = [w.HWND]
    u.SetForegroundWindow(ha)
    time.sleep(0.8)

    la, lb = child_list(ha), child_list(hb)
    check("两侧都有列表控件", bool(la and lb))

    src_pt = client_center(la, dx=45, dy=40)   # 第一行文件
    dst_pt = client_center(lb)

    print("  拖动: A%s -> B%s" % (src_pt, dst_pt))
    drag(src_pt, dst_pt)
    time.sleep(2.0)                            # 复制 + 刷新

    ok1 = os.path.exists(os.path.join(DST, "drag1.txt"))
    ok2 = os.path.exists(os.path.join(SRC, "zzz2.bin")) and os.path.exists(os.path.join(SRC, "drag1.txt"))
    check("放开鼠标后目标目录出现被拖文件", ok1)
    check("是复制不是移动：源文件仍在", ok2)
    check("实例A未崩溃", a.poll() is None)
    check("实例B未崩溃", b.poll() is None)
    if ok1:
        with open(os.path.join(DST, "drag1.txt"), "r", encoding="utf-8") as f:
            check("复制内容一致", f.read() == "drag-drop e2e marker")
finally:
    for p in (a, b):
        p.terminate()
        time.sleep(0.2)
        if p.poll() is None:
            p.kill()
    time.sleep(0.5)
    shutil.rmtree(SRC, ignore_errors=True)
    shutil.rmtree(DST, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails))
    sys.exit(1)
print("全部通过")
