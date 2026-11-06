# -*- coding: utf-8 -*-
"""rar 拖入：压缩包目录里只有一个 arch.rar（无子目录→无分组），源文件放别的目录"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, struct

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetDlgItem.argtypes = [w.HWND, ctypes.c_int]
u.GetDlgItem.restype = w.HWND
u.PostMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_uint]
u.MoveWindow.argtypes = [w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.IsWindowVisible.argtypes = [w.HWND]
k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
k.GlobalAlloc.restype = ctypes.c_void_p
k.GlobalLock.argtypes = [ctypes.c_void_p]
k.GlobalLock.restype = ctypes.c_void_p
k.GlobalUnlock.argtypes = [ctypes.c_void_p]

WM_DROPFILES = 0x0233
CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")
RAR = r"C:\Program Files\WinRAR\Rar.exe"


def cls(h):
    b = ctypes.create_unicode_buffer(128)
    u.GetClassNameW(h, b, 128)
    return b.value


def txt(h):
    b = ctypes.create_unicode_buffer(256)
    u.GetWindowTextW(h, b, 256)
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


def make_hdrop(path):
    raw = (path + "\0\0").encode("utf-16-le")
    h = k.GlobalAlloc(0x0042, 20 + len(raw))
    p = k.GlobalLock(h)
    ctypes.memmove(p, struct.pack("<IiiII", 20, 0, 0, 0, 1), 20)
    ctypes.memmove(p + 20, raw, len(raw))
    k.GlobalUnlock(h)
    return h


def rar_list(arc):
    r = subprocess.run([RAR, "lb", arc], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return [x.strip() for x in r.stdout.splitlines() if x.strip()]


def rar_content(arc, name):
    tmp = os.path.join(os.path.dirname(arc), "_xtmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    subprocess.run([RAR, "x", "-y", arc, name, tmp + "\\"], capture_output=True)
    p = os.path.join(tmp, name)
    c = open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else None
    shutil.rmtree(tmp, ignore_errors=True)
    return c


arcdir = os.path.join(CWD, "build", "_rar3")
srcdir = os.path.join(CWD, "build", "_rar3_src")
shutil.rmtree(arcdir, ignore_errors=True)
shutil.rmtree(srcdir, ignore_errors=True)
os.makedirs(arcdir)
os.makedirs(srcdir)
open(os.path.join(srcdir, "a.txt"), "w").write("AAA")
open(os.path.join(srcdir, "same.txt"), "w").write("OLD")
arc = os.path.join(arcdir, "arch.rar")
subprocess.run([RAR, "a", "-y", arc, "a.txt", "same.txt"], cwd=srcdir, capture_output=True)
print("造 rar:", rar_list(arc), " 目录里:", os.listdir(arcdir))
payload = os.path.join(srcdir, "newfile.txt")
open(payload, "w").write("NEW")
over = os.path.join(srcdir, "same.txt")
open(over, "w").write("REPLACED")

p = subprocess.Popen([EXE, arcdir])
main = None
t0 = time.time()
while not main and time.time() - t0 < 10:
    for h in wins(p.pid):
        if cls(h) == "FFMainWnd":
            main = h
            break
    time.sleep(0.1)
time.sleep(1.8)
u.SetWindowPos(main, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
u.MoveWindow(main, 60, 30, 900, 650, True)
time.sleep(0.8)

lst = u.GetDlgItem(main, 1001)
rc = w.RECT()
u.GetWindowRect(lst, ctypes.byref(rc))
u.SetCursorPos(rc.left + 120, rc.top + 46)
time.sleep(0.2)
dlgb = [txt(h) for h in wins(p.pid) if u.IsWindowVisible(h) and cls(h) == "#32770"]
u.PostMessageW(main, WM_DROPFILES, make_hdrop(payload), 0)
time.sleep(3.5)
dlga = [txt(h) for h in wins(p.pid) if u.IsWindowVisible(h) and cls(h) == "#32770"]
got = rar_list(arc)
print("\n① 拖 newfile.txt ->", got)
if dlga != dlgb:
    print("   弹框:", dlga)
okA = "newfile.txt" in got
print("   ->", "PASS" if okA else "FAIL")

okB = False
if okA:
    u.SetCursorPos(rc.left + 120, rc.top + 46)
    time.sleep(0.2)
    u.PostMessageW(main, WM_DROPFILES, make_hdrop(over), 0)
    time.sleep(3.5)
    c = rar_content(arc, "same.txt")
    print("② 同名 same.txt =", repr(c))
    okB = (c == "REPLACED")
    print("   ->", "PASS" if okB else "FAIL")

p.terminate()
time.sleep(0.4)
shutil.rmtree(arcdir, ignore_errors=True)
shutil.rmtree(srcdir, ignore_errors=True)
print("\nRESULT:", "PASS" if (okA and okB) else "FAIL")
