# -*- coding: utf-8 -*-
"""在主窗口内部做 z 序命中测试（ChildWindowFromPointEx，不受外层窗口遮挡影响），
判断点击地址栏时实际命中的子窗口是谁。
若命中 FFToolBar 而非地址栏 ComboBox/Edit -> 点击永远到不了地址栏（无法输入的根因）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os
u=ctypes.WinDLL("user32")
EXE=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","build","FileCE.exe"))
u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.FindWindowExW.argtypes=[w.HWND,w.HWND,w.LPCWSTR,w.LPCWSTR]; u.FindWindowExW.restype=w.HWND
u.SendMessageW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]; u.SendMessageW.restype=ctypes.c_ssize_t
u.ScreenToClient.argtypes=[w.HWND,ctypes.POINTER(w.POINT)]
u.ChildWindowFromPointEx.argtypes=[w.HWND,w.POINT,ctypes.c_uint]; u.ChildWindowFromPointEx.restype=w.HWND
u.GetParent.argtypes=[w.HWND]; u.GetParent.restype=w.HWND
CWP_ALL=0x0000
WM_GETTEXT=0x000D; WM_GETTEXTLENGTH=0x000E

def wtext(h):
    if not h: return ""
    n=u.SendMessageW(h,WM_GETTEXTLENGTH,0,0)
    b=ctypes.create_unicode_buffer(n+2); u.SendMessageW(h,WM_GETTEXT,n+1,ctypes.addressof(b)); return b.value
def cls(h):
    if not h: return "?"
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96); return b.value

found=[]; PID=w.DWORD(0)
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def cb(h,l):
    if not u.IsWindowVisible(h): return True
    pid=w.DWORD(0); u.GetWindowThreadProcessId(h,ctypes.byref(pid))
    if pid.value!=PID.value: return True
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    if b.value=="FFMainWnd": found.append(h)
    return True
p=subprocess.Popen([EXE, r"E:\临时"]); PID.value=p.pid
t0=time.time()
while not found and time.time()-t0<10:
    u.EnumWindows(cb,0); time.sleep(0.1)
time.sleep(1.5)
main=found[0]
kids={}
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def kcb(h,l):
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    kids.setdefault(b.value,[]).append(h); return True
u.EnumChildWindows(main,kcb,0)
addr=None
for c in kids.get("ComboBox",[]):
    if ":" in wtext(c) or wtext(c)=="计算机": addr=c; break
aedit=u.FindWindowExW(addr,None,"Edit",None)
tb=kids.get("FFToolBar",[None])[0]
print("main=%s addr=%s aedit=%s toolbar=%s" % (hex(main),hex(addr),hex(aedit),hex(tb) if tb else "?"),flush=True)

for name,h in (("地址栏ComboBox",addr),("工具栏FFToolBar",tb),("标签栏FFTabBar",kids.get("FFTabBar",[None])[0])):
    if not h: continue
    r=w.RECT(); u.GetWindowRect(h,ctypes.byref(r))
    print("%-16s 屏幕矩形=(%d,%d,%d,%d)" % (name,r.left,r.top,r.right,r.bottom),flush=True)

rc=w.RECT(); u.GetWindowRect(addr,ctypes.byref(rc))
print("--- 主窗口内 z 序命中测试（地址栏区域）---")
for frac in (0.2,0.4,0.6,0.8):
    sx=int(rc.left+(rc.right-rc.left)*frac); sy=(rc.top+rc.bottom)//2
    pt=w.POINT(sx,sy); u.ScreenToClient(main,ctypes.byref(pt))
    h=u.ChildWindowFromPointEx(main, pt, CWP_ALL)
    ok = (h==addr or h==aedit)
    print("  屏幕点(%d,%d)->客户(%d,%d) 命中=%s cls=%r %s" %
          (sx,sy,pt.x,pt.y, hex(h) if h else "NULL", cls(h), "OK" if ok else "!!! 不是地址栏"), flush=True)

# 反向检查：工具栏条（上面那条 FFToolBar）的 8 个按钮必须都能命中它自己，
# 不能被上面/下面的兄弟窗口挡住。按钮从左往右排，宽度由条带实测反推。
bars=kids.get("FFToolBar",[])
def rect_of(h):
    r=w.RECT(); u.GetWindowRect(h,ctypes.byref(r)); return r
bars=sorted(bars, key=lambda h: rect_of(h).top)
toolbar=bars[0] if bars else tb          # 上面那条 = 工具栏条
tr=w.RECT(); u.GetWindowRect(toolbar,ctypes.byref(tr))
print("--- 命中测试（工具栏条按钮，应命中 FFToolBar）---")
print("  工具栏条矩形=(%d,%d,%d,%d)" % (tr.left,tr.top,tr.right,tr.bottom), flush=True)
# 按钮尺寸：现在地址栏输入框就紧贴在按钮段右侧，
# 因此用「地址框 left - 条带 left - 6（左右各 2/4px 内边距）」反推按钮宽度，
# 不要再拿条带整宽去除（条带窗口是全宽的，那样算出的宽是错的）。
bar_left = tr.left + 2
seg = max(8, (rc.left - bar_left - 4)) if addr else 240
bsz = max(8, seg // 8)
bad=0
for n in range(8):
    sx=bar_left+int((n+0.5)*bsz); sy=(tr.top+tr.bottom)//2
    pt=w.POINT(sx,sy); u.ScreenToClient(main,ctypes.byref(pt))
    h=u.ChildWindowFromPointEx(main, pt, CWP_ALL)
    okc = (h==toolbar)
    if not okc: bad+=1
    print("  按钮%d 屏幕点(%d,%d) 命中=%s cls=%r %s" %
          (n,sx,sy,hex(h) if h else "NULL", cls(h), "OK" if okc else "!!! 按钮被挡住"), flush=True)
print("工具栏按钮被挡数量=%d %s" % (bad, "OK" if bad==0 else "FAIL"), flush=True)

p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
