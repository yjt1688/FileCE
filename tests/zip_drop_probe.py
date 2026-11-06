# -*- coding: utf-8 -*-
"""验证：拖文件到 .zip 上，文件被写进压缩包（系统压缩文件夹），同名直接替换、不弹框"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, shutil, zipfile, struct

u = ctypes.WinDLL("user32")
k = ctypes.WinDLL("kernel32")
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
k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
k.GlobalAlloc.restype = ctypes.c_void_p
k.GlobalLock.argtypes = [ctypes.c_void_p]
k.GlobalLock.restype = ctypes.c_void_p
k.GlobalUnlock.argtypes = [ctypes.c_void_p]

WM_DROPFILES = 0x0233
CWD = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
EXE = os.path.join(CWD, "build", "FileCE.exe")


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


def make_hdrop(path):
    """DROPFILES + 宽字符列表（双 NUL）"""
    data = path + "\0\0"
    raw = data.encode("utf-16-le")
    size = 20 + len(raw)
    h = k.GlobalAlloc(0x0042, size)          # GHND
    p = k.GlobalLock(h)
    hdr = struct.pack("<IiiII", 20, 0, 0, 0, 1)   # pFiles=20, pt, fNC=0, fWide=1
    ctypes.memmove(p, hdr, 20)
    ctypes.memmove(p + 20, raw, len(raw))
    k.GlobalUnlock(h)
    return h


base = os.path.join(CWD, "build", "_ziptest")
shutil.rmtree(base, ignore_errors=True)
os.makedirs(base)
zipp = os.path.join(base, "arch.zip")
with zipfile.ZipFile(zipp, "w") as z:
    z.writestr("a.txt", "AAA")
    z.writestr("same.txt", "OLD")
src_new = os.path.join(base, "newfile.txt")
open(src_new, "w").write("NEW")
src_same = os.path.join(base, "same.txt")
open(src_same, "w").write("REPLACED")


def names_in_zip():
    with zipfile.ZipFile(zipp) as z:
        return z.namelist()


def content_in_zip(n):
    with zipfile.ZipFile(zipp) as z:
        return z.read(n).decode("utf-8", "replace")


def start():
    p = subprocess.Popen([EXE, base])
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
    time.sleep(0.7)
    return p, main


def drop_on_row(main, row, path):
    """把光标放到列表第 row 行上，投递 WM_DROPFILES"""
    lst = u.GetDlgItem(main, 1001)
    r = w.RECT()
    u.GetWindowRect(lst, ctypes.byref(r))
    x = r.left + 120
    y = r.top + 46 + row * 24
    u.SetCursorPos(x, y)
    time.sleep(0.2)
    hd = make_hdrop(path)
    u.PostMessageW(main, WM_DROPFILES, hd, 0)
    time.sleep(2.5)


print("初始 zip 内容:", names_in_zip())
p, main = start()

# 列表按名称排序：arch.zip, newfile.txt, same.txt  → zip 在第 0 行
print("\n① 拖 newfile.txt 到 arch.zip 上")
drop_on_row(main, 0, src_new)
n1 = names_in_zip()
print("   zip 内容:", n1)
okA = "newfile.txt" in n1
print("   ->", "PASS 新文件加进去了" if okA else "FAIL")

print("\n② 拖 same.txt 到 arch.zip 上（同名，应直接替换不弹框）")
dlg_before = [h for h in wins(p.pid) if u.IsWindowVisible(h) and cls(h) == "#32770"]
drop_on_row(main, 0, src_same)
dlg_after = [h for h in wins(p.pid) if u.IsWindowVisible(h) and cls(h) == "#32770"]
c = content_in_zip("same.txt")
print("   same.txt 内容:", repr(c), "（应为 REPLACED）")
print("   弹框:", "有" if len(dlg_after) > len(dlg_before) else "无")
okB = (c == "REPLACED") and len(dlg_after) == len(dlg_before)
print("   ->", "PASS" if okB else "FAIL")

p.terminate()
time.sleep(0.4)
shutil.rmtree(base, ignore_errors=True)
print("\nRESULT:", "PASS" if (okA and okB) else "FAIL")
