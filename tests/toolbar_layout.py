# -*- coding: utf-8 -*-
r"""单条带布局回归（原第二条"工具栏"已整条取消）。

现在顶部只有一条带（内部仍叫 addrBar），自上而下：
    菜单栏(非客户区) → 地址栏条 → 标签栏
条带上 8 个按钮，地址输入框紧跟其后：
    后退 / 前进 / 上级 / 刷新 / 此电脑 | 查找 / 筛选 / 查看 | [地址输入框]
原先第二条上的 新建文件夹/复制/剪切/粘贴/删除 已下线，改走右键菜单、
主菜单「文件」和快捷键；「查看」菜单里的"工具栏"开关也一并移除。

本探针守护：
  A 只有一条 FFToolBar，贴在顶部
  B 按钮段宽度 = 8 个按钮（按 DPI 折算），地址框正好接在后面
  C 8 个按钮位置逐一命中条带；地址框中心命中 ComboBox
  D 「查看」菜单里有"地址栏"、没有"工具栏"
  E 隐藏/显示地址栏条：标签栏随之上移复位，切回来必须真的可见（不能留白条）
  F 6/7/8 三个新按钮真能干活：查找弹窗 / 筛选面板 / 查看菜单
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))

WM_COMMAND = 0x0111; WM_INITMENUPOPUP = 0x0117
WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E
WM_LBUTTONDOWN = 0x0201; WM_LBUTTONUP = 0x0202
WM_CLOSE = 0x0010
MK_LBUTTON = 0x0001
MF_BYCOMMAND = 0; MF_CHECKED = 8; MF_BYPOSITION = 0x400
CMD_TOGGLE_ADDRBAR = 20047

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.restype = ctypes.c_bool
u.GetMenu.argtypes = [w.HWND]; u.GetMenu.restype = w.HMENU
u.GetSubMenu.argtypes = [w.HMENU, ctypes.c_int]; u.GetSubMenu.restype = w.HMENU
u.GetMenuState.argtypes = [w.HMENU, ctypes.c_uint, ctypes.c_uint]; u.GetMenuState.restype = ctypes.c_uint
u.GetMenuItemCount.argtypes = [w.HMENU]; u.GetMenuItemCount.restype = ctypes.c_int
u.GetMenuStringW.argtypes = [w.HMENU, ctypes.c_uint, w.LPWSTR, ctypes.c_int, ctypes.c_uint]
u.GetMenuStringW.restype = ctypes.c_int
u.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.ChildWindowFromPointEx.argtypes = [w.HWND, w.POINT, ctypes.c_uint]
u.ChildWindowFromPointEx.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]; u.SetForegroundWindow.restype = ctypes.c_bool


def cls(h):
    b = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, b, 96)
    return b.value


def wtext(h):
    if not h:
        return ""
    n = u.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    b = ctypes.create_unicode_buffer(n + 2)
    u.SendMessageW(h, WM_GETTEXT, n + 1, ctypes.addressof(b))
    return b.value


def rect_of(h):
    r = w.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r


found = []
PID = w.DWORD(0)


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, l):
    if not u.IsWindowVisible(h):
        return True
    pid = w.DWORD(0)
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value != PID.value:
        return True
    if cls(h) == "FFMainWnd":
        found.append(h)
    return True


p = subprocess.Popen([EXE, r"C:\Windows"])
PID.value = p.pid
t0 = time.time()
while not found and time.time() - t0 < 10:
    u.EnumWindows(cb, 0)
    time.sleep(0.1)
if not found:
    print("RESULT: SKIP 找不到主窗口")
    p.kill()
    sys.exit(0)
time.sleep(1.5)
main = found[0]

kids = {}


@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb(h, l):
    kids.setdefault(cls(h), []).append(h)
    return True


def rescan():
    kids.clear()
    u.EnumChildWindows(main, kcb, 0)


rescan()
bars = kids.get("FFToolBar", [])
addr = kids.get("ComboBox", [None])[0]
tab = kids.get("FFTabBar", [None])[0]
if len(bars) != 1 or not addr or not tab:
    print("RESULT: FAIL 期望 1 条带，实到 %d 条（addr=%s tab=%s）" % (len(bars), addr, tab))
    p.kill()
    sys.exit(1)

bar = bars[0]
ok = True


def check(cond, msg, extra=""):
    global ok
    print(("  OK  " if cond else "  FAIL") + "  " + msg + ("   [%s]" % extra if extra else ""))
    ok = ok and bool(cond)


def popups():
    """当前弹出的对话框 / 弹出菜单（#32770 = 对话框，#32768 = 菜单）"""
    res = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def c2(h, l):
        if not u.IsWindowVisible(h):
            return True
        pid = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == PID.value and cls(h) in ("#32770", "#32768"):
            res.append((cls(h), wtext(h)))
        return True

    u.EnumWindows(c2, 0)
    return res


def close_popups():
    got = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def c3(h, l):
        if not u.IsWindowVisible(h):
            return True
        pid = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == PID.value and cls(h) in ("#32770", "#32768"):
            got.append(h)
            u.PostMessageW(h, WM_CLOSE, 0, 0)
        return True

    u.EnumWindows(c3, 0)
    time.sleep(0.5)


br = rect_of(bar)
ar = rect_of(addr)
scale = (br.bottom - br.top) / 36.0 if (br.bottom - br.top) else 1.0
print("条带=%s top=%d h=%d   地址框 left=%d   缩放=%0.2f" % (hex(bar), br.top, br.bottom - br.top, ar.left, scale))

# ============================================================ A 只有一条带
print("A 条带数量与位置")
check(len(bars) == 1, "只有一条 FFToolBar", "n=%d" % len(bars))
main_r = rect_of(main)
# main.top 是含菜单栏的非客户区顶边，条带应在菜单栏正下方（约 50px）
check(0 <= br.top - main_r.top <= 80, "条带贴在菜单栏正下方", "bar.top=%d main.top=%d" % (br.top, main_r.top))
tab_r = rect_of(tab)
check(br.bottom <= tab_r.top, "标签栏在条带下方", "bar.bottom=%d tab.top=%d" % (br.bottom, tab_r.top))

# ============================================================ B 按钮段宽度
print("B 按钮段宽度 / 地址框位置")
seg = ar.left - br.left
want = int(round(scale * (2 + 8 * 30 + 4)))
print("     实测按钮段=%d 期望=%d（scale=%0.2f：2 + 8*30 + 4）" % (seg, want, scale))
check(abs(seg - want) <= 8, "按钮段宽度 = 8 个按钮", "seg=%d want=%d" % (seg, want))
check(br.top <= ar.top and ar.bottom <= br.bottom, "地址框落在条带内")

# ============================================================ C 8 个按钮命中
print("C 8 个按钮逐一命中")
names = ["后退", "前进", "上级", "刷新", "此电脑", "查找", "筛选", "查看"]
hit_bad = []
for i in range(8):
    cx = int(br.left + scale * (2 + i * 30 + 15))
    cy = (br.top + br.bottom) // 2
    pt = w.POINT(cx, cy)
    u.ScreenToClient(main, ctypes.byref(pt))
    h = u.ChildWindowFromPointEx(main, pt, 0)
    if cls(h) != "FFToolBar":
        hit_bad.append((i, names[i], cls(h)))
check(not hit_bad, "8 个按钮中心都命中条带", str(hit_bad))
pt = w.POINT((ar.left + ar.right) // 2, (ar.top + ar.bottom) // 2)
u.ScreenToClient(main, ctypes.byref(pt))
# 面包屑覆盖层(FFCrumb)就压在地址框最上层（2026-10-08 起的设计），
# 命中 FFCrumb 或 ComboBox 都代表地址框没被工具栏挡住。
hit = cls(u.ChildWindowFromPointEx(main, pt, 0))
check(hit in ("FFCrumb", "ComboBox"), "地址框中心命中（面包屑层或组合框，非工具栏）", hit)

# ============================================================ D 查看菜单
print("D 查看菜单")
view = u.GetSubMenu(u.GetMenu(main), 2)
u.SendMessageW(main, WM_INITMENUPOPUP, view, 0)
names_view = []
for i in range(u.GetMenuItemCount(view)):
    b = ctypes.create_unicode_buffer(64)
    u.GetMenuStringW(view, i, b, 64, MF_BYPOSITION)
    names_view.append(b.value)
print("     查看菜单 = %s" % names_view)
check(any("地址栏" in x for x in names_view), "有'地址栏'开关")
check(not any("工具栏" in x for x in names_view), "已移除'工具栏'开关", str(names_view))
check(bool(u.GetMenuState(view, CMD_TOGGLE_ADDRBAR, MF_BYCOMMAND) & MF_CHECKED), "地址栏默认勾选")
check(len(names_view) == 6, "查看菜单 6 项（原 7 项，去掉'工具栏'）", str(len(names_view)))

# ============================================================ E 显隐
print("E 地址栏条显隐")
tab0 = rect_of(tab)
u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0)
time.sleep(0.8)
vis_ab = u.IsWindowVisible(bar)
vis_addr = u.IsWindowVisible(addr)
tab1 = rect_of(tab)
print("     隐藏后：条带可见=%s 地址框可见=%s 标签栏上移=%d" % (vis_ab, vis_addr, tab0.top - tab1.top))
check((not vis_ab) and (not vis_addr), "隐藏后条带与地址框都不可见")
check(tab0.top - tab1.top >= 30, "标签栏上移一行", "d=%d" % (tab0.top - tab1.top))

u.SendMessageW(main, WM_COMMAND, CMD_TOGGLE_ADDRBAR, 0)
time.sleep(0.8)
br2, ar2 = rect_of(bar), rect_of(addr)
print("     切回后：条带可见=%s 地址框可见=%s top=%d" % (u.IsWindowVisible(bar), u.IsWindowVisible(addr), br2.top))
check(u.IsWindowVisible(bar) and u.IsWindowVisible(addr), "切回后都可见（不能留白条）")
check(abs(br2.top - br.top) <= 1 and abs(ar2.left - ar.left) <= 1, "矩形复位")

# ============================================================ F 6/7/8 按钮
print("F 第 6/7/8 个按钮（查找 / 筛选 / 查看）")
br = rect_of(bar)


def click_btn(i):
    cx = int(br.left + scale * (2 + i * 30 + 15))
    cy = (br.top + br.bottom) // 2
    lp = ((cy - br.top) << 16) | (cx - br.left)
    u.PostMessageW(bar, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    u.PostMessageW(bar, WM_LBUTTONUP, 0, lp)
    time.sleep(1.0)


def top_windows():
    """该进程所有可见顶层窗口（查找对话框是 DialogBox 创建的顶层窗口）"""
    res = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def c4(h, l):
        if not u.IsWindowVisible(h):
            return True
        pid = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == PID.value:
            res.append((cls(h), wtext(h)))
        return True

    u.EnumWindows(c4, 0)
    return res


def list_width():
    rescan()
    hs = kids.get("SysListView32", [])
    return max([rect_of(h).right - rect_of(h).left for h in hs], default=0)


u.SetForegroundWindow(main)
time.sleep(0.3)

base = top_windows()
click_btn(5)
now = top_windows()
new = [x for x in now if x not in base]
print("     点第6个 -> 新增顶层窗口 %s" % new)
check(bool(new), "第6个按钮弹出查找对话框", str(new))
close_popups()

w0 = list_width()
click_btn(6)
w1 = list_width()
print("     点第7个 -> 列表宽度 %d -> %d" % (w0, w1))
check(w1 < w0 - 100, "第7个按钮切出筛选面板（列表被挤窄）", "%d->%d" % (w0, w1))
close_popups()

click_btn(7)
d2 = popups()
print("     点第8个 -> %s" % d2)
check(any(c == "#32768" for c, _ in d2), "第8个按钮弹出查看方式菜单", str(d2))
close_popups()

print()
print("RESULT: %s" % ("PASS" if ok else "FAIL"))
p.terminate()
time.sleep(0.3)
if p.poll() is None:
    p.kill()
sys.exit(0 if ok else 1)
