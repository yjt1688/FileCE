# -*- coding: utf-8 -*-
r"""精简后的「此电脑」视图 + 目录树探针
A: 空路径列表 = 6 常用文件夹 + 「设备和驱动器」组头 + 盘符（无网络）
B: 目录树顶层只有「此电脑」一个根；点它保持选中
C: 回车打开"视频" → 进入真实视频目录
D: 无网络节点/条目；深层目录仍能定位到叶子节点
附: 主窗口截图 pc_groups.png
"""
import ctypes, ctypes.wintypes as w, subprocess, time, os, sys

u = ctypes.WinDLL("user32"); k = ctypes.WinDLL("kernel32"); g = ctypes.WinDLL("gdi32")
EXE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "FileCE.exe"))
HERE = os.path.dirname(os.path.abspath(__file__))
SHOT = os.path.join(HERE, "pc_groups.png")

WM_GETTEXT = 0x000D; WM_GETTEXTLENGTH = 0x000E; WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100; WM_KEYUP = 0x0101; WM_COMMAND = 0x0111
VK_RETURN = 0x0D
TVGN_ROOT = 0; TVGN_NEXT = 1; TVGN_CHILD = 4; TVGN_CARET = 9
TVM_GETNEXTITEM = 0x1100 + 10; TVM_GETITEMW = 0x1100 + 62; TVM_SELECTITEM = 0x1100 + 11
TVIF_TEXT = 0x0001; TVIF_HANDLE = 0x0010; TVIF_PARAM = 0x0004
LVM_GETITEMCOUNT = 0x1004; LVM_GETITEMTEXTW = 0x1000 + 115
LVM_GETGROUPCOUNT = 0x1000 + 152
LVM_SETITEMSTATE = 0x1000 + 43
LVIF_TEXT = 0x0001; LVIS_SELECTED = 0x0002; LVIS_FOCUSED = 0x0001
CMD_HOME = 20005
PROCESS_ALL = 0x1F0FFF; MEM_COMMIT = 0x1000; MEM_RELEASE = 0x8000; PAGE_READWRITE = 4

u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.IsWindowVisible.argtypes = [w.HWND]; u.IsWindowVisible.restype = ctypes.c_bool
u.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
u.EnumChildWindows.argtypes = [w.HWND, ctypes.c_void_p, w.LPARAM]
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.SendMessageW.argtypes = [w.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
u.SendMessageW.restype = ctypes.c_ssize_t
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
u.PrintWindow.argtypes = [w.HWND, w.HDC, ctypes.c_uint]; u.PrintWindow.restype = ctypes.c_bool
u.GetDC.argtypes = [w.HWND]; u.GetDC.restype = w.HDC
u.ReleaseDC.argtypes = [w.HWND, w.HDC]
g.CreateCompatibleDC.argtypes = [w.HDC]; g.CreateCompatibleDC.restype = w.HDC
g.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; g.CreateCompatibleBitmap.restype = w.HBITMAP
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]; g.SelectObject.restype = w.HGDIOBJ
g.GetDIBits.argtypes = [w.HDC, w.HBITMAP, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
g.DeleteObject.argtypes = [w.HGDIOBJ]; g.DeleteObject.restype = ctypes.c_bool
g.DeleteDC.argtypes = [w.HDC]; g.DeleteDC.restype = ctypes.c_bool
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; k.OpenProcess.restype = w.HANDLE
k.VirtualAllocEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_size_t, w.DWORD, w.DWORD]
k.VirtualAllocEx.restype = ctypes.c_void_p
k.VirtualFreeEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_size_t, w.DWORD]
k.VirtualFreeEx.restype = ctypes.c_bool
k.WriteProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.WriteProcessMemory.restype = ctypes.c_bool
k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.ReadProcessMemory.restype = ctypes.c_bool


def cls(h):
    b = ctypes.create_unicode_buffer(96); u.GetClassNameW(h, b, 96); return b.value


fails = []
def check(cond, label, detail=""):
    tag = "OK " if cond else "FAIL"
    print("  [%s] %s %s" % (tag, label, detail))
    if not cond: fails.append(label)


found = []; PID = w.DWORD(0)
@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def cb(h, l):
    if not u.IsWindowVisible(h): return True
    pid = w.DWORD(0); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value != PID.value: return True
    if cls(h) == "FFMainWnd": found.append(h)
    return True

p = subprocess.Popen([EXE]); PID.value = p.pid
t0 = time.time()
while not found and time.time() - t0 < 10:
    u.EnumWindows(cb, 0); time.sleep(0.1)
time.sleep(1.5)
main = found[0]

kids = {}
@ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
def kcb(h, l):
    kids.setdefault(cls(h), []).append(h); return True
u.EnumChildWindows(main, kcb, 0)
tree = (kids.get("SysTreeView32") or [None])[0]
lst = (kids.get("SysListView32") or [None])[0]
addr = None
for c in kids.get("ComboBox", []):
    t = ctypes.create_unicode_buffer(300)
    u.SendMessageW(c, WM_GETTEXT, 300, ctypes.addressof(t))
    if t.value: addr = c; break

proc = k.OpenProcess(PROCESS_ALL, False, PID.value)

class TVITEMW(ctypes.Structure):
    _fields_ = [("mask", ctypes.c_uint), ("hItem", ctypes.c_void_p),
                ("state", ctypes.c_uint), ("stateMask", ctypes.c_uint),
                ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
                ("iImage", ctypes.c_int), ("iSelectedImage", ctypes.c_int),
                ("cChildren", ctypes.c_int), ("lParam", ctypes.c_size_t)]

def tree_text(hitem):
    txt = k.VirtualAllocEx(proc, None, 600, MEM_COMMIT, PAGE_READWRITE)
    st = k.VirtualAllocEx(proc, None, ctypes.sizeof(TVITEMW), MEM_COMMIT, PAGE_READWRITE)
    ti = TVITEMW()
    ti.mask = TVIF_TEXT | TVIF_HANDLE | TVIF_PARAM
    ti.hItem = ctypes.c_void_p(hitem & 0xFFFFFFFFFFFFFFFF)
    ti.pszText = ctypes.c_void_p(txt); ti.cchTextMax = 300
    nw = ctypes.c_size_t(0)
    k.WriteProcessMemory(proc, st, ctypes.byref(ti), ctypes.sizeof(ti), ctypes.byref(nw))
    u.SendMessageW(tree, TVM_GETITEMW, 0, st)
    b = ctypes.create_unicode_buffer(300)
    k.ReadProcessMemory(proc, txt, b, 600, ctypes.byref(nw))
    k.ReadProcessMemory(proc, st, ctypes.byref(ti), ctypes.sizeof(ti), ctypes.byref(nw))
    k.VirtualFreeEx(proc, st, 0, MEM_RELEASE); k.VirtualFreeEx(proc, txt, 0, MEM_RELEASE)
    return b.value, ti.lParam

def tree_find(top, text, maxn=64):
    h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, top) if top else \
        u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    g_ = 0
    while h and g_ < maxn:
        t, _ = tree_text(h)
        if t == text: return h
        h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, h)
        g_ += 1
    return None

def caret_text():
    h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CARET, 0)
    return tree_text(h)[0] if h else "(none)"

def tree_click(name):
    root = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    h = tree_find(root, name) or tree_find(0, name)
    if h: u.SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, h)
    return h

class LVITEMW(ctypes.Structure):
    _fields_ = [("mask", ctypes.c_uint), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
                ("state", ctypes.c_uint), ("stateMask", ctypes.c_uint),
                ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
                ("iImage", ctypes.c_int), ("lParam", ctypes.c_ssize_t),
                ("iIndent", ctypes.c_int), ("groupId", ctypes.c_int),
                ("cColumns", ctypes.c_uint), ("puColumns", ctypes.c_void_p),
                ("piColFmt", ctypes.c_void_p), ("iGroup", ctypes.c_int)]

def row_text(idx):
    txt = k.VirtualAllocEx(proc, None, 1200, MEM_COMMIT, PAGE_READWRITE)
    st = k.VirtualAllocEx(proc, None, ctypes.sizeof(LVITEMW), MEM_COMMIT, PAGE_READWRITE)
    li = LVITEMW()
    li.mask = LVIF_TEXT; li.iItem = idx; li.iSubItem = 0
    li.pszText = ctypes.c_void_p(txt); li.cchTextMax = 600
    nw = ctypes.c_size_t(0)
    k.WriteProcessMemory(proc, st, ctypes.byref(li), ctypes.sizeof(li), ctypes.byref(nw))
    u.SendMessageW(lst, LVM_GETITEMTEXTW, idx, st)
    b = ctypes.create_unicode_buffer(600)
    k.ReadProcessMemory(proc, txt, b, 1200, ctypes.byref(nw))
    k.VirtualFreeEx(proc, st, 0, MEM_RELEASE); k.VirtualFreeEx(proc, txt, 0, MEM_RELEASE)
    return b.value

def list_count():
    return u.SendMessageW(lst, LVM_GETITEMCOUNT, 0, 0)

def title_str():
    b = ctypes.create_unicode_buffer(300)
    u.GetWindowTextW(main, b, 300)
    return b.value

def addr_text():
    b = ctypes.create_unicode_buffer(300)
    u.SendMessageW(addr, WM_GETTEXT, 300, ctypes.addressof(b))
    return b.value

def goto(path):
    buf = ctypes.create_unicode_buffer(path)
    u.SendMessageW(addr, WM_SETTEXT, 0, ctypes.addressof(buf))
    u.SendMessageW(addr, WM_KEYDOWN, VK_RETURN, 0)
    u.SendMessageW(addr, WM_KEYUP, VK_RETURN, 0)

# ============================================================ A 分组视图
print("A 此电脑分组视图（自绘组头行）")
time.sleep(0.8)
n = list_count()
rows = [row_text(i) for i in range(n)]
hdrs = [r for r in rows if r.startswith("设备和驱动器")]
check(len(hdrs) == 1, "只有「设备和驱动器」一个组头行", str(hdrs))
check("网络位置" not in "".join(rows), "不再有「网络位置」分组")
check("网络" not in rows, "不再有「网络」条目", str([r for r in rows if "网络" in r]))
print("     行: %s" % rows)
folders = [r for r in rows if r in ("视频", "图片", "文档", "下载", "音乐", "桌面")]
check(len(folders) == 6, "六个常用文件夹齐全", str(sorted(folders)))
first6 = rows[:6]
check(set(first6) == set(folders), "文件夹在最顶部（Win10 顺序）", str(first6))
hdrdrv = next((r for r in rows if r.startswith("设备和驱动器")), "")
ndrv = hdrdrv.count("(") and "".join(ch for ch in hdrdrv if ch.isdigit())
drvs = [r for r in rows if len(r) >= 2 and r[1] == ":"]
check(len(drvs) >= 1, "驱动器条目存在", str(drvs))
if ndrv:
    check(str(len(drvs)) == ndrv, "组头条数与驱动器数一致", "头=%s 盘=%d" % (hdrdrv, len(drvs)))
check(hdrs and rows.index(hdrs[0]) == 6 and rows.index(drvs[0]) == 7,
      "组头行位置正确（6 文件夹之后、盘符之前）",
      "hdr@%d firstdrv@%d" % (rows.index(hdrs[0]), rows.index(drvs[0])))
check(n == 6 + 1 + len(drvs), "总行数 = 6 + 组头 + 盘符", "%d vs %d" % (n, 7 + len(drvs)))

# 截图供人工核对分组头
rc = w.RECT(); u.GetWindowRect(main, ctypes.byref(rc))
W, H = rc.right - rc.left, rc.bottom - rc.top
dc0 = u.GetDC(0); mem = g.CreateCompatibleDC(dc0)
bmp = g.CreateCompatibleBitmap(dc0, W, H); g.SelectObject(mem, bmp)
u.PrintWindow(main, mem, 2)
class BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]
bi = BMIH(); bi.biSize = ctypes.sizeof(BMIH); bi.biWidth = W; bi.biHeight = -H
bi.biPlanes = 1; bi.biBitCount = 32; bi.biCompression = 0
px = (ctypes.c_ubyte * (W * H * 4))()
g.GetDIBits(mem, bmp, 0, H, px, ctypes.byref(bi), 0)
import zlib, struct
def write_png(path, width, height, rgba):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f: f.write(png)
write_png(SHOT, W, H, bytes(px))
g.DeleteObject(bmp); g.DeleteDC(mem); u.ReleaseDC(0, dc0)
print("     截图 -> %s" % SHOT)

# ============================================================ C 回车打开"视频"
print("C 回车打开列表第一行（视频 → 真实目录）")
# 选中 row 0
st = k.VirtualAllocEx(proc, None, ctypes.sizeof(LVITEMW), MEM_COMMIT, PAGE_READWRITE)
li = LVITEMW(); li.mask = 0; li.iItem = 0
li.state = LVIS_SELECTED | LVIS_FOCUSED; li.stateMask = LVIS_SELECTED | LVIS_FOCUSED
nw = ctypes.c_size_t(0)
k.WriteProcessMemory(proc, st, ctypes.byref(li), ctypes.sizeof(li), ctypes.byref(nw))
u.SendMessageW(lst, LVM_SETITEMSTATE, 0, st)
k.VirtualFreeEx(proc, st, 0, MEM_RELEASE)
time.sleep(0.3)
u.SendMessageW(lst, WM_KEYDOWN, VK_RETURN, 0)
time.sleep(1.2)
t = title_str()
a = addr_text()
base = a.rstrip("\\").rsplit("\\", 1)[-1] if a else ""
check(a.startswith("C:\\") or a.startswith("\\\\"), "进入了真实目录", "addr=%r" % a)
check(t.startswith(base) and base != "", "标题与地址一致（本机视频可能重定向）",
      "title=%r addr=%r" % (t, a))

# 回此电脑
u.SendMessageW(main, WM_COMMAND, CMD_HOME, 0)
time.sleep(0.8)

# ============================================================ B 目录树两个根
print("B 目录树顶层 = 快速访问 + 此电脑")
def top_level():
    out = []
    h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    while h:
        out.append(tree_text(h)[0])
        h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, h)
    return out

tops = top_level()
print("     顶层: %s" % tops)
check(tops == ["快速访问", "此电脑"], "顶层 = 快速访问 + 此电脑（快速访问排第一）", str(tops))
check(tree_click("此电脑") is not None, "能选中「此电脑」")
time.sleep(0.8)
check(caret_text() == "此电脑", "点此电脑 → 光标保持'此电脑'", "caret=%r" % caret_text())
check("此电脑" in title_str(), "标题为此电脑", "title=%r" % title_str())
check(tree_find(0, "网络") is None, "树里没有「网络」节点")
check(tree_find(0, "计算机") is None, "树里没有「计算机」节点")
check(tree_find(0, "控制面板") is None, "树里没有「控制面板」节点")
subs = []
h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, tree_find(0, "此电脑"))
while h:
    subs.append(tree_text(h)[0]); h = u.SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, h)
print("     此电脑子节点: %s" % subs)
check(len(subs) >= 3 and "桌面" in subs and "文档" in subs,
      "此电脑子节点 = 盘符 + 桌面 + 文档", str(subs))

# 树点「桌面」→ 进真实桌面目录（本机桌面可能被重定向，不能写死 Desktop）
print("B2 树点「桌面」进入真实桌面目录")
hdesk = tree_find(tree_find(0, "此电脑"), "桌面")
if hdesk:
    u.SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, hdesk)
    time.sleep(1.2)
    real = ctypes.create_unicode_buffer(400)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, real)   # CSIDL_DESKTOP
    check(addr_text().rstrip("\\").lower() == real.value.rstrip("\\").lower(),
          "地址 = 真实桌面路径", "addr=%r real=%r" % (addr_text(), real.value))
else:
    check(False, "树里有「桌面」节点")

# 回此电脑
u.SendMessageW(main, WM_COMMAND, CMD_HOME, 0); time.sleep(0.8)

# ============================================================ D 深层定位
print("D 深层目录定位")
goto(r"C:\Windows\System32\drivers"); time.sleep(1.4)
check(caret_text() == "drivers", "导航到 C:\\Windows\\System32\\drivers → 定位到叶子",
      "caret=%r" % caret_text())
check(list_count() > 1, "列表有内容", "n=%d" % list_count())

# 体积检查（用户明确要求回到 558K 量级）
size = os.path.getsize(EXE)
check(size < 600 * 1024, "exe 体积 < 600KB", "%d bytes (%d KB)" % (size, size // 1024))

p.terminate(); time.sleep(0.4)
if p.poll() is None: p.kill()

print("=" * 60)
if fails:
    print("RESULT: FAIL -> %s" % fails); sys.exit(1)
print("RESULT: PASS")
