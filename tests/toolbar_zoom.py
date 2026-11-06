# -*- coding: utf-8 -*-
# 抓工具栏条带，裁剪左侧按钮区并放大 N 倍，便于人工审看图标细节。
# 用法: python tests/toolbar_zoom.py [放大倍数] [裁剪宽度]
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os, zlib, struct

u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolbar_zoom.png")
SCALE = int(sys.argv[1]) if len(sys.argv) > 1 else 5
CROPW = int(sys.argv[2]) if len(sys.argv) > 2 else 260

u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]; u.FindWindowExW.restype = w.HWND
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.PrintWindow.argtypes = [w.HWND, w.HDC, ctypes.c_uint]; u.PrintWindow.restype = ctypes.c_bool
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]


def write_png(path, width, height, bgra):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rgba = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        rgba[i] = bgra[i + 2]; rgba[i + 1] = bgra[i + 1]; rgba[i + 2] = bgra[i]; rgba[i + 3] = bgra[i + 3]
    rgba = bytes(rgba)
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


found = []
@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, l):
    if not u.IsWindowVisible(h):
        return True
    buf = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, buf, 96)
    if buf.value == "FFMainWnd":
        found.append(h)
    return True


p = subprocess.Popen([EXE, r"E:\临时"])
t0 = time.time()
while not found and time.time() - t0 < 15:
    u.EnumWindows(cb, 0); time.sleep(0.1)
if not found:
    print("FAIL: 未找到主窗口"); sys.exit(1)
time.sleep(1.2)
main = found[0]

# 先做一次"上级目录"导航（WM_COMMAND / CMD_UP=20003），
# 这样"后退"变成可用态（绿色圆底）、"前进"仍是禁用态（灰色圆底）——
# 一张图里同时能看到启用/禁用两种圆，正是参考图前两个按钮的样子。
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW(main, 0x0111, 20003, 0)
time.sleep(0.8)

tb = u.FindWindowExW(main, None, "FFToolBar", None)
if not tb:
    print("FAIL: 未找到工具栏"); p.kill(); sys.exit(1)

rc = w.RECT(); u.GetWindowRect(tb, ctypes.byref(rc))
W, H = rc.right - rc.left, rc.bottom - rc.top
dc0 = u.GetDC(0); mem = g.CreateCompatibleDC(dc0)
bmp = g.CreateCompatibleBitmap(dc0, W, H); g.SelectObject(mem, bmp)
u.PrintWindow(tb, mem, 2)


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]


bi = BMIH(); bi.biSize = ctypes.sizeof(BMIH); bi.biWidth = W; bi.biHeight = -H
bi.biPlanes = 1; bi.biBitCount = 32; bi.biCompression = 0
src = (ctypes.c_ubyte * (W * H * 4))()
g.GetDIBits(mem, bmp, 0, H, src, ctypes.byref(bi), 0)
b = bytes(src)
cw = min(CROPW, W)
ow, oh = cw * SCALE, H * SCALE
out = bytearray(ow * oh * 4)
for y in range(oh):
    sy = y // SCALE
    for x in range(ow):
        sx = x // SCALE
        i = (sy * W + sx) * 4
        j = (y * ow + x) * 4
        out[j:j + 4] = b[i:i + 4]
write_png(OUT, ow, oh, bytes(out))
print("crop %dx%d  scale x%d  ->  %s" % (cw, H, SCALE, OUT))
# 收尾务必确保进程真的退出：否则下次 make 链接 exe 会 Permission denied
p.terminate()
for _ in range(30):
    if p.poll() is not None:
        break
    time.sleep(0.1)
if p.poll() is None:
    subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    time.sleep(0.5)
