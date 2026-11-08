"""截取标签栏并统计各标签关闭按钮区域的深色像素（验证 × 的显隐逻辑）"""
import subprocess, time, ctypes, ctypes.wintypes as w, struct, zlib, sys

u = ctypes.WinDLL('user32')
g = ctypes.WinDLL('gdi32')
EXE = r'C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe'
WM_COMMAND = 0x0111
CMD_TAB_NEW = 20040

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
g.DeleteObject.argtypes = [w.HGDIOBJ]
g.DeleteDC.argtypes = [w.HDC]

HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)


class BIH(ctypes.Structure):
    _fields_ = [('biSize', w.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
                ('biPlanes', w.WORD), ('biBitCount', w.WORD), ('biCompression', w.DWORD),
                ('biSizeImage', w.DWORD), ('biXPelsPerMeter', ctypes.c_long),
                ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', w.DWORD),
                ('biClrImportant', w.DWORD)]


def find(cls):
    out = []
    u.EnumWindows(HWNDCB(lambda h, l: (out.append(h)
                                       if (lambda c: (u.GetClassNameW(h, c, 96), c.value == cls)[1])
                                       (ctypes.create_unicode_buffer(96)) and u.IsWindowVisible(h)
                                       else None) or True, 0))
    return out


found = []
def enum_cb(h, l):
    c = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, c, 96)
    if c.value == 'FFMainWnd' and u.IsWindowVisible(h):
        found.append(h)
    return True
CB = HWNDCB(enum_cb)


def grab(rect, path):
    x0, y0, x1, y1 = rect
    sw, sh = x1 - x0, y1 - y0
    hdc = u.GetDC(0)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, sw, sh)
    old = g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, sw, sh, hdc, x0, y0, 0x00CC0020)
    bi = BIH(); bi.biSize = ctypes.sizeof(bi); bi.biWidth = sw; bi.biHeight = -sh
    bi.biPlanes = 1; bi.biBitCount = 32
    buf = ctypes.create_string_buffer(sw * sh * 4)
    g.GetDIBits(mem, bmp, 0, sh, buf, ctypes.byref(bi), 0)
    g.SelectObject(mem, old); g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, hdc)
    px = buf.raw

    # 保存 PNG
    raw = bytearray()
    for y in range(sh):
        row = px[y * sw * 4:(y + 1) * sw * 4]
        line = bytearray(b'\x00')
        for x in range(sw):
            b, gg, r_ = row[x * 4], row[x * 4 + 1], row[x * 4 + 2]
            line += bytes((r_, gg, b))
        raw += line
    def ch(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    open(path, 'wb').write(
        b'\x89PNG\r\n\x1a\n'
        + ch(b'IHDR', struct.pack('>IIBBBBB', sw, sh, 8, 2, 0, 0, 0))
        + ch(b'IDAT', zlib.compress(bytes(raw), 6)) + ch(b'IEND', b''))
    return px, sw, sh


p = subprocess.Popen([EXE])
t0 = time.time()
while not found and time.time() - t0 < 15:
    found.clear()
    u.EnumWindows(CB, 0)
    time.sleep(0.1)
hwnd = found[0]
u.SetWindowPos(hwnd, 0, 40, 40, 1000, 700, 0x0005)
time.sleep(0.8)

# 建两个新标签 -> 共 3 个
for _ in range(2):
    u.SendMessageW(hwnd, WM_COMMAND, CMD_TAB_NEW, 0)
    time.sleep(0.15)

tabs = []
def tab_cb(c, l):
    cn = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(c, cn, 96)
    if cn.value == 'FFTabBar':
        tabs.append(c)
    return True
u.EnumChildWindows(hwnd, HWNDCB(tab_cb), 0)
tb = tabs[0]
r = w.RECT(); u.GetWindowRect(tb, ctypes.byref(r))

rect = (r.left, r.top, r.right, r.bottom)
px, sw, sh = grab(rect, 'tabbar.png')
print('标签栏区域: %dx%d, 已保存 tabbar.png' % (sw, sh))

# ASCII 像素图（每字符 = 8x3 像素块）——用文字直接"看"标签栏
print('ASCII 像素图 (#=深色, .=浅色), 每字符=8x3px:')
for by in range(0, sh, 3):
    line = ''
    for bx in range(0, sw, 8):
        dark = False
        for y in range(by, min(by + 3, sh)):
            for x in range(bx, min(bx + 8, sw)):
                o = (y * sw + x) * 4
                if px[o + 2] < 150 and px[o + 1] < 150 and px[o] < 150:
                    dark = True
                    break
            if dark: break
        line += '#' if dark else '.'
    print('  ' + line)

p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()
