# -*- coding: utf-8 -*-
"""验证"打开方式"对话框的三件事（真实鼠标 + 真实进程判定）：

  1. 点"取消"绝不能打开文件 —— 之前 sel 一上来就=0，ff_dlg_open_with
     只看 sel 有效就返回 true，于是取消也打开。
  2. 点"确定"会用选中的程序真的打开文件。
  3. 列表最后一行是"浏览其它应用程序…"，系统枚举不到程序时也不为空。

用记事本当被打开的目标程序：判定"文件是否被打开"靠记事本窗口标题里
有没有文件名，比靠"出现了新窗口"可靠得多。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys, winreg

u = ctypes.WinDLL("user32", use_last_error=True)
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
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND

LDOWN, LUP, RDOWN, RUP = 0x0002, 0x0004, 0x0008, 0x0010
VK_DOWN, VK_UP, VK_RIGHT, VK_RETURN, VK_ESCAPE = 0x28, 0x26, 0x27, 0x0D, 0x1B
KEYUP = 0x0002
LB_GETCOUNT, LB_GETCURSEL = 0x018B, 0x0188
# WM_SETTEXT 的 LPARAM 是字符串指针，签名跟普通 SendMessage 不一样，单列一个
SendMessageWPtr = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p
)(("SendMessageW", u))
IDCANCEL = 2
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DIR = r"C:\ffce\owcancel"
EXT = ".zzc"                 # 自定义扩展名，避免动到真实关联
NOTEPAD = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "notepad.exe")

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


def notepad_windows(basename):
    """记事本窗口标题里含文件名的数量 —— 用来判定文件到底被没被打开。"""
    return [x for x in tops() if basename.lower() in (x[2] or "").lower()]


def kill_notepad():
    subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)


shutil.rmtree(DIR, ignore_errors=True)
os.makedirs(DIR)
base = "cancelfile"
fname = base + EXT
target = os.path.join(DIR, fname)
with open(target, "w", encoding="utf-8") as f:
    f.write("open-with cancel e2e\n")

# 让 .zzc 的候选里至少有记事本：通过 Applications 注册表声明它支持该扩展名
try:
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Classes\Applications\notepad.exe\SupportedTypes")
    winreg.SetValueEx(k, EXT, 0, winreg.REG_SZ, "")
    winreg.CloseKey(k)
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s" % EXT)
    winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "Applications\\notepad.exe")
    winreg.SetValueEx(k, "OpenWithProgids", 0, winreg.REG_SZ, "Applications\\notepad.exe")
    winreg.CloseKey(k)
except OSError as e:
    print("  [WARN] 预置注册表失败: %s" % e)

kill_notepad()
subprocess.run(["taskkill", "/F", "/IM", "FileCE.exe"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.5)


def launch():
    """起一个干净的 FileCE 实例，走到“选择其他应用”对话框并返回 (proc, dlg)。"""
    proc = subprocess.Popen([EXE, DIR])
    main = find_main(proc.pid)
    if not main:
        proc.kill()
        return None, None
    time.sleep(1.2)
    raise_top(main); force_focus(main); time.sleep(0.5)

    lst = u.FindWindowExW(main, None, "SysListView32", None)
    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(0, 0); u.ClientToScreen(lst, ctypes.byref(org))
    rx, ry = org.x + 60, org.y + 34

    click(rx, ry)
    time.sleep(0.3)
    click(rx, ry, right=True)
    time.sleep(0.6)
    if not menus(proc.pid):
        print("    [dbg] 右键没弹出菜单")
        proc.kill()
        return proc, None

    # 父菜单："打开" -> "打开方式"，然后展开子菜单。
    # 子菜单高亮是循环的，展开后直接按一次 ↑ 就落到末项"选择其他应用"。
    key(VK_DOWN)
    for _ in range(4):
        if len(menus(proc.pid)) >= 2:
            break
        key(VK_RIGHT)
        if len(menus(proc.pid)) >= 2:
            break
        key(VK_DOWN)
    if len(menus(proc.pid)) < 2:
        print("    [dbg] 没走进子菜单（层数=%d）" % len(menus(proc.pid)))
        proc.kill()
        return proc, None
    key(VK_UP)

    before = set(h for h, _, _, _ in tops())
    key(VK_RETURN)
    time.sleep(2.5)
    d = [x for x in tops() if x[0] not in before and x[1] == "FFOpenWithDlg"]
    if not d:
        print("    [dbg] 回车后没出现 FFOpenWithDlg")
    return proc, (d[0][0] if d else None)


def stop(proc):
    if not proc:
        return
    proc.terminate(); time.sleep(0.4)
    if proc.poll() is None:
        proc.kill()


def click_ctrl(hwnd):
    r = w.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r))
    click((r.left + r.right) // 2, (r.top + r.bottom) // 2)


# ================= 场景 1：点“取消”绝不能打开文件 =================
proc, dh = launch()
check("“选择其他应用”弹出对话框", bool(dh), str(dh))
if dh:
    olst = u.GetDlgItem(dh, 5301)
    n = u.SendMessageW(olst, LB_GETCOUNT, 0, 0) if olst else 0
    check("列表里有内容（候选 + 末行的浏览项）", n >= 2, "行数=%d" % n)

    # 选中一个真实程序（往上走，别停在浏览行），让“确定/取消”都有意义
    u.SetForegroundWindow(dh); time.sleep(0.4)
    key(VK_UP)
    cur = u.SendMessageW(olst, LB_GETCURSEL, 0, 0)
    check("可以选中列表里的程序", 0 <= cur < n - 1, "当前行=%d / 共%d 行" % (cur, n))

    kill_notepad()
    click_ctrl(u.GetDlgItem(dh, IDCANCEL))
    time.sleep(4.5)

    check("对话框已关闭", not u.IsWindow(dh))
    check("★ 点“取消”后没有打开文件", not notepad_windows(base),
          str([t for _, _, t, _ in notepad_windows(base)]))
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq notepad.exe", "/NH"],
                         capture_output=True)
    listing = out.stdout.decode("mbcs", "ignore")
    check("★ 取消后没有拉起记事本进程", "notepad.exe" not in listing,
          listing.strip()[:80])
    check("★ FileCE 进程仍在运行", proc.poll() is None)
stop(proc)

# ================= 场景 2：点“确定”必须真的打开 =================
kill_notepad()
proc, dh = launch()
check("第二次也能弹出对话框", bool(dh), str(dh))
if dh:
    olst = u.GetDlgItem(dh, 5301)
    u.SetForegroundWindow(dh); time.sleep(0.4)
    key(VK_UP)                        # 选第一个真实程序，别选浏览行
    click_ctrl(u.GetDlgItem(dh, 5303))   # 确定
    time.sleep(5.0)
    check("★ 点“确定”后真的打开了文件", bool(notepad_windows(base)),
          str([t for _, _, t, _ in notepad_windows(base)]))
    check("对话框已关闭", not u.IsWindow(dh))
    check("FileCE 进程未崩溃", proc.poll() is None)
stop(proc)

# ================= 场景 3：ESC / 关闭按钮也必须等于取消 =================
kill_notepad()
proc, dh = launch()
if dh:
    u.SetForegroundWindow(dh); time.sleep(0.4)
    key(VK_ESCAPE)
    time.sleep(4.0)
    check("★ 按 ESC 也没有打开文件", not notepad_windows(base),
          str([t for _, _, t, _ in notepad_windows(base)]))
    check("ESC 后对话框已关闭", not u.IsWindow(dh))

kill_notepad()
proc, dh = launch()
if dh:
    u.SetForegroundWindow(dh); time.sleep(0.4)
    u.PostMessageW(dh, 0x0010, 0, 0)     # WM_CLOSE= 关闭按钮
    time.sleep(4.0)
    check("★ 点关闭按钮也没有打开文件", not notepad_windows(base),
          str([t for _, _, t, _ in notepad_windows(base)]))
stop(proc)

kill_notepad()
shutil.rmtree(DIR, ignore_errors=True)
for p_ in [r"Software\Classes\%s" % EXT]:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p_ + r"\OpenWithProgids")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, p_)
    except OSError:
        pass
# 场景 1 预置的 SupportedTypes\<EXT> 值也必须清掉，否则记事本的
# SupportedTypes 里永远留着 .zzc（上一版就是漏了这里，把真实
# 记事本的注册表污染了）。只删我们写的那个值，键留给孩子别的值。
try:
    st = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r"Software\Classes\Applications\notepad.exe"
                        r"\SupportedTypes", 0, winreg.KEY_ALL_ACCESS)
    try:
        winreg.DeleteValue(st, EXT)
    except OSError:
        pass
    winreg.CloseKey(st)
except OSError:
    pass
# ================= 场景 4：自己浏览挑程序 =================
# 用一个系统里几乎没人注册的扩展名，让候选列表里没有记事本，
# 再点"浏览..."亲自挑它 —— 这正是"列表里没有要打开的程序"时用户的出路。
EXT2 = ".zzy"
base2 = "browsepick"
d2 = r"C:\ffce\owbrowse"
shutil.rmtree(d2, ignore_errors=True)
os.makedirs(d2)
open(os.path.join(d2, base2 + EXT2), "w", encoding="utf-8").write("browse\n")

# 清掉所有残留关联，保证列表里确实列不出记事本
for root, sub in [(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s" % EXT2)]:
    for name in [r"\OpenWithProgids", ""]:
        try:
            winreg.DeleteKey(root, sub + name)
        except OSError:
            pass

proc2 = subprocess.Popen([EXE, d2])
main2 = find_main(proc2.pid)
check("第二个实例的主窗口出现", bool(main2), str(main2))
dh2 = None
if main2:
    time.sleep(1.2)
    raise_top(main2); force_focus(main2); time.sleep(0.5)
    lst2 = u.FindWindowExW(main2, None, "SysListView32", None)
    rc2 = w.RECT(); u.GetClientRect(lst2, ctypes.byref(rc2))
    o2 = w.POINT(0, 0); u.ClientToScreen(lst2, ctypes.byref(o2))
    bx, by = o2.x + 60, o2.y + 34
    click(bx, by); time.sleep(0.3)
    click(bx, by, right=True); time.sleep(0.6)
    key(VK_DOWN)
    for _ in range(4):
        if len(menus(proc2.pid)) >= 2:
            break
        key(VK_RIGHT)
        if len(menus(proc2.pid)) >= 2:
            break
        key(VK_DOWN)
    key(VK_UP)
    before2 = set(h for h, _, _, _ in tops())
    key(VK_RETURN); time.sleep(2.5)
    dd = [x for x in tops() if x[0] not in before2 and x[1] == "FFOpenWithDlg"]
    check("无候选的扩展名也能弹出对话框（不是“什么都不弹”）", bool(dd),
          str([(c, t) for _, c, t, _ in dd]))
    if dd:
        dh2 = dd[0][0]
        olst2 = u.GetDlgItem(dh2, 5301)
        n3 = u.SendMessageW(olst2, LB_GETCOUNT, 0, 0)
        check("列表里至少有“浏览”行", n3 >= 1, "行数=%d" % n3)

        kill_notepad()
        check("底部有常驻的“浏览...”按钮", bool(u.GetDlgItem(dh2, 5306)))
        click_ctrl(u.GetDlgItem(dh2, 5306))
        time.sleep(2.5)
        fdlg = [x for x in tops() if "选择用来打开" in (x[2] or "")]
        check("“浏览...”弹出了文件选择框", bool(fdlg),
              str([(c, t) for _, c, t, _ in tops()
                   if c not in ("FFMainWnd", "Shell_TrayWnd", "Progman",
                                "WorkerW", "Chrome_WidgetWin_1")])[:400])
        if fdlg:
            fh = fdlg[0][0]
            # 用 WM_SETTEXT 往文件名框里塞路径（比逐字符敲键盘可靠得多）
            ed = u.FindWindowExW(fh, None, "Edit", None)
            if not ed:
                cb = u.FindWindowExW(fh, None, "ComboBoxEx32", None)
                if cb:
                    cb2 = u.FindWindowExW(cb, None, "ComboBox", None)
                    if cb2:
                        ed = u.FindWindowExW(cb2, None, "Edit", None)
            check("找到文件名输入框", bool(ed))
            NP = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                              "System32", "notepad.exe")
            if ed:
                SendMessageWPtr(ed, 0x000C, 0,               # WM_SETTEXT
                                   ctypes.cast(ctypes.create_unicode_buffer(NP),
                                             ctypes.c_void_p))
                time.sleep(0.6)
            u.SetForegroundWindow(fh); time.sleep(0.4)
            key(VK_RETURN)                     # 回车 = 选这个文件
            time.sleep(2.5)

        still = [x for x in tops() if "选择用来打开" in (x[2] or "")]
        check("文件框已关闭（路径被接受）", not still,
              str([t for _, _, t, _ in still])[:100])

        if u.IsWindow(dh2):
            n4 = u.SendMessageW(u.GetDlgItem(dh2, 5301), LB_GETCOUNT, 0, 0)
            cur4 = u.SendMessageW(u.GetDlgItem(dh2, 5301), LB_GETCURSEL, 0, 0)
            # 行数可能不变 —— 挑中的 exe 本来就在候选里（ow_append_choice 去重
            # 后直接复用那一项）。真正要保证的是"挑完之后选中的是那个程序，
            # 而不是停在浏览行上"。
            check("挑完之后选中的是程序行（不是浏览行）",
                  0 <= cur4 < n4 - 1, "行数 %d -> %d，当前行=%d" % (n3, n4, cur4))
            click_ctrl(u.GetDlgItem(dh2, 5303))       # 确定
            time.sleep(5.5)
            check("★ 用自己挑的程序打开了文件", bool(notepad_windows(base2)),
                  str([t for _, _, t, _ in notepad_windows(base2)]))
        else:
            # 一个候选都没有时：挑完直接打开，对话框已关
            check("★ 挑完直接用该程序打开（无候选时的快捷路径）",
                  bool(notepad_windows(base2)),
                  str([t for _, _, t, _ in notepad_windows(base2)]))
stop(proc2)
kill_notepad()
shutil.rmtree(d2, ignore_errors=True)

print()
print("=" * 52)
if fails:
    print("失败项: %s" % ", ".join(fails)); sys.exit(1)
print("全部通过")
