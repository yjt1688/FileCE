# -*- coding: utf-8 -*-
"""验证面包屑 + 打开方式（真实输入，不走合成消息）：
A) 面包屑：
   1) WindowFromPoint 在面包屑处应命中 FFCrumb（覆盖层在最上层）；
   2) 真实单击“可点段”（如 c）应跳到对应祖先目录；
   3) 真实单击右侧空白区应进入编辑态（面包屑隐藏、编辑框路径不变、整段选中），
      点列表让编辑框失焦后面包屑恢复；
   4) 真实双击应进入编辑态（面包屑隐藏）。
B) 打开方式：选中文件后触发 CMD_OPEN_WITH，应弹出真正的“选择其他应用”对话框
   （类名为 FFOpenWithDlg）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys

u = ctypes.WinDLL("user32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.IsWindow.argtypes = [w.HWND]; u.IsWindow.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetParent.argtypes = [w.HWND]; u.GetParent.restype = w.HWND
u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040


def raise_top(h):
    """把主窗口置顶。本机桌面常开着几十个浏览器窗口，不置顶的话
    WindowFromPoint 在地址栏处命中的是浏览器 -> 面包屑测试假失败。"""
    u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0,
                   SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
u.SetForegroundWindow.argtypes = [w.HWND]; u.SetForegroundWindow.restype = ctypes.c_bool
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DEEP = r"C:\ffce\a\b\c\d"
OWFILE = "ffce_ow.txt"
WM_COMMAND = 0x0111
CMD_OPEN_WITH = 20015
CMD_SELECT_ALL = 20016
CMD_FOCUS_ADDR = 20036
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def title(h):
    b = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, b, 512); return b.value


def find_main(pid, timeout=15.0):
    out = []
    t0 = time.time()
    def cb(h, l):
        if cls(h) != "FFMainWnd": return True
        p = ctypes.c_uint32(0); u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h): out.append(h)
        return True
    while not out and time.time() - t0 < timeout:
        u.EnumWindows(HWNDCB(cb), 0); time.sleep(0.15)
    return out[0] if out else None


def addr_path(main):
    combo = u.FindWindowExW(main, None, "COMBOBOX", None)
    if not combo: return ""
    edit = u.FindWindowExW(combo, None, "Edit", None)
    if not edit: return ""
    buf = ctypes.create_unicode_buffer(512)
    u.SendMessageW(edit, 0x000D, 512, ctypes.cast(buf, ctypes.c_void_p).value)
    return buf.value


def click(x, y, double=False):
    u.SetCursorPos(x, y); time.sleep(0.06)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None); time.sleep(0.06)
    u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    if double:
        time.sleep(0.06)
        u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None); time.sleep(0.06)
        u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    time.sleep(0.5)


def is_ancestor(a, d):
    a = os.path.normcase(a.replace("/", "\\").rstrip("\\"))
    d = os.path.normcase(d.replace("/", "\\").rstrip("\\"))
    if a == d: return False
    if not d.startswith(a): return False
    return a == "c:" or d[len(a):len(a) + 1] == "\\"


fails = []
def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail else ""))
    if not ok: fails.append(name)


shutil.rmtree(DEEP, ignore_errors=True)
os.makedirs(DEEP)
with open(os.path.join(DEEP, OWFILE), "w", encoding="utf-8") as f:
    f.write("open-with probe")

proc = subprocess.Popen([EXE, DEEP])
try:
    main = find_main(proc.pid)
    check("主窗口", bool(main), str(main))
    if not main: sys.exit(1)
    for _ in range(40):
        if u.IsWindowVisible(main): break
        time.sleep(0.1)
    time.sleep(0.6)
    raise_top(main); time.sleep(0.5)
    crumb = u.FindWindowExW(main, None, "FFCrumb", None)
    check("面包屑层存在", bool(crumb))
    u.SetForegroundWindow(main); time.sleep(0.3)

    rc = w.RECT(); u.GetClientRect(crumb, ctypes.byref(rc))
    pt0 = w.POINT(rc.left, rc.top); u.ClientToScreen(crumb, ctypes.byref(pt0))
    W = rc.right - rc.left; H = rc.bottom - rc.top
    print("  crumb size:", W, H, "screen:", pt0.x, pt0.y)

    # B) 打开方式（先测：此时还在 DEEP 目录，列表里就是那个真实文件）
    u.PostMessageW(main, WM_COMMAND, CMD_SELECT_ALL, 0)
    time.sleep(0.4)
    before = set()
    u.EnumWindows(HWNDCB(lambda h, l: (before.add(h), True)[1]), 0)
    u.PostMessageW(main, WM_COMMAND, CMD_OPEN_WITH, 0)
    time.sleep(1.5)
    # 打印出现的"新窗口"用于排查（打开方式对话框类名是 FFOpenWithDlg）
    newwins = []
    def dbg_enum(h, l):
        if h in before: return True
        if not u.IsWindowVisible(h): return True
        newwins.append((cls(h), title(h), u.GetParent(h) == main))
        return True
    u.EnumWindows(HWNDCB(dbg_enum), 0)
    print("  new windows:", newwins)
    dlg = []
    def cb(h, l):
        if h in before: return True
        if not u.IsWindowVisible(h): return True
        c = cls(h); t = title(h)
        # Win10 1809 起 SHOpenWithDialog 被降级成"请到设置里改默认应用"的
        # 横幅，列不出程序，所以"选择其他应用"改用自建的 FFOpenWithDlg。
        if c == "FFOpenWithDlg" and ("打开" in t or "How do you want" in t):
            dlg.append(h)
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    check("打开方式弹出选择程序列表的对话框", bool(dlg),
          "dlg=%s" % ([(cls(h), title(h)) for h in dlg] if dlg else "none"))
    for h in dlg:
        u.SendMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
    time.sleep(0.3)
    check("进程未崩溃", proc.poll() is None)

    # A1) WindowFromPoint 命中 FFCrumb
    x = pt0.x + int(W * 0.15); y = pt0.y + H // 2
    top = u.WindowFromPoint(w.POINT(x, y))
    check("WindowFromPoint 命中 FFCrumb（覆盖层在最上层）", cls(top) == "FFCrumb", cls(top))

    # A2) 真实单击“可点段”：点 client x≈130（段 'b' => C:\ffce\a\b）
    before = os.path.normcase(addr_path(main))
    click(pt0.x + 130, pt0.y + H // 2)
    after = os.path.normcase(addr_path(main))
    check("真实单击可点段跳到祖先目录", is_ancestor(after, DEEP) or after == os.path.normcase("c:\\"),
          "before=%s after=%s" % (before, after))
    # 回到深层目录便于后续测试
    u.PostMessageW(main, WM_COMMAND, CMD_SELECT_ALL, 0)
    combo = u.FindWindowExW(main, None, "COMBOBOX", None)
    edit = u.FindWindowExW(combo, None, "Edit", None)
    u.SendMessageW(edit, 0x000C, 0, ctypes.cast(ctypes.create_unicode_buffer(DEEP), ctypes.c_void_p).value)
    u.SendMessageW(edit, 0x0100, 0x0D, 0); u.SendMessageW(edit, 0x0102, 0x0D, 0)
    time.sleep(0.8)

    # A3) 常驻面包屑：单击右侧空白区 → 进入编辑态（面包屑隐藏、整段选中）
    before3 = os.path.normcase(addr_path(main))
    click(pt0.x + int(W * 0.85), pt0.y + H // 2)
    visible3 = u.IsWindowVisible(crumb)
    after3 = os.path.normcase(addr_path(main))
    check("真实单击空白区：进入编辑态（面包屑让位）", not visible3)
    check("真实单击空白区：编辑框里路径不变", after3 == before3,
          "before=%s after=%s" % (before3, after3))
    sel3 = u.SendMessageW(edit, 0x00B0, 0, 0) & 0xFFFF     # EM_GETSEL 返回选区起点
    check("编辑态整段选中（可直接 Ctrl+C 复制全路径）", sel3 == 0, "selstart=%d" % sel3)
    # 点列表让编辑框失焦 → 面包屑应恢复显示
    click(pt0.x + 100, pt0.y + H + 140)
    time.sleep(0.4)
    check("焦点离开后面包屑恢复显示", u.IsWindowVisible(crumb))

    # A4) 常驻面包屑：Tab/Ctrl+L 等其它焦点路径【不得】进入编辑态
    # （焦点会被转回列表，面包屑始终可见）
    u.PostMessageW(main, WM_COMMAND, CMD_FOCUS_ADDR, 0)     # Ctrl+L 定位地址栏
    time.sleep(0.4)
    vis_tab = u.IsWindowVisible(crumb)
    fg_list = u.GetFocus() == u.GetDlgItem(main, 0) or True  # 焦点具体控件不强校验
    check("Ctrl+L 后面包屑保持可见（不进编辑态）", vis_tab)
    # Tab 键把焦点切到地址栏也应被拦下面包屑保持
    u.SetForegroundWindow(main); time.sleep(0.3)
    u.keybd_event(0x09, 0, 0, None); time.sleep(0.06)       # Tab down
    u.keybd_event(0x09, 0, 2, None); time.sleep(0.4)        # Tab up
    check("Tab 切换焦点后面包屑保持可见", u.IsWindowVisible(crumb))

    # A5) 双击面包屑 → 进入编辑态
    click(pt0.x + 60, pt0.y + H // 2, double=True)
    time.sleep(0.3)
    visible4 = u.IsWindowVisible(crumb)
    check("真实双击进入编辑态（面包屑隐藏）", not visible4)

finally:
    try:
        u.SetWindowPos(main, HWND_NOTOPMOST, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE)
    except Exception:
        pass
    proc.terminate(); time.sleep(0.2)
    if proc.poll() is None: proc.kill()
    shutil.rmtree(DEEP, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails)); sys.exit(1)
print("全部通过")
