# -*- coding: utf-8 -*-
"""列表渲染验证：截取 SysListView32 客户区，统计正文区深色像素与有文字的行数。
阈值：有文字的行数 > 10 判为渲染正常。用法: python tests/listrender_probe.py [目录]"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys, os
u = ctypes.WinDLL("user32"); g = ctypes.WinDLL("gdi32")
HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "..", "build", "FileCE.exe")
TARGET = sys.argv[1] if len(sys.argv) > 1 else r"C:/Windows"
u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.PrintWindow.argtypes=[w.HWND,w.HDC,ctypes.c_uint]; u.PrintWindow.restype=ctypes.c_bool
u.GetDC.argtypes=[w.HWND]; u.GetDC.restype=w.HDC
g.CreateCompatibleDC.argtypes=[w.HDC]; g.CreateCompatibleDC.restype=w.HDC
g.CreateCompatibleBitmap.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int]; g.CreateCompatibleBitmap.restype=w.HBITMAP
g.SelectObject.argtypes=[w.HDC,w.HGDIOBJ]; g.SelectObject.restype=w.HGDIOBJ
g.GetDIBits.argtypes=[w.HDC,w.HBITMAP,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
found=[]
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def cb(h,l):
    if not u.IsWindowVisible(h): return True
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    if b.value=="FFMainWnd": found.append(h)
    return True
kids=[]
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def kcb(h,l):
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    kids.append((b.value,h)); return True
p=subprocess.Popen([EXE, TARGET])
t0=time.time()
while not found and time.time()-t0<10:
    u.EnumWindows(cb,0); time.sleep(0.1)
if not found: print("FAIL: 窗口未出现"); sys.exit(1)
time.sleep(2.0)
u.EnumChildWindows(found[0],kcb,0)
lv=[h for c,h in kids if c=="SysListView32"]
if not lv: print("FAIL: 无列表"); p.kill(); sys.exit(1)
lv=lv[0]
rc=w.RECT(); u.GetClientRect(lv,ctypes.byref(rc))
W,H=rc.right-rc.left, rc.bottom-rc.top
dc0=u.GetDC(0); mem=g.CreateCompatibleDC(dc0)
bmp=g.CreateCompatibleBitmap(dc0,W,H); g.SelectObject(mem,bmp)
u.PrintWindow(lv,mem,2)
class BMIH(ctypes.Structure):
    _fields_=[("biSize",ctypes.c_uint32),("biWidth",ctypes.c_int32),("biHeight",ctypes.c_int32),
              ("biPlanes",ctypes.c_uint16),("biBitCount",ctypes.c_uint16),("biCompression",ctypes.c_uint32),
              ("biSizeImage",ctypes.c_uint32),("biXPelsPerMeter",ctypes.c_int32),
              ("biYPelsPerMeter",ctypes.c_int32),("biClrUsed",ctypes.c_uint32),("biClrImportant",ctypes.c_uint32)]
bi=BMIH(); bi.biSize=ctypes.sizeof(BMIH); bi.biWidth=W; bi.biHeight=-H
bi.biPlanes=1; bi.biBitCount=32; bi.biCompression=0
px=(ctypes.c_ubyte*(W*H*4))()
g.GetDIBits(mem,bmp,0,H,px,ctypes.byref(bi),0)
def get(x,y):
    o=(y*W+x)*4
    return px[o+2],px[o+1],px[o]
header_h=28; rows=0
for y in range(header_h,H):
    d=0
    for x in range(0,min(W,420)):
        r,gg,b=get(x,y)
        if r<140 and gg<140 and b<140: d+=1
    if d>3: rows+=1
print("有文字的行数=%d" % rows)
p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()
ok = rows > 10
print("PASS: 列表渲染正常" if ok else "FAIL: 列表正文空白（复现了用户的 bug）")
sys.exit(0 if ok else 1)
