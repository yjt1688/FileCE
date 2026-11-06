# -*- coding: utf-8 -*-
# 开 4 个标签后截取标签栏左半段，放大输出 PNG —— 供人工审看
# 「标签之间的竖直分隔线」和「+ 新建按钮」的大小/粗细。
#   python tests/tabbar_shot.py [放大倍率] [裁剪宽度] [选中第几个标签，默认 3=最后一个] [裁剪起点X，默认 0]
#   例：裁最右侧的「+」按钮 -> python tests/tabbar_shot.py 8 80 3 440
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(os.path.dirname(HERE), "build", "FileCE.exe")
OUT = os.path.join(HERE, "tabbar_zoom.png")

SCALE = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CROPW = int(sys.argv[2]) if len(sys.argv) > 2 else 480
SEL   = int(sys.argv[3]) if len(sys.argv) > 3 else 3
CROPX = int(sys.argv[4]) if len(sys.argv) > 4 else 0
WM_COMMAND = 0x0111
CMD_TAB_NEW = 20040
WM_FF_TAB_SEL = 0x8000 + 21

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]
u.FindWindowExW.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.PrintWindow.argtypes = [w.HWND, w.HDC, ctypes.c_uint]; u.PrintWindow.restype = ctypes.c_bool
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool

import zlib, struct
def write_png(path, width, height, bgra):
    """GetDIBits 给的是 BGRA，写 PNG 前必须换回 RGBA，否则红蓝互换。"""
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
time.sleep(1.0)
main = found[0]
u.SetWindowPos(main, 0, 40, 40, 1000, 700, 0x0004)
time.sleep(0.5)

# 再开 3 个标签 -> 共 4 个（用户就是从 4 个标签看出"分不清"的）
for _ in range(3):
    u.SendMessageW(main, WM_COMMAND, CMD_TAB_NEW, 0)
    time.sleep(0.2)
time.sleep(0.6)

tabs = []
@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def child_cb(h, l):
    buf = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, buf, 96)
    if buf.value == "FFTabBar": tabs.append(h)
    return True
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows(main, child_cb, 0)
if not tabs:
    print("FAIL: 未找到标签栏"); p.kill(); sys.exit(1)
tb = tabs[0]

# 切到指定标签，验证分隔线会跟着活动标签挪位置（活动标签两侧不画线）
if SEL >= 0:
    u.SendMessageW(main, WM_FF_TAB_SEL, SEL, 0)
    time.sleep(0.5)

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
src = bytes(px)
u.ReleaseDC(0, dc0); g.DeleteObject(bmp); g.DeleteDC(mem)

# 裁剪指定横段 + 最近邻放大（放大看像素级细节）；CROPX 用来对准最右侧的「+」
x0 = max(0, min(CROPX, W - 1))
cw = min(CROPW, W - x0)
out = bytearray()
for y in range(H):
    for _ in range(SCALE):
        line = src[y * W * 4 + x0 * 4:(y + 1) * W * 4]
        row = line[:cw * 4]
        row = b"".join(row[i * 4:i * 4 + 4] * SCALE for i in range(cw))
        out += row
write_png(OUT, cw * SCALE, H * SCALE, bytes(out))

print("PrintWindow=%s  标签栏 %dx%d  裁剪 x=%d 宽 %d x%d  ->  %s" % (ok, W, H, x0, cw, SCALE, OUT))

p.terminate()
for _ in range(30):
    if p.poll() is not None: break
    time.sleep(0.1)
if p.poll() is None:
    subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    time.sleep(0.5)
