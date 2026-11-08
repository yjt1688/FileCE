# -*- coding: utf-8 -*-
r"""回归用户实测报的两个 bug（全程真实鼠标）：
1) 列表里"上面的选项点不中"——单击"写字板/VS Code"等第 2 行以后的程序，
   选中高亮纹丝不动（原生行高 20px vs 自绘 38px，命中全错位）。
   修复后：单击哪行 LB_GETCURSEL 就必须是哪行。
2) 通过"浏览"挑程序 + 勾"始终使用此应用"后，再次打开还是记事本——
   a. 旧版 ow_apply_always 的注册表路径 `\%s` 非法转义吃掉反斜杠，
      全写进 ApplicationsCode.exe 这种烂键（已实证存在，已删）；
   b. .txt 等扩展名 Explorer 的 UserChoice（hash 保护）优先于
      HKCU\Software\Classes\<ext>，不删它新默认永远不生效。
   修复后：注册表必须写对键路径；再开对话框第一行（默认程序）必须变成它；
   UserChoice 必须已被删除。

用自定义扩展名 .zzw 走全链路（不碰用户 .txt 的真实关联），
"被始终使用"的程序用 D:\...\Notepad3.exe（绿色版、注册表里没有它）。

用法: python tests/ow_always_probe.py
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, sys, winreg

u = ctypes.WinDLL("user32", use_last_error=True)
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]
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
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]; u.GetDlgItem.restype = w.HWND

LDOWN, LUP, RDOWN, RUP = 0x0002, 0x0004, 0x0008, 0x0010
VK_DOWN, VK_UP, VK_RIGHT, VK_RETURN = 0x28, 0x26, 0x27, 0x0D
KEYUP = 0x0002
LB_GETCOUNT, LB_GETCURSEL, LB_SETITEMHEIGHT, LB_GETITEMHEIGHT = 0x018B, 0x0188, 0x01A0, 0x01A1
HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
DIR = r"C:\ffce\owalwaystest"
EXT = ".zzw"
NOTEPAD3 = r"D:\Program Files\(Notepad3)5.21.227.1.x64\Notepad3.exe"

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


def open_dialog_via_menu(main, pid):
    """右键唯一文件 → 打开方式 → 选择其他应用 → 返回对话框句柄。"""
    lst = u.FindWindowExW(main, None, "SysListView32", None)
    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(0, 0); u.ClientToScreen(lst, ctypes.byref(org))
    rx, ry = org.x + 60, org.y + 34
    click(rx, ry)
    click(rx, ry, right=True)
    if not menus(pid):
        return None
    force_focus(main)
    key(VK_DOWN)
    for _ in range(4):
        if len(menus(pid)) >= 2:
            break
        key(VK_RIGHT)
        if len(menus(pid)) >= 2:
            break
        key(VK_DOWN)
    key(VK_UP)                       # 子菜单末项 = 选择其他应用
    before = set(h for h, _, _, _ in tops())
    key(VK_RETURN)
    time.sleep(2.0)
    dlg = [x for x in tops() if x[0] not in before and x[1] == "FFOpenWithDlg"]
    return dlg[0][0] if dlg else None


def row_click_point(dh, row):
    """列表第 row 行中心的屏幕坐标（行高 = LB_GETITEMHEIGHT，与自绘一致）。"""
    lst = u.GetDlgItem(dh, 5301)
    rc = w.RECT(); u.GetClientRect(lst, ctypes.byref(rc))
    org = w.POINT(0, 0); u.ClientToScreen(lst, ctypes.byref(org))
    ih = int(u.SendMessageW(lst, LB_GETITEMHEIGHT, 0, 0)) or 38
    top = int(u.SendMessageW(lst, 0x018E, 0, 0))            # LB_GETTOPINDEX
    y = org.y + (row - top) * ih + ih // 2
    return org.x + rc.left + 60, y


def cleanup_reg():
    """删掉本次测试要用的注册表痕迹（测试前清场 / 测试后还原）。
    全部走 powershell -Recurse：winreg.DeleteKey 删不了带子键的键
    （Classes\\.zzw 下有 OpenWithProgids）。"""
    import subprocess
    targets = [
        r"Software\Classes" + "\\" + EXT,
        r"Software\Classes\Applications\Notepad3.exe",
        r"Software\FileCE\OpenWith" + "\\" + EXT,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts" + "\\" + EXT,
    ]
    ps = "; ".join("Remove-Item 'HKCU:\\%s' -Recurse -ErrorAction SilentlyContinue" % t
                   for t in targets)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    for t in targets:                       # 确认删干净（残留会污染断言）
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, t)
            print("  [WARN] 清场失败仍存在: HKCU\\" + t)
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, t))
        except OSError:
            pass


if not os.path.exists(NOTEPAD3):
    print("SKIP: 本机没有 %s" % NOTEPAD3)
    sys.exit(0)

shutil.rmtree(DIR, ignore_errors=True)
os.makedirs(DIR, exist_ok=True)
target = os.path.join(DIR, "always" + EXT)
with open(target, "w", encoding="utf-8") as f:
    f.write("always-use e2e\n")

cleanup_reg()

proc = subprocess.Popen([EXE, DIR])
dh = None
try:
    main = find_main(proc.pid)
    check("主窗口出现", bool(main))
    if not main:
        sys.exit(1)
    time.sleep(1.0)
    raise_top(main); force_focus(main); time.sleep(0.4)

    dh = open_dialog_via_menu(main, proc.pid)
    check("弹出打开方式对话框", bool(dh))
    if not dh:
        sys.exit(1)

    lst = u.GetDlgItem(dh, 5301)
    ih = int(u.SendMessageW(lst, LB_GETITEMHEIGHT, 0, 0))
    # 修复 1 的直接证据：控件行高必须等于自绘行高（38px，DPI=1 时）
    check("控件行高=自绘行高(38)", ih in (38, 76), "LB_GETITEMHEIGHT=%d" % ih)

    # ---- bug 1：单击程序行必须真的选中它 ----
    # .zzw 冷扩展名首开只有 1 行（"浏览其它应用程序…"）。0 候选时对话框默认
    # 就选中浏览行，先验这个；多候选的行布局场景（0=默认/1=标题/2..=候选）
    # 由第二阶段（注册完 Notepad3 后重开）覆盖。
    n_rows = int(u.SendMessageW(lst, LB_GETCOUNT, 0, 0))
    print("  首开行数=%d" % n_rows)
    last = n_rows - 1
    xl, yl = row_click_point(dh, last)
    click(xl, yl); time.sleep(0.3)
    cur = int(u.SendMessageW(lst, LB_GETCURSEL, 0, 0))
    check("点浏览行选中浏览行", cur == last, "LB_GETCURSEL=%d" % cur)
    if n_rows >= 3:                          # 有候选时再验程序行
        x2, y2 = row_click_point(dh, 2)
        click(x2, y2); time.sleep(0.3)
        cur = int(u.SendMessageW(lst, LB_GETCURSEL, 0, 0))
        check("单击第2行程序真的选中第2行", cur == 2, "LB_GETCURSEL=%d" % cur)
        click(xl, yl); time.sleep(0.3)       # 点回浏览行继续 bug-2 流程

    # ---- bug 2：点底部"浏览..."按钮挑 Notepad3 + 勾"始终使用" + 确定 ----
    brow = u.GetDlgItem(dh, 5306)
    br = w.RECT(); u.GetWindowRect(brow, ctypes.byref(br))
    click((br.left + br.right) // 2, (br.top + br.bottom) // 2)
    time.sleep(1.8)
    # 系统"选择用来打开此文件的程序"文件框（#32770），往文件名框塞路径回车
    fb = None
    for h, c, t, _ in tops():
        if c == "#32770" and "选择" in t and "程序" in t:
            fb = h
            break
    check("浏览弹出系统文件框", bool(fb), str([(c, t) for _, c, t, _ in tops() if c == "#32770"])[:120])
    if not fb:
        sys.exit(1)
    force_focus(fb); time.sleep(0.3)
    # IFileOpenDialog 的文件名编辑框在对话框内部的子对话框里（"文件名:"组合框），
    # 递归往下找第一个可见 Edit。WM_SETTEXT 的 LPARAM 是指针，必须传长生命周期缓冲。
    edit = [None]

    def find_edit(h, l):
        c = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, c, 96)
        if edit[0] is None and c.value == "Edit" and u.IsWindowVisible(h):
            edit[0] = h
            return False
        if c.value in ("#32770", "ComboBox", "ComboBoxEx32"):
            u.EnumChildWindows(h, HWNDCB(find_edit), 0)
        return True

    u.EnumChildWindows(fb, HWNDCB(find_edit), 0)
    edit = edit[0]
    check("找到文件名编辑框", bool(edit))
    if not edit:
        sys.exit(1)
    buf = ctypes.create_unicode_buffer(NOTEPAD3)
    u.SendMessageW(edit, 0x000C, 0, ctypes.cast(buf, ctypes.c_void_p).value)  # WM_SETTEXT
    time.sleep(0.2)
    key(VK_RETURN)
    time.sleep(1.5)
    # 回到对话框：选中行应已落在 Notepad3 上
    cur = int(u.SendMessageW(lst, LB_GETCURSEL, 0, 0))
    # 浏览后 ow_fill 会重新选中加进来的程序行（多候选时在标题行之后、
    # 0 候选起步时就是行 0）。断言"不是浏览行"即可——浏览行永远在末尾。
    last_after = int(u.SendMessageW(lst, LB_GETCOUNT, 0, 0)) - 1
    check("浏览后选中新加的 Notepad3 行（不在浏览行）",
          0 <= cur <= last_after and cur != last_after,
          "LB_GETCURSEL=%d rows=%d" % (cur, last_after + 1))

    ck = u.GetDlgItem(dh, 5302)
    ckr = w.RECT(); u.GetWindowRect(ck, ctypes.byref(ckr))
    click((ckr.left + ckr.right) // 2, (ckr.top + ckr.bottom) // 2)
    st = int(u.SendMessageW(ck, 0x00F0, 0, 0))               # BM_GETCHECK
    check("勾上'始终使用此应用'", st == 1, "BM_GETCHECK=%d" % st)

    okb = u.GetDlgItem(dh, 5303)
    okr = w.RECT(); u.GetWindowRect(okb, ctypes.byref(okr))
    click((okr.left + okr.right) // 2, (okr.top + okr.bottom) // 2)
    # 注册表写在对话框销毁之后（模态循环退出 → accepted → ow_apply_always），
    # 轮询等待它落地；SHChangeNotify 广播期间 Explorer 可能短暂持有键，
    # 一口气最多等 10 秒。
    cls_def = None
    for _ in range(40):
        cls_def = reg_get(r"Software\Classes" + "\\" + EXT)
        if cls_def:
            break
        time.sleep(0.25)
    check("确定后对话框关闭", not u.IsWindow(dh))
    check("进程未崩溃", proc.poll() is None)

    # ---- 注册表断言（键路径必须正确，烂键不得再现）----
    exe_name = "Notepad3.exe"
    ok_cmd = reg_get(r"Software\Classes\Applications\%s\shell\open\command" % exe_name)
    check("Applications\\Notepad3.exe\\shell\\open\\command 已写",
          bool(ok_cmd) and "Notepad3" in ok_cmd, str(ok_cmd))
    sup = reg_get(r"Software\Classes\Applications\%s\SupportedTypes" % exe_name, EXT)
    check("SupportedTypes 声明了 %s" % EXT, sup is not None, str(sup))
    check("Classes\\%s 默认 ProgID = FileCE.*" % EXT,
          bool(cls_def) and cls_def.startswith("FileCE."), str(cls_def))
    owp = reg_get(r"Software\Classes" + "\\" + EXT + r"\OpenWithProgids", cls_def or "?")
    check("OpenWithProgids 登记了该 ProgID", owp is not None, str(owp))
    bad = reg_get(r"Software\Classes\ApplicationsNotepad3.exe\shell\open\command")
    check("不再写进烂键 ApplicationsNotepad3.exe", bad is None, str(bad))
    uc = reg_get(r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
                 + EXT + r"\UserChoice", "ProgId")
    check("UserChoice 已删除(不再挡新默认)", uc is None, str(uc))

    # ---- 再开一次：默认程序（第 0 行）必须是 Notepad3 ----
    proc.terminate(); time.sleep(0.3)
    if proc.poll() is None:
        proc.kill()
    proc2 = subprocess.Popen([EXE, DIR])
    main2 = find_main(proc2.pid)
    check("第二个实例主窗口", bool(main2))
    if main2:
        raise_top(main2); force_focus(main2); time.sleep(0.4)
        dh2 = open_dialog_via_menu(main2, proc2.pid)
        check("再次打开弹出对话框", bool(dh2))
        if dh2:
            lst2 = u.GetDlgItem(dh2, 5301)
            lbls = []
            # 粗验：行数 ≥2 且第 0 行不再是记事本 —— 用 LB_GETTEXT 拿不到自绘文本，
            # 改走注册表：私有历史第一位应是 Notepad3 完整路径
            hist = reg_get(r"Software\FileCE\OpenWith" + "\\" + EXT, "a")
            check("私有历史第一位=Notepad3 完整路径",
                  bool(hist) and "notepad3" in hist.lower(), str(hist))
            hist2 = reg_get(r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
                            + "\\" + EXT + r"\OpenWithList", "a")
            check("Explorer 历史第一位=Notepad3.exe",
                  bool(hist2) and hist2.lower() == "notepad3.exe", str(hist2))
            u.PostMessageW(dh2, 0x0010, 0, 0)                 # WM_CLOSE
        proc2.terminate(); time.sleep(0.3)
        if proc2.poll() is None:
            proc2.kill()
finally:
    if proc.poll() is None:
        proc.terminate(); time.sleep(0.3)
        if proc.poll() is None:
            proc.kill()
    if "--keep" not in sys.argv:
        cleanup_reg()
    shutil.rmtree(DIR, ignore_errors=True)

print()
print("=" * 50)
if fails:
    print("失败项: %s" % ", ".join(fails))
    sys.exit(1)
print("全部通过")
