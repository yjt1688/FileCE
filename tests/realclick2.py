# -*- coding: utf-8 -*-
"""真实点击导航 + 立即响应检测 + 卡住即抓栈"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys
u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32"); dbgh = ctypes.WinDLL("dbghelp")
EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.SendMessageTimeoutW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_size_t)]
u.PostMessageW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
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
k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]; k.OpenProcess.restype=w.HANDLE
k.OpenThread.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]; k.OpenThread.restype=w.HANDLE
k.SuspendThread.argtypes=[w.HANDLE]; k.SuspendThread.restype=ctypes.c_uint32
k.ResumeThread.argtypes=[w.HANDLE]; k.ResumeThread.restype=ctypes.c_uint32
k.GetProcessTimes.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
dbgh.SymGetModuleBase64.argtypes=[w.HANDLE,ctypes.c_uint64]; dbgh.SymGetModuleBase64.restype=ctypes.c_uint64
dbgh.SymFromAddr.argtypes=[w.HANDLE,ctypes.c_uint64,ctypes.POINTER(ctypes.c_uint64),ctypes.c_void_p]
LVM_GETITEMCOUNT=0x1004

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

def title(h):
    t=ctypes.create_unicode_buffer(256); u.GetWindowTextW(h,t,256); return t.value
class BMIH(ctypes.Structure):
    _fields_=[("biSize",ctypes.c_uint32),("biWidth",ctypes.c_int32),("biHeight",ctypes.c_int32),
              ("biPlanes",ctypes.c_uint16),("biBitCount",ctypes.c_uint16),("biCompression",ctypes.c_uint32),
              ("biSizeImage",ctypes.c_uint32),("biXPelsPerMeter",ctypes.c_int32),
              ("biYPelsPerMeter",ctypes.c_int32),("biClrUsed",ctypes.c_uint32),("biClrImportant",ctypes.c_uint32)]
def pixel_rows(lv):
    rc=w.RECT(); u.GetClientRect(lv,ctypes.byref(rc))
    W,H=rc.right-rc.left, rc.bottom-rc.top
    dc0=u.GetDC(0); mem=g.CreateCompatibleDC(dc0)
    bmp=g.CreateCompatibleBitmap(dc0,W,H); g.SelectObject(mem,bmp)
    u.PrintWindow(lv,mem,2)
    bi=BMIH(); bi.biSize=ctypes.sizeof(BMIH); bi.biWidth=W; bi.biHeight=-H
    bi.biPlanes=1; bi.biBitCount=32
    px=(ctypes.c_ubyte*(W*H*4))()
    g.GetDIBits(mem,bmp,0,H,px,ctypes.byref(bi),0)
    n=0
    for y in range(28,H):
        d=0
        for x in range(0,min(W,420)):
            o=(y*W+x)*4
            if px[o+2]<140 and px[o+1]<140 and px[o]<140: d+=1
        if d>3: n+=1
    return n
def alive(hwnd, ms=3000):
    r=ctypes.c_size_t(0)
    return u.SendMessageTimeoutW(hwnd,0,0,0,2,ms,ctypes.byref(r))!=0

# ---- 线程栈采样 ----
dbgh.SymFromAddrW = dbgh.SymFromAddr
class SYMBOL_INFOW(ctypes.Structure):
    _fields_=[("SizeOfStruct",ctypes.c_uint32),("TypeIndex",ctypes.c_uint32),("Reserved",ctypes.c_uint64*2),
              ("Index",ctypes.c_uint32),("Size",ctypes.c_uint32),("ModBase",ctypes.c_uint64),("Flags",ctypes.c_uint32),
              ("Value",ctypes.c_uint64),("Address",ctypes.c_uint64),("Register",ctypes.c_uint32),("Scope",ctypes.c_uint32),
              ("Tag",ctypes.c_uint32),("NameLen",ctypes.c_uint32),("MaxNameLen",ctypes.c_uint32),
              ("Name",ctypes.c_wchar*256)]
class THREADENTRY32(ctypes.Structure):
    _fields_=[("dwSize",ctypes.c_uint32),("cntUsage",ctypes.c_uint32),("th32ThreadID",ctypes.c_uint32),
              ("th32OwnerProcessID",ctypes.c_uint32),("tpBasePri",ctypes.c_long),("tpPri",ctypes.c_long),("dwFlags",ctypes.c_uint32)]
k.CreateToolhelp32Snapshot.argtypes=[ctypes.c_uint32,ctypes.c_uint32]; k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Thread32First.argtypes=[w.HANDLE,ctypes.c_void_p]; k.Thread32Next.argtypes=[w.HANDLE,ctypes.c_void_p]
k.GetThreadContext.argtypes=[w.HANDLE,ctypes.c_void_p]
k.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
def all_threads(pid):
    out=[]
    snap=k.CreateToolhelp32Snapshot(0x4,0)
    te=THREADENTRY32(); te.dwSize=ctypes.sizeof(te)
    ok=k.Thread32First(snap,ctypes.byref(te))
    while ok:
        if te.th32OwnerProcessID==pid: out.append(te.th32ThreadID)
        ok=k.Thread32Next(snap,ctypes.byref(te))
    k.CloseHandle(snap)
    return out
def sample_all(ph, label):
    for tid in all_threads_from:
        th=k.OpenThread(0x1FFFF,0,tid)
        if not th: continue
        k.SuspendThread(th)
        buf=(ctypes.c_uint64*160)()
        ctypes.cast(buf,ctypes.POINTER(ctypes.c_uint32))[6]=0x10001B
        if not k.GetThreadContext(th,ctypes.cast(buf,ctypes.c_void_p)):
            k.ResumeThread(th); k.CloseHandle(th); continue
        rip=buf[31]; rsp=buf[19]
        print("    [%s] tid=%d rip=0x%X" % (label,tid,rip), flush=True)
        stk=(ctypes.c_uint64*512)()
        got=ctypes.c_size_t(0)
        k.ReadProcessMemory(ph,ctypes.c_void_p(rsp),stk,4096,ctypes.byref(got))
        n=got.value//8; prev=-10
        for i in range(n):
            v=stk[i]
            if v<0x10000 or v>0x7FFFFFFF0000: continue
            base=dbgh.SymGetModuleBase64(ph,v)
            if not base: continue
            if i-prev<=1: prev=i; continue
            si=SYMBOL_INFOW(); si.MaxNameLen=260
            disp=ctypes.c_uint64(0)
            name=None
            try:
                if dbgh.SymFromAddr(ph,v,ctypes.byref(disp),ctypes.byref(si)): name=si.Name
            except Exception: pass
            print("      stk+0x%04x 0x%X %s" % (i*8,v,name or "base0x%X"%base), flush=True)
            prev=i
        k.ResumeThread(th); k.CloseHandle(th)

p=subprocess.Popen([EXE, r"C:\Users\Administrator\WorkBuddy"])
t0=time.time()
while not found and time.time()-t0<10:
    u.EnumWindows(cb,0); time.sleep(0.1)
time.sleep(1.5)
main=found[0]
del kids[:]
u.EnumChildWindows(main,kcb,0)
lv=[h for c,h in kids if c=="SysListView32"][0]
ph=k.OpenProcess(0x1F0FFF,0,p.pid)
ft=(ctypes.c_uint64*4)()
def cpu_delta():
    k.GetProcessTimes(ph,ctypes.cast(ft,ctypes.c_void_p),ctypes.cast(ft,ctypes.c_void_p),ctypes.cast(ft+2,ctypes.c_void_p),ctypes.cast(ft+3,ctypes.c_void_p))
    return (ft[2]+ft[3])/10000.0
dbgh.SymInitialize(ph,None,True)
all_threads_from=all_threads(p.pid)
print("启动: count=%d 行=%d tid列表=%d个" % (u.SendMessageW(lv,LVM_GETITEMCOUNT,0,0),pixel_rows(lv),len(all_threads_from)), flush=True)

levels=0
for step in range(3):
    before=title(main)
    navigated=False
    for y in (40,46,52,58,64,70,76):
        pt=w.POINT(150,y); u.ClientToScreen(lv,ctypes.byref(pt))
        u.SetCursorPos(pt.x,pt.y); time.sleep(0.05)
        lp=ctypes.c_ssize_t(((y&0xFFFF)<<16)|(150&0xFFFF))
        u.PostMessageW(lv,0x0201,1,lp); time.sleep(0.04)
        u.PostMessageW(lv,0x0202,0,lp); time.sleep(0.12)
        u.PostMessageW(lv,0x0203,1,lp); time.sleep(0.04)
        u.PostMessageW(lv,0x0202,0,lp); time.sleep(0.8)
        if title(main)!=before: navigated=True; break
    print("第%d层 导航=%s 标题=%r" % (step+1,navigated,title(main)[:34]), flush=True)
    if not navigated: break
    levels+=1
    # 立即检测响应性,最多等 12 秒,失败即抓栈
    stuck=False
    for wait_i in range(4):
        if alive(main, 3000):
            print("  响应正常 (第%d次检查)" % (wait_i+1), flush=True)
            stuck=False; break
        stuck=True
        print("  !! 无响应 (%d秒), 抓栈:" % ((wait_i+1)*3), flush=True)
        cA=cpu_delta(); time.sleep(0.8); cB=cpu_delta()
        print("  CPU增量 %.0fms/0.8s" % (cB-cA), flush=True)
        sample_all(ph, "STUCK%d"%wait_i)
    rows=pixel_rows(lv)
    print("  count=%d 行=%d" % (u.SendMessageW(lv,LVM_GETITEMCOUNT,0,0),rows), flush=True)
    if stuck and rows<=2:
        print("FAIL: 导航后白屏+无响应"); break
print("完成,进入%d层" % levels)
p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()
