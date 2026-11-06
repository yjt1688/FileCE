# -*- coding: utf-8 -*-
r"""目录树右键 + 树内拖动 回归（全程真实鼠标）：
1) 树右键弹上下文菜单（复用列表那套）；
2) 树节点拖到另一个树节点松手 → 弹"复制到此处/移动到此处/取消"菜单；
   点"复制" → 目标下出现副本、源仍在；
3) 再拖一次点"移动" → 源消失、目标下出现。

树节点定位：TVM_GETITEMW 的节点数据（文本/lParam）必须放在【目标进程】
（VirtualAllocEx + WriteProcessMemory），缓冲在探针本进程里永远读不到 ——
与 pc_groups_probe 的 tree_text 同一套手法。TVGN 常量：ROOT=0 NEXT=1 CHILD=4 CARET=9。

用法: python tests/tree_drag_probe.py
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys

u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))

WM_GETTEXT = 0x000D; WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100; WM_KEYUP = 0x0101; WM_CHAR = 0x0102
VK_RETURN = 0x0D
TVGN_ROOT = 0; TVGN_NEXT = 1; TVGN_CHILD = 4; TVGN_CARET = 9; TVGN_PARENT = 3
TVGN_FIRSTVISIBLE = 5     # commctrl.h: TVGN_FIRSTVISIBLE=0x5
TVGN_NEXTVISIBLE = 6      # 0x6;NEXTVISIBLE 才会跨层走完整可见序
TVM_GETITEMHEIGHT = 0x1100 + 28
TVM_GETNEXTITEM = 0x1100 + 10; TVM_GETITEMW = 0x1100 + 62; TVM_GETITEMRECT = 0x1100 + 4
TVIF_TEXT = 0x0001; TVIF_HANDLE = 0x0010; TVIF_PARAM = 0x0004
PROCESS_ALL = 0x1F0FFF; MEM_COMMIT = 0x1000; MEM_RELEASE = 0x8000; PAGE_READWRITE = 4
LDOWN, LUP, RDOWN, RUP = 0x0002, 0x0004, 0x0008, 0x0010

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.SetForegroundWindow.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
k.OpenProcess.restype = ctypes.c_void_p
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
k.VirtualAllocEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_size_t, w.DWORD, w.DWORD]
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualFreeEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_size_t, w.DWORD]
k.WriteProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


fails = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        fails.append(name)


class RECT16(ctypes.Structure):
    _fields_ = [("left", w.LONG), ("top", w.LONG), ("right", w.LONG), ("bottom", w.LONG)]


class TVITEMW(ctypes.Structure):
    _fields_ = [("mask", ctypes.c_uint), ("hItem", ctypes.c_void_p),
                ("state", ctypes.c_uint), ("stateMask", ctypes.c_uint),
                ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
                ("iImage", ctypes.c_int), ("iSelectedImage", ctypes.c_int),
                ("cChildren", ctypes.c_int), ("lParam", ctypes.c_size_t)]


class TreeReader:
    """跨进程读树节点文本/矩形（缓冲必须放目标进程）。
    ★ TVM_GETITEMRECT 的缓冲前 8 字节是【输入】：发消息前必须把 hItem 写进
    *(HTREEITEM*)prc（commctrl.h 的 TreeView_GetItemRect 宏就是这么干的），
    只给一块零缓冲永远返回 0。"""

    def __init__(self, tree, proc):
        self.tree = tree
        self.proc = proc
        self._txt = k.VirtualAllocEx(proc, None, 600, MEM_COMMIT, PAGE_READWRITE)
        self._st = k.VirtualAllocEx(proc, None, ctypes.sizeof(TVITEMW), MEM_COMMIT, PAGE_READWRITE)
        self._rc = k.VirtualAllocEx(proc, None, 32, MEM_COMMIT, PAGE_READWRITE)

    def text(self, hitem):
        ti = TVITEMW()
        ti.mask = TVIF_TEXT | TVIF_HANDLE | TVIF_PARAM
        ti.hItem = ctypes.c_void_p(hitem & 0xFFFFFFFFFFFFFFFF)
        ti.pszText = ctypes.c_void_p(self._txt); ti.cchTextMax = 300
        nw = ctypes.c_size_t(0)
        k.WriteProcessMemory(self.proc, self._st, ctypes.byref(ti),
                             ctypes.sizeof(ti), ctypes.byref(nw))
        u.SendMessageW(self.tree, TVM_GETITEMW, 0, self._st)
        b = ctypes.create_unicode_buffer(300)
        k.ReadProcessMemory(self.proc, self._txt, b, 600, ctypes.byref(nw))
        return b.value

    def rect(self, hitem):
        """节点文字部分的屏幕坐标中心。"""
        payload = (ctypes.c_ssize_t * 1)(hitem)
        nw = ctypes.c_size_t(0)
        k.WriteProcessMemory(self.proc, self._rc, payload, 8, ctypes.byref(nw))
        ok = u.SendMessageW(self.tree, TVM_GETITEMRECT, 1, self._rc)
        r = (ctypes.c_long * 4)()
        k.ReadProcessMemory(self.proc, self._rc, r, 16, ctypes.byref(nw))
        if not ok:
            return None
        pt = w.POINT(r[0], r[1])
        u.ClientToScreen(self.tree, ctypes.byref(pt))
        return (pt.x + (r[2] - r[0]) // 2, pt.y + (r[3] - r[1]) // 2)


def send_mouse(flags):
    class MI(ctypes.Structure):
        _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
                    ("dwFlags", w.DWORD), ("time", w.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(w.ULONG))]
    class IU(ctypes.Union):
        _fields_ = [("mi", MI)]
    class INP(ctypes.Structure):
        _fields_ = [("type", w.DWORD), ("u", IU)]
    inp = INP(0, IU(MI(0, 0, 0, flags, 0, None)))
    u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INP))


def click(x, y, right=False):
    u.SetCursorPos(int(x), int(y)); time.sleep(0.08)
    u.mouse_event(RDOWN if right else LDOWN, 0, 0, 0, None); time.sleep(0.09)
    u.mouse_event(RUP if right else LUP, 0, 0, 0, None); time.sleep(0.6)


def drag(fx, fy, tx, ty, steps=16):
    u.SetCursorPos(int(fx), int(fy)); time.sleep(0.25)
    send_mouse(LDOWN); time.sleep(0.35)
    for i in range(1, steps + 1):
        u.SetCursorPos(int(fx + (tx - fx) * i // steps), int(fy + (ty - fy) * i // steps))
        time.sleep(0.035)
    time.sleep(0.3)
    send_mouse(LUP); time.sleep(0.9)


def menus():
    res = []

    def cb(h, l):
        if u.IsWindowVisible(h) and cls(h) == "#32768":
            res.append(h)
        return True
    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)(cb), 0)
    return res


def menu_pick(index_from_top):
    for _ in range(index_from_top):
        u.keybd_event(0x28, 0, 0, None); time.sleep(0.08)
        u.keybd_event(0x28, 0, 2, None); time.sleep(0.15)
    u.keybd_event(0x0D, 0, 0, None); time.sleep(0.08)
    u.keybd_event(0x0D, 0, 2, None); time.sleep(0.3)


def menu_close_all():
    for _ in range(4):
        mx = menus()
        if not mx:
            break
        u.PostMessageW(mx[0], 0x0010, 0, 0)
        time.sleep(0.3)


def menu_click(index_from_top, total_items=0):
    """真实鼠标点击弹出菜单的第 index 项。
    三选菜单(复制/移动/分隔/取消)的项高按【菜单总高 / total_items】推
    (SM_CYMENU 在 DPI 1.25 下偏大,按它点会串行);total_items=0 时
    (普通右键菜单,项数未知)用 SM_CYMENU。"""
    m = menus()
    if not m:
        return False
    rc = w.RECT()
    u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    # 多个菜单并存时挑【高度最小的】(三选菜单 ~79px;残留右键菜单几百 px)
    best = None
    for mh in m:
        r2 = w.RECT()
        u.GetWindowRect(mh, ctypes.byref(r2))
        h = r2.bottom - r2.top
        if best is None or h < best[0]:
            best = (h, mh, r2)
    mh_h, m[0], rc = best
    if total_items:
        rowh = (rc.bottom - rc.top) / float(total_items)
    else:
        rowh = u.GetSystemMetrics(21) or 20   # SM_CYMENU
    x = rc.right - 12
    y = int(rc.top + index_from_top * rowh + rowh * 0.65)
    print("  menu_click(%d): menu=%dx%d at (%d,%d) -> click (%d,%d)" %
          (index_from_top, rc.right - rc.left, rc.bottom - rc.top,
           rc.left, rc.top, x, y))
    # 先把鼠标移进菜单悬停一拍（让菜单完成首绘并高亮该项），再按下/抬起
    u.SetCursorPos(x, y)
    time.sleep(0.35)
    u.mouse_event(LDOWN, 0, 0, 0, None); time.sleep(0.1)
    u.mouse_event(LUP, 0, 0, 0, None); time.sleep(0.6)
    return True


def raise_top(h):
    u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)


import winreg

CF_HDROP = 15


def cf_paths():
    """读剪贴板里的 CF_HDROP 路径列表（GetClipboardData 返回的 HGLOBAL 本进程可读）。"""
    u.OpenClipboard.argtypes = [w.HWND]
    if not u.OpenClipboard(None):
        return None, False
    try:
        h = u.GetClipboardData(CF_HDROP)
        if not h:
            return None, False
        k32 = ctypes.WinDLL("kernel32")
        ptr = k32.GlobalLock.argtypes = [w.HGLOBAL]
        k32.GlobalLock.restype = ctypes.c_void_p
        p = k32.GlobalLock(h)
        if not p:
            return None, False

        class DROPFILES(ctypes.Structure):
            _fields_ = [("pFiles", w.DWORD), ("pt", w.POINT),
                        ("fNC", w.BOOL), ("fWide", w.BOOL)]
        df = DROPFILES.from_address(p)
        base = p + df.pFiles
        paths = []
        if df.fWide:
            i = 0
            while True:
                s = ctypes.c_wchar_from_address(base + i * 2)
                # 逐段读到双 0
                start = i
                while ctypes.wstring_at(base + i * 2, 1) != "\x00":
                    i += 1
                paths.append(ctypes.wstring_at(base + start * 2, i - start))
                i += 1
                if ctypes.wstring_at(base + i * 2, 1) == "\x00":
                    break
        k32.GlobalUnlock(h)
        return paths, True
    finally:
        u.CloseClipboard()


def cf_has_projA():
    paths, _ = cf_paths()
    if not paths:
        return False
    return any(os.path.normcase(p) == os.path.normcase(SRC) for p in paths)


def cf_is_cut():
    """ Preferred DropEffect == 2(DROP) 表示剪切。"""
    u.OpenClipboard.argtypes = [w.HWND]
    if not u.OpenClipboard(None):
        return False
    try:
        fmt = u.RegisterClipboardFormatW("Preferred DropEffect")
        h = u.GetClipboardData(fmt) if fmt else None
        if not h:
            return False
        k32 = ctypes.WinDLL("kernel32")
        k32.GlobalLock.restype = ctypes.c_void_p
        p = k32.GlobalLock(h)
        if not p:
            return False
        val = ctypes.cast(p, ctypes.POINTER(ctypes.c_uint32)).contents.value
        k32.GlobalUnlock(h)
        return val == 2
    finally:
        u.CloseClipboard()


def dst_copies():
    """DST 下 projA* 副本计数（检测重复复制）。"""
    if not os.path.isdir(DST):
        return 0
    return sum(1 for n in os.listdir(DST)
               if n == "projA" or n.startswith("projA ("))


def caret_row(tree):
    """caret(BASE 节点)所在的可见行号。
    做法:从树客户区顶部往下逐行右键,右键会选中节点并弹菜单;菜单出现时
    该行就是 caret?不行——右键在树里也会 TVM_SELECTITEM。逐行右键后
    【检查菜单消失后 caret 是否影响标题】太绕。改:树展开后 caret=BASE,
    行号 = 树内自上而下数。可见链无法跨进程读,就用【磁盘布局推算】:
    此电脑(0) C:\(1) Users(2) Administrator(3) ffce_tree_drag(4) projA(5) projB(6)
    中间若有其它可见项,序号会漂移 —— 用「逐行试探拖拽」兜底:对 n=3..8,
    拖行 n 到行 n+1,若 DST 出现副本即锁定行号。为确定性,先假设 4/5/6。"""
    return 4   # Administrator(3) 的下一行 = ffce_tree_drag(4)


# ---- 准备 ----
BASE = r"C:\ffce_tree_drag"          # 别放 %TEMP%:AppData 链路是隐藏目录,树不展开
SRC = os.path.join(BASE, "projA")
DST = os.path.join(BASE, "projB")
MARK = "tree-drag marker"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(SRC); os.makedirs(DST)
with open(os.path.join(SRC, "in_proj.txt"), "w", encoding="utf-8") as f:
    f.write(MARK)
with open(os.path.join(DST, "dst_file.txt"), "w", encoding="utf-8") as f:
    f.write("dst")

PID = w.DWORD(0)
proc = subprocess.Popen([EXE, BASE]); PID.value = proc.pid
tr = None
try:
    main = []
    t0 = time.time()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        pid = w.DWORD(0); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == PID.value and cls(h) == "FFMainWnd":
            main.append(h)
        return True
    while not main and time.time() - t0 < 10:
        u.EnumWindows(cb, 0); time.sleep(0.1)
    check("主窗口出现", bool(main))
    if not main:
        sys.exit(1)
    time.sleep(1.0)
    raise_top(main[0]); u.SetForegroundWindow(main[0]); time.sleep(0.5)

    tree = [None]
    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def kcb(h, l):
        if cls(h) == "SysTreeView32":
            tree[0] = h
        return True
    u.EnumChildWindows(main[0], kcb, 0)
    check("找到树控件", bool(tree[0]))
    if not tree[0]:
        sys.exit(1)
    tr = TreeReader(tree[0], k.OpenProcess(PROCESS_ALL, False, PID.value))

    # 地址栏导航到 BASE → 树展开定位（caret = BASE 节点）
    combo = [None]
    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def ccb(h, l):
        if cls(h) == "ComboBox" and not combo[0]:
            t = ctypes.create_unicode_buffer(300)
            u.SendMessageW(h, WM_GETTEXT, 300, ctypes.addressof(t))
            if t.value:
                combo[0] = h
        return True
    u.EnumChildWindows(main[0], ccb, 0)
    edit = u.FindWindowExW(combo[0], None, "Edit", None) if combo[0] else None
    check("找到地址栏编辑框", bool(edit))
    if not edit:
        sys.exit(1)
    # 与 addr_crumb_probe 相同：WM_SETTEXT 发给【ComboBox】，回车键发给 Edit
    buf = ctypes.create_unicode_buffer(BASE)
    u.SendMessageW(combo[0], WM_SETTEXT, 0, ctypes.addressof(buf))
    time.sleep(0.2)
    u.SendMessageW(edit, WM_KEYDOWN, VK_RETURN, 0)
    u.SendMessageW(edit, WM_CHAR, VK_RETURN, 0)
    time.sleep(1.8)

    caret = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_CARET, 0)
    check("树定位到 BASE（caret 有效）", bool(caret))
    caretText = tr.text(caret)
    check("caret 文本 = ffce_tree_drag", caretText == "ffce_tree_drag", caretText)
    check("BASE 父节点有效", bool(u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_PARENT, caret)))

    # projA/projB 是 BASE 的子目录，在 caret 节点的子链里（读文本精确匹配），
    # 坐标 = TVM_GETITEMRECT（远程缓冲前 8 字节必须先写 hItem，见 TreeReader.rect）
    hA = hB = None
    h = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_CHILD, caret)
    while h:
        t = tr.text(h)
        if t == "projA":
            hA = h
        elif t == "projB":
            hB = h
        h = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_NEXT, h)
    check("树里定位到 projA", bool(hA))
    check("树里定位到 projB", bool(hB))
    if not (hA and hB):
        sys.exit(1)
    rA = tr.rect(hA)
    rB = tr.rect(hB)
    check("projA/projB 矩形可取", bool(rA and rB), str(rA) + str(rB))

    # ---- 1) 树右键弹菜单，点"复制" → 剪贴板里应出现 projA（灰色修复回归）----
    click(*rA, right=True)
    time.sleep(0.7)
    mm = menus()
    check("树右键弹出上下文菜单", len(mm) == 1, "menus=%d" % len(mm))
    copied_cb = False
    if mm:
        u.PostMessageW(mm[0], 0x0010, 0, 0)   # 先关掉：试第 2 项(目录的菜单: 打开/分隔/复制)
        time.sleep(0.5)
        # 菜单捕获键盘,↓ 导航比坐标点击稳。目录菜单:打开(0)/分隔/复制(2)…,
        # 分隔线是否占一个 ↓ 不定,试 2 和 3 两种;每次重新弹菜单。
        # 右键菜单 ~14 项(DPI 1.25 项高≈30px);菜单捕获键盘而本机环境拦截
        # 合成键盘注入(见 09-28 日志),只能用鼠标。'复制'在 index 2 附近,逐个试。
        for picks, rowh in ((2, 30), (3, 30), (2, 26), (3, 26)):
            click(*rA, right=True)
            time.sleep(0.7)
            mx = menus()
            if not mx:
                continue
            m = menus()
            mh2 = w.RECT()
            u.GetWindowRect(m[0], ctypes.byref(mh2))
            x = mh2.right - 12
            y = int(mh2.top + picks * rowh + rowh * 0.6)
            u.SetCursorPos(x, y); time.sleep(0.3)
            u.mouse_event(LDOWN, 0, 0, 0, None); time.sleep(0.1)
            u.mouse_event(LUP, 0, 0, 0, None); time.sleep(0.6)
            if cf_has_projA():
                copied_cb = True
                break
            menu_close_all()
    check("树右键'复制'后剪贴板含 projA", copied_cb)
    if copied_cb:
        check("粘贴标志(非剪切)成立", not cf_is_cut())

    # ---- 2) 拖 projA → projB：弹三选，真实点击第 0 项"复制到此处"----
    click(*rA)                     # 先左键选中该节点（真实用户操作序列）
    time.sleep(0.4)
    drag(rA[0], rA[1], rB[0], rB[1])
    time.sleep(0.7)
    mm = menus()
    check("松手弹出 复制/移动/取消 菜单", len(mm) == 1, "menus=%d" % len(mm))
    if mm:
        menu_click(0)              # 三选菜单：0=复制到此处（松手点弹出，SM_CYMENU 项高）
    copied = False
    for _ in range(30):                 # 最多 7.5s 等复制落盘
        if dst_copies() == 1:
            copied = True
            break
        time.sleep(0.25)
    copies = dst_copies()
    check("点'复制到此处' → projB 下出现 projA 副本", copied,
          "副本数=%d" % copies)
    check("★只复制一份（不出现 'projA (2)'）", copies <= 1, "副本数=%d" % copies)
    check("复制不移动：源 projA 仍在", os.path.isdir(SRC))
    if copied:
        ok = open(os.path.join(DST, "projA", "in_proj.txt"), encoding="utf-8").read() == MARK
        check("副本内容一致", ok)

    # ---- 3) 再拖一次点"移动到此处"（第 1 项）----
    # 复制后树整体重建（ff_tree_populate），旧 hItem/caret 全部失效 ——
    # 从根重新逐层下潜(此电脑→C:→ffce_tree_drag→projA/projB)。
    if os.path.isdir(SRC):
        time.sleep(1.5)             # 树重建/重新定位需要时间，矩形稳定后再拖
        hA2 = hB2 = None
        node = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_ROOT, 0)
        for want in ("C:", "ffce_tree_drag"):        # 逐层找
            h = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_CHILD, node)
            while h:
                if tr.text(h).startswith(want):
                    node = h
                    break
                h = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_NEXT, h)
        h = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_CHILD, node)
        while h:
            t = tr.text(h)
            if t == "projA":
                hA2 = h
            elif t == "projB":
                hB2 = h
            h = u.SendMessageW(tree[0], TVM_GETNEXTITEM, TVGN_NEXT, h)
        if hA2 and hB2:
            rA = tr.rect(hA2)
            rB = tr.rect(hB2)
            print("  重建后矩形:", rA, rB)
        # 树重建后 TVN_BEGINDRAG 偶发不触发（合成输入时序），最多重试 3 轮拖动；
        # 每轮先右键一下（走 NM_RCLICK 的选中链路让树稳定），关闭菜单再拖。
        mm = []
        for attempt in range(3):
            click(*rA, right=True)
            time.sleep(0.6)
            mx = menus()
            if mx:
                u.PostMessageW(mx[0], 0x0010, 0, 0)
                time.sleep(0.4)
            click(*rA)             # 重新选中拖动源
            time.sleep(0.5)
            drag(rA[0], rA[1], rB[0], rB[1])
            mm = menus()
            for _ in range(6):      # 菜单创建时机偶发滞后，重试枚举
                if mm:
                    break
                time.sleep(0.25)
                mm = menus()
            if mm:
                break
        check("第二次拖动也弹三选菜单", len(mm) == 1, "menus=%d" % len(mm))
        if mm:
            menu_click(1, total_items=4)   # 1=移动到此处
        for _ in range(30):             # 最多 7.5s 等移动完成
            if not os.path.isdir(SRC):
                break
            time.sleep(0.25)
    check("点'移动到此处' → 源 projA 消失", not os.path.isdir(SRC))
    check("移动后 projB 下有 projA", os.path.isdir(os.path.join(DST, "projA")))
    check("进程未崩溃", proc.poll() is None)
finally:
    proc.terminate(); time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
    if "--keep" not in sys.argv:
        shutil.rmtree(BASE, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails))
    sys.exit(1)
print("全部通过")
