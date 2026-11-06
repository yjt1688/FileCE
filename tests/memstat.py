"""分别测量工作集(含共享)与私有提交内存"""
import subprocess, time, ctypes, ctypes.wintypes as w

u = ctypes.WinDLL('user32')
k = ctypes.WinDLL('kernel32')
ps = ctypes.WinDLL('psapi')
EXE = r'C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe'


class PMC(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_uint32), ('PageFaultCount', ctypes.c_uint32),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]
u.IsWindowVisible.restype = ctypes.c_bool
k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
k.OpenProcess.restype = w.HANDLE
ps.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_uint]

found = []


def enum_cb(h, l):
    c = ctypes.create_unicode_buffer(96)
    u.GetClassNameW(h, c, 96)
    if c.value == 'FFMainWnd' and u.IsWindowVisible(h):
        found.append(h)
    return True


CB = HWNDCB(enum_cb)


def has_window():
    found.clear()
    u.EnumWindows(CB, 0)
    return bool(found)


for label, args in [('计算机(3项)', []), ('WinSxS(15678项)', [r'C:\Windows\WinSxS'])]:
    p = subprocess.Popen([EXE] + args)
    t0 = time.time()
    while not has_window() and time.time() - t0 < 15:
        time.sleep(0.1)
    time.sleep(1.5)
    ph = k.OpenProcess(0x0410, 0, p.pid)
    m = PMC()
    m.cb = ctypes.sizeof(m)
    ps.GetProcessMemoryInfo(ph, ctypes.byref(m), m.cb)
    print('%-18s 工作集=%6d KB   私有提交=%6d KB'
          % (label, m.WorkingSetSize // 1024, m.PagefileUsage // 1024))
    k.CloseHandle(ph)
    p.terminate()
    time.sleep(0.4)
    if p.poll() is None:
        p.kill()
