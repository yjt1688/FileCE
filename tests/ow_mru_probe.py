# 复现并验证用户报告的现象：
#   "我选择始终用这个打开，就是有的。我又换成记事本，它有没有了。在选就又有了。"
#
# 根因不是"没注册"，而是读槽位时 RegQueryValueExW 的 cb 没复位：
# 它是 in/out 参数，第一次读完内核会把 cb 改成实际字节数；循环里继续用
# 同一个 cb，下一次就只能读到首字符 -> 拿到 "N" 这种碎片，
# 于是后面几个槽位被当成无效值丢掉。被丢的正是"用户以前用过、
# 这次没选"的那几个 —— 于是表现为"刚勾了始终使用它在列表里，
# 一旦改回默认程序它就消失了"。
#
# 注意：不是缓冲区太小。原来的 wchar_t old[8][64] 有 64 个 wchar_t，
# 能装 63 字符路径，而本机最长的那条才 58 字符。真正的坑是 cb 不复位。
#
# 本测试验的是：8 个槽位全填满真实存在的路径时，一个都不能少。

import io
import os
import subprocess
import sys
import time
import winreg

EXE = os.path.abspath("build/FileCE.exe")
NP3 = r"D:\Program Files\(Notepad3)5.21.227.1.x64\Notepad3.exe"
NP = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "notepad.exe")
OWL = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
       r"\FileExts\.txt\OpenWithList")
PRIV = r"Software\FileCE\OpenWith\.txt"
OUT = os.path.join(os.environ["TEMP"], "ffce_owlist.txt")

fails, oks = [], []


def check(name, cond, extra=""):
    (oks if cond else fails).append(name)
    print(("  OK   " if cond else "  FAIL ") + name +
          (("<< " + extra) if (extra and not cond) else ""))


def del_tree(root, sub):
    try:
        k = winreg.OpenKey(root, sub, 0, winreg.KEY_ALL_ACCESS)
    except OSError:
        return
    while True:
        try:
            child = winreg.EnumKey(k, 0)
        except OSError:
            break
        del_tree(root, sub + "\\" + child)
    winreg.CloseKey(k)
    try:
        winreg.DeleteKey(root, sub)
    except OSError:
        pass


def probe(ext=".txt"):
    if os.path.exists(OUT):
        os.remove(OUT)
    subprocess.run([EXE, "--list-open-with=" + ext], timeout=60)
    return io.open(OUT, "rb").read().decode("utf-16-le")


# ---- 先备份用户真实的 OpenWithList，测完原样还原 ------------------
backup = {}
try:
    bk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, OWL)
    i = 0
    while True:
        try:
            nm = winreg.EnumValue(bk, i)[0]
        except OSError:
            break
        backup[nm] = winreg.EnumValue(bk, i)[1]
        i += 1
    winreg.CloseKey(bk)
except OSError:
    pass
print("已备份 OpenWithList：%d 个值" % len(backup))

# 全部用磁盘上真实存在的路径。原来这组里有几条是编的
# （notepad.exe 大小写不同、SumatraPDF/wmplayer 路径根本不存在），
# 断言失败其实是"正确地跳过了不存在的路径"，不是 bug。
# 注意：不能放画图/WMP —— 它们声明的 SupportedTypes 不含 .txt，
# 会被"门当户对"过滤正确地挡掉（那是 ow_relevance_probe 的活），
# 放进来只会让断言失败。换用没有 SupportedTypes 声明的程序。
LONG = [p for p in [
    NP3,
    NP,
    r"D:\360极速浏览器X下载\IrfanView_4.54.x64中文绿色便携全功能版图片\i_view64.exe",
    r"D:\software\办公软件\office2016\Office16\WINWORD.EXE",
    r"C:\Program Files\Windows NT\Accessories\WORDPAD.EXE",
    r"D:\Program Files\Everything-1.4.1.1015.x64.Lite\Everything.exe",
    r"C:\Users\Administrator\AppData\Local\Programs\WorkBuddy\WorkBuddy.exe",
    r"D:\program\QianwenApp\qianwen.exe",
] if os.path.exists(p)]
# 槽位名只有 a..h 共 8 个，路径条数必须等于槽位数才能验证"一个都不丢"
LONG = LONG[:8]
print("用于测试的真实路径 %d 条（最长 %d 字符）"
      % (len(LONG), max(len(p) for p in LONG)))
assert len(LONG) == 8, "可用路径太少，测不出丢槽位的问题"

try:
    print()
    print("=" * 64)
    print("场景：8 个长路径写进历史，然后模拟\"换成记事本\"的重排")
    print("=" * 64)
    del_tree(winreg.HKEY_CURRENT_USER, PRIV)
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, OWL)
    for i, p in enumerate(LONG):
        winreg.SetValueEx(k, chr(ord('a') + i), 0, winreg.REG_SZ, p)
    winreg.SetValueEx(k, "MRUList", 0, winreg.REG_SZ,
                      "".join(chr(ord('a') + i) for i in range(len(LONG))))
    winreg.CloseKey(k)

    txt = probe()
    print(txt.rstrip())
    low = txt.lower()
    for p in LONG:
        # Windows 路径不区分大小写，exe_resolve 也可能回填成别的写法
        check("长路径也能枚举出来：%s" % os.path.basename(p)[:46],
              p.lower() in low, "没找到 " + p)

    print()
    print("--- 关键：不存在的路径不能被列出来（不能列出来点不动）")
    # 放到本程序私有的历史里测，不碰 OpenWithList —— LONG 有9 条，
    # 槽位只有 8 个，往 OpenWithList 塞ghost 会挤掉 LONG 的最后一条，
    # 断言失败看着像 bug，其实是测试自己污染了数据（上一版就这么错的）。
    del_tree(winreg.HKEY_CURRENT_USER, PRIV)
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, PRIV)
    winreg.SetValueEx(k, "a", 0, winreg.REG_SZ,
                      r"C:\不存在的程序\ghost_xyz.exe")
    winreg.SetValueEx(k, "MRUList", 0, winreg.REG_SZ, "a")
    winreg.CloseKey(k)
    txt2 = probe()
    check("磁盘上不存在的条目不会出现在列表里", "ghost_xyz" not in txt2)
finally:
    # ---- 原样还原用户真实的打开方式历史 ----
    del_tree(winreg.HKEY_CURRENT_USER, OWL)
    del_tree(winreg.HKEY_CURRENT_USER, PRIV)
    if backup:
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, OWL)
        for nm, val in backup.items():
            winreg.SetValueEx(k, nm, 0, winreg.REG_SZ, val)
        winreg.CloseKey(k)
    print()
    print("已还原用户原始OpenWithList（%d 个值）" % len(backup))
    if os.path.exists(OUT):
        os.remove(OUT)

print()
print("=" * 64)
if fails:
    print("失败 %d / %d 项: %s" % (len(fails), len(oks) + len(fails),
                                   ", ".join(fails)))
    sys.exit(1)
print("全部 %d 项通过" % len(oks))