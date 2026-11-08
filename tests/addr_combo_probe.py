# -*- coding: utf-8 -*-
r"""地址栏下拉点选回归。

用户报的三件事：
  1) 下拉里点盘符根，列表和树都不动；
  2) 要连点两次才对上；
  3) "桌面" / "文档" 点下去直接报错。

根因：CBN_SELENDOK 处理里用 GetWindowTextW 读编辑框。对可编辑组合框，通知发出的
那一刻编辑框里还是用户自己敲的旧串（系统要等通知处理完才把列表项文本填进去），
于是第一次点击拿旧串去跳转 —— 旧串是当前目录就"没反应"，旧串是"桌"就弹"路径
不存在"。第二次点击时编辑框已经是上次选中的项了，才对上。

修法：点选一律走 CB_GETCURSEL + itemdata 里存的真实路径，与编辑框内容无关。

本探针的"点选"刻意把编辑框改回旧内容再发 CBN_SELENDOK，属于最坏情况；
只要这样还能一次跳对，说明确实不再依赖编辑框。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
sh = ctypes.WinDLL("shell32")

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.abspath(os.path.join(HERE, "..", "build", "FileCE.exe"))

WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E; WM_SETTEXT = 0x000C
WM_COMMAND = 0x0111
WM_KEYDOWN = 0x0100; VK_RETURN = 0x0D
CB_GETCOUNT = 0x0146; CB_GETLBTEXT = 0x0148; CB_GETLBTEXTLEN = 0x0149
CB_SETCURSEL = 0x014E; CB_GETCURSEL = 0x0147
CB_GETITEMDATA = 0x0151; CB_SHOWDROPDOWN = 0x014F
CBN_SELENDOK = 9
IDC_ADDR = 1003
TVM_GETNEXTITEM = 0x110A + 0
TVGN_CARET = 0x0009
LVM_GETITEMCOUNT = 0x1000 + 4

u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PostMessageW.restype = ctypes.c_bool
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
sh.SHGetFolderPathW.argtypes = [w.HWND, ctypes.c_int, w.HANDLE, w.DWORD, w.LPWSTR]
sh.SHGetFolderPathW.restype = ctypes.c_uint

FAILS = []


def check(cond, msg, extra=""):
    print(("  OK  " if cond else "  FAIL") + "  " + msg + ("   [%s]" % extra if extra else ""))
    if not cond:
        FAILS.append(msg)


def wtext(h):
    if not h:
        return ""
    n = u.SendMessageW(h, WM_GETTEXTLENGTH, 0, 0)
    b = ctypes.create_unicode_buffer(n + 2)
    u.SendMessageW(h, WM_GETTEXT, n + 1, ctypes.addressof(b))
    return b.value


def cls(h):
    if not h:
        return "?"
    b = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, b, 96)
    return b.value


def known(csidl):
    b = ctypes.create_unicode_buffer(1024)
    if sh.SHGetFolderPathW(0, csidl, 0, 0, b) != 0:
        return ""
    return b.value


DESKTOP = known(0)      # CSIDL_DESKTOP
DOCS = known(5)         # CSIDL_PERSONAL


def find_main(pid):
    res = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        p = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and len(wtext(h)) > 0:
            res.append(h)
        return True

    u.EnumWindows(cb, 0)
    return res[0] if res else 0


def find_child(parent, clsname):
    h = u.FindWindowExW(parent, 0, clsname, None)
    return h


def find_tree(main):
    return u.FindWindowExW(main, 0, "SysTreeView32", None)


_setbufs = []


def settext(h, s):
    """跨进程 WM_SETTEXT：目标进程读的是我们给的指针，缓冲必须一直活着"""
    b = ctypes.create_unicode_buffer(s)
    _setbufs.append(b)
    u.SendMessageW(h, WM_SETTEXT, 0, ctypes.addressof(b))


def dialog_open(pid):
    """有没有弹出错误对话框（MessageBox 类名 #32770）"""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        p = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and cls(h) == "#32770":
            found.append(wtext(h))
        return True

    u.EnumWindows(cb, 0)
    return found


# ---------------------------------------------------------------- 启动
proc = subprocess.Popen([EXE, r"C:\Windows"])
time.sleep(2.2)
main = find_main(proc.pid)
if not main:
    print("FAIL: 找不到主窗口")
    sys.exit(1)

addr = find_child(main, "ComboBox")
edit = u.FindWindowExW(addr, 0, "Edit", None)
tree = find_tree(main)
lst = find_child(main, "SysListView32")
print("main=%s addr=%s edit=%s tree=%s list=%s" % (main, addr, edit, tree, lst))


def items():
    n = u.SendMessageW(addr, CB_GETCOUNT, 0, 0)
    out = []
    for i in range(n):
        ln = u.SendMessageW(addr, CB_GETLBTEXTLEN, i, 0)
        b = ctypes.create_unicode_buffer(ln + 2)
        u.SendMessageW(addr, CB_GETLBTEXT, i, ctypes.addressof(b))
        out.append(b.value)
    return out


def pick(idx, stale):
    """模拟点击下拉第 idx 项。stale = 编辑框里残留的用户输入（复现 bug 的关键）"""
    u.SendMessageW(addr, CB_SETCURSEL, idx, 0)      # 触发 CBN_SELCHANGE（不处理）
    settext(edit, stale)                            # 编辑框退回旧内容
    u.PostMessageW(main, WM_COMMAND, (CBN_SELENDOK << 16) | IDC_ADDR, addr)
    time.sleep(1.4)


def type_enter(text):
    """在编辑框里敲字 + 回车（回车用 SendMessage 直投，见 addr_enter.py 说明）"""
    settext(edit, text)
    u.SendMessageW(edit, WM_KEYDOWN, VK_RETURN, 0)
    time.sleep(1.4)


def caret_text():
    h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CARET, 0)
    if not h:
        return ""
    # 跨进程读树文本太麻烦，这里改用列表行数 + 地址栏判断定位，caret 只求存在
    return "yes" if h else ""


def list_count():
    return u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)


# ================================================================ A 下拉项
print("A 下拉列表内容")
it = items()
print("     %s" % it)
check(len(it) >= 8, "下拉项数量 >= 8", "n=%d" % len(it))
check(any(x == "此电脑" for x in it), "有'此电脑'项")
check(any(len(x) >= 2 and x[1] == ":" for x in it), "有盘符根项")
check(any(x.startswith("桌面    [") for x in it), "有'桌面'项")
check(any(x.startswith("文档    [") for x in it), "有'文档'项")
# 回归：曾经把 fs_enum_drives 里的桌面/文档虚拟节点也当盘符，拼出 "桌:\" "文:\"
bad = [x for x in it if len(x) >= 2 and x[1] == ":" and not x[0].isascii()]
check(not bad, "没有'桌:\\''文:\\'这类假盘符", str(bad))

# ================================================================ B 点"桌面"（编辑框残留"桌"）
print("B 下拉点'桌面'（编辑框残留'桌'——旧代码正是这里报错）")
i_desktop = next((i for i, x in enumerate(it) if x.startswith("桌面    [")), -1)
check(i_desktop >= 0, "找到'桌面'项", "idx=%d" % i_desktop)
pick(i_desktop, "桌")
dlg = dialog_open(proc.pid)
addr_now = wtext(edit)
print("     地址=%r 标题=%r 行数=%d 弹窗=%s" % (addr_now, wtext(main), list_count(), dlg))
check(not dlg, "没有弹出报错对话框", str(dlg))
check(addr_now.lower() == DESKTOP.lower(), "一次点击即进入真实桌面目录", "addr=%r want=%r" % (addr_now, DESKTOP))
check(list_count() > 0, "文件区有内容", "n=%d" % list_count())

# ================================================================ C 点"文档"（编辑框残留"文"）
print("C 下拉点'文档'（编辑框残留'文'）")
i_docs = next((i for i, x in enumerate(it) if x.startswith("文档    [")), -1)
check(i_docs >= 0, "找到'文档'项", "idx=%d" % i_docs)
pick(i_docs, "文")
dlg = dialog_open(proc.pid)
addr_now = wtext(edit)
print("     地址=%r 标题=%r 行数=%d 弹窗=%s" % (addr_now, wtext(main), list_count(), dlg))
check(not dlg, "没有弹出报错对话框", str(dlg))
check(addr_now.lower() == DOCS.lower(), "一次点击即进入真实文档目录", "addr=%r want=%r" % (addr_now, DOCS))

# ================================================================ D 点盘符根（编辑框残留当前目录）
print("D 下拉点盘符根（编辑框残留旧目录）")
drv_idx = [i for i, x in enumerate(it) if len(x) >= 2 and x[1] == ":"]
drv = it[drv_idx[0]] if drv_idx else ""
if drv == "C:\\" and len(drv_idx) > 1:
    drv = it[drv_idx[1]]        # 换一个非当前盘，效果更明显
    i_drv = drv_idx[1]
else:
    i_drv = drv_idx[0]
before = wtext(edit)
print("     点选 %r，点击前地址=%r" % (drv, before))
pick(i_drv, before)             # 编辑框保持点击前的旧目录 —— 旧代码会原地不动
addr_now = wtext(edit)
print("     地址=%r 标题=%r 行数=%d 弹窗=%s" % (addr_now, wtext(main), list_count(), dialog_open(proc.pid)))
check(not dialog_open(proc.pid), "没有弹出报错对话框")
check(addr_now.lower() == drv.lower(), "一次点击即进入盘符根", "addr=%r want=%r" % (addr_now, drv))
check(list_count() > 3, "文件区列出根目录内容", "n=%d" % list_count())
check(bool(caret_text()), "左侧树有定位（光标非空）")

# ================================================================ E 手敲中文别名
print("E 地址栏手敲中文别名回车")
type_enter("桌")
addr_now = wtext(edit)
print("     敲'桌' -> 地址=%r 弹窗=%s" % (addr_now, dialog_open(proc.pid)))
check(not dialog_open(proc.pid), "敲'桌'不再报错")
check(addr_now.lower() == DESKTOP.lower(), "'桌' -> 桌面", "addr=%r" % addr_now)

type_enter("文")
addr_now = wtext(edit)
print("     敲'文' -> 地址=%r 弹窗=%s" % (addr_now, dialog_open(proc.pid)))
check(not dialog_open(proc.pid), "敲'文'不再报错")
check(addr_now.lower() == DOCS.lower(), "'文' -> 文档", "addr=%r" % addr_now)

type_enter("桌面")
check(wtext(edit).lower() == DESKTOP.lower(), "'桌面' -> 桌面", "addr=%r" % wtext(edit))
type_enter("文档")
check(wtext(edit).lower() == DOCS.lower(), "'文档' -> 文档", "addr=%r" % wtext(edit))

# ================================================================ F "此电脑"项
print("F 下拉点'此电脑'")
i_pc = next((i for i, x in enumerate(it) if x == "此电脑"), -1)
pick(i_pc, "桌")
addr_now = wtext(edit)
print("     地址=%r 标题=%r 行数=%d" % (addr_now, wtext(main), list_count()))
check(not dialog_open(proc.pid), "没有弹出报错对话框")
check(addr_now == "此电脑", "回到此电脑视图", "addr=%r" % addr_now)
check(list_count() >= 8, "此电脑页有内容", "n=%d" % list_count())

# ================================================================ G 正常路径仍然能进
print("G 手敲绝对路径回车")
type_enter(r"C:\Windows\System32")
check(wtext(edit).lower() == r"c:\windows\system32", "绝对路径可用", "addr=%r" % wtext(edit))
check(list_count() > 3, "文件区有内容", "n=%d" % list_count())

print()
if FAILS:
    print("RESULT: FAIL (%d)" % len(FAILS))
    for f in FAILS:
        print("   - " + f)
else:
    print("RESULT: PASS")

try:
    proc.kill()
except Exception:
    pass
sys.exit(1 if FAILS else 0)
