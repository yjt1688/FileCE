# -*- coding: utf-8 -*-
"""地址栏面包屑 + 右键"打开方式"端到端回归：
1) 启动实例浏览到 C:\\ffce\\a\\b\\c（短路径，面包屑不折叠）；
2) 面包屑层（FFCrumb）在编辑框未聚焦时可见；
3) 点根段 → 跳到盘根；点中间段 → 跳到对应祖先目录；点空白 → 进编辑模式；
4) 编辑模式输路径回车仍能导航，之后面包屑恢复；
5) 选中文件后"打开方式"(CMD_OPEN_WITH) 弹出 FFOpenWithDlg 程序列表对话框，进程不崩。

用法: python tests/addr_crumb_probe.py
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
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DEEP = r"C:\ffce\a\b\c"          # 短路径，面包屑不折叠
OWFILE = "ffce_openwith.txt"

WM_LBUTTONDOWN = 0x0201
WM_COMMAND = 0x0111
VK_RETURN = 0x0D
CMD_OPEN_WITH = 20015
CMD_SELECT_ALL = 20016

HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


def title_of(hwnd):
    b = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, b, 512)
    return b.value


def title_path(hwnd):
    t = title_of(hwnd)
    return t.split(" - FileCE")[0].strip() if " - FileCE" in t else t


def addr_path(main):
    """地址栏编辑框里的完整当前路径（比窗口标题更可靠，标题只显示末级目录名）。"""
    combo = u.FindWindowExW(main, None, "COMBOBOX", None)
    if not combo:
        return ""
    edit = u.FindWindowExW(combo, None, "Edit", None)
    if not edit:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    u.SendMessageW(edit, 0x000D, 512, ctypes.cast(buf, ctypes.c_void_p).value)  # WM_GETTEXT
    return buf.value


def find_main(pid, timeout=15.0):
    time.sleep(1.0)                      # 等主窗口建出
    out = []
    pid_arg = [pid]
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
    if out:
        return out[0]
    fallback = []

    def fcb(h, l):
        c = ctypes.create_unicode_buffer(96)
        u.GetClassNameW(h, c, 96)
        if c.value == "FFMainWnd":
            p = ctypes.c_uint32(0)
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid_arg[0]:
                fallback.append(h)
        return True
    u.EnumWindows(HWNDCB(fcb), 0)
    return fallback[0] if fallback else None


def click(hwnd, x, y):
    u.SendMessageW(hwnd, WM_LBUTTONDOWN, 1, (y << 16) | (x & 0xFFFF))
    time.sleep(0.4)


def set_combo_text(combo, text):
    buf = ctypes.create_unicode_buffer(text)
    u.SendMessageW(combo, 0x000C, 0, ctypes.cast(buf, ctypes.c_void_p).value)


def press_enter(edit):
    u.SendMessageW(edit, 0x0100, VK_RETURN, 0)
    u.SendMessageW(edit, 0x0102, VK_RETURN, 0)


def goto_via_edit(main, combo, crumb, path):
    """点面包屑空白进编辑模式，输入 path 回车导航；返回后 breadcrumb 恢复。"""
    rc = w.RECT()
    u.GetClientRect(crumb, ctypes.byref(rc))
    click(crumb, rc.right - 6, (rc.bottom - rc.top) // 2)
    time.sleep(0.3)
    edit = u.FindWindowExW(combo, None, "Edit", None)
    set_combo_text(combo, path)
    press_enter(edit)
    time.sleep(0.8)


fails = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not ok:
        fails.append(name)


shutil.rmtree(DEEP, ignore_errors=True)
os.makedirs(DEEP)
with open(os.path.join(DEEP, OWFILE), "w", encoding="utf-8") as f:
    f.write("open-with probe")

proc = subprocess.Popen([EXE, DEEP])
try:
    main = find_main(proc.pid)
    check("主窗口", bool(main))
    if not main:
        sys.exit(1)
    for _ in range(40):
        if u.IsWindowVisible(main):
            break
        time.sleep(0.1)
    time.sleep(0.5)
    crumb = u.FindWindowExW(main, None, "FFCrumb", None)
    check("面包屑层已创建", bool(crumb))
    if not crumb:
        sys.exit(1)
    check("未聚焦时面包屑可见", u.IsWindowVisible(crumb))

    rc = w.RECT()
    u.GetClientRect(crumb, ctypes.byref(rc))
    W, H = rc.right - rc.left, rc.bottom - rc.top

    # 1) 点根段（最左边）→ 跳到盘根
    click(crumb, 8, H // 2)
    ap = os.path.normcase(addr_path(main))
    check("点根段跳到盘根", ap.replace("/", "\\").startswith("c:\\"), ap)

    # 2) 编辑模式回到深层目录（验证输入框没被面包屑破坏）
    combo = u.FindWindowExW(main, None, "COMBOBOX", None)
    edit = u.FindWindowExW(combo, None, "Edit", None)
    check("找到地址组合框/编辑框", bool(combo and edit))
    goto_via_edit(main, combo, crumb, DEEP)
    ap = os.path.normcase(addr_path(main))
    check("编辑模式输入路径回车仍可导航", ap.endswith("c"), ap)
    check("导航后面包屑恢复显示", u.IsWindowVisible(crumb))

    # 3) 扫描面包屑各 x 位置，确认能跳到祖先目录（容忍折叠/宽度差异）
    seen = set()
    for x in (8, 40, 80, 120, 160, 200, 240):
        click(crumb, x, H // 2)
        seen.add(os.path.normcase(addr_path(main)))
        if x != 8:
            goto_via_edit(main, combo, crumb, DEEP)
    # 期望：盘根 + 至少一个 DEEP 的祖先目录被命中
    def is_ancestor(a):
        a = os.path.normcase(a.replace("/", "\\").rstrip("\\"))
        d = os.path.normcase(DEEP.replace("/", "\\").rstrip("\\"))
        if a == d:
            return False
        if not d.startswith(a):
            return False
        return a == "c:" or d[len(a):len(a) + 1] == "\\"
    ancestors_hit = [a for a in seen if is_ancestor(a)]
    check("点根段可达盘根", os.path.normcase("c:\\") in seen or any(a == "c:\\" for a in seen), str(seen))
    check("点中间段可跳到祖先目录", len(ancestors_hit) >= 1, str(ancestors_hit))

    # 4) 打开方式对话框（自建的 FFOpenWithDlg 程序列表；系统 SHOpenWithDialog
    #    在 Win10 1809+ 已被降级成横幅，见 2026-10-08 日志）
    u.PostMessageW(main, WM_COMMAND, CMD_SELECT_ALL, 0)
    time.sleep(0.4)
    before = set()
    u.EnumWindows(HWNDCB(lambda h, l: (before.add(h), True)[1]), 0)
    u.PostMessageW(main, WM_COMMAND, CMD_OPEN_WITH, 0)
    time.sleep(1.5)
    dlg = []
    def cb(h, l):
        if h not in before and u.IsWindowVisible(h):
            c = ctypes.create_unicode_buffer(96)
            u.GetClassNameW(h, c, 96)
            if c.value == "FFOpenWithDlg":
                dlg.append(h)
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    check("打开方式弹出选择程序列表对话框", bool(dlg))
    for h in dlg:
        u.SendMessageW(h, 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(0.4)

    check("进程未崩溃", proc.poll() is None)
finally:
    proc.terminate()
    time.sleep(0.2)
    if proc.poll() is None:
        proc.kill()
    shutil.rmtree(DEEP, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails))
    sys.exit(1)
print("全部通过")
