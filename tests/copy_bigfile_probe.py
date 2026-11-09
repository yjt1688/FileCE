# -*- coding: utf-8 -*-
"""验证：复制大文件期间窗口是否还响应（SendMessageTimeout 不超时）。
   修复前：CopyFileExW 回调 NULL，同步阻塞 → 全部超时
   修复后：回调里泵消息 → 每次都能应答"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil

u = ctypes.WinDLL("user32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageTimeoutW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
                                  ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
u.SendMessageTimeoutW.restype = w.LPARAM
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]

CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")
CMD_COPY, CMD_PASTE = 20007, 20009


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(h, b, 256)
    return b.value


def txt(h):
    b = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(h, b, 512)
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


def find_main(pid):
    for h in wins(pid):
        if cls(h) == "FFMainWnd":
            return h
    return None


def child_of(parent, name):
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if cls(h) == name:
            out.append(h)
        return True
    u.EnumChildWindows(parent, cb, 0)
    return out[0] if out else None


def responsive(hwnd, ms=200):
    r = ctypes.c_size_t(0)
    return u.SendMessageTimeoutW(hwnd, 0x0000, 0, 0, 0x0002, ms, ctypes.byref(r)) != 0


# 源目录和目标目录分开，避免"同目录复制到自身"
ROOT = os.path.join(CWD, "build", "_prog")
SRC = os.path.join(ROOT, "src")
shutil.rmtree(ROOT, ignore_errors=True)
os.makedirs(SRC)
big = os.path.join(SRC, "big.bin")
print("造 800MB 文件...")
with open(big, "wb") as f:
    chunk = b"\0" * (1024 * 1024)
    for _ in range(800):
        f.write(chunk)

p = subprocess.Popen([EXE, SRC])
main = None
t0 = time.time()
while not main and time.time() - t0 < 12:
    main = find_main(p.pid)
    time.sleep(0.1)
if not main:
    print("启动失败")
    raise SystemExit(1)
time.sleep(2.5)
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
u.MoveWindow(main, 60, 30, 900, 620, True)
time.sleep(1.2)

lv = child_of(main, "SysListView32")
u.PostMessageW(lv, 0x0100, 0x24, 0x00000001)
u.PostMessageW(lv, 0x0101, 0x24, 0xC0000001)
time.sleep(0.3)
u.PostMessageW(lv, 0x0100, 0x28, 0x01500001)
u.PostMessageW(lv, 0x0101, 0x28, 0xC1500001)
time.sleep(0.5)

u.PostMessageW(main, 0x0111, CMD_COPY, 0)
time.sleep(0.8)
print("同目录粘贴（触发复制，测响应）...")
u.PostMessageW(main, 0x0111, CMD_PASTE, 0)

checks = timeouts = 0
saw_title = ""
t_start = time.time()
while time.time() - t_start < 30:
    if p.poll() is not None:
        print("!! 进程退出")
        break
    checks += 1
    if not responsive(main, 200):
        timeouts += 1
    t = txt(main)
    if "正在复制" in t:
        saw_title = t[:45]
    extra = [x for x in os.listdir(SRC) if x != "big.bin"]
    if extra:
        break
    time.sleep(0.12)

took = time.time() - t_start
extra = [x for x in os.listdir(SRC) if x != "big.bin"]
alive = p.poll() is None
if alive:
    p.terminate()
time.sleep(0.6)
shutil.rmtree(ROOT, ignore_errors=True)

print("\n结果:")
print("  探测 %d 次, 超时 %d 次" % (checks, timeouts))
print("  标题栏进度: %s" % (saw_title if saw_title else "(没看到)"))
print("  产物: %s" % (extra if extra else "(无)"))
print("  耗时 %.1f 秒" % took)
print("\nRESULT:", "PASS 复制期间窗口始终响应" if timeouts == 0
      else "FAIL 有 %d 次超时（窗口卡住）" % timeouts)
