# -*- coding: utf-8 -*-
"""右键「更多选项…」→ Windows 系统右键菜单 端到端回归

为什么要有这个探针：这条链路的失败模式在截图上看不出来 ——
    "菜单弹出来了但里面是空的"、"扩展项在、但点了没反应"、"ID 偏移错一位
    于是点'属性'执行了别的命令"，三者长得一模一样。只能断言枚举结果 + 真实动作。

五段检查：
  A 自检模式（不开 GUI）：--dump-shell-menu 枚举结果里必须有系统独有项
    （发送到 / 创建快捷方式 / 还原以前的版本 / 压缩…），且项数是合理的
  B 列表右键：本程序菜单弹出来，最后一项是「更多选项…」，
    且本程序菜单里【不该】有系统独有项（证明两者确实是两份菜单）
  C 真按回车激活「更多选项…」：弹出的菜单里【必须】有系统独有项
    （证明拿到的是 shell 那份，不是又弹了一遍自己的）
  D 在系统菜单里按 END 落到「属性」再回车：必须真的出现属性对话框
    —— 这一条专门验"命令 ID → 相对序号"的换算，算错一位这一步就什么都不弹
  E 目录树右键同样有「更多选项…」入口

依赖：exe 自带 --dump-shell-menu=<路径> 自检模式（见 src/shellmenu.c）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys, tempfile, shutil, struct

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.abspath(os.path.join(HERE, "..", "build", "FileCE.exe"))

WM_CLOSE = 0x0010
LVM_GETITEMCOUNT = 0x1004
MN_GETHMENU = 0x01E1
MF_BYPOSITION = 0x400
# 菜单里用 VK_UP 从首项"绕回"末项（菜单项高亮是循环的）—— 既有 openwith 探针
# 也是这么干的；VK_END 在本程序菜单里不被识别（实测按了没反应，回车会落到首项）
VK_UP, VK_DOWN, VK_RETURN, VK_ESCAPE = 0x26, 0x28, 0x0D, 0x1B
CF_HDROP = 15
IDC_LIST, IDC_TREE = 1001, 1002
CMD_MORE_OPTIONS = 20080

# 系统菜单独有的项（本程序自己那份菜单里绝不会有这些文字）
SHELL_ONLY = ("发送到", "创建快捷方式", "还原以前的版本", "压缩", "解压",
              "授予访问权限", "共享", "固定到")

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetWindowThreadProcessId.restype = w.DWORD
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.GetMenuItemCount.argtypes = [w.HMENU]; u.GetMenuItemCount.restype = ctypes.c_int
u.GetMenuState.argtypes = [w.HMENU, ctypes.c_uint, ctypes.c_uint]
u.GetMenuState.restype = ctypes.c_uint
u.GetMenuItemRect.argtypes = [w.HWND, w.HMENU, ctypes.c_uint, ctypes.POINTER(w.RECT)]
u.GetMenuItemRect.restype = ctypes.c_bool
u.GetMenuStringW.argtypes = [w.HMENU, ctypes.c_uint, w.LPWSTR, ctypes.c_int, ctypes.c_uint]
u.GetMenuStringW.restype = ctypes.c_int
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]; u.GetDlgItem.restype = w.HWND
u.SetForegroundWindow.argtypes = [w.HWND]
u.SetForegroundWindow.restype = ctypes.c_bool
u.SetFocus.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.SetWindowPos.restype = ctypes.c_bool
u.GetForegroundWindow.restype = w.HWND
u.BringWindowToTop.argtypes = [w.HWND]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_size_t]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_size_t]
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
    """常规 SetForegroundWindow 在别的进程持有前台时会失败，这里用
    AttachThreadInput 借用前台线程的输入队列再切一次，并确认真的切过去了
    （不确认的话键盘会被别的前台窗口吃掉，菜单里的按键全部无声无息）。"""
    for _ in range(tries):
        if u.GetForegroundWindow() == hwnd:
            return True
        fg = u.GetForegroundWindow()
        t_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
        t_me = k.GetCurrentThreadId()
        if t_fg and t_fg != t_me:
            u.AttachThreadInput(t_me, t_fg, True)
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
    "点了没反应"。消息驱动只要求窗口句柄有效，菜单仍然是由程序自己弹的
    （弹出来以后菜单窗口在最上层，点菜单项那一步照旧用真实鼠标）。"""
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    u.PostMessageW(main, 0x8000 + (29 if tree else 12), 0, lp)
    time.sleep(0.6)


def click_menu_item(mw, owner, label):
    """按文本找到菜单项，用真实鼠标点它的中心（比键盘可靠：菜单刚弹出时
    键盘焦点不一定已经进去，↑/↓ 会落到别的项上；本机还常被别的窗口抢前台）。"""
    hm = u.SendMessageW(mw, MN_GETHMENU, 0, 0)
    if not hm:
        return False
    n = u.GetMenuItemCount(hm)
    for i in range(max(0, n)):
        b = ctypes.create_unicode_buffer(256)
        u.GetMenuStringW(hm, i, b, 256, MF_BYPOSITION)
        if not b.value.strip() or label not in b.value:
            continue
        rc = w.RECT()
        if not u.GetMenuItemRect(owner, hm, i, ctypes.byref(rc)):
            return False
        u.SetCursorPos((rc.left + rc.right) // 2, (rc.top + rc.bottom) // 2)
        time.sleep(0.15)
        u.mouse_event(0x0002, 0, 0, 0, 0)     # LEFTDOWN
        time.sleep(0.05)
        u.mouse_event(0x0004, 0, 0, 0, 0)     # LEFTUP
        time.sleep(0.35)
        return True
    return False


def right_click(x, y, activate=True):
    """真实右键。activate=True 时先在同一位置左键点一下 ——
    未激活的窗口第一次点击只会被用来激活，不转发给控件，右键会"点了没反应"。"""
    u.SetCursorPos(x, y)
    time.sleep(0.12)
    if activate:
        u.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
        time.sleep(0.03)
        u.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
        time.sleep(0.2)
    u.mouse_event(0x0008, 0, 0, 0, 0)       # RIGHTDOWN
    time.sleep(0.06)
    u.mouse_event(0x0010, 0, 0, 0, 0)       # RIGHTUP
    time.sleep(0.35)


def press(vk):
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.12)
    u.keybd_event(vk, 0, 2, 0)
    time.sleep(0.28)


def rect(h):
    r = w.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    return r


def has_shell_only(items):
    return [t for t in items if any(s in t for s in SHELL_ONLY)]


# ---------------------------------------------------------------- 准备沙盒目录
sand = tempfile.mkdtemp(prefix="ffce_sm_")
sample = os.path.join(sand, "hello.txt")
open(sample, "w", encoding="utf-8").write("shellmenu probe\n")

print("== 沙盒目录 %s" % sand, flush=True)

# ---------------------------------------------------------------- A 自检模式
dump = os.path.join(tempfile.gettempdir(), "ffce_shellmenu.txt")


def run_dump(target):
    if os.path.exists(dump):
        os.remove(dump)
    p = subprocess.Popen([EXE, "--dump-shell-menu=" + target])
    p.wait(timeout=60)
    if not os.path.exists(dump):
        return None
    # 自检文件是裸 UTF-16LE（不带 BOM，省得和 WriteFile 的字节数打架）
    return [ln.rstrip("\r\n")
            for ln in open(dump, encoding="utf-16-le", errors="replace") if ln.strip()]


rows = run_dump(sample)
if rows is None:
    print("A !!! 自检模式没有输出文件", flush=True)
    ok = False
else:
    items = [r.split("text=", 1)[1] for r in rows if "text=" in r]
    hits = has_shell_only(items)
    icons = [r for r in rows if "icon=1" in r]
    print("A 文件菜单项=%d，含系统独有项 %s -> %s"
          % (len(items), hits[:3], "OK" if hits else "!!! 没有系统扩展项"), flush=True)
    print("   %s" % " ".join(rows[:3]), flush=True)
    ok &= bool(hits) and len(items) >= 3

    # ★宿主补全：资源管理器那份菜单里有"重命名"，只拿 shell 半成品是没有的
    has_rename = any("重命名" in t for t in items)
    print("A1 含「重命名」=%s -> %s"
          % (has_rename, "OK 宿主补全生效" if has_rename else "!!! 缺重命名"), flush=True)
    ok &= has_rename
    # ★图标：Explorer 的项全有图标，我们按 verb 语义补位图，至少要覆盖大半
    print("A2 带图标的项=%d/%d -> %s"
          % (len(icons), len(items), "OK" if len(icons) >= 15 else "!!! 图标太少"), flush=True)
    ok &= len(icons) >= 15

    # 目录（空白处）菜单也要能建出来，且补齐资源管理器那几项
    rows_d = run_dump(sand)
    items_d = [r.split("text=", 1)[1] for r in rows_d if "text=" in r] if rows_d else []
    print("A3 目录空白处菜单项=%d %s"
          % (len(items_d), "OK" if len(items_d) >= 2 else "!!! 建不出菜单"), flush=True)
    ok &= len(items_d) >= 2
    for want in ("刷新", "粘贴", "粘贴快捷方式", "自定义文件夹"):
        got = any(want in t for t in items_d)
        print("A4 空白处含 %-6s -> %s" % (want, "OK" if got else "!!! 缺失"), flush=True)
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
print("   前台=%s -> %s" % (fg_ok, "OK 键盘能进菜单" if fg_ok else "注意：抢不到前台，全部改用鼠标点击"))
# 这台机器上常驻着浏览器/行情软件，前台锁经常抢不到；把被测算窗口置顶，
# 后面的操作全部走"鼠标点菜单项"（不依赖键盘焦点）。
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # TOPMOST|NOSIZE|NOMOVE|SHOWWINDOW
time.sleep(0.3)

# ---------------------------------------------------------------- B 自己那份菜单
lr = rect(lst)
cx, cy = lr.left + 90, lr.top + 46          # 首行（沙盒里只有一个文件，点哪都命中它）
post_context_menu(cx, cy)
m1 = find_menu()
items1 = []
if not m1:
    print("B !!! 右键没有弹出菜单", flush=True)
    ok = False
else:
    items1 = menu_items(m1)
    last = items1[-1] if items1 else ""
    print("B 本程序菜单项=%d，末项=[%s] -> %s"
          % (len(items1), last, "OK" if "更多选项" in last else "!!! 末项不是更多选项"), flush=True)
    print("   前几项=%s" % items1[:6], flush=True)
    ok &= ("更多选项" in last)
    own_shell = has_shell_only(items1)
    print("B2 本程序菜单里不该有系统独有项，实测=%s -> %s"
          % (own_shell[:3], "OK" if not own_shell else "!!! 混在一起了"), flush=True)
    ok &= not own_shell

# ---------------------------------------------------------------- G 重命名（DFM_CMD_RENAME）
if proc.poll() is None:
    time.sleep(1.2)                   # 等上一段（粘贴快捷方式）彻底收尾再开新菜单
    edit = None

    def _find_edit(h, l):
        global edit
        if cls(h) == "Edit" and u.IsWindowVisible(h):
            edit = h
        return True

    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)(_find_edit)
    # 上一段刚跑过系统菜单命令，主窗口还在收尾；偶发一次"新菜单没弹出来"，
    # 重试即可（不掩盖功能问题：真没有「重命名」入口时两次都会报同一条）。
    for attempt in range(3):
        edit = None
        post_context_menu(lr.left + 90, lr.top + 46)       # 选中文件行
        m6 = find_menu()
        if not m6:
            continue
        if not click_menu_item(m6, main, "更多选项"):
            print("G !!! 本程序菜单里没有「更多选项」", flush=True)
            break
        m7 = find_menu(3.0)
        if not m7:
            press(VK_ESCAPE)
            time.sleep(0.8)
            continue                                    # 重试
        if not click_menu_item(m7, main, "重命名"):
            print("G !!! 系统菜单里没有「重命名」", flush=True)
            break
        time.sleep(0.6)
        u.EnumChildWindows(lst, cb, 0)                  # 重命名由宿主接管 → 内联编辑框
        break

    print("G 重命名进入内联编辑 -> %s"
          % ("OK 出现编辑框" if edit else "!!! 没有编辑框（DFM_CMD_RENAME 没接管）"),
          flush=True)
    ok &= bool(edit)
    if edit:
        press(VK_ESCAPE)                                # 取消重命名
        time.sleep(0.3)

# ---------------------------------------------------------------- C 激活系统菜单
# 自己重新开一份菜单：G 段（重命名）已经把 B 段那个消耗掉了
items2 = []
post_context_menu(lr.left + 90, lr.top + 46)
mc = find_menu()
if not mc:
    print("C !!! 没能重新打开本程序菜单", flush=True)
    ok = False
else:
    click_menu_item(mc, main, "更多选项")   # 点它 → 换系统菜单（不依赖键盘焦点）
    m2 = find_menu(3.0)
    if not m2:
        print("C !!! 激活后没有弹出系统菜单", flush=True)
        ok = False
    else:
        items2 = menu_items(m2)
        hits2 = has_shell_only(items2)
        print("C 系统菜单项=%d，系统独有项=%s -> %s"
              % (len(items2), hits2[:4], "OK" if hits2 else "!!! 没有扩展项"), flush=True)
        print("   前几项=%s" % items2[:8], flush=True)
        ok &= bool(hits2)
        same = (len(items2) == len(items1)) and items2[:3] == items1[:3]
        print("C2 与自己那份是否同一份=%s -> %s"
              % (same, "!!! 还是自己那份" if same else "OK 是另一份"), flush=True)
        ok &= (not same)

# ---------------------------------------------------------------- D 真点「属性」
if items2:
    # 系统菜单里的「属性」：点它必须真的弹出属性对话框（验命令 ID→序号换算）
    click_menu_item(m2, main, "属性")
    dlg = None
    t0 = time.time()
    while time.time() - t0 < 4 and not dlg:
        for h in our_windows():
            if cls(h) == "#32770" and "属性" in title(h):
                dlg = h
                break
        time.sleep(0.1)
    if dlg:
        print("D 属性对话框已弹出 标题=[%s] -> OK（命令 ID→序号换算正确）" % title(dlg), flush=True)
        u.PostMessageW(dlg, WM_CLOSE, 0, 0)
        time.sleep(0.8)
    else:
        print("D !!! 按 END+回车没有弹出属性对话框（命令 ID→序号可能错位）", flush=True)
        ok = False

def set_clipboard_files(paths):
    """把文件放进剪贴板（CF_HDROP），用来验证"粘贴/粘贴快捷方式"。"""
    k.GlobalAlloc.restype = w.HGLOBAL
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [w.HGLOBAL]
    k.GlobalUnlock.argtypes = [w.HGLOBAL]
    u.SetClipboardData.argtypes = [ctypes.c_uint, w.HANDLE]
    u.SetClipboardData.restype = w.HANDLE
    u.EmptyClipboard.argtypes = []
    u.OpenClipboard.argtypes = [w.HWND]
    u.OpenClipboard.restype = ctypes.c_bool
    u.CloseClipboard.argtypes = []

    blob = b"".join(p.encode("utf-16-le") + b"\x00\x00" for p in paths) + b"\x00\x00"
    # DROPFILES: pFiles(4) pt(8) fNC(4) fWide(4) = 20 字节头，然后宽字符文件列表
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
    data = header + blob
    h = k.GlobalAlloc(0x0042, len(data))       # GHND
    if not h:
        return False
    p = k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k.GlobalUnlock(h)
    if not u.OpenClipboard(None):
        return False
    u.EmptyClipboard()
    okc = bool(u.SetClipboardData(CF_HDROP, h))
    u.CloseClipboard()
    return okc


# ---------------------------------------------------------------- F 粘贴快捷方式
if proc.poll() is None:
    clipok = False
    for _ in range(4):                     # 剪贴板偶尔被别的进程占着，重试几次
        clipok = set_clipboard_files([sample])
        if clipok:
            break
        time.sleep(0.3)
    print("F0 剪贴板已放入 hello.txt =%s -> %s"
          % (clipok, "OK" if clipok else "!!! 设不上（粘贴项会置灰）"), flush=True)
    ok &= clipok
    post_context_menu(lr.left + 70, lr.bottom - 40)    # 列表空白处
    m4 = find_menu()
    if not m4:
        print("F !!! 空白处右键没弹菜单", flush=True)
        ok = False
    else:
        # 直接点「更多选项」而不是键盘 ↑：菜单弹出时初始高亮跟着光标走，
        # ↑ 一次未必落在末项（实测会误执行别的项）。
        if not click_menu_item(m4, main, "更多选项"):
            print("F !!! 本程序背景菜单里没有「更多选项」", flush=True)
            ok = False
            m5 = None
        else:
            m5 = find_menu(3.0)
        if not m5:
            if ok:
                print("F !!! 空白处「更多选项」没弹出系统菜单", flush=True)
            ok = False
        elif not click_menu_item(m5, main, "粘贴快捷方式"):
            print("F !!! 系统背景菜单里没有「粘贴快捷方式」", flush=True)
            ok = False
        else:
            lnk = os.path.join(sand, "hello.lnk")
            t0 = time.time()
            while time.time() - t0 < 3 and not os.path.exists(lnk):
                time.sleep(0.1)
            # 诊断：是"命令没执行"（菜单还开着/点空了），还是"执行了但失败"（弹错误框）
            dlgs = [h for h in our_windows() if cls(h) == "#32770"]
            if dlgs:
                print("   [dbg] 弹出对话框: %s" % [title(h) for h in dlgs], flush=True)
                for h in dlgs:
                    u.PostMessageW(h, WM_CLOSE, 0, 0)
                time.sleep(0.3)
            left = [h for h in our_windows() if cls(h) == "#32768"]
            if left:
                print("   [dbg] 菜单仍开着 -> 这次点击没落到菜单上", flush=True)
                press(VK_ESCAPE)
            got = os.path.exists(lnk)
            print("F 粘贴快捷方式 -> %s"
                  % ("OK 生成了 hello.lnk" if got else "!!! 没有生成 .lnk"), flush=True)
            if not got:
                print("   目录实际内容=%s" % sorted(os.listdir(sand)), flush=True)
            ok &= got
            if got:
                os.remove(lnk)

# ---------------------------------------------------------------- E 目录树入口
# ★放在最后：树右键「此电脑」会把当前目录切成空（虚拟节点），
#   之后再要"空白处菜单"就没有真实目录可用了（F 段会被这个前提绊死）。
if tree and proc.poll() is None:
    tr = rect(tree)
    post_context_menu(tr.left + 46, tr.top + 24, tree=True)   # 「此电脑」根节点
    m3 = find_menu()
    if m3:
        items3 = menu_items(m3)
        print("E 树右键菜单项=%d 末项=[%s] -> %s"
              % (len(items3), items3[-1] if items3 else "",
                 "OK" if items3 and "更多选项" in items3[-1] else "!!! 没有更多选项入口"), flush=True)
        ok &= bool(items3) and "更多选项" in items3[-1]
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
print("RESULT: %s" % ("PASS" if ok else "FAIL"), flush=True)
sys.exit(0 if ok else 1)
