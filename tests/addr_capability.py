# -*- coding: utf-8 -*-
"""验证地址栏（文件路径）是否满足：可选择 / 可输入 / 可复制 / 可粘贴。
并对"真实鼠标点击地址栏后焦点是否留在编辑框"做可靠判定（GetGUIThreadInfo 前台线程）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u=ctypes.WinDLL("user32"); k=ctypes.WinDLL("kernel32")
EXE=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","build","FileCE.exe"))

u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.FindWindowExW.argtypes=[w.HWND,w.HWND,w.LPCWSTR,w.LPCWSTR]; u.FindWindowExW.restype=w.HWND
u.SendMessageW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]; u.SendMessageW.restype=ctypes.c_ssize_t
u.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
u.SetForegroundWindow.argtypes=[w.HWND]
u.GetForegroundWindow.restype=w.HWND
u.ShowWindow.argtypes=[w.HWND,ctypes.c_int]
u.mouse_event.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
u.GetWindowLongPtrW.argtypes=[w.HWND,ctypes.c_int]; u.GetWindowLongPtrW.restype=ctypes.c_void_p
u.GetGUIThreadInfo.argtypes=[ctypes.c_uint,ctypes.c_void_p]; u.GetGUIThreadInfo.restype=ctypes.c_bool
u.OpenClipboard.argtypes=[w.HWND]; u.OpenClipboard.restype=ctypes.c_bool
u.GetClipboardData.argtypes=[ctypes.c_uint]; u.GetClipboardData.restype=w.HANDLE
u.SetClipboardData.argtypes=[ctypes.c_uint,w.HANDLE]; u.SetClipboardData.restype=w.HANDLE
k.GlobalAlloc.argtypes=[ctypes.c_uint,ctypes.c_size_t]; k.GlobalAlloc.restype=ctypes.c_void_p
k.GlobalLock.argtypes=[ctypes.c_void_p]; k.GlobalLock.restype=ctypes.c_void_p
k.GlobalUnlock.argtypes=[ctypes.c_void_p]; k.GlobalUnlock.restype=ctypes.c_bool

WM_GETTEXT=0x000D; WM_GETTEXTLENGTH=0x000E
WM_COPY=0x0301; WM_PASTE=0x0302; WM_CLEAR=0x0303
EM_SETSEL=0x00B1; EM_GETSEL=0x00B0
GWL_STYLE=-16
ME_LDOWN=0x0002; ME_LUP=0x0004

class GUI(ctypes.Structure):
    _fields_=[("cbSize",ctypes.c_uint),("flags",ctypes.c_uint),("hwndActive",w.HWND),
              ("hwndFocus",w.HWND),("hwndCapture",w.HWND),("hwndMenuOwner",w.HWND),
              ("hwndMoveSize",w.HWND),("hwndCaret",w.HWND),("rcCaret",w.RECT)]

def wtext(h):
    if not h: return ""
    n=u.SendMessageW(h,WM_GETTEXTLENGTH,0,0)
    b=ctypes.create_unicode_buffer(n+2); u.SendMessageW(h,WM_GETTEXT,n+1,ctypes.addressof(b)); return b.value

def focus_now():
    g=GUI(); g.cbSize=ctypes.sizeof(GUI)
    if u.GetGUIThreadInfo(0, ctypes.byref(g)):   # 0 = 前台线程
        return g.hwndFocus
    return None

def bring_front(h):
    """强抢前台：先直接试；失败则用 AttachThreadInput 经典手法。"""
    u.ShowWindow(h,9); time.sleep(0.1)
    for _ in range(10):
        u.SetForegroundWindow(h)
        if u.GetForegroundWindow()==h: return True
        time.sleep(0.12)
    # 经典手法：把自己的输入挂到目标线程，再置前台
    tid=w.DWORD(0); u.GetWindowThreadProcessId(h,ctypes.byref(tid))
    my=k.GetCurrentThreadId()
    u.AttachThreadInput(my,tid.value,True)
    u.BringWindowToTop(h); u.SetForegroundWindow(h); u.SetFocus(h)
    ok=u.GetForegroundWindow()==h
    u.AttachThreadInput(my,tid.value,False)
    if ok: return True
    for _ in range(10):
        u.SetForegroundWindow(h)
        if u.GetForegroundWindow()==h: return True
        time.sleep(0.12)
    return u.GetForegroundWindow()==h

def set_clip_text(s):
    u.OpenClipboard(0); u.EmptyClipboard()
    h=k.GlobalAlloc(0x0042, (len(s)+1)*2)  # GMEM_MOVEABLE
    p=k.GlobalLock(h)
    ctypes.memmove(p, (s+"\0").encode("utf-16-le"), (len(s)+1)*2)
    k.GlobalUnlock(h)
    u.SetClipboardData(13, h); u.CloseClipboard()

def get_clip_text():
    u.OpenClipboard(0)
    h=u.GetClipboardData(13)
    p=k.GlobalLock(h)
    s=ctypes.wstring_at(p) if p else ""
    k.GlobalUnlock(h); u.CloseClipboard()
    return s

found=[]; PID=w.DWORD(0)
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def cb(h,l):
    if not u.IsWindowVisible(h): return True
    pid=w.DWORD(0); u.GetWindowThreadProcessId(h,ctypes.byref(pid))
    if pid.value!=PID.value: return True
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    if b.value=="FFMainWnd": found.append(h)
    return True

TARGET=r"E:\临时"
p=subprocess.Popen([EXE, TARGET]); PID.value=p.pid
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
    t=wtext(c)
    if t and (":" in t or t=="计算机"): addr=c; break
aedit=u.FindWindowExW(addr,None,"Edit",None)
style=u.GetWindowLongPtrW(addr,GWL_STYLE) or 0
print("地址栏=%s Edit=%s style=0x%x" % (hex(addr), hex(aedit) if aedit else "?", style),flush=True)
print("地址栏文本=%r" % wtext(addr),flush=True)

front=bring_front(main)
f0=focus_now()
print("前台=%s 点击前焦点=%s" % (front, hex(f0) if f0 else "NULL"),flush=True)

# 真实鼠标点击地址栏
rc=w.RECT(); u.GetWindowRect(addr,ctypes.byref(rc))
cx=rc.left+40; cy=(rc.top+rc.bottom)//2
u.SetCursorPos(cx,cy); time.sleep(0.12)
u.mouse_event(ME_LDOWN,0,0,0,0); time.sleep(0.06); u.mouse_event(ME_LUP,0,0,0,0); time.sleep(0.4)
f1=focus_now()
focus_ok=bool(f1) and (f1==aedit or f1==addr)
print("点击后焦点=%s (Edit=%s) -> 焦点在地址栏=%s" % (hex(f1) if f1 else "NULL", hex(aedit), focus_ok),flush=True)

# 1) 选择（对编辑框 EM_SETSEL 全选，再 EM_GETSEL 读回 start/end）
u.SendMessageW(aedit, EM_SETSEL, 0, -1)
r=u.SendMessageW(aedit, EM_GETSEL, 0, 0)     # 返回值: LOWORD=start HIWORD=end
start=r & 0xFFFF; end=(r>>16) & 0xFFFF
sel_ok = (start==0 and end>0)
print("选择: start=%d end=%d -> %s" % (start,end,sel_ok),flush=True)

# 2) 复制（确保有选区后再 WM_COPY）
u.SendMessageW(aedit, EM_SETSEL, 0, -1)
set_clip_text("")            # 先清空剪贴板，避免读到上一次残留
u.SendMessageW(aedit, WM_COPY, 0, 0); time.sleep(0.25)
clip=get_clip_text()
copy_ok = clip.strip().upper().startswith("E:\\")
print("复制: 剪贴板=%r -> %s" % (clip, copy_ok),flush=True)

# 3) 粘贴
test=r"C:\Windows"
set_clip_text(test)
u.SendMessageW(aedit, EM_SETSEL, 0, -1)
u.SendMessageW(aedit, WM_PASTE, 0, 0); time.sleep(0.3)
after=wtext(addr)
paste_ok = after.strip().upper()==test.upper()
print("粘贴: 地址栏=%r -> %s" % (after, paste_ok),flush=True)

# 4) 输入（打字）
u.SendMessageW(aedit, EM_SETSEL, 0, -1); u.SendMessageW(aedit, WM_CLEAR, 0, 0)
for ch in "C:\\Temp":
    u.SendMessageW(aedit, 0x0102, ord(ch), 0)  # WM_CHAR
time.sleep(0.2)
typed=wtext(addr)
type_ok = typed.strip().upper()=="C:\\TEMP"
print("输入: 地址栏=%r -> %s" % (typed, type_ok),flush=True)

print("RESULT: 焦点=%s 选择=%s 复制=%s 粘贴=%s 输入=%s" % (focus_ok,sel_ok,copy_ok,paste_ok,type_ok),flush=True)
ok = all([focus_ok,sel_ok,copy_ok,paste_ok,type_ok])
print("RESULT:", "PASS" if ok else "FAIL", flush=True)
p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
