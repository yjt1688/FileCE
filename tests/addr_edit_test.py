# -*- coding: utf-8 -*-
"""地址栏可编辑性回归测试

背景 bug：主窗口 WM_SETFOCUS 无条件 SetFocus(list)，会把刚点进地址栏编辑框的
焦点又抢回列表 -> 地址栏变白、无法输入路径。修复后 WM_SETFOCUS 不再抢子控件焦点。

本测试分两级：
  A. 结构性断言（确定性）：地址栏必须是可编辑下拉框 CBS_DROPDOWN（非 DROPDOWNLIST），
     且存在 Edit 子控件。这是"能输入路径"的前提。
  B. 功能验证（尽力而为）：真实点击地址栏 -> 键入 -> 回车导航。
     若运行环境拦截了合成输入（SendInput 注入 0 事件），B 判为 SKIP（不计失败）。
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))

u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.SendMessageW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
u.SendMessageW.restype=ctypes.c_ssize_t
u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
u.SetForegroundWindow.argtypes=[w.HWND]
u.GetForegroundWindow.restype=w.HWND
u.ShowWindow.argtypes=[w.HWND,ctypes.c_int]
u.FindWindowExW.argtypes=[w.HWND,w.HWND,w.LPCWSTR,w.LPCWSTR]
u.FindWindowExW.restype=w.HWND
u.mouse_event.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]
u.SendInput.argtypes=[ctypes.c_uint,ctypes.c_void_p,ctypes.c_int]
u.SendInput.restype=ctypes.c_uint
u.GetWindowLongPtrW.argtypes=[w.HWND,ctypes.c_int]
u.GetWindowLongPtrW.restype=ctypes.c_void_p

WM_GETTEXT=0x000D; WM_GETTEXTLENGTH=0x000E
GWL_STYLE=-16
CBS_DROPDOWNLIST=0x0003
MOUSEEVENTF_LEFTDOWN=0x0002; MOUSEEVENTF_LEFTUP=0x0004

def wtext(h):
    if not h: return ""
    n=u.SendMessageW(h,WM_GETTEXTLENGTH,0,0)
    b=ctypes.create_unicode_buffer(n+2)
    u.SendMessageW(h,WM_GETTEXT,n+1,ctypes.addressof(b))
    return b.value

class KEYBDINPUT(ctypes.Structure):
    _fields_=[("wVk",w.WORD),("wScan",w.WORD),("dwFlags",w.DWORD),("time",w.DWORD),("dwExtraInfo",ctypes.POINTER(ctypes.c_ulong))]
class INPUT(ctypes.Structure):
    class U(ctypes.Union): _fields_=[("ki",KEYBDINPUT)]
    _anonymous_=("u",)
    _fields_=[("type",w.DWORD),("u",U)]
def key_char(ch):
    inp=(INPUT*2)()
    inp[0].type=1; inp[0].ki=KEYBDINPUT(0,ord(ch),0x0004,0,None)
    inp[1].type=1; inp[1].ki=KEYBDINPUT(0,ord(ch),0x0004|0x0002,0,None)
    return u.SendInput(2,inp,ctypes.sizeof(INPUT))
def key_vk(vk):
    inp=(INPUT*2)()
    inp[0].type=1; inp[0].ki=KEYBDINPUT(vk,0,0,0,None)
    inp[1].type=1; inp[1].ki=KEYBDINPUT(vk,0,0x0002,0,None)
    return u.SendInput(2,inp,ctypes.sizeof(INPUT))
def real_click_at(cx, cy):
    u.SetCursorPos(cx,cy); time.sleep(0.12)
    u.mouse_event(MOUSEEVENTF_LEFTDOWN,0,0,0,0); time.sleep(0.06)
    u.mouse_event(MOUSEEVENTF_LEFTUP,0,0,0,0); time.sleep(0.35)

def bring_front(main):
    u.ShowWindow(main,9)
    for _ in range(15):
        u.SetForegroundWindow(main)
        if u.GetForegroundWindow()==main: return True
        time.sleep(0.1)
    return u.GetForegroundWindow()==main

found=[]; TARGET_PID=w.DWORD(0)
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def cb(h,l):
    if not u.IsWindowVisible(h): return True
    pid=w.DWORD(0); u.GetWindowThreadProcessId(h,ctypes.byref(pid))
    if pid.value!=TARGET_PID.value: return True
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    if b.value=="FFMainWnd": found.append(h)
    return True

p=subprocess.Popen([EXE, r"C:\\"])
TARGET_PID.value=p.pid
t0=time.time()
while not found and time.time()-t0<10:
    u.EnumWindows(cb,0); time.sleep(0.1)
time.sleep(1.2)
main=found[0]

kids=[]
@ctypes.WINFUNCTYPE(ctypes.c_bool,w.HWND,w.LPARAM)
def kcb(h,l):
    b=ctypes.create_unicode_buffer(96); u.GetClassNameW(h,b,96)
    kids.append((b.value,h)); return True
u.EnumChildWindows(main,kcb,0)

combos=[h for c,h in kids if c=="ComboBox"]
addr=None
for c in combos:
    t=wtext(c)
    if t and (":" in t or t=="计算机"):
        addr=c; break
if addr is None and combos: addr=combos[0]
addr_edit=u.FindWindowExW(addr,None,"Edit",None)

# ---------- A. 结构性断言 ----------
style=u.GetWindowLongPtrW(addr, GWL_STYLE) or 0
is_editable = (style & 0x3) != CBS_DROPDOWNLIST   # DROPDOWN/SIMPLE 才有 Edit
has_edit = bool(addr_edit)
print("地址栏=%s style=0x%x 可编辑(非DROPDOWNLIST)=%s Edit子控件=%s" % (
    hex(addr) if addr else "?", style, is_editable, has_edit), flush=True)
structural_ok = is_editable and has_edit

# ---------- B. 功能验证（尽力而为） ----------
functional=None
if structural_ok:
    front=bring_front(main)
    rc=w.RECT(); u.GetWindowRect(addr,ctypes.byref(rc))
    cx=(rc.left+rc.right)//2; cy=(rc.top+rc.bottom)//2
    real_click_at(cx,cy)
    injected=0
    for ch in "C:\\Windows": injected+=key_char(ch); time.sleep(0.04)
    time.sleep(0.4)
    typed=wtext(addr)
    typed_ok=(typed.strip().upper()=="C:\\WINDOWS")
    if injected==0:
        print("环境拦截合成输入（SendInput 注入 0 事件）—— 功能验证 SKIP", flush=True)
    else:
        key_vk(0x0D); time.sleep(1.2)
        t=ctypes.create_unicode_buffer(256); u.GetWindowTextW(main,t,256)
        nav_ok=("Windows" in t.value)
        print("前台=%s 键入回填=%s 回车导航=%s 标题=%r" % (front, typed_ok, nav_ok, t.value[:44]), flush=True)
        functional = typed_ok and nav_ok

ok = structural_ok and (functional is not False)
print("RESULT:", "PASS" if ok else "FAIL",
      "(结构性 OK，功能 SKIP)" if (ok and functional is None) else "", flush=True)
p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()
sys.exit(0 if ok else 1)
