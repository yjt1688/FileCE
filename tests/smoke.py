"""FileCE 综合冒烟 / 压力测试。

用法: python smoke.py
覆盖：冷启动耗时、大目录打开、视图切换、排序、多标签、内存占用、崩溃检测。
"""
import subprocess, time, ctypes, ctypes.wintypes as w, sys, os

u = ctypes.WinDLL('user32', use_last_error=True)
k = ctypes.WinDLL('kernel32', use_last_error=True)
p_ = ctypes.WinDLL('psapi', use_last_error=True)

u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int,
                           ctypes.c_int, ctypes.c_int, ctypes.c_uint]
k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
k.OpenProcess.restype = w.HANDLE
p_.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_uint]

EXE = os.environ.get('FFCE_EXE',
                     r'C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE\build\FileCE.exe')
WM_COMMAND = 0x0111
LVM_GETITEMCOUNT = 0x1004

CMD_REFRESH, CMD_HOME = 20004, 20005
CMD_VIEW_LARGE, CMD_VIEW_SMALL, CMD_VIEW_LIST, CMD_VIEW_DETAIL = 20020, 20021, 20022, 20023
CMD_SORT_NAME, CMD_SORT_TYPE, CMD_SORT_SIZE, CMD_SORT_MTIME = 20024, 20025, 20026, 20027
CMD_TOGGLE_FILTER, CMD_TOGGLE_TREE = 20028, 20035
CMD_TAB_NEW, CMD_TAB_CLOSE, CMD_TAB_NEXT, CMD_TAB_PREV = 20040, 20041, 20042, 20043
CMD_SELECT_ALL, CMD_INVERT_SEL = 20016, 20037


class PMC(ctypes.Structure):
    _fields_ = [('cb', ctypes.c_uint32), ('PageFaultCount', ctypes.c_uint32),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]


HWNDCB = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
fails = []


def check(name, ok, detail=''):
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (('  ' + detail) if detail else ''))
    if not ok:
        fails.append(name)


def find_main(pid=None):
    """只看指定 pid 的主窗口：机器上可能还留着上一次测试的 FileCE，
    拿错了窗口会得到完全跑偏的测量结果。"""
    out = []

    def cb(h, l):
        c = ctypes.create_unicode_buffer(96)
        u.GetClassNameW(h, c, 96)
        if c.value != 'FFMainWnd' or not u.IsWindowVisible(h):
            return True
        if pid is not None:
            p = ctypes.c_uint32(0)
            u.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value != pid:
                return True
        b = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(h, b, 512)
        out.append((h, b.value))
        return True
    u.EnumWindows(HWNDCB(cb), 0)
    return out


u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(ctypes.c_uint32)]


def child_by_class(hwnd, cls):
    out = []

    def cb(c, l):
        cn = ctypes.create_unicode_buffer(96)
        u.GetClassNameW(c, cn, 96)
        if cn.value == cls:
            out.append(c)
        return True
    u.EnumChildWindows(hwnd, HWNDCB(cb), 0)
    return out


def item_count(lv):
    return u.SendMessageW(lv, LVM_GETITEMCOUNT, 0, 0)


def titlestr(hwnd):
    b = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, b, 512)
    return b.value


def mem_kb(ph):
    """私有提交内存。工作集包含共享的系统图像列表页（约 29MB），不能代表本进程开销。"""
    pmc = PMC(); pmc.cb = ctypes.sizeof(pmc)
    p_.GetProcessMemoryInfo(ph, ctypes.byref(pmc), pmc.cb)
    return pmc.PagefileUsage // 1024


def launch(args, settle=1.0):
    t0 = time.time()
    proc = subprocess.Popen([EXE] + args)
    while time.time() - t0 < 20:
        time.sleep(0.1)
        ws = find_main(proc.pid)
        if ws:
            break
    dt = time.time() - t0
    if not ws:
        return None, dt, proc
    hwnd = ws[0][0]
    time.sleep(settle)
    # 稳定后再读标题：创建时标题与导航后的标题不同，过早读会拿到旧值
    ws = find_main(proc.pid)
    return (hwnd, ws[0][1] if ws else ''), dt, proc


print('=' * 62)
print('1) 冷启动 / "此电脑" 视图')
print('=' * 62)
(title_tuple, dt, proc) = launch([])
if not title_tuple:
    print('  NO WINDOW, exit =', proc.poll()); proc.kill(); sys.exit(1)
hwnd, title = title_tuple
print('  startup   = %.3f s' % dt)
print('  title     = %s' % title)
lvs = child_by_class(hwnd, 'SysListView32')
lv = lvs[0]
check('窗口在 0.5s 内呈现', dt < 0.5, '%.3fs' % dt)
check('标题正确', 'FileCE' in title and '此电脑' in title)
check('存在文件列表控件', lv is not None)
check('驱动器条目数 > 0', item_count(lv) > 0, '%d 项' % item_count(lv))
ph = k.OpenProcess(0x0410, 0, proc.pid)
check('私有内存 < 20MB', mem_kb(ph) < 20 * 1024, '%d KB' % mem_kb(ph))
k.CloseHandle(ph)
proc.terminate(); time.sleep(0.3)
if proc.poll() is None: proc.kill()

print()
print('=' * 62)
print('2) 大目录压力：C:\\Windows\\WinSxS (15678 项)')
print('=' * 62)
(title_tuple, dt, proc) = launch([r'C:\Windows\WinSxS'], settle=1.5)
hwnd, title = title_tuple
lv = child_by_class(hwnd, 'SysListView32')[0]
n = item_count(lv)
print('  startup   = %.3f s' % dt)
print('  title     = %s' % title)
print('  items     = %d' % n)
check('全部条目载入', n == 15678, '%d' % n)
check('大目录启动 < 2.0s', dt < 2.0, '%.3fs' % dt)
base_mem = mem_kb(k.OpenProcess(0x0410, 0, proc.pid))
print('  MemKB     = %d' % base_mem)

print()
print('=' * 62)
print('3) 命令压力测试（视图 / 排序 / 面板 / 标签）')
print('=' * 62)
ops = [
    ('大图标视图', CMD_VIEW_LARGE), ('小图标视图', CMD_VIEW_SMALL),
    ('列表视图', CMD_VIEW_LIST), ('详细视图', CMD_VIEW_DETAIL),
    ('按名称排序', CMD_SORT_NAME), ('按类型排序', CMD_SORT_TYPE),
    ('按大小排序', CMD_SORT_SIZE), ('按修改时间排序', CMD_SORT_MTIME),
    ('全选', CMD_SELECT_ALL), ('反选', CMD_INVERT_SEL),
    ('筛选面板', CMD_TOGGLE_FILTER), ('筛选面板2', CMD_TOGGLE_FILTER),
    ('目录树', CMD_TOGGLE_TREE), ('目录树2', CMD_TOGGLE_TREE),
    ('刷新', CMD_REFRESH),
]
for name, cmd in ops:
    u.SendMessageW(hwnd, WM_COMMAND, cmd, 0)
    time.sleep(0.05)
check('全部 15 条命令执行后进程存活', proc.poll() is None)
check('列表仍在且条目不丢', item_count(lv) == n, '%d' % item_count(lv))

# 回归：F5 曾经会把当前目录"跳"到别处（重建目录树时系统自动选中了"网络"
# 节点，TVN_SELCHANGED 被当成用户点击，于是导航到了 \\）。刷新必须原地不动。
t_before = titlestr(hwnd)
u.SendMessageW(hwnd, WM_COMMAND, CMD_REFRESH, 0)
time.sleep(0.4)
check('刷新后仍停在同一目录', titlestr(hwnd) == t_before and item_count(lv) == n,
      '%s / %d' % (titlestr(hwnd), item_count(lv)))

print()
print('  标签页:')
for _ in range(6):
    u.SendMessageW(hwnd, WM_COMMAND, CMD_TAB_NEW, 0)
    time.sleep(0.06)
check('开 6 个标签后存活', proc.poll() is None)
tabs = child_by_class(hwnd, 'FFTabBar')
check('标签栏控件存在', bool(tabs))
for _ in range(3):
    u.SendMessageW(hwnd, WM_COMMAND, CMD_TAB_NEXT, 0)
    u.SendMessageW(hwnd, WM_COMMAND, CMD_TAB_PREV, 0)
    time.sleep(0.03)
for _ in range(4):
    u.SendMessageW(hwnd, WM_COMMAND, CMD_TAB_CLOSE, 0)
    time.sleep(0.05)
check('关 4 个标签后存活', proc.poll() is None)
u.SendMessageW(hwnd, WM_COMMAND, CMD_HOME, 0)
time.sleep(0.3)

# 反复刷新，观察内存是否收敛（而不是持续泄漏）
u.SendMessageW(hwnd, WM_COMMAND, CMD_HOME, 0)
time.sleep(0.3)
check('回到"此电脑"视图', titlestr(hwnd).startswith('此电脑'), titlestr(hwnd)[:40])
u.SendMessageW(hwnd, WM_COMMAND, CMD_HOME, 0)
time.sleep(0.2)

curve = []
prev = 0
for rounds in (10, 30, 60, 120):
    for _ in range(rounds - prev):
        u.SendMessageW(hwnd, WM_COMMAND, CMD_REFRESH, 0)
    prev = rounds
    time.sleep(0.5)
    ph = k.OpenProcess(0x0410, 0, proc.pid)
    m = mem_kb(ph)
    k.CloseHandle(ph)
    curve.append((rounds, m))
    print('  刷新 %3d 次 -> MemKB = %d' % (rounds, m))

check('大量刷新无崩溃', proc.poll() is None)
check('列表条目仍正确', item_count(lv) > 0, '%d' % item_count(lv))
grow = curve[-1][1] - curve[1][1]
check('内存收敛（后 90 次刷新增长 < 3MB）', grow < 3 * 1024,
      '%d -> %d (+%d KB)' % (curve[1][1], curve[-1][1], grow))

proc.terminate(); time.sleep(0.3)
if proc.poll() is None: proc.kill()

print()
print('=' * 62)
if fails:
    print('失败项: %s' % ', '.join(fails))
    sys.exit(1)
print('全部通过')
print('=' * 62)
