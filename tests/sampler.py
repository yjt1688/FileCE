# -*- coding: utf-8 -*-
"""真实点击导航 -> 卡住时采样各线程栈(按模块/符号)"""
import ctypes, ctypes.wintypes as w, subprocess, time, sys
u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32"); dbgh = ctypes.WinDLL("dbghelp")
EXE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe"
u.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.IsWindowVisible.argtypes=[w.HWND]; u.IsWindowVisible.restype=ctypes.c_bool
u.EnumWindows.argtypes=[ctypes.c_void_p,w.LPARAM]
u.EnumChildWindows.argtypes=[w.HWND,ctypes.c_void_p,w.LPARAM]
u.GetWindowTextW.argtypes=[w.HWND,w.LPWSTR,ctypes.c_int]
u.PostMessageW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]; k.OpenProcess.restype=w.HANDLE
k.OpenThread.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]; k.OpenThread.restype=w.HANDLE
k.SuspendThread.argtypes=[w.HANDLE]; k.SuspendThread.restype=ctypes.c_uint32
k.ResumeThread.argtypes=[w.HANDLE]; k.ResumeThread.restype=ctypes.c_uint32
dbgh.SymGetModuleBase64.argtypes=[w.HANDLE,ctypes.c_uint64]; dbgh.SymGetModuleBase64.restype=ctypes.c_uint64
dbgh.SymFromAddr.argtypes=[w.HANDLE,ctypes.c_uint64,ctypes.POINTER(ctypes.c_uint64),ctypes.c_void_p]

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

p=subprocess.Popen([EXE, r"C:\Users\Administrator\WorkBuddy"])
t0=time.time()
while not found and time.time()-t0<10:
    u.EnumWindows(cb,0); time.sleep(0.1)
time.sleep(1.5)
main=found[0]
del kids[:]
u.EnumChildWindows(main,kcb,0)
lv=[h for c,h in kids if c=="SysListView32"][0]

def title(h):
    t=ctypes.create_unicode_buffer(256); u.GetWindowTextW(h,t,256); return t.value

before=title(main)
for y in (40,46,52,58,64,70,76):
    lp=ctypes.c_ssize_t(((y&0xFFFF)<<16)|(150&0xFFFF))
    u.PostMessageW(lv,0x0201,1,lp); time.sleep(0.04)
    u.PostMessageW(lv,0x0202,0,lp); time.sleep(0.12)
    u.PostMessageW(lv,0x0203,1,lp); time.sleep(0.04)
    u.PostMessageW(lv,0x0202,0,lp); time.sleep(0.8)
    if title(main)!=before: break
print("导航到:", title(main)[:40], flush=True)

ph=k.OpenProcess(0x1F0FFF,0,p.pid)
ft=(ctypes.c_uint64*4)()
def cpu_delta():
    k.GetProcessTimes(ph,*(ctypes.cast(ft,ctypes.c_void_p),)*4)
    return (ft[2]+ft[3])/10000.0
c0=cpu_delta(); time.sleep(1.5); c1=cpu_delta()
print("1.5s 窗口 CPU: %.0f ms (%.0f%%)" % (c1-c0,(c1-c0)/15.0), flush=True)

class THREADENTRY32(ctypes.Structure):
    _fields_=[("dwSize",ctypes.c_uint32),("cntUsage",ctypes.c_uint32),("th32ThreadID",ctypes.c_uint32),
              ("th32OwnerProcessID",ctypes.c_uint32),("tpBasePri",ctypes.c_long),("tpPri",ctypes.c_long),("dwFlags",ctypes.c_uint32)]
k.CreateToolhelp32Snapshot.argtypes=[ctypes.c_uint32,ctypes.c_uint32]; k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Thread32First.argtypes=[w.HANDLE,ctypes.c_void_p]; k.Thread32Next.argtypes=[w.HANDLE,ctypes.c_void_p]
threads=[]
snap=k.CreateToolhelp32Snapshot(0x4,0)
te=THREADENTRY32(); te.dwSize=ctypes.sizeof(te)
ok=k.Thread32First(snap,ctypes.byref(te))
while ok:
    if te.th32OwnerProcessID==p.pid: threads.append(te.th32ThreadID)
    ok=k.Thread32Next(snap,ctypes.byref(te))
k.CloseHandle(snap)

dbgh.SymInitialize(ph,None,True)
class SYMBOL_INFOW(ctypes.Structure):
    _fields_=[("SizeOfStruct",ctypes.c_uint32),("TypeIndex",ctypes.c_uint32),("Reserved",ctypes.c_uint64*2),
              ("Index",ctypes.c_uint32),("Size",ctypes.c_uint32),("ModBase",ctypes.c_uint64),("Flags",ctypes.c_uint32),
              ("Value",ctypes.c_uint64),("Address",ctypes.c_uint64),("Register",ctypes.c_uint32),("Scope",ctypes.c_uint32),
              ("Tag",ctypes.c_uint32),("NameLen",ctypes.c_uint32),("MaxNameLen",ctypes.c_uint32),
              ("Name",ctypes.c_wchar*256)]
CONTEXT_FULL=0x10001B
class CONTEXT(ctypes.Structure):
    _fields_=[("P1Home",ctypes.c_uint64),("P2Home",ctypes.c_uint64),("P3Home",ctypes.c_uint64),("P4Home",ctypes.c_uint64),
              ("P5Home",ctypes.c_uint64),("P6Home",ctypes.c_uint64),("ContextFlags",ctypes.c_uint32),("MxCsr",ctypes.c_uint32),
              ("SegCs",ctypes.c_uint16),("SegDs",ctypes.c_uint16),("SegEs",ctypes.c_uint16),("SegFs",ctypes.c_uint16),
              ("SegGs",ctypes.c_uint16),("SegSs",ctypes.c_uint16),("EFlags",ctypes.c_uint32),
              ("Dr0",ctypes.c_uint64),("Dr1",ctypes.c_uint64),("Dr2",ctypes.c_uint64),("Dr3",ctypes.c_uint64),
              ("Dr6",ctypes.c_uint64),("Dr7",ctypes.c_uint64),
              ("Rax",ctypes.c_uint64),("Rcx",ctypes.c_uint64),("Rdx",ctypes.c_uint64),("Rbx",ctypes.c_uint64),
              ("Rsp",ctypes.c_uint64),("Rbp",ctypes.c_uint64),("Rsi",ctypes.c_uint64),("Rdi",ctypes.c_uint64),
              ("R8",ctypes.c_uint64),("R9",ctypes.c_uint64),("R10",ctypes.c_uint64),("R11",ctypes.c_uint64),
              ("R12",ctypes.c_uint64),("R13",ctypes.c_uint64),("R14",ctypes.c_uint64),("R15",ctypes.c_uint64),
              ("Rip",ctypes.c_uint64),("Spare",ctypes.c_uint64*256)]
class KDHELP64(ctypes.Structure):
    _fields_=[("Thread",ctypes.c_uint64),("ThCallbackStack",ctypes.c_uint32),("ThCallbackBStore",ctypes.c_uint32),
              ("NextCallback",ctypes.c_uint32),("FramePointer",ctypes.c_uint32),("KernelStack",ctypes.c_uint64*4)]
k.GetThreadContext.argtypes=[w.HANDLE,ctypes.c_void_p]
k.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]

CTX_BUF = (ctypes.c_uint64*160)()   # 1280 bytes >= 1232
def sample_thread(tid, label):
    th=k.OpenThread(0x1FFFF,0,tid)
    if not th:
        print("  %s tid=%d OpenThread err=%d" % (label,tid,k.GetLastError()), flush=True); return
    k.SuspendThread(th)
    buf=(ctypes.c_uint64*160)()
    ctypes.cast(buf,ctypes.POINTER(ctypes.c_uint32))[6] = 0x10001B  # ContextFlags @0x30
    if not k.GetThreadContext(th,ctypes.cast(buf,ctypes.c_void_p)):
        print("  %s tid=%d GetContext err=%d" % (label,tid,k.GetLastError()), flush=True)
        k.ResumeThread(th); k.CloseHandle(th); return
    rip=buf[31]   # 0xF8
    rsp=buf[19]   # 0x98
    print("  === %s tid=%d rip=0x%X rsp=0x%X ===" % (label,tid,rip,rsp), flush=True)
    stk=(ctypes.c_uint64*512)()
    got=ctypes.c_size_t(0)
    k.ReadProcessMemory(ph,ctypes.c_void_p(rsp),stk,4096,ctypes.byref(got))
    n=got.value//8
    prev=-10
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
        print("    stk+0x%04x 0x%X %s!%s" % (i*8,v,"base0x%X"%base,name or "?"), flush=True)
        prev=i
    k.ResumeThread(th); k.CloseHandle(th)

# 持续观察 10 秒:响应性 + CPU + 栈采样
import ctypes as C
u.SendMessageTimeoutW.argtypes=[w.HWND,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_size_t)]
for round_i in range(6):
    r=C.c_size_t(0)
    resp = u.SendMessageTimeoutW(main,0,0,0,2,1000,C.byref(r))!=0
    cA=cpu_delta(); time.sleep(1.0); cB=cpu_delta()
    print("round%d 响应=%s CPU=%.0fms" % (round_i,resp,(cB-cA)), flush=True)
    if not resp:
        for tid in threads:
            try: sample_thread(tid,"STUCK")
            except Exception as ex: print("  失败:",ex)
        break
p.terminate(); time.sleep(0.3)
if p.poll() is None: p.kill()
