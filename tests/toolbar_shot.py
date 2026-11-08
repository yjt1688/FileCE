# -*- coding: utf-8 -*-
# 截取工具栏条带保存为 PNG（供人工查看"查看方式"下拉按钮的效果）。
# 布局正确性由 tests/toolbar_unittest.c 保证，这里只负责出图。
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")
EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbar.png")

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.PrintWindow.argtypes = [w.HWND, w.HDC, ctypes.c_uint]; u.PrintWindow.restype = ctypes.c_bool
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool
g.GetDeviceCaps.argtypes = [w.HDC, ctypes.c_int]

# ---- 写 PNG（纯 zlib/struct，不依赖 PIL）----
# 注意：GetDIBits 取到的是 BGRA，写 PNG 前必须换回 RGBA，
# 否则图上红蓝通道互换（浅蓝高亮会显示成橙色），看图会误判配色。
import zlib, struct
def write_png(path, width, height, bgra):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rgba = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        rgba[i] = bgra[i + 2]; rgba[i + 1] = bgra[i + 1]; rgba[i + 2] = bgra[i]; rgba[i + 3] = bgra[i + 3]
    rgba = bytes(rgba)
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f: f.write(png)

found = []
@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, l):
    if not u.IsWindowVisible(h): return True
    buf = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, buf, 96)
    if buf.value == "FFMainWnd": found.append(h)
    return True

p = subprocess.Popen([EXE])
t0 = time.time()
while not found and time.time() - t0 < 15:
    u.EnumWindows(cb, 0); time.sleep(0.1)
if not found:
    print("FAIL: 未找到主窗口"); sys.exit(1)
time.sleep(1.2)
main = found[0]
# 先导航一次（CMD_UP=20003），好让截图里同时有"启用的绿圆"和"禁用的灰圆"
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW(main, 0x0111, 20003, 0)
time.sleep(0.8)
tb = u.FindWindowExW(main, None, "FFToolBar", None)
if not tb: print("FAIL: 未找到工具栏"); p.kill(); sys.exit(1)

rc = w.RECT(); u.GetWindowRect(tb, ctypes.byref(rc))
W, H = rc.right - rc.left, rc.bottom - rc.top
dc0 = u.GetDC(0); mem = g.CreateCompatibleDC(dc0)
bmp = g.CreateCompatibleBitmap(dc0, W, H); g.SelectObject(mem, bmp)
ok = u.PrintWindow(tb, mem, 2)

class BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]
bi = BMIH(); bi.biSize = ctypes.sizeof(BMIH); bi.biWidth = W; bi.biHeight = -H
bi.biPlanes = 1; bi.biBitCount = 32; bi.biCompression = 0
px = (ctypes.c_ubyte * (W * H * 4))()
g.GetDIBits(mem, bmp, 0, H, px, ctypes.byref(bi), 0)
write_png(OUT, W, H, bytes(px))

print("PrintWindow=%s  %dx%d  ->  %s" % (ok, W, H, OUT))
# 收尾务必确保进程真的退出：否则下次 make 链接 exe 会 Permission denied
p.terminate()
for _ in range(30):
    if p.poll() is not None:
        break
    time.sleep(0.1)
if p.poll() is None:
    subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    time.sleep(0.5)
