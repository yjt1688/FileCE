# -*- coding: utf-8 -*-
"""列表图标出图 + 回归：抓 SysListView32 客户区，裁左侧图标列放大存 PNG，
并按像素校验「图标长在文件里」的类型（.exe/.ico/.lnk…）不再共用同一个通用图标。

用法: python tests/list_icon_shot.py [目录] [放大倍率] [裁剪宽]
默认目录 D:\\tools\\自用程序（4 个自带图标的 exe + 1 个 rar + 2 个 ini）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os, zlib, struct

u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
OUT = os.path.join(HERE, "list_icon.png")
TARGET = sys.argv[1] if len(sys.argv) > 1 else "D:\\tools\\自用程序"
SCALE = int(sys.argv[2]) if len(sys.argv) > 2 else 2
CROPW = int(sys.argv[3]) if len(sys.argv) > 3 else 300

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.PrintWindow.argtypes = [w.HWND, w.HDC, ctypes.c_uint]; u.PrintWindow.restype = ctypes.c_bool
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool


def write_png(path, width, height, bgra):
    """GetDIBits 给的是 BGRA，写 PNG 前换回 RGBA（否则红蓝互换）。"""
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rgba = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        rgba[i] = bgra[i + 2]; rgba[i + 1] = bgra[i + 1]
        rgba[i + 2] = bgra[i]; rgba[i + 3] = bgra[i + 3]
    raw = b"".join(b"\x00" + bytes(rgba[y * width * 4:(y + 1) * width * 4]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def find_main(timeout=15.0):
    found = []
    @ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96)
        if b.value == "FFMainWnd":
            found.append(h)
        return True
    t0 = time.time()
    while not found and time.time() - t0 < timeout:
        u.EnumWindows(cb, 0); time.sleep(0.15)
    return found[0] if found else None


p = subprocess.Popen([EXE, TARGET])
main = find_main()
if not main:
    print("FAIL: 未找到主窗口（旧实例没退干净？重跑一次）"); p.kill(); sys.exit(1)
time.sleep(1.5)

kids = []
@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb(h, l):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96)
    kids.append((b.value, h))
    return True
u.EnumChildWindows(main, kcb, 0)
lv = [h for c, h in kids if c == "SysListView32"]
if not lv:
    print("FAIL: 未找到列表"); p.kill(); sys.exit(1)
lv = lv[0]

rc = w.RECT(); u.GetWindowRect(lv, ctypes.byref(rc))
W, H = rc.right - rc.left, rc.bottom - rc.top
dc0 = u.GetDC(0); mem = g.CreateCompatibleDC(dc0)
bmp = g.CreateCompatibleBitmap(dc0, W, H); g.SelectObject(mem, bmp)
ok = u.PrintWindow(lv, mem, 2)


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


def get(x, y):
    o = (y * W + x) * 4
    return px[o + 2], px[o + 1], px[o]      # RGB


cw = min(CROPW, W)
out = bytearray()
for y in range(H):
    row = bytes(px[y * W * 4:(y + 1) * W * 4])[:cw * 4]
    row = b"".join(row[i * 4:i * 4 + 4] * SCALE for i in range(cw))
    for _ in range(SCALE):
        out += row
write_png(OUT, cw * SCALE, H * SCALE, bytes(out))
print("PrintWindow=%s 列表 %dx%d 裁剪 %d 宽 x%d -> %s" % (ok, W, H, cw, SCALE, OUT))

# ---- 回归：图标列每一行的 16x16 图块指纹，看「自带图标」的行是否各不相同 ----
ROW_H = 22          # 报表视图默认行高（96 DPI）
HDR_H = 26          # 表头
ICON_X = 8          # 图标列左上角
def block(y0):
    n = 0
    for y in range(y0, min(y0 + 16, H)):
        for x in range(ICON_X, ICON_X + 16):
            r, gg, b = get(x, y)
            if not (r > 240 and gg > 240 and b > 240):
                n += 1
    return n

rows = []
y = HDR_H
while y + 16 < H:
    rows.append((y, block(y)))
    y += ROW_H
nonEmpty = [b for _, b in rows if b > 3]
print("可见行=%d 其中带图形像素的行=%d" % (len(rows), len(nonEmpty)))
distinct = len(set(nonEmpty))
print("图标图块指纹种类=%d（全用通用应用程序图标时同类型会完全一致）" % distinct)

p.terminate()
for _ in range(30):
    if p.poll() is not None:
        break
    time.sleep(0.1)
if p.poll() is None:
    subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    time.sleep(0.5)
