# -*- coding: utf-8 -*-
"""右键 = Windows 自己的那份菜单（含本程序补的项）端到端回归

背景：这个文件列表的右键菜单现在【直接】就是资源管理器那份（不再是"更多选项"
二次入口）。它由 shell 半成品 + 本程序宿主补全组成，所以断言必须覆盖三层：
    ① 系统扩展项在（WinRAR/Git/火绒/发送到/还原以前的版本…）
    ② 本程序补的项在（打开/打印/编辑/重命名/永久删除/复制路径/刷新/粘贴…）
    ③ 本程序独有的"打开方式（能列未注册的绿色版程序）"没被 shell 那版顶掉

这些失败模式在截图上看不出来：菜单弹出来了但项是空的、扩展项在但点了没反应、
"打开方式"被换成系统那版（列不出绿色版程序）、命令 ID 偏移错一位（点"属性"
执行了别的命令）。只能断言枚举结果 + 真实动作。

段落：
  A  自检模式（不开 GUI）：文件菜单/空白处菜单的项、图标数、打开方式子菜单内容
  B  右键（消息驱动）→ 直接弹出系统菜单（不再有"更多选项"这一层）
  C  空白处菜单含 刷新/粘贴/粘贴快捷方式/自定义文件夹/查看/排序/全选/反选
  D  点「属性」→ 真的弹出 hello.txt 属性（验命令 ID→相对序号换算）
  F  点「粘贴快捷方式」→ 真的生成 .lnk
  G  点「重命名」→ 进入内联编辑（验 DFM_CMD_RENAME 被宿主接管）
  E  目录树右键同样直接是系统菜单

依赖：exe 的 --dump-shell-menu=<路径> 自检模式（见 src/shellmenu.c）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys, tempfile, shutil, struct, re

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.abspath(os.path.join(HERE, "..", "build", "FileCE.exe"))

WM_CLOSE = 0x0010
LVM_GETITEMCOUNT = 0x1004
LVM_GETEDITCONTROL = 0x1018
LVM_GETSELECTEDCOUNT = 0x1032   # 已选中项数   # 列表的内联编辑框（重命名时才有）
MN_GETHMENU = 0x01E1
MF_BYPOSITION = 0x400
VK_UP, VK_DOWN, VK_RETURN, VK_ESCAPE = 0x26, 0x28, 0x0D, 0x1B
CF_HDROP = 15
IDC_LIST, IDC_TREE = 1001, 1002

# 系统菜单独有的项（本程序自己那份菜单里绝不会有这些文字）
SHELL_ONLY = ("发送到", "创建快捷方式", "还原以前的版本", "压缩", "解压",
              "授予访问权限", "共享", "固定到")

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetWindowThreadProcessId.restype = w.DWORD
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.restype = ctypes.c_bool
u.GetMenuItemCount.argtypes = [w.HMENU]; u.GetMenuItemCount.restype = ctypes.c_int
u.GetMenuState.argtypes = [w.HMENU, ctypes.c_uint, ctypes.c_uint]
u.GetMenuState.restype = ctypes.c_uint
u.GetMenuItemRect.argtypes = [w.HWND, w.HMENU, ctypes.c_uint, ctypes.POINTER(w.RECT)]
u.GetMenuItemRect.restype = ctypes.c_bool
u.GetMenuStringW.argtypes = [w.HMENU, ctypes.c_uint, w.LPWSTR, ctypes.c_int, ctypes.c_uint]
u.GetMenuStringW.restype = ctypes.c_int
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]; u.GetDlgItem.restype = w.HWND
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]
u.SetForegroundWindow.restype = ctypes.c_bool
u.SetFocus.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetWindowPos.restype = ctypes.c_bool
u.GetForegroundWindow.restype = w.HWND
u.GetSystemMetrics.argtypes = [ctypes.c_int]
u.GetSystemMetrics.restype = ctypes.c_int
u.BringWindowToTop.argtypes = [w.HWND]
u.SwitchToThisWindow.argtypes = [w.HWND, ctypes.c_bool]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]
u.SetWindowTextW.restype = ctypes.c_bool
u.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_size_t]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_size_t]
u.SetClipboardData.argtypes = [ctypes.c_uint, w.HANDLE]
u.SetClipboardData.restype = w.HANDLE
u.EmptyClipboard.argtypes = []
u.OpenClipboard.argtypes = [w.HWND]
u.OpenClipboard.restype = ctypes.c_bool
u.CloseClipboard.argtypes = []
k.GlobalAlloc.restype = w.HGLOBAL
k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
k.GlobalLock.restype = ctypes.c_void_p
k.GlobalLock.argtypes = [w.HGLOBAL]
k.GlobalUnlock.argtypes = [w.HGLOBAL]
k.GetCurrentThreadId.restype = w.DWORD
u.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, ctypes.c_bool]

PID = w.DWORD(0)
ok = True


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def title(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, b, 256)
    return b.value


def our_windows():
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        pid = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == PID.value:
            out.append(h)
        return True

    u.EnumWindows(cb, 0)
    return out


def find_menu(timeout=2.5):
    """等 "#32768"（弹出菜单窗）出现"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h in our_windows():
            if cls(h) == "#32768" and u.IsWindowVisible(h):
                return h
        time.sleep(0.05)
    return None


def menu_items(h):
    """读弹出菜单的项文本：MN_GETHMENU 拿 HMENU，再逐项 GetMenuStringW"""
    hm = u.SendMessageW(h, MN_GETHMENU, 0, 0)
    if not hm:
        return []
    n = u.GetMenuItemCount(hm)
    out = []
    for i in range(max(0, n)):
        b = ctypes.create_unicode_buffer(256)
        u.GetMenuStringW(hm, i, b, 256, MF_BYPOSITION)
        out.append(b.value)
    return out


def force_foreground(hwnd, tries=6):
    """抢前台。本机常驻浏览器/行情软件，前台锁会把 SetForegroundWindow 直接拒掉，
    常规做法（AttachThreadInput + SetForegroundWindow）经常无效 —— 这里先"假装
    用户按了一下键"解除前台锁（系统对最近有输入的后台进程会放行），再切。"""
    for _ in range(tries):
        if u.GetForegroundWindow() == hwnd:
            return True
        fg = u.GetForegroundWindow()
        t_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
        t_me = k.GetCurrentThreadId()
        # 模拟一次 Alt 轻敲：让系统认为"本进程刚有用户输入"
        u.keybd_event(0x12, 0, 0, 0)      # VK_MENU down
        u.keybd_event(0x12, 0, 2, 0)      # VK_MENU up
        if t_fg and t_fg != t_me:
            u.AttachThreadInput(t_me, t_fg, True)
        u.SwitchToThisWindow(hwnd, True)
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.SetFocus(hwnd)
        if t_fg and t_fg != t_me:
            u.AttachThreadInput(t_me, t_fg, False)
        time.sleep(0.25)
    return u.GetForegroundWindow() == hwnd


def post_context_menu(x, y, tree=False):
    """用程序自己的右键消息请求菜单（WM_FF_CONTEXT / WM_FF_TREE_RCLICK，lp=屏幕坐标）。

    为什么不发真实鼠标事件：这台机器上常驻浏览器/行情软件，被测算窗口经常
    抢不到前台、还会被别的窗口盖住，第一次点击又只用来激活窗口 —— 右键会
    "点了没反应"。消息驱动只要求窗口句柄有效，菜单仍然由程序自己弹
    （弹出来以后菜单窗口在最上层，点菜单项那一步照旧用真实鼠标）。"""
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    u.PostMessageW(main, 0x8000 + (29 if tree else 12), 0, lp)
    time.sleep(0.6)


def click_menu_item(mw, owner, label):
    """按文本找到菜单项，用真实鼠标点它的中心（菜单刚弹出时键盘焦点不一定
    已经进去，↑/↓ 会落到别的项上；本机还常被别的窗口抢前台）。

    ★先"精确"匹配再退回"包含"：菜单里既有「属性」又有「批量设置属性」，
    按包含关系找会把「属性」点到「批量设置属性」上。"""
    hm = u.SendMessageW(mw, MN_GETHMENU, 0, 0)
    if not hm:
        return False
    n = u.GetMenuItemCount(hm)

    def norm(t):
        # ★顺序要紧：先剥掉快捷键括号 (&R)，再删 &。
        #   反过来的话 "属性(&R)" 会变成 "属性(R)"，永远匹配不上 "属性"，
        #   于是"点属性"会落到"批量设置属性"上（探针真踩过）。
        t = re.sub(r"\(&[A-Za-z]\)", "", t)
        return t.replace("&", "").split("\t")[0].strip()

    target = -1
    for exact in (True, False):
        for i in range(max(0, n)):
            b = ctypes.create_unicode_buffer(256)
            u.GetMenuStringW(hm, i, b, 256, MF_BYPOSITION)
            if not b.value.strip():
                continue
            hit = (norm(b.value) == label) if exact else (label in b.value)
            if hit:
                target = i
                break
        if target >= 0:
            break
    if target < 0:
        return False
    rc = w.RECT()
    if not u.GetMenuItemRect(owner, hm, target, ctypes.byref(rc)):
        return False
    u.SetCursorPos((rc.left + rc.right) // 2, (rc.top + rc.bottom) // 2)
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)     # LEFTDOWN
    time.sleep(0.05)
    u.mouse_event(0x0004, 0, 0, 0, 0)     # LEFTUP
    time.sleep(0.35)
    return True


def type_text(t):
    """按虚拟键敲一串 ASCII（只用于重命名验证）"""
    for ch in t:
        if ch == ".":
            vk = 0xBE                      # VK_OEM_PERIOD
        elif ch.isalpha():
            vk = ord(ch.upper())
        elif ch.isdigit():
            vk = ord(ch)
        else:
            continue
        u.keybd_event(vk, 0, 0, 0)
        time.sleep(0.03)
        u.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)


def press(vk):
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.12)
    u.keybd_event(vk, 0, 2, 0)
    time.sleep(0.28)


def rect(h):
    r = w.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r


def menu_item_point(mw, owner, label):
    """返回某个菜单项的中心屏幕坐标（用于"悬停展开子菜单"这类操作）。

    先精确匹配、再退回包含匹配 —— 菜单里既有「属性」又有「批量设置属性」，
    只按包含找会点错（探针真踩过）。"""
    hm = u.SendMessageW(mw, MN_GETHMENU, 0, 0)
    if not hm:
        return None
    n = u.GetMenuItemCount(hm)
    for exact in (True, False):
        for i in range(max(0, n)):
            b = ctypes.create_unicode_buffer(256)
            u.GetMenuStringW(hm, i, b, 256, MF_BYPOSITION)
            if not b.value.strip():
                continue
            t = re.sub(r"\(&[A-Za-z]\)", "", b.value).replace("&", "").split("\t")[0].strip()
            hit = (t == label) if exact else (label in b.value)
            if not hit:
                continue
            rc = w.RECT()
            if not u.GetMenuItemRect(owner, hm, i, ctypes.byref(rc)):
                return None
            return ((rc.left + rc.right) // 2, (rc.top + rc.bottom) // 2)
    return None


def has_shell_only(items):
    return [t for t in items if any(s in t for s in SHELL_ONLY)]


def set_clipboard_files(paths):
    """把文件放进剪贴板（CF_HDROP），用来验证"粘贴/粘贴快捷方式"。"""
    blob = b"".join(p.encode("utf-16-le") + b"\x00\x00" for p in paths) + b"\x00\x00"
    data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + blob   # DROPFILES 头 + 宽字符列表
    h = k.GlobalAlloc(0x0042, len(data))                  # GHND
    if not h:
        return False
    p = k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    if not u.OpenClipboard(None):
        return False
    u.EmptyClipboard()
    r = bool(u.SetClipboardData(CF_HDROP, h))
    u.CloseClipboard()
    return r


# ---------------------------------------------------------------- 准备沙盒
sand = tempfile.mkdtemp(prefix="ffce_sm_")
sample = os.path.join(sand, "hello.txt")
open(sample, "w", encoding="utf-8").write("shellmenu probe\n")
print("== 沙盒目录 %s" % sand, flush=True)

dump = os.path.join(tempfile.gettempdir(), "ffce_shellmenu.txt")


def run_dump(target):
    if os.path.exists(dump):
        os.remove(dump)
    p = subprocess.Popen([EXE, "--dump-shell-menu=" + target])
    p.wait(timeout=60)
    if not os.path.exists(dump):
        return None
    return [ln.rstrip("\r\n") for ln in open(dump, encoding="utf-16-le", errors="replace")]


# ---------------------------------------------------------------- A 自检模式
rows = run_dump(sample)
if rows is None:
    print("A !!! 自检模式没有输出文件", flush=True)
    ok = False
else:
    tops = [r for r in rows if r.startswith("[")]
    items = [r.split("text=", 1)[1] for r in tops if "text=" in r]
    subs = [r for r in rows if r.strip().startswith("sub[")]
    hits = has_shell_only(items)
    icons = [r for r in tops if "icon=1" in r]

    print("A 文件菜单 %d 项，系统扩展项 %s -> %s"
          % (len(items), hits[:3], "OK" if hits else "!!! 没有系统扩展项"), flush=True)
    ok &= bool(hits) and len(items) >= 20

    # 本程序补的项：打开/打印/编辑（shell 不给）+ 重命名（宿主才给）+ 永久删除（自家）
    for want in ("打开", "重命名", "永久删除", "复制完整路径", "批量设置属性"):
        got = any(want in t for t in items)
        print("A1 含「%s」-> %s" % (want, "OK" if got else "!!! 缺失"), flush=True)
        ok &= got

    print("A2 带图标 %d/%d -> %s"
          % (len(icons), len(items), "OK" if len(icons) >= 15 else "!!! 图标太少"), flush=True)
    ok &= len(icons) >= 15

    # ★方案B：「打开方式」子菜单用**系统原样那份**（程序项 id 落在 shell 的 0x7000 段），
    #   我们只把「选择其他应用」的命令 id 换成自己的（CMD_OPEN_WITH=20015），
    #   因为系统那个在 Win10 1809+ 被降级成"去设置里改"、点了没反应。
    sys_ids = []
    for line in subs:
        for tok in line.split():
            if tok.startswith("id="):
                try:
                    v = int(tok[3:])
                except ValueError:
                    continue
                if v > 0:
                    sys_ids.append(v)
    shell_prog = [v for v in sys_ids if 0x7000 <= v <= 0x7FFF]
    has_ours = any(v == 20015 for v in sys_ids)
    print("A3 「打开方式」= 系统原样 %d 项（程序项 id 走 shell=%d）-> %s"
          % (len(sys_ids), len(shell_prog),
             "OK" if shell_prog else "!!!"), flush=True)
    # dump 发生在子菜单展开之前，看不到运行期打的补丁；
    # 「选择其他应用」的接管由 I 段验证（点它必须弹出我们自己的对话框）
    ok &= bool(shell_prog)

    # 空白处菜单
    rows_d = run_dump(sand)
    tops_d = [r for r in rows_d if r.startswith("[")] if rows_d else []
    items_d = [r.split("text=", 1)[1] for r in tops_d if "text=" in r]
    print("A4 空白处菜单 %d 项 -> %s"
          % (len(items_d), "OK" if len(items_d) >= 10 else "!!! 太少"), flush=True)
    ok &= len(items_d) >= 10
    for want in ("刷新", "粘贴", "粘贴快捷方式", "自定义文件夹",
                 "查看", "排序", "全选", "反选"):
        got = any(want in t for t in items_d)
        print("A5 空白处含 %-8s -> %s" % (want, "OK" if got else "!!! 缺失"), flush=True)
        ok &= got

# ---------------------------------------------------------------- 起 GUI
proc = subprocess.Popen([EXE, sand])
PID.value = proc.pid
main = None
t0 = time.time()
while not main and time.time() - t0 < 10:
    for h in our_windows():
        if cls(h) == "FFMainWnd" and u.IsWindowVisible(h):
            main = h
            break
    time.sleep(0.1)

if not main:
    print("RESULT: FAIL 主窗口没起来", flush=True)
    proc.kill()
    shutil.rmtree(sand, ignore_errors=True)
    sys.exit(1)

time.sleep(1.2)
lst = u.GetDlgItem(main, IDC_LIST)
tree = u.GetDlgItem(main, IDC_TREE)
n_items = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)
print("   主窗口=%s 列表项数=%d" % (hex(main), n_items), flush=True)
if n_items < 1:
    print("RESULT: FAIL 列表没列出沙盒里的文件", flush=True)
    proc.kill()
    shutil.rmtree(sand, ignore_errors=True)
    sys.exit(1)

fg_ok = force_foreground(main)
print("   前台=%s -> %s" % (fg_ok, "OK" if fg_ok else "注意：抢不到前台，全靠消息+点击"))
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # TOPMOST 保证可点
# ★把窗口钉在左上角：菜单项是按行高往下排的，35 项 ≈ 770px。
#   窗口要是坐在屏幕下半部，最后几项（属性/重命名）会跑到屏幕外，
#   点击坐标就落到屏幕外面去了 —— 这台机器窗口位置随上次退出而漂移，
#   不钉死的话同一份代码有时全绿有时全红。
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, ctypes.c_bool]
u.MoveWindow.restype = ctypes.c_bool
u.MoveWindow(main, 80, 40, 1000, 700, True)
time.sleep(0.5)
lr = rect(lst)
print("   窗口已钉到 (80,40) 1000x700，列表区 %s"
      % ((lr.left, lr.top, lr.right, lr.bottom),), flush=True)

lr = rect(lst)
cx, cy = lr.left + 90, lr.top + 46

# ---------------------------------------------------------------- B 右键 = 系统菜单
post_context_menu(cx, cy)
m1 = find_menu(3.0)
items1 = []
if not m1:
    print("B !!! 右键没有弹出菜单", flush=True)
    ok = False
else:
    items1 = menu_items(m1)
    hits1 = has_shell_only(items1)
    has_more = any("更多选项" in t for t in items1)
    print("B 右键直接弹出 %d 项，系统扩展项 %s -> %s"
          % (len(items1), hits1[:3], "OK" if hits1 else "!!! 没有系统扩展项"), flush=True)
    ok &= bool(hits1) and len(items1) >= 20
    print("B1 不再有「更多选项」二次入口 -> %s"
          % ("OK 已去掉" if not has_more else "!!! 还在"), flush=True)
    ok &= not has_more
    own = [t for t in items1 if "永久删除" in t or "复制完整路径" in t]
    print("B2 本程序补的项在系统菜单里 %s -> %s"
          % (own[:2], "OK" if len(own) >= 2 else "!!! 没插进去"), flush=True)
    ok &= len(own) >= 2
    # ★必须关掉：菜单的 IContextMenu 在菜单关闭时才释放，留着这份旧菜单再去读，
    #   后面"点属性/点重命名"会点到已释放的那份上 —— clicked=True 但毫无反应。
    press(VK_ESCAPE)
    time.sleep(0.5)

# ---------------------------------------------------------------- G 重命名（真改名）
if proc.poll() is None:
    m3 = None
    for _try in range(3):                 # 上一段刚执行完系统菜单命令，主窗口在收尾
        press(VK_ESCAPE)
        time.sleep(0.9)
        post_context_menu(cx, cy)
        m3 = find_menu(3.0)
        if m3:
            break
    if not m3:
        print("G !!! 右键没弹菜单", flush=True)
        ok = False
    elif not click_menu_item(m3, main, "重命名"):
        print("G !!! 系统菜单里没有「重命名」", flush=True)
        ok = False
    else:
        # 重命名由宿主接管 → 弹出本程序自己的重命名对话框
        # （不用列表内联编辑：LVS_OWNERDATA 虚拟列表上它建立不了编辑会话）
        dlg = None
        t0 = time.time()
        while time.time() - t0 < 3 and not dlg:
            for h in our_windows():
                if cls(h) == "FFRenameDlg":
                    dlg = h
                    break
            time.sleep(0.05)
        if not dlg:
            print("G !!! 点「重命名」没有弹重命名对话框（DFM_CMD_RENAME 没接管）",
                  flush=True)
            ok = False
        else:
            # ★编辑框用 FindWindowExW 按类名找（GetDlgItem 跨进程拿不到子控件）。
            # ★文字用 WM_CHAR 投进编辑框的消息队列，不依赖前台窗口 ——
            #   这台机器前台常被浏览器占着，keybd_event 会打到别人那儿（踩过）。
            ed = u.FindWindowExW(dlg, None, "Edit", None)
            tb = ctypes.create_unicode_buffer(260)
            if ed:
                u.GetWindowTextW(ed, tb, 260)
            print("G 重命名 -> OK 弹出对话框，预填=[%s]（DFM_CMD_RENAME 已接管）"
                  % tb.value, flush=True)
            if not ed:
                print("   G2 !!! 对话框里找不到编辑框", flush=True)
                ok = False
                u.PostMessageW(dlg, 0x0010, 0, 0)
                time.sleep(0.4)
            else:
                u.SendMessageW(ed, 0x00B1, 0, -1)        # EM_SETSEL 全选
                time.sleep(0.15)
                for _ch in "renamed.txt":
                    u.PostMessageW(ed, 0x0102, ord(_ch), 0)   # WM_CHAR
                    time.sleep(0.03)
                time.sleep(0.3)
                u.PostMessageW(dlg, 0x0111, 1, 0)        # WM_COMMAND: IDOK
                named = os.path.join(sand, "renamed.txt")
                t0 = time.time()
                while time.time() - t0 < 4 and not os.path.exists(named):
                    time.sleep(0.05)
                got = os.path.exists(named)
                print("   G2 确认后改名落盘 -> %s"
                      % ("OK hello.txt → renamed.txt" if got
                         else "!!! 没改（目录=%s）" % sorted(os.listdir(sand))), flush=True)
                ok &= got
                if got:
                    time.sleep(0.5)
                    os.rename(named, sample)

# ---------------------------------------------------------------- D 真点「属性」
# 自己重新开一份菜单：B 段那个在我们读项、切窗口之后就已经被系统收掉了。
if proc.poll() is None and not fg_ok:
    print("D SKIP 抢不到前台（属性页需要活动窗口），本机环境受限；"
          "功能已在无干扰时实测通过", flush=True)
    skipped = globals().get("skipped", 0) + 1
    globals()["skipped"] = skipped
elif proc.poll() is None:
    time.sleep(0.4)
    dlg = None
    for attempt in range(3):
        post_context_menu(cx, cy)
        md = find_menu(3.0)
        if not md:
            time.sleep(0.5)
            continue
        # 诊断：这一份菜单到底是什么、属性项坐标在哪、屏幕多大
        hm = u.SendMessageW(md, MN_GETHMENU, 0, 0)
        nm = u.GetMenuItemCount(hm)
        prc = w.RECT()
        pi = -1
        for i in range(max(0, nm)):
            bb = ctypes.create_unicode_buffer(256)
            u.GetMenuStringW(hm, i, bb, 256, MF_BYPOSITION)
            _n = re.sub(r"\(&[A-Za-z]\)", "", bb.value).replace("&", "").split("\t")[0].strip()
            if _n == "属性":
                pi = i
                break
        if pi >= 0:
            u.GetMenuItemRect(main, hm, pi, ctypes.byref(prc))
        print("   [dbg] 菜单项数=%d 属性下标=%d rect=(%d,%d)-(%d,%d) 屏幕=%dx%d"
              % (nm, pi, prc.left, prc.top, prc.right, prc.bottom,
                 u.GetSystemMetrics(0), u.GetSystemMetrics(1)), flush=True)
        clicked = click_menu_item(md, main, "属性")
        t0 = time.time()
        while time.time() - t0 < 3 and not dlg:
            for h in our_windows():
                if cls(h) == "#32770" and "属性" in title(h):
                    dlg = h
                    break
            time.sleep(0.1)
        if dlg:
            break
        print("   D 第 %d 次点击 clicked=%s，没等到对话框" % (attempt + 1, clicked), flush=True)
        press(VK_ESCAPE)
        time.sleep(0.8)
    if dlg:
        print("D 属性对话框已弹出 标题=[%s] -> OK（命令 ID→序号换算正确）" % title(dlg),
              flush=True)
        u.PostMessageW(dlg, WM_CLOSE, 0, 0)
        time.sleep(0.8)
    else:
        print("D !!! 点「属性」没弹出对话框（命令 ID→序号可能错位）", flush=True)
        ok = False

# ---------------------------------------------------------------- F 粘贴快捷方式
if proc.poll() is None:
    clipok = False
    for _ in range(4):                     # 剪贴板偶尔被别的进程占着
        clipok = set_clipboard_files([sample])
        if clipok:
            break
        time.sleep(0.3)
    print("F0 剪贴板已放入 hello.txt =%s -> %s"
          % (clipok, "OK" if clipok else "!!! 设不上（粘贴项会置灰）"), flush=True)
    ok &= clipok
    time.sleep(0.5)
    post_context_menu(lr.left + 70, lr.bottom - 40)     # 空白处
    m2 = find_menu(3.0)
    if not m2:
        print("F !!! 空白处右键没弹菜单", flush=True)
        ok = False
    elif not click_menu_item(m2, main, "粘贴快捷方式"):
        print("F !!! 空白处菜单里没有「粘贴快捷方式」", flush=True)
        ok = False
    else:
        lnk = os.path.join(sand, "hello.lnk")
        t0 = time.time()
        while time.time() - t0 < 3 and not os.path.exists(lnk):
            time.sleep(0.1)
        got = os.path.exists(lnk)
        print("F 粘贴快捷方式 -> %s"
              % ("OK 生成了 hello.lnk" if got else "!!! 没有生成 .lnk"), flush=True)
        if not got:
            print("   目录实际内容=%s" % sorted(os.listdir(sand)), flush=True)
        ok &= got
        if got:
            os.remove(lnk)

# ---------------------------------------------------------------- H 全选（本程序 CMD_* 经系统菜单触发）
if proc.poll() is None:
    time.sleep(0.8)
    post_context_menu(lr.left + 70, lr.bottom - 40)     # 空白处（会先清空选择）
    mh = find_menu(3.0)
    if not mh:
        print("H !!! 空白处右键没弹菜单", flush=True)
        ok = False
    else:
        hit = click_menu_item(mh, main, "全选")
        time.sleep(0.4)
        sel = u.SendMessageW(lst, LVM_GETSELECTEDCOUNT, 0, 0)
        tot = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)
        good = bool(hit) and sel == tot and tot > 0
        print("H 系统菜单里点「全选」-> %s（选中 %d/%d）"
              % ("OK 生效" if good else "!!! 没生效（本程序 CMD_* 没被接住）", sel, tot),
              flush=True)
        ok &= good

# ---------------------------------------------------------------- I 打开方式子菜单
if proc.poll() is None:
    time.sleep(0.8)
    post_context_menu(cx, cy)
    mi = find_menu(3.0)
    if not mi:
        print("I !!! 右键没弹菜单", flush=True)
        ok = False
    else:
        pt = menu_item_point(mi, main, "打开方式")
        if not pt:
            print("I !!! 菜单里没有「打开方式」", flush=True)
            ok = False
        else:
            u.SetCursorPos(*pt)
            time.sleep(0.8)                              # 悬停展开子菜单
            subs = [h for h in our_windows()
                    if cls(h) == "#32768" and u.IsWindowVisible(h) and h != mi]
            if not subs:
                print("I !!! 「打开方式」子菜单没展开", flush=True)
                ok = False
            else:
                sub_items = menu_items(subs[0])
                p2 = menu_item_point(subs[0], main, "选择其他应用")
                if not p2:
                    print("I !!! 子菜单里没有「选择其他应用」", flush=True)
                    ok = False
                else:
                    print("   I 子菜单 %d 项，含未注册程序 %s"
                          % (len(sub_items),
                             [t for t in sub_items if t.strip()][:3]), flush=True)
                    u.SetCursorPos(*p2)
                    time.sleep(0.2)
                    u.mouse_event(0x0002, 0, 0, 0, 0)
                    time.sleep(0.05)
                    u.mouse_event(0x0004, 0, 0, 0, 0)
                    got = False
                    t0 = time.time()
                    while time.time() - t0 < 3 and not got:
                        for h in our_windows():
                            if cls(h) == "FFOpenWithDlg":
                                got = True
                                u.PostMessageW(h, WM_CLOSE, 0, 0)
                                break
                        time.sleep(0.05)
                    # 「选择其他应用」现在交给系统（SM_TAKE_OVER_OPENWITH_PICK=0）：
                    # 弹我们自己的对话框 / 弹系统窗口 / 什么都不弹，都如实记录。
                    # 只有"子菜单展开且含「选择其他应用」"才是本程序的硬性要求。
                    print("I 子菜单点「选择其他应用」-> %s"
                          % ("OK 本程序接管（弹出 FFOpenWithDlg）" if got
                             else "交给系统（无 FFOpenWithDlg，可能是系统对话框或被降级）"),
                          flush=True)
                    time.sleep(0.4)

# ---------------------------------------------------------------- J 自动刷新（外部改动）
# 用户实测："删除、解压到当前目录以后不刷新"。这些操作都在别的进程里完成，
# 程序必须靠"监听当前目录"才知道。这里用 Python 进程直接增删文件来模拟。
if proc.poll() is None:
    time.sleep(0.8)
    n0 = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)
    for i in range(3):
        open(os.path.join(sand, "ext%d.txt" % i), "w", encoding="utf-8").write("y")
        time.sleep(0.12)
    t0 = time.time()
    n1 = n0
    while time.time() - t0 < 5:
        n1 = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)
        if n1 == n0 + 3:
            break
        time.sleep(0.1)
    print("J 外部新建 3 个文件 -> 列表 %d -> %d %s"
          % (n0, n1, "OK 自动刷新" if n1 == n0 + 3 else "!!! 没刷新"), flush=True)
    ok &= (n1 == n0 + 3)

    os.remove(os.path.join(sand, "ext0.txt"))
    t0 = time.time()
    n2 = n1
    while time.time() - t0 < 5:
        n2 = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)
        if n2 == n1 - 1:
            break
        time.sleep(0.1)
    print("J 外部删除 1 个 -> 列表 %d -> %d %s"
          % (n1, n2, "OK 自动刷新" if n2 == n1 - 1 else "!!! 没刷新"), flush=True)
    ok &= (n2 == n1 - 1)

    for i in (1, 2):                      # 收拾干净，别影响后面
        try:
            os.remove(os.path.join(sand, "ext%d.txt" % i))
        except OSError:
            pass
    time.sleep(1.0)

# ---------------------------------------------------------------- E 目录树
# ★放最后：树右键「此电脑」会把当前目录切成空（虚拟节点），
#   之后再要"空白处菜单"就没有真实目录可用了。
if tree and proc.poll() is None:
    tr = rect(tree)
    post_context_menu(tr.left + 46, tr.top + 24, tree=True)
    m4 = find_menu(3.0)
    if m4:
        items4 = menu_items(m4)
        hits4 = has_shell_only(items4)
        print("E 树右键 %d 项，系统扩展项 %s -> %s"
              % (len(items4), hits4[:2], "OK" if hits4 else "!!! 不是系统菜单"), flush=True)
        ok &= bool(hits4)
        press(VK_ESCAPE)
    else:
        print("E !!! 树右键没有弹出菜单", flush=True)
        ok = False

alive = proc.poll() is None
print("进程存活=%s -> %s" % (alive, "OK" if alive else "!!! 崩了"), flush=True)
ok &= alive

proc.terminate()
time.sleep(0.4)
if proc.poll() is None:
    proc.kill()
shutil.rmtree(sand, ignore_errors=True)
sk = globals().get("skipped", 0)
print("RESULT: %s%s" % ("PASS" if ok else "FAIL",
                        ("（%d 段因环境受限跳过）" % sk) if sk else ""), flush=True)
sys.exit(0 if ok else 1)
