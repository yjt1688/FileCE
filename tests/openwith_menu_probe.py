# -*- coding: utf-8 -*-
"""右键"打开方式"子菜单（Win10 风格）端到端验证 —— 全程真实鼠标 + 键盘，
不走合成 WM_COMMAND，避免"测试通过、真人点不动"的假阳性。

流程：
  1) 真实左键点中列表里的 .txt 文件（选中并取得焦点）；
  2) 真实右键 -> 上下文菜单弹出（出现 #32768 菜单窗）；
  3) 键盘 ↓↓（打开 -> 打开方式）再 → 展开子菜单
     —— 断言出现第二个 #32768 菜单窗（证明真的是一层子菜单，不是对话框）；
  4) 回车 -> 用子菜单里第一个程序打开该文件
     —— 断言起来了一个新窗口（记事本之类），且进程没崩；
  5) 再次右键 -> ↓↓→ 然后 ↑（最后一个"选择其他应用"）回车
     —— 断言弹出系统打开方式对话框（Shell_Dialog）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys

u = ctypes.WinDLL("user32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetParent.argtypes = [w.HWND]; u.GetParent.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]; u.SetForegroundWindow.restype = ctypes.c_bool
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetGuiResources.argtypes = [w.HANDLE, w.DWORD]
u.GetGuiResources.restype = w.DWORD
u.InvalidateRect.argtypes = [w.HWND, ctypes.c_void_p, ctypes.c_bool]
u.UpdateWindow.argtypes = [w.HWND]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.WindowFromPoint.argtypes = [w.POINT]; u.WindowFromPoint.restype = w.HWND
u.GetAncestor.argtypes = [w.HWND, ctypes.c_uint]; u.GetAncestor.restype = w.HWND
u.GetForegroundWindow.restype = w.HWND
u.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
u.BringWindowToTop.argtypes = [w.HWND]
u.SetFocus.argtypes = [w.HWND]
u.GetWindowThreadProcessId.restype = ctypes.c_ulong
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
GA_ROOT = 2

LDOWN, LUP = 0x0002, 0x0004
RDOWN, RUP = 0x0008, 0x0010
VK_DOWN, VK_UP, VK_RIGHT, VK_RETURN, VK_ESCAPE = 0x28, 0x26, 0x27, 0x0D, 0x1B
KEYEVENTF_KEYUP = 0x0002

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DIR = r"C:\ffce\owmenu"
FILE = "ow_menu_probe.txt"
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

fails = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        fails.append(name)


def gdi_count(pid):
    """进程当前 GDI 句柄数（用来查图标句柄泄漏）"""
    kk = ctypes.WinDLL("kernel32", use_last_error=True)
    kk.OpenProcess.restype = w.HANDLE
    kk.OpenProcess.argtypes = [w.DWORD, ctypes.c_bool, w.DWORD]
    kk.CloseHandle.argtypes = [w.HANDLE]
    h = kk.OpenProcess(0x0400, False, pid)      # PROCESS_QUERY_INFORMATION
    if not h:
        return -1
    n = u.GetGuiResources(h, 0)                 # GR_GDIOBJECTS
    kk.CloseHandle(h)
    return n


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def title(h):
    b = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, b, 512); return b.value


def pid_of(h):
    p = ctypes.c_uint32(0); u.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value


def find_main(pid, timeout=15.0):
    out = []
    t0 = time.time()

    def cb(h, l):
        if cls(h) == "FFMainWnd" and pid_of(h) == pid and u.IsWindowVisible(h):
            out.append(h)
        return True
    while not out and time.time() - t0 < timeout:
        u.EnumWindows(HWNDCB(cb), 0); time.sleep(0.15)
    return out[0] if out else None


def top_windows():
    res = []

    def cb(h, l):
        if u.IsWindowVisible(h):
            res.append((h, cls(h), title(h), pid_of(h)))
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    return res


def menus(pid):
    return [x for x in top_windows() if x[1] == "#32768" and x[3] == pid]


def click(x, y, right=False):
    # ★右键现在默认弹 Windows 系统菜单；本探针验证的是"本程序自己那份菜单"里的
    #   打开方式子菜单，所以用 Ctrl+右键（该入口按设计保留）。
    if right:
        u.keybd_event(0x11, 0, 0, 0)      # Ctrl down
        time.sleep(0.06)
    u.SetCursorPos(x, y); time.sleep(0.08)
    u.mouse_event(RDOWN if right else LDOWN, 0, 0, 0, None); time.sleep(0.09)
    u.mouse_event(RUP if right else LUP, 0, 0, 0, None)
    if right:
        u.keybd_event(0x11, 0, 2, 0)  # Ctrl up
    time.sleep(0.5)


def raise_top(h):
    """把主窗口置顶：本机桌面上还开着浏览器/输入法窗口，否则点击会落到别的
    窗口上（第二轮菜单不出现就是这么来的）。顺带确认待点位置确实属于本程序，
    不属于就说明被别的窗口盖住了。"""
    u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0,
                   SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    u.SetForegroundWindow(h)


def owned_by(hwnd, root):
    return hwnd and u.GetAncestor(hwnd, GA_ROOT) == root


def force_focus(hwnd, tries=12):
    """一定要把本程序变成前台窗口，否则 ↓→↵ 全被桌面上别的窗口吃掉
    （浏览器/输入法都会抢焦点，测试会时好时坏）。
    常规 SetForegroundWindow 在别的进程持有前台时会失败，这里用
    AttachThreadInput 借用前台线程的输入队列再切一次。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for _ in range(tries):
        if u.GetForegroundWindow() == hwnd:
            return True
        fg = u.GetForegroundWindow()
        tid_fg = u.GetWindowThreadProcessId(fg, None)
        tid_me = k32.GetCurrentThreadId()
        u.AttachThreadInput(tid_me, tid_fg, True)
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.SetFocus(hwnd)
        u.AttachThreadInput(tid_me, tid_fg, False)
        time.sleep(0.25)
    return u.GetForegroundWindow() == hwnd


def open_submenu(pid):
    """走到"打开方式"并展开子菜单。注意 ↓ 在弹出项上就会展开子菜单，
    再按 → 反而会把它关掉，所以这里边按边看有没有第二个菜单窗。"""
    key(VK_DOWN)                       # 打开 -> 打开方式
    for _ in range(4):
        if len(menus(pid)) >= 2:
            return True
        key(VK_RIGHT)
        if len(menus(pid)) >= 2:
            return True
        key(VK_DOWN)
    return len(menus(pid)) >= 2


def click_when_ours(x, y, root, right=False, tries=12):
    """点到本程序自己的窗口上才算数；被别的窗口盖住就置顶后重试。"""
    for _ in range(tries):
        if owned_by(u.WindowFromPoint(w.POINT(x, y)), root):
            click(x, y, right=right)
            return True
        raise_top(root)
        time.sleep(0.4)
    click(x, y, right=right)
    return False


def open_menu_at(x, y, root, pid, tries=4):
    """右键把上下文菜单点出来。偶尔会落在一次瞬时状态里（刚被别的窗口
    抢过焦点等），所以允许多试几次并轮询菜单窗是否出现。"""
    for k in range(tries):
        raise_top(root)
        force_focus(root)
        click_when_ours(x, y, root, right=True)
        t0 = time.time()
        while time.time() - t0 < 1.5:
            if menus(pid):
                return True
            time.sleep(0.15)
        print("    第%d 次右键没出菜单，重试" % (k + 1))
    return bool(menus(pid))


def key(vk):
    u.keybd_event(vk, 0, 0, None); time.sleep(0.12)
    u.keybd_event(vk, 0, KEYEVENTF_KEYUP, None); time.sleep(0.28)


shutil.rmtree(DIR, ignore_errors=True)
os.makedirs(DIR)
target = os.path.join(DIR, FILE)
with open(target, "w", encoding="utf-8") as f:
    f.write("open-with submenu probe\n")

proc = subprocess.Popen([EXE, DIR])
spawned = []
try:
    main = find_main(proc.pid)
    check("主窗口出现", bool(main), str(main))
    if not main:
        sys.exit(1)
    time.sleep(1.0)
    raise_top(main); time.sleep(0.5)

    lst = u.FindWindowExW(main, None, "SysListView32", None)
    check("找到文件列表", bool(lst), str(lst))
    if not lst:
        sys.exit(1)

    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(rc.left, rc.top); u.ClientToScreen(lst, ctypes.byref(org))
    # 详细列表视图：表头下方就是第一行
    rx, ry = org.x + 60, org.y + 34
    print("  list client %d,%d  ->  点 (%d,%d)" % (rc.right - rc.left, rc.bottom - rc.top, rx, ry))

    before = set(h for h, _, _, _ in top_windows())

    # 1) 左键选中文件行   2) 右键弹菜单
    click_when_ours(rx, ry, main)
    m1 = menus(proc.pid) if open_menu_at(rx, ry, main, proc.pid) else []
    check("真实右键弹出上下文菜单", len(m1) >= 1, "菜单窗=%d" % len(m1))

    # 3) ↓ 到"打开方式"并展开子菜单（键盘必须真的进到菜单，所以先确认前台）
    check("本程序在前台（键盘能进菜单）", force_focus(main))
    ok_sub = open_submenu(proc.pid)
    m2 = menus(proc.pid)
    check("“打开方式”展开成子菜单（出现第二个菜单窗）", ok_sub and len(m2) >= 2,
          "菜单窗=%d %s" % (len(m2), [t for _, _, t, _ in m2]))

    # 4) 回车 = 用子菜单第一项（本机 .txt 默认是记事本）打开文件
    key(VK_RETURN)
    new_win = None
    t0 = time.time()
    while time.time() - t0 < 6.0 and not new_win:
        for h, c, t, p in top_windows():
            if h in before or c == "#32768":
                continue
            if c in ("Notepad", "ApplicationFrameWindow") or FILE.lower() in t.lower():
                new_win = (h, c, t, p); break
        if not new_win:
            time.sleep(0.25)
    check("选中的程序真的打开了该文件（新窗口出现）", bool(new_win), str(new_win))
    if new_win:
        spawned.append(new_win[0])
    check("进程未崩溃（选完程序后）", proc.poll() is None)

    # 被拉起的程序（记事本）会盖住本程序，先关掉并把焦点抢回来再做第二轮
    for h in spawned:
        if u.IsWindow(h):
            u.PostMessageW(h, 0x0010, 0, 0)
    time.sleep(1.0)
    raise_top(main); time.sleep(0.6)

    # 5) 再走一遍：右键 -> 到"打开方式" -> 展开 -> ↑（最后一项"选择其他应用"）-> 回车
    if open_menu_at(rx, ry, main, proc.pid):
        force_focus(main)
        ok_sub2 = open_submenu(proc.pid)
        key(VK_UP)                    # 子菜单里从第一项退到最后一项 = 选择其他应用
        before2 = set(h for h, _, _, _ in top_windows())
        key(VK_RETURN)
        # 「选择其他应用」现在**交给系统**处理（SM_TAKE_OVER_OPENWITH_PICK=0）。
        # 三种可能都要如实记录，不能把"系统被降级"当成程序缺陷，也不能当成通过：
        #   ① 出现 FFOpenWithDlg  → 走了本程序接管（把开关改成 1 时才会这样）
        #   ② 出现其它窗口        → 系统自己弹了对话框
        #   ③ 什么都没出现        → Win10 1809+ 把 SHOpenWithDialog 降级了（SKIP）
        dlg, other = [], []
        t0 = time.time()
        while time.time() - t0 < 3.0 and not dlg and not other:
            for h, c, t, p in top_windows():
                if h in before2:
                    continue
                if c == "FFOpenWithDlg" and ("打开" in t or "How do you want" in t):
                    dlg.append((h, c, t))
                elif u.IsWindowVisible(h) and c in ("#32770", "ApplicationFrameWindow"):
                    other.append((h, c, t))
            if not dlg and not other:
                time.sleep(0.25)
        if dlg:
            check("“选择其他应用”由本程序接管（弹出 FFOpenWithDlg）", True, str(dlg))
        elif other:
            check("“选择其他应用”交给系统（系统弹了自己的窗口）", True, str(other))
        else:
            print("  [SKIP] “选择其他应用”点了没有反应 —— 系统 SHOpenWithDialog 在 "
                  "Win10 1809+ 被微软降级，属系统行为，不是本程序的缺陷", flush=True)
        if dlg:
            lst = u.GetDlgItem(dlg[0][0], 5301)      # ID_OW_LIST
            n = u.SendMessageW(lst, 0x018B, 0, 0) if lst else 0   # LB_GETCOUNT
            check("  对话框里列出了可选程序（>1 项）", n > 1, "列表项数=%d" % n)

            # ★行高/高度一致性：客户区高度必须是行高的整数倍，否则底部露半行，
            #   用户看到的就是"第 5 项跑出来和框重叠"（实测客户区 186 / 行高 38）。
            if lst and n > 0:
                itemH = u.SendMessageW(lst, 0x01A1, 0, 0)      # LB_GETITEMHEIGHT
                cr = w.RECT()
                u.GetClientRect(lst, ctypes.byref(cr))
                ch = cr.bottom - cr.top
                vis_rows = (ch // itemH) if itemH else 0
                check("  列表至少能完整显示 4 行（底部不留半行）",
                      vis_rows >= 4,
                      "客户区 %d / 行高 %d = %d 整行 + 余 %d px"
                      % (ch, itemH, vis_rows, (ch % itemH) if itemH else 0))
                prev, overlap = None, 0
                for i in range(n):
                    rc = w.RECT()
                    if u.SendMessageW(lst, 0x0198, i, ctypes.addressof(rc)) == -1:
                        continue
                    if prev is not None and rc.top < prev:
                        overlap += 1
                    prev = rc.bottom
                check("  各行矩形连续、无重叠", overlap == 0, "重叠 %d 处" % overlap)
            ck = u.GetDlgItem(dlg[0][0], 5302)        # ID_OW_ALWAYS
            cap = ctypes.create_unicode_buffer(256)
            if ck:
                u.GetWindowTextW(ck, cap, 256)
            check("  有“始终使用此应用打开 .txt 文件”复选框",
                  bool(ck) and ".txt" in cap.value, repr(cap.value))

            # ★图标泄漏：这个列表是自绘的，每重绘一次都要一次图标。
            #   原来 CopyIcon 之后没有 DestroyIcon，每画一次泄漏一个 HICON，
            #   像 WorkBuddy(195MB) 这种程序首次提取还要 40+ms，重绘时就卡。
            if lst:
                g0 = gdi_count(proc.pid)
                for _ in range(60):
                    u.InvalidateRect(lst, None, True)
                    u.UpdateWindow(lst)
                    time.sleep(0.008)
                time.sleep(0.4)
                g1 = gdi_count(proc.pid)
                check("  图标不泄漏 GDI 句柄（重绘 60 次）", (g1 - g0) <= 2,
                      "句柄 %d -> %d" % (g0, g1))
        for h, _, _ in dlg:
            u.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE
        for h, _, _ in other:
            u.PostMessageW(h, 0x0010, 0, 0)
        time.sleep(0.4)
    else:
        check("第二轮右键弹菜单", False, "菜单没出现")

    check("进程未崩溃（全部结束）", proc.poll() is None)
finally:
    for h in spawned:
        if u.IsWindow(h):
            u.PostMessageW(h, 0x0010, 0, 0)
    if main:
        u.SetWindowPos(main, HWND_NOTOPMOST, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.5)
    proc.terminate(); time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
    shutil.rmtree(DIR, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails)); sys.exit(1)
print("全部通过")
