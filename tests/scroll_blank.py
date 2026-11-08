# -*- coding: utf-8 -*-
"""复现:大目录滚动到底后导航到小目录 => 报告视图空白?
流科: 启动 C:\\Windows -> LVM_SCROLL 滚到底 -> 地址栏 VK_RETURN 去 C:\\Users -> 像素验证
"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys
u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32")
EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
u.SendMessageW.restype=ctypes.c_ssize_t
u.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
u.PrintWindow.argtypes=[w.HWND,w.HDC,ctypes.c_uint]; u.PrintWindow.restype=ctypes.c_bool
u.GetDC.argtypes=[w.HWND]; u.GetDC.restype=w.HDC
g = ctypes.WinDLL("gdi32")
g.CreateCompatibleDC.argtypes=[w.HDC]; g.CreateCompatibleDC.restype=w.HDC
g.CreateCompatibleBitmap.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int]; g.CreateCompatibleBitmap.restype=w.HBITMAP
g.SelectObject.argtypes=[w.HDC,w.HGDIOBJ]; g.SelectObject.restype=w.HGDIOBJ
g.GetDIBits.argtypes=[w.HDC,w.HBITMAP,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]

LVM_GETITEMCOUNT=0x1004
LVM_SCROLL=0x1014
LVM_GETTOPINDEX=0x1027
LVM_GETCOUNTPERPAGE=0x1028
LVM_GETITEMSPACING=0x1011
WM_SETTEXT=0x000C
WM_KEYDOWN=0x0100
WM_KEYUP=0x0101
VK_RETURN=0x0D

found=[]
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def cb(h,l):
    if not u.IsWindowVisible(h): return True
    pid=w.DWORD(0)
    u.GetWindowThreadProcessId(h,ctypes.byref(pid))
    if pid.value!=TARGET_PID.value: return True
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    if b.value=="FFMainWnd": found.append(h)
    return True

def title(h):
    t=ctypes.create_unicode_buffer(256); u.GetWindowTextW(h,t,256); return t.value
class BMIH(ctypes.Structure):
    _fields_=[("biSize",ctypes.c_uint32),("biWidth",ctypes.c_int32),("biHeight",ctypes.c_int32),
              ("biPlanes",ctypes.c_uint16),("biBitCount",ctypes.c_uint16),("biCompression",ctypes.c_uint32),
              ("biSizeImage",ctypes.c_uint32),("biXPelsPerMeter",ctypes.c_int32),
              ("biYPelsPerMeter",ctypes.c_int32),("biClrUsed",ctypes.c_uint32),("biClrImportant",ctypes.c_uint32)]
def pixel_rows(lv, y0=28):
    rc=w.RECT(); u.GetClientRect(lv,ctypes.byref(rc))
    W,H=rc.right-rc.left, rc.bottom-rc.top
    dc0=u.GetDC(0); mem=g.CreateCompatibleDC(dc0)
    bmp=g.CreateCompatibleBitmap(dc0,W,H); g.SelectObject(mem,bmp)
    u.PrintWindow(lv,mem,2)
    bi=BMIH(); bi.biSize=ctypes.sizeof(BMIH); bi.biWidth=W; bi.biHeight=-H
    bi.biPlanes=1; bi.biBitCount=32
    px=(ctypes.c_ubyte*(W*H*4))()
    g.GetDIBits(mem,bmp,0,H,px,ctypes.byref(bi),0)
    rows=[]
    for y in range(y0,H):
        d=0
        for x in range(0,min(W,420)):
            o=(y*W+x)*4
            if px[o+2]<140 and px[o+1]<140 and px[o]<140: d+=1
        if d>3: rows.append(y)
    return rows

p=subprocess.Popen([EXE, r"C:\Windows"])
TARGET_PID=w.DWORD(p.pid)
u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
t0=time.time()
while not found and time.time()-t0<10:
    u.EnumWindows(cb,0); time.sleep(0.1)
time.sleep(1.5)
main=found[0]
kids=[]
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def kcb(h,l):
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    kids.append((b.value,h)); return True
u.EnumChildWindows(main,kcb,0)
lv=[h for c,h in kids if c=="SysListView32"][0]
addr=[h for c,h in kids if c=="Edit"][0]

cnt=u.SendMessageW(lv,LVM_GETITEMCOUNT,0,0)
print("C:\\Windows count=%d" % cnt, flush=True)
print("行距=0x%X" % u.SendMessageW(lv,LVM_GETITEMSPACING,0,0), flush=True)

# 滚到底
u.SendMessageW(lv,LVM_SCROLL,0,200000)
time.sleep(0.3)
top=u.SendMessageW(lv,LVM_GETTOPINDEX,0,0)
print("滚动后 top=%d count=%d" % (top,cnt), flush=True)
rows0=pixel_rows(lv)
print("滚动后可见暗行数=%d (应>3)" % len(rows0), flush=True)

# 地址栏导航到 C:\Users
buf=ctypes.create_unicode_buffer("C:\\Users")
u.SendMessageW(addr,WM_SETTEXT,0,ctypes.addressof(buf))
time.sleep(0.2)
u.SendMessageW(addr,WM_KEYDOWN,VK_RETURN,0)
u.SendMessageW(addr,WM_KEYUP,VK_RETURN,0)
time.sleep(1.0)
cnt2=u.SendMessageW(lv,LVM_GETITEMCOUNT,0,0)
top2=u.SendMessageW(lv,LVM_GETTOPINDEX,0,0)
print("导航后 标题=%r" % title(main)[:40], flush=True)
print("导航后 count=%d top=%d (count应为6)" % (cnt2,top2), flush=True)
rows1=pixel_rows(lv)
print("导航后可见暗行数=%d (应>3, 0=白屏!)" % len(rows1), flush=True)
print("暗行y:", rows1[:20], flush=True)

ok = (cnt2==6) and len(rows1)>=3
print("RESULT:", "PASS" if ok else "FAIL: 复现白屏")
p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
