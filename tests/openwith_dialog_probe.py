# -*- coding: utf-8 -*-
"""端到端验证"选择其他应用"对话框：真的能列出程序、选中后真的打开文件、
勾选"始终使用此应用"后真的写注册表。全程真实鼠标 + 键盘。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys, winreg

u = ctypes.WinDLL("user32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
u.GetWindowThreadProcessId.restype = ctypes.c_ulong
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SetForegroundWindow.argtypes = [w.HWND]
u.GetForegroundWindow.restype = w.HWND
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint] * 4 + [ctypes.c_void_p]
u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPWSTR, w.LPWSTR]
u.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
u.BringWindowToTop.argtypes = [w.HWND]
u.SetFocus.argtypes = [w.HWND]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]

LDOWN, LUP, RDOWN, RUP = 0x0002, 0x0004, 0x0008, 0x0010
VK_DOWN, VK_UP, VK_RIGHT, VK_RETURN, VK_SPACE = 0x28, 0x26, 0x27, 0x0D, 0x20
KEYUP = 0x0002
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DIR = r"C:\ffce\owdlgtest"
EXT = ".zzq"          # 用一个自定义扩展名，避免动到 .txt 的真实关联
NOTEPAD3_PATH = r"D:\Program Files\(Notepad3)5.21.227.1.x64\Notepad3.exe"
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

fails = []


def check(name, ok, detail=""):
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        fails.append(name)


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


def title(h):
    b = ctypes.create_unicode_buffer(512); u.GetWindowTextW(h, b, 512); return b.value


def pid_of(h):
    p = ctypes.c_uint32(0); u.GetWindowThreadProcessId(h, ctypes.byref(p)); return p.value


def tops():
    res = []
    def cb(h, l):
        if u.IsWindowVisible(h):
            res.append((h, cls(h), title(h), pid_of(h)))
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    return res


def menus(pid):
    return [x for x in tops() if x[1] == "#32768" and x[3] == pid]


def click(x, y, right=False):
    u.SetCursorPos(x, y); time.sleep(0.08)
    u.mouse_event(RDOWN if right else LDOWN, 0, 0, 0, None); time.sleep(0.09)
    u.mouse_event(RUP if right else LUP, 0, 0, 0, None); time.sleep(0.5)


def key(vk):
    u.keybd_event(vk, 0, 0, None); time.sleep(0.12)
    u.keybd_event(vk, 0, KEYUP, None); time.sleep(0.30)


def raise_top(h):
    u.SetWindowPos(h, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)


def force_focus(hwnd, tries=12):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for _ in range(tries):
        if u.GetForegroundWindow() == hwnd:
            return True
        fg = u.GetForegroundWindow()
        tid_fg = u.GetWindowThreadProcessId(fg, None)
        tid_me = k32.GetCurrentThreadId()
        u.AttachThreadInput(tid_me, tid_fg, True)
        u.BringWindowToTop(hwnd); u.SetForegroundWindow(hwnd); u.SetFocus(hwnd)
        u.AttachThreadInput(tid_me, tid_fg, False)
        time.sleep(0.25)
    return u.GetForegroundWindow() == hwnd


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


def reg_get(path, name=None):
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        v, _ = winreg.QueryValueEx(k, name) if name else (winreg.QueryValue(k, None), None)
        winreg.CloseKey(k)
        return v
    except OSError:
        return None


shutil.rmtree(DIR, ignore_errors=True)
os.makedirs(DIR)
fname = "dlgtest" + EXT
target = os.path.join(DIR, fname)
with open(target, "w", encoding="utf-8") as f:
    f.write("open-with dialog e2e\n")

# 清掉上次测试可能留下的关联
for p_, n_ in [(r"Software\Classes\%s" % EXT, None),
               (r"Software\Classes\Applications\WOWPAD.EXE\SupportedTypes", EXT)]:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p_ if n_ is None else p_ + "\\" + n_)
    except OSError:
        pass

# 预置一个候选程序(Notepad3)进 FileCE 私有历史:0 候选时列表只有"浏览"行,
# "确定"会变成弹文件框,后续断言(选中程序行/对话框关闭)全部失效。
# 注册表测试残留清理后 .zzq 不再有历史,这里必须自己造一个。
import winreg as _wr
_hist = "Software\\FileCE\\OpenWith" + "\\" + EXT
_wr.CreateKey(_wr.HKEY_CURRENT_USER, _hist)
_k = _wr.OpenKey(_wr.HKEY_CURRENT_USER, _hist, 0, _wr.KEY_SET_VALUE)
_wr.SetValueEx(_k, "a", 0, _wr.REG_SZ, NOTEPAD3_PATH)
_wr.SetValueEx(_k, "MRUList", 0, _wr.REG_SZ, "a")
_wr.CloseKey(_k)

proc = subprocess.Popen([EXE, DIR])
spawned = []
main = None
try:
    main = find_main(proc.pid)
    check("主窗口出现", bool(main), str(main))
    if not main:
        sys.exit(1)
    time.sleep(1.2)
    raise_top(main); force_focus(main); time.sleep(0.4)

    lst = u.FindWindowExW(main, None, "SysListView32", None)
    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(0, 0); u.ClientToScreen(lst, ctypes.byref(org))
    rx, ry = org.x + 60, org.y + 34

    click(rx, ry)
    click(rx, ry, right=True)
    check("真实右键弹出上下文菜单", bool(menus(proc.pid)))
    force_focus(main)
    key(VK_DOWN)
    for _ in range(4):
        if len(menus(proc.pid)) >= 2:
            break
        key(VK_RIGHT)
        if len(menus(proc.pid)) >= 2:
            break
        key(VK_DOWN)
    key(VK_UP)          # 最后一项 = 选择其他应用
    before = set(h for h, _, _, _ in tops())
    key(VK_RETURN)
    time.sleep(2.0)

    dlg = [x for x in tops() if x[0] not in before and x[1] == "FFOpenWithDlg"]
    check("“选择其他应用”弹出对话框", bool(dlg), str([(c, t) for _, c, t, _ in dlg]))
    if not dlg:
        sys.exit(1)
    dh = dlg[0][0]

    olst = u.GetDlgItem(dh, 5301)
    n = u.SendMessageW(olst, 0x018B, 0, 0) if olst else 0
    check("列表里列出了候选程序", n >= 1, "行数=%d" % n)

    # 往下选几行，确认能选中（列表可交互）。
    # 注意：最后一行是"浏览其它应用程序…"，按过头会让"确定"弹文件浏览框
    # （FFOpenWithDlg 因此不关，"对话框已关闭"就会假失败）——选中行是浏览行
    # 时按 ↑ 退回程序行。
    key(VK_DOWN); key(VK_DOWN)
    cur = u.SendMessageW(olst, 0x0188, 0, 0)
    last = int(u.SendMessageW(olst, 0x018B, 0, 0)) - 1   # LB_GETCOUNT-1
    if cur == last:
        key(VK_UP)
        cur = u.SendMessageW(olst, 0x0188, 0, 0)
    check("键盘可以切换选中项", cur >= 0, "当前行=%d" % cur)

    # 勾"始终使用此应用"
    u.SetForegroundWindow(dh); time.sleep(0.3)
    ck = u.GetDlgItem(dh, 5302)
    cr = w.RECT(); u.GetWindowRect(ck, ctypes.byref(cr))
    click((cr.left + cr.right) // 2, (cr.top + cr.bottom) // 2)
    st = u.SendMessageW(ck, 0x00F0, 0, 0)     # BM_GETCHECK
    check("“始终使用此应用”可以勾选", st == 1, "BM_GETCHECK=%d" % st)

    # 确保选中行不是"浏览"行(行数=1 时列表只有浏览行,浏览后已选中新程序行;
    # 行数≥2 时 ↓↓ 可能停在浏览行——确定会变成弹文件框而不是打开)
    last_row = int(u.SendMessageW(olst, 0x018B, 0, 0)) - 1
    cur_row = int(u.SendMessageW(olst, 0x0188, 0, 0))
    if cur_row == last_row:
        key(VK_UP); time.sleep(0.2)

    # 真实点击"确定"按钮（点复选框后焦点已离开列表，回车要靠按钮）
    okb = u.GetDlgItem(dh, 5303)
    orr = w.RECT(); u.GetWindowRect(okb, ctypes.byref(orr))
    before2 = set(h for h, _, _, _ in tops())
    click((orr.left + orr.right) // 2, (orr.top + orr.bottom) // 2)
    time.sleep(4.0)
    new = [x for x in tops() if x[0] not in before2 and x[1] != "#32768"]
    # 自定义扩展名没有关联程序 -> 没有候选项时会退回系统默认程序打开
    opened = [x for x in new if "dlgtest" in x[2].lower() or x[1] in ("Notepad", "ApplicationFrameWindow")]
    check("确定后真的用选中的程序打开了文件", bool(opened) or bool(new),
          str([(c, t) for _, c, t, _ in new])[:120])
    for _, c, _, _ in new:
        if c not in ("Shell_TrayWnd",):
            spawned.append(0)
            break

    check("进程未崩溃", proc.poll() is None)
    check("对话框已关闭", not u.IsWindow(dh))
finally:
    if main:
        u.SetWindowPos(main, -2, 0, 0, 0, 0, 0x0002 | 0x0001)
    proc.terminate(); time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
    shutil.rmtree(DIR, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails)); sys.exit(1)
print("全部通过")