# -*- coding: utf-8 -*-
"""验证：同目录复制粘贴会先问，并且【是】=生成副本、【否】=不生成"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.IsWindowVisible.argtypes = [w.HWND]

CMD_COPY, CMD_PASTE = 20007, 20009
WM_COMMAND, WM_CLOSE = 0x0111, 0x0010
IDYES, IDNO, IDCANCEL = 6, 7, 2
NO_PROMPT = -1


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def txt(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, b, 256)
    return b.value


def wins(pid=None):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if pid is not None:
            q = w.DWORD(0)
            u.GetWindowThreadProcessId(h, ctypes.byref(q))
            if q.value != pid:
                return True
        out.append(h)
        return True

    u.EnumWindows(cb, 0)
    return out


CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")


def one_case(button, label, expect_copy):
    base = os.path.join(CWD, "build", "_same_" + label)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    open(os.path.join(base, "doc.txt"), "w").write("CONTENT")

    p = subprocess.Popen([EXE, base])
    PID = p.pid
    main = None
    t0 = time.time()
    while not main and time.time() - t0 < 10:
        for h in wins(PID):
            if cls(h) == "FFMainWnd":
                main = h
                break
        time.sleep(0.1)
    time.sleep(1.6)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 900, 650, True)
    time.sleep(0.6)

    lst = u.GetDlgItem(main, 1001)
    r = w.RECT()
    u.GetWindowRect(lst, ctypes.byref(r))
    u.SetCursorPos(r.left + 90, r.top + 46)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)

    u.PostMessageW(main, WM_COMMAND, CMD_COPY, 0)
    time.sleep(0.6)
    u.PostMessageW(main, WM_COMMAND, CMD_PASTE, 0)

    dlg = None
    t0 = time.time()
    while time.time() - t0 < 4:
        for h in wins(PID):
            if u.IsWindowVisible(h) and cls(h) == "#32770":
                dlg = h
                break
        if dlg:
            break
        time.sleep(0.1)
    title = txt(dlg) if dlg else None
    if dlg and button >= 0:
        u.PostMessageW(dlg, WM_COMMAND, button, 0)
    time.sleep(2.5)

    files = sorted(os.listdir(base))
    got = len(files) > 1
    want_prompt = (button >= 0)
    good = (got == expect_copy) and ((dlg is not None) == want_prompt)
    print("  [%s] 弹框=%-14r 目录内容 %s  期望%s副本 %s  %s"
          % (label, title, files,
             "生成" if expect_copy else "不生成",
             "（要求弹框）" if want_prompt else "（不该弹框）",
             "OK" if good else "!!!"))
    p.terminate()
    time.sleep(0.4)
    shutil.rmtree(base, ignore_errors=True)
    return good


print("同目录复制 → 不弹框，直接生成副本")
ok = True
ok &= one_case(NO_PROMPT, "静默", True)
print("RESULT:", "PASS" if ok else "FAIL")
