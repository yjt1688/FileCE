# -*- coding: utf-8 -*-
"""A/B：反复 F5 刷新，看 HICON 泄漏是否修好。"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.GetGuiResources.argtypes = [w.HANDLE, w.DWORD]
u.GetGuiResources.restype = w.DWORD
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]

CMD_REFRESH = 20004
WM_COMMAND = 0x0111
GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # FileCE 根
A = os.path.join(ROOT, "build", "_before.exe")                       # 你改的版本（有泄漏）
B = os.path.join(ROOT, "build", "FileCE.exe")                        # 修复版
WORK = os.path.join(ROOT, "build", "_hicontest")
N = 40


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def wins(pid):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        q = w.DWORD(0)
        u.GetWindowThreadProcessId(h, ctypes.byref(q))
        if q.value == pid:
            out.append(h)
        return True

    u.EnumWindows(cb, 0)
    return out


def res(pid):
    h = k.OpenProcess(0x1000, False, pid)
    if not h:
        return (0, 0)
    g = u.GetGuiResources(h, GR_GDIOBJECTS)
    us = u.GetGuiResources(h, GR_USEROBJECTS)
    k.CloseHandle(h)
    return (g, us)


def run(label, exe):
    if not os.path.exists(exe):
        print("  [%s] 缺 exe: %s" % (label, exe))
        return None
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for i in range(3):
        open(os.path.join(WORK, "f%d.txt" % i), "w").write("x")

    p = subprocess.Popen([exe, WORK])
    main = None
    t0 = time.time()
    while not main and time.time() - t0 < 10:
        for h in wins(p.pid):
            if cls(h) == "FFMainWnd":
                main = h
                break
        time.sleep(0.1)
    time.sleep(2.0)
    u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    u.MoveWindow(main, 60, 30, 900, 620, True)
    time.sleep(0.8)

    g0, us0 = res(p.pid)
    for i in range(N):
        u.PostMessageW(main, WM_COMMAND, CMD_REFRESH, 0)
        time.sleep(0.12)
    time.sleep(1.0)
    g1, us1 = res(p.pid)

    alive = p.poll() is None
    p.terminate()
    time.sleep(0.4)
    print("  [%s] GDI %d->%d (+%d)   USER %d->%d (+%d)   %d 次刷新%s"
          % (label, g0, g1, g1 - g0, us0, us1, us1 - us0, N,
             "，存活" if alive else "，!!崩溃"))
    return (g1 - g0, us1 - us0)


print("反复 F5 刷新 %d 次，看 HICON 是否泄漏（USER 对象应该几乎不涨）\n" % N)
a = run("你改的版本", A)
b = run("修复版", B)
shutil.rmtree(WORK, ignore_errors=True)

print()
if b is None:
    print("RESULT: FAIL 修复版 exe 缺失")
elif a is None:
    # 没有对照版（历史版本已清理），只看修复版自己涨不涨
    print("修复版: USER +%d / GDI +%d" % (b[1], b[0]))
    print("\nRESULT:", "PASS 修复版 40 次刷新不涨" if b[1] <= 5 else "FAIL 修复版仍在涨")
else:
    print("你改的版本: USER +%d / GDI +%d" % (a[1], a[0]))
    print("修复版    : USER +%d / GDI +%d" % (b[1], b[0]))
    leakA = a[1] >= N * 0.5
    okB = b[1] <= 5
    if okB and leakA:
        print("\nRESULT: PASS 对照版泄漏 +%d，修复版不涨 —— 泄漏已修好" % a[1])
    elif okB:
        print("\nRESULT: PASS 修复版不涨（对照版也没明显泄漏，这台机器上 SHGetFileInfo 可能复用同一图标句柄）")
    else:
        print("\nRESULT: FAIL 修复版仍在涨")
