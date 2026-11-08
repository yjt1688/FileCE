# -*- coding: utf-8 -*-
"""新建标签按钮「+」的完整性探针。

这个加号反复出过问题：用两根 2px 宽的 GDI 直线画时，LineTo 不含终点、
必须对端点做 +1 补偿，横竖两条的补偿方向一错位，十字就整体偏一格
（横臂相对竖臂偏上偏右各 1px），看起来就像"没画全"。
所以这里按像素验收，而不是靠肉眼：

  ① 取下标签栏最右侧那段深色像素（就是「+」，左边那段是活动标签的「×」）
  ② 横臂、竖臂都要存在，且长度接近（差 ≤ 2px）
  ③ 横竖严格同心：两臂中心偏差 ≤ 1px（2px 偶数线宽不可能做到 0）
  ④ 不贴边：上下左右余量 ≥ 3px
  ⑤ 尺寸落在 7~14px（太小看不清、太大会顶到边界）

用法：python tests/tabbar_plus_probe.py
"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os

u = ctypes.WinDLL("user32")
g = ctypes.WinDLL("gdi32")
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(os.path.dirname(HERE), "build", "FileCE.exe")

WM_COMMAND = 0x0111
CMD_TAB_NEW = 20040
DARK = 110          # 判定"深色像素"的阈值
TAB_H = 30          # 标签栏逻辑高度，用来估算底边线位置

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.FindWindowExW.argtypes = [w.HWND, w.HWND, w.LPCWSTR, w.LPCWSTR]; u.FindWindowExW.restype = w.HWND
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u.PrintWindow.argtypes = [w.HWND, w.HDC, ctypes.c_uint]; u.PrintWindow.restype = ctypes.c_bool
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint,
                        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool

fails = []
def check(ok, msg):
    print(("  [ OK ] " if ok else "  [FAIL] ") + msg, flush=True)
    if not ok: fails.append(msg)


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
time.sleep(0.4)
for _ in range(3):                       # 共 4 个标签，和用户的实际场景一致
    u.SendMessageW(main, WM_COMMAND, CMD_TAB_NEW, 0); time.sleep(0.2)
time.sleep(0.6)

tb = u.FindWindowExW(main, None, "FFTabBar", None)
if not tb: print("FAIL: 未找到标签栏"); p.kill(); sys.exit(1)

rc = w.RECT(); u.GetWindowRect(tb, ctypes.byref(rc))
W, H = rc.right - rc.left, rc.bottom - rc.top
dc0 = u.GetDC(0); mem = g.CreateCompatibleDC(dc0)
bmp = g.CreateCompatibleBitmap(dc0, W, H); g.SelectObject(mem, bmp)
u.PrintWindow(tb, mem, 2)

class BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]
bi = BMIH(); bi.biSize = ctypes.sizeof(BMIH); bi.biWidth = W; bi.biHeight = -H
bi.biPlanes = 1; bi.biBitCount = 32; bi.biCompression = 0
buf = (ctypes.c_ubyte * (W * H * 4))()
g.GetDIBits(mem, bmp, 0, H, buf, ctypes.byref(bi), 0)
px = buf

def dark(x, y):
    o = (y * W + x) * 4
    return px[o] < DARK and px[o + 1] < DARK and px[o + 2] < DARK

print("标签栏 %dx%d" % (W, H), flush=True)

# ① 最右侧的深色列段 = 加号
cols = [x for x in range(W) if any(dark(x, y) for y in range(H))]
if not cols:
    print("FAIL: 标签栏上没有任何深色像素"); p.kill(); sys.exit(1)
segs = []; s = prev = cols[0]
for c in cols[1:]:
    if c - prev > 6: segs.append((s, prev)); s = c
    prev = c
segs.append((s, prev))
x0, x1 = segs[-1]
print("深色列段: %r  → 取最右段 (%d..%d) 当加号" % (segs, x0, x1), flush=True)

xs = [x for x in range(x0, x1 + 1) if any(dark(x, y) for y in range(H))]
ys = [y for y in range(H) if any(dark(x, y) for x in range(x0, x1 + 1))]
bw, bh = xs[-1] - xs[0] + 1, ys[-1] - ys[0] + 1
cx, cy = (xs[0] + xs[-1]) / 2.0, (ys[0] + ys[-1]) / 2.0

# ② 两臂长度：过中心的横排 / 竖列
mid_row = int(round(cy))
mid_col = int(round(cx))
arm_h = sum(1 for x in range(x0, x1 + 1) if dark(x, mid_row))      # 横臂长
col_dark = [y for y in range(H) if dark(mid_col, y)]
arm_v = (col_dark[-1] - col_dark[0] + 1) if col_dark else 0        # 竖臂长
# 横臂（较长的那一维）与竖臂都必须在
check(bw >= 5 and bh >= 5, "十字尺寸 %dx%d ≥ 5x5" % (bw, bh))
check(abs(bw - bh) <= 2, "横竖两臂长度接近：宽 %d / 高 %d（差 %d ≤ 2）" % (bw, bh, abs(bw - bh)))
check(arm_h >= 5 and arm_v >= 5, "横臂 %dpx / 竖臂 %dpx 都画出来了" % (arm_h, arm_v))

# ③ 同心：竖臂中心 vs 横臂中心、横臂行中心 vs 竖臂列中心
row_dark = [x for x in range(x0, x1 + 1) if dark(x, mid_row)]
vcol = [x for x in range(x0, x1 + 1) if all(dark(x, y) for y in range(col_dark[0], col_dark[-1] + 1))] \
       if col_dark else []
dx = abs((row_dark[0] + row_dark[-1]) / 2.0 - (vcol[0] + vcol[-1]) / 2.0) if vcol else 99
check(dx <= 1.0, "横竖同心：横臂中心与竖臂中心偏差 %.1fpx ≤ 1" % dx)

# ④ 不贴边（底边线占最后 1px）
check(ys[0] >= 3, "上边距 %dpx ≥ 3" % ys[0])
check(H - 1 - ys[-1] >= 3, "下边距 %dpx ≥ 3（未压到标签栏底边线）" % (H - 1 - ys[-1]))
check(xs[0] >= 3, "左边距 %dpx ≥ 3" % xs[0])
check(W - xs[-1] >= 3, "右边距 %dpx ≥ 3" % (W - xs[-1]))

# ⑤ 尺寸合理
check(7 <= bw <= 14 and 7 <= bh <= 14, "十字尺寸 %dx%d 落在 7~14" % (bw, bh))

# ⑥ 居中与对称（用户反馈"左边和上边差一点"就是这里出问题）
check(abs(cy - H / 2.0) <= 1.0,
      "垂直居中：十字中心 y=%.1f，客户区中心 %.1f（差 ≤1）" % (cy, H / 2.0))
up = sum(1 for y in range(ys[0], mid_row) if dark(mid_col, y))
dn = sum(1 for y in range(mid_row + 1, ys[-1] + 1) if dark(mid_col, y))
check(abs(up - dn) <= 1, "竖臂上下对称：中心行以上 %dpx / 以下 %dpx" % (up, dn))
lf = sum(1 for x in range(xs[0], mid_col) if dark(x, mid_row))
rt = sum(1 for x in range(mid_col + 1, xs[-1] + 1) if dark(x, mid_row))
check(abs(lf - rt) <= 1, "横臂左右对称：中心列以左 %dpx / 以右 %dpx" % (lf, rt))

print("   十字 bbox: x %d..%d  y %d..%d  (中心 %.1f, %.1f)"
      % (xs[0], xs[-1], ys[0], ys[-1], cx, cy), flush=True)

p.terminate()
for _ in range(30):
    if p.poll() is not None: break
    time.sleep(0.1)
if p.poll() is None:
    subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
    time.sleep(0.5)

print("RESULT: %s" % ("PASS" if not fails else "FAIL -> " + "; ".join(fails)), flush=True)
sys.exit(1 if fails else 0)
