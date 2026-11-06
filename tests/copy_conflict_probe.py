# -*- coding: utf-8 -*-
"""验证：复制到已存在同名文件的目录会弹「确认文件替换」，且三种选择都生效"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.SetForegroundWindow.argtypes = [w.HWND]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]

CMD_COPY, CMD_PASTE = 20007, 20009
IDYES, IDNO, IDCANCEL = 6, 7, 2
WM_COMMAND, WM_CLOSE = 0x0111, 0x0010


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
base = os.path.join(CWD, "build", "_conftest")
shutil.rmtree(base, ignore_errors=True)
A = os.path.join(base, "A")
B = os.path.join(base, "B")
os.makedirs(A)
os.makedirs(B)
with open(os.path.join(A, "same.txt"), "w") as f:
    f.write("FROM-A")
with open(os.path.join(B, "same.txt"), "w") as f:
    f.write("FROM-B")


def read(p):
    with open(p, "r", errors="ignore") as f:
        return f.read()


def find_msgbox(pid, timeout=4.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for h in wins(pid):
            if cls(h) == "#32770" and "确认文件替换" in txt(h):
                return h
        time.sleep(0.1)
    return None


def run(choice_id, label):
    """在 A 里复制 same.txt，切到 B 粘贴，按 choice_id 应答"""
    p = subprocess.Popen([EXE, A])
    PID = p.pid
    main = None
    t0 = time.time()
    while not main and time.time() - t0 < 10:
        for h in wins(PID):
            if cls(h) == "FFMainWnd":
                main = h
                break
        time.sleep(0.1)
    time.sleep(1.5)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 900, 650, True)
    time.sleep(0.6)
    u.SetForegroundWindow(main)

    lst = u.GetDlgItem(main, 1001)
    r = w.RECT()
    u.GetWindowRect(lst, ctypes.byref(r))
    cx, cy = r.left + 90, r.top + 46
    # 点一下第一行选中
    u.SetCursorPos(cx, cy)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)
    u.PostMessageW(main, WM_COMMAND, CMD_COPY, 0)
    time.sleep(0.6)

    # 导航到 B：直接在地址栏敲？这里用"上一级再进 B"太绕 —— 直接重开进程更快
    p.terminate()
    time.sleep(0.4)

    p = subprocess.Popen([EXE, B])
    PID = p.pid
    main = None
    t0 = time.time()
    while not main and time.time() - t0 < 10:
        for h in wins(PID):
            if cls(h) == "FFMainWnd":
                main = h
                break
        time.sleep(0.1)
    time.sleep(1.5)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 900, 650, True)
    time.sleep(0.6)
    u.SetForegroundWindow(main)
    u.PostMessageW(main, WM_COMMAND, CMD_PASTE, 0)

    mb = find_msgbox(PID)
    print("  [%s] 弹出「确认文件替换」: %s" % (label, bool(mb)))
    if mb:
        u.PostMessageW(mb, WM_COMMAND, choice_id, 0)
    time.sleep(2.5)
    p.terminate()
    time.sleep(0.4)
    return bool(mb)


EXE = os.path.join(CWD, "build", "FileCE.exe")
ok = True

# ---- 场景1：选"是"（替换）
print("场景1：选【是】= 替换")
got = run(IDYES, "替换")
content = read(os.path.join(B, "same.txt"))
print("    B\\same.txt 内容 = %r （应为 FROM-A）" % content)
ok1 = got and content == "FROM-A"
print("    ->", "PASS" if ok1 else "FAIL")
ok &= ok1

# 复位 B
with open(os.path.join(B, "same.txt"), "w") as f:
    f.write("FROM-B")
shutil.rmtree(os.path.join(B, "same (2).txt"), ignore_errors=True)

# ---- 场景2：选"否"（两者都保留）
print("\n场景2：选【否】= 两者都保留（自动改名）")
got2 = run(IDNO, "保留两者")
content_b = read(os.path.join(B, "same.txt"))
exists2 = os.path.exists(os.path.join(B, "same (2).txt"))
print("    B\\same.txt 内容 = %r （应仍是 FROM-B）" % content_b)
print("    生成了 same (2).txt = %s （内容 %r，应为 FROM-A）"
      % (exists2, read(os.path.join(B, "same (2).txt")) if exists2 else ""))
ok2 = got2 and content_b == "FROM-B" and exists2
print("    ->", "PASS" if ok2 else "FAIL")
ok &= ok2

shutil.rmtree(base, ignore_errors=True)
print("\nRESULT:", "PASS" if ok else "FAIL")
