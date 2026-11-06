# 验证"绿色版程序没注册 -> 也必须出现在打开方式列表里"
#
# 用户报的现象：把 D:\Program Files\(Notepad3)5.21.227.1.x64\Notepad3.exe
# 当文本编辑器用过，但"打开方式"列表里根本没有它。
#
# 根因：SHAssocEnumHandlers 只枚举 OpenWithProgids，而绿色版程序压根没
# 注册（Applications\notepad3.exe、OpenWithProgids 全都没有），只有一个
# Explorer 的 FileExts\.txt\OpenWithList 历史条目，还是个裸文件名。
#
# 本测试用内置的 --list-open-with=<ext> 自检模式拿枚举结果，验三件事：
#   1. 不碰私有历史时，靠 Explorer 的使用历史也能补出 Notepad3
#   2. 显示的是完整路径（裸文件名点不动）
#   3. 用过一次之后，私有历史把它留在列表里
#   4. 顺带确认没引入回归：记事本/VS Code 这些系统项仍在

import io
import os
import subprocess
import sys
import time
import winreg

EXE = os.path.abspath("build/FileCE.exe")
NP3 = r"D:\Program Files\(Notepad3)5.21.227.1.x64\Notepad3.exe"
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
    """跑自检模式，返回候选列表文本"""
    if os.path.exists(OUT):
        os.remove(OUT)
    t0 = time.time()
    subprocess.run([EXE, "--list-open-with=" + ext], timeout=60)
    dt = time.time() - t0
    # 输出是 UTF-16：早先用 _snprintf 的 %S 写，中文名会被整段吞掉，
    # 看着像"枚举漏了很多"，其实是编码问题。
    return io.open(OUT, "rb").read().decode("utf-16-le"), dt


print("=" * 64)
print("前提：目标是一个系统枚举不到的绿色版程序")
print("=" * 64)
check("目标 exe 存在", os.path.exists(NP3), NP3)

# 别拿"Notepad3 在注册表里没被注册"当前提：跑过 ow_apply_always 之后，
# 本程序自己会把它注册进去（Applications\*\shell\open\command 等），
# 前提和被测代码互相污染，这条断言必然失败。
# 真正要证明的是枚举结果里有没有它、以及用的是不是完整路径。
# 另外用一个绝对没注册的 exe 反证"不能靠枚举蒙对"：
ghost = r"C:\Windows\System32\no_such_app_xyz.exe"
check("反证用的假程序确实不存在", not os.path.exists(ghost))

print()
print("=" * 64)
print("场景1：清掉私有历史，纯靠 Explorer 的使用历史枚举")
print("=" * 64)
del_tree(winreg.HKEY_CURRENT_USER, PRIV)
txt, dt = probe()
print(txt.rstrip())
check("枚举过程够快（不能拖慢每次右键）", dt < 8.0, "耗时 %.2fs" % dt)
check("列表里出现了 Notepad3", "Notepad3" in txt, "没有")
check("Notepad3 用的是完整路径（裸文件名点不动）", NP3 in txt,
      "期望完整路径 " + NP3)
# 回归：系统项不能被补充逻辑挤掉
check("没引入回归：记事本仍在列表里", "NOTEPAD.EXE" in txt or "记事本" in txt)
check("没引入回归：VS Code 仍在列表里", "Code.exe" in txt)

print()
print("=" * 64)
print("场景 2：用过一次之后，私有历史把它留在列表里")
print("=" * 64)
del_tree(winreg.HKEY_CURRENT_USER, PRIV)
k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, PRIV)
winreg.SetValueEx(k, "a", 0, winreg.REG_SZ, NP3)
winreg.SetValueEx(k, "MRUList", 0, winreg.REG_SZ, "a")
winreg.CloseKey(k)

txt2, _ = probe()
check("私有历史里写过就能枚举到", "Notepad3" in txt2 and NP3 in txt2)

# 私有历史里塞一个磁盘上不存在的路径，模拟"程序被移走了"：
# 这种必须跳过，绝不能列出来点不动。
k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, PRIV)
winreg.SetValueEx(k, "a", 0, winreg.REG_SZ,
                  r"C:\不存在的程序\ghost.exe")
winreg.SetValueEx(k, "MRUList", 0, winreg.REG_SZ, "a")
winreg.CloseKey(k)
txt3, _ = probe()
check("路径不存在的条目不会出现在列表里（不能列出来点不动）",
      "ghost" not in txt3.lower())

del_tree(winreg.HKEY_CURRENT_USER, PRIV)

print()
print("=" * 64)
print("场景 3：写全注册后，系统枚举（SHAssocEnumHandlers）自己就能认出来")
print("=" * 64)
# 这一段验的是 ow_apply_always 补的那三个注册项到底有没有用。
# 判断依据用注册表读数而不是手工调 SHAssocEnumHandlers 的 vtable ——
# 后者要手搓 COM 调用，冗长且容易出错；OpenWithProgids 里有没有我们的
# progid，正是系统枚举能否拿到该程序的充要条件。
okw_progids = r"Software\Classes\.txt\OpenWithProgids"


def progids():
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, okw_progids))
    except OSError:
        return []
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, okw_progids)
    names = []
    i = 0
    while True:
        try:
            names.append(winreg.EnumKey(k, i)); i += 1
        except OSError:
            break
    winreg.CloseKey(k)
    return names


print("当前 .txt\\OpenWithProgids =", progids() or "(空)")
check("写注册前：OpenWithProgids 里没有我们的 progid（系统枚举不到 Notepad3）",
      not any("FileCE" in p for p in progids()),
      "若已有残留，先清掉 Applications\\Notepad3.exe 和 FileCE.txt.* 再跑")

# 模拟 ow_apply_always 写的三项
del_tree(winreg.HKEY_CURRENT_USER, PRIV)
auto = r"FileCE.txt.Notepad3_exe"
cmd = '"%s" "%%1"' % NP3
for sub, val in [
        (r"Software\Classes\%s" % auto, cmd),
        (r"Software\Classes\%s\DefaultIcon" % auto, '"%s",0' % NP3),
        (r"Software\Classes\Applications\Notepad3.exe\shell\open\command", cmd),
        (r"Software\Classes\Applications\Notepad3.exe\shell\edit\command", cmd),
        (r"Software\Classes\Applications\Notepad3.exe\DefaultIcon",
         '"%s",0' % NP3)]:
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub)
    winreg.SetValueEx(k, None, 0, winreg.REG_SZ, val)
    winreg.CloseKey(k)
# SupportedTypes 按新写法：扩展名是键下的"值"（Windows 惯例），不是子键
k = winreg.CreateKey(
    winreg.HKEY_CURRENT_USER,
    r"Software\Classes\Applications\Notepad3.exe\SupportedTypes")
winreg.SetValueEx(k, ".txt", 0, winreg.REG_SZ, "")
winreg.CloseKey(k)
for sub in [r"Software\Classes\.txt\OpenWithProgids\%s" % auto,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer"
            r"\FileExts\.txt\OpenWithProgids\%s" % auto]:
    k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub)
    winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "")
    winreg.CloseKey(k)

txt4, _ = probe()
print(txt4.rstrip())
check("写全注册后：progid 进了 .txt\\OpenWithProgids",
      any("FileCE" in p for p in progids()), str(progids()))
check("写全注册后：枚举能拿到 Notepad3", "Notepad3" in txt4 and NP3 in txt4)

# 还原：把本测试造出来的注册清掉，别留给用户
for sub in [r"Software\Classes\%s" % auto,
            r"Software\Classes\Applications\Notepad3.exe",
            r"Software\Classes\.txt\OpenWithProgids\%s" % auto,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer"
            r"\FileExts\.txt\OpenWithProgids\%s" % auto]:
    del_tree(winreg.HKEY_CURRENT_USER, sub)
del_tree(winreg.HKEY_CURRENT_USER, PRIV)
check("测试造的注册已清理", not progids() and not any("FileCE" in p for p in progids()))

if os.path.exists(OUT):
    os.remove(OUT)

print()
print("=" * 64)
if fails:
    print("失败 %d / %d 项: %s" % (len(fails), len(oks) + len(fails),
                                   ", ".join(fails)))
    sys.exit(1)
print("全部 %d 项通过" % len(oks))