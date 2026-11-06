# -*- coding: utf-8 -*-
# 对比：真实路径取图标 vs 「合成文件名 + USEFILEATTRIBUTES」取图标。
# 目的：验证「.exe 在 FileCE 里显示通用图标、在资源管理器里显示自身图标」的原因。
import ctypes, ctypes.wintypes as w

sh = ctypes.WinDLL("shell32")


class SFI(ctypes.Structure):
    _fields_ = [("hIcon", w.HANDLE), ("iIcon", ctypes.c_int),
                ("dwAttributes", ctypes.c_uint32),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName", ctypes.c_wchar * 80)]


sh.SHGetFileInfoW.argtypes = [w.LPCWSTR, ctypes.c_uint32, ctypes.POINTER(SFI),
                             ctypes.c_uint, ctypes.c_uint]
sh.SHGetFileInfoW.restype = ctypes.c_void_p

SHGFI_SYSICONINDEX = 0x4000
SHGFI_SMALLICON = 0x1
SHGFI_USEFILEATTRIBUTES = 0x10
SHGFI_TYPENAME = 0x400
FILE_ATTRIBUTE_NORMAL = 0x80


def q(path, attrs, flags):
    f = SFI()
    r = sh.SHGetFileInfoW(path, attrs, ctypes.byref(f), ctypes.sizeof(f), flags)
    return (bool(r), f.iIcon, f.szTypeName)


D = "D:\\tools\\自用程序\\"
files = ["FileCE.exe", "dsync.exe", "NetTool.exe", "快启.exe", "自用程序.rar", "config.ini"]

print("%-16s %-10s %-10s %s" % ("文件", "真实icon", "合成icon", "类型名(真实)"))
for n in files:
    real = q(D + n, FILE_ATTRIBUTE_NORMAL, SHGFI_SYSICONINDEX | SHGFI_SMALLICON)
    ext = n[n.rfind("."):]
    syn = q("file" + ext, FILE_ATTRIBUTE_NORMAL,
            SHGFI_SYSICONINDEX | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES)
    tn = q(D + n, FILE_ATTRIBUTE_NORMAL, SHGFI_TYPENAME)
    mark = "  <== 不同" if real[1] != syn[1] else ""
    print("%-16s %-10d %-10d %s%s" % (n, real[1], syn[1], tn[2], mark))

print()
print("文件夹 folder 合成 icon =", q("folder", 0x10,
      SHGFI_SYSICONINDEX | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES)[1])
print("D:\\tools\\测试工具 真实 icon =", q("D:\\tools\\测试工具", 0x10,
      SHGFI_SYSICONINDEX | SHGFI_SMALLICON)[1])
print("D:\\tools 真实 icon =", q("D:\\tools", 0x10, SHGFI_SYSICONINDEX | SHGFI_SMALLICON)[1])
