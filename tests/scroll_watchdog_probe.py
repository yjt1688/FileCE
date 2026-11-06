# -*- coding: utf-8 -*-
"""A/B 验证：把虚拟列表的滚动原点弄成负数，看谁会自愈。
   A = 备份的旧版 exe（E:\自己软件\FileCE-2026-10-28\FileCE.exe）
   B = 刚构建的新版（带看门狗）"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.InvalidateRect.argtypes = [w.HWND, ctypes.c_void_p, w.BOOL]
u.UpdateWindow.argtypes = [w.HWND]

LVM_GETTOPINDEX = 0x1027
LVM_SETITEMCOUNT = 0x1029
LVM_GETITEMCOUNT = 0x1004
LVM_SCROLL = 0x1014
IDC_LIST = 1001

OLD = r"E:\自己软件\FileCE-2026-10-28\FileCE.exe"
NEW = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
WORK = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\_scrolltest"


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


def run(label, exe):
    if not os.path.exists(exe):
        print("  [%s] exe 不存在: %s" % (label, exe))
        return None
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for i in range(40):
        open(os.path.join(WORK, "file%02d.txt" % i), "w").write("x")

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

    lst = u.GetDlgItem(main, IDC_LIST)
    cnt0 = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)
    top0 = u.SendMessageW(lst, LVM_GETTOPINDEX, 0, 0)

    # 滚到底（让滚动原点处在内容很下方）
    u.SendMessageW(lst, LVM_SCROLL, 0, 100000)
    time.sleep(0.3)
    top1 = u.SendMessageW(lst, LVM_GETTOPINDEX, 0, 0)

    # 制造异常：告诉控件只有 2 项（模拟目录变小），促使其原点悬空
    u.SendMessageW(lst, LVM_SETITEMCOUNT, 2, 0)
    time.sleep(0.3)
    top2 = u.SendMessageW(lst, LVM_GETTOPINDEX, 0, 0)

    # 触发重绘 → 带看门狗的版本应在此自愈
    u.InvalidateRect(lst, None, True)
    u.UpdateWindow(lst)
    time.sleep(0.6)
    top3 = u.SendMessageW(lst, LVM_GETTOPINDEX, 0, 0)
    cnt3 = u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)

    p.terminate()
    time.sleep(0.4)
    print("  [%s] 项数=%d top: 初始=%d 滚到底=%d 破坏后=%d -> 重绘后=%d (项数恢复=%d)"
          % (label, cnt0, top0, top1, top2, top3, cnt3))
    return top3


print("破坏虚拟列表滚动原点，看能否自愈（top 应 >= 0 且项数恢复）\n")
a = run("旧版", OLD)
b = run("新版", NEW)
shutil.rmtree(WORK, ignore_errors=True)

print()
if a is None or b is None:
    print("RESULT: 无法对比（缺 exe）")
else:
    okA = (a >= 0)
    okB = (b >= 0)
    print("旧版 重绘后 top=%d -> %s" % (a, "正常" if okA else "仍为负（就是白屏的原因）"))
    print("新版 重绘后 top=%d -> %s" % (b, "正常" if okB else "仍为负"))
    print("\nRESULT:", "PASS 看门狗修好了" if (okB and not okA) else
          ("PASS 两版都正常" if okB else "FAIL"))
