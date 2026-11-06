# -*- coding: utf-8 -*-
# 验证"打开方式列表按扩展名过滤，不把不相干的程序一锅端"
#
# 用户报的现象：右键打开方式里塞了一大堆程序 —— JPG 里也有记事本、
# Word、写字板、WMP，TXT 里也有画图。是什么扩展名就该用什么程序打。
#
# 根因有两个：
#   1. SHAssocEnumHandlers(ASSOC_FILTER_NONE) 会把系统里注册过的所有
#      程序都倒出来，不分扩展名；
#   2. ow_supplement 照单全收 Explorer 的 FileExts\<ext>\OpenWithList
#      —— 拿画图开过 txt 它也记，我们也跟着列。
#
# 修法：
#   - 系统枚举只留 ASSOC_FILTER_RECOMMENDED；
#   - 历史补齐的条目过"门当户对"检查：程序自己声明了 SupportedTypes
#     且不含该扩展名 -> 不列；没声明（绿色版程序）-> 照列。
#
# 本测试用内置 --list-open-with=<ext> 自检模式拿枚举结果，验证：
#   1. JPG 列表里没有记事本/Word/写字板/WMP/Qianwen
#   2. TXT 列表里没有画图/WMP
#   3. TXT 列表里仍有记事本、写字板、Notepad3（绿色版不退化）
#   4. JPG 列表里仍有图片类程序（画图/照片）

import io
import os
import subprocess
import time

EXE = os.path.abspath("build/FileCE.exe")
OUT = os.path.join(os.environ["TEMP"], "ffce_owlist.txt")

fails, oks = [], []


def check(name, cond, extra=""):
    (oks if cond else fails).append(name)
    print(("  OK   " if cond else "  FAIL ") + name +
          (("<< " + extra) if (extra and not cond) else ""))


def probe(ext):
    if os.path.exists(OUT):
        os.remove(OUT)
    t0 = time.time()
    subprocess.run([EXE, "--list-open-with=" + ext], timeout=60)
    dt = time.time() - t0
    return io.open(OUT, "rb").read().decode("utf-16-le"), dt


def names_of(text):
    """从自检输出里取每条的显示名。
    输出按 UTF-16 写，行首会残留一个 \\x00，必须去掉，否则 startswith('[')
    永远不成立、候选列表解析成空 —— 断言就会空转变全过。"""
    ns = []
    for ln in text.splitlines():
        ln = ln.replace("\x00", "").strip()
        if ln.startswith("[") and "]" in ln:
            ns.append(ln.split("]", 1)[1].split("|")[0].strip())
    return ns


print("=" * 64)
print("前提：本机 Explorer 历史里有'画图开过 txt'等交叉污染记录")
print("=" * 64)

jpg_txt, jpg_dt = probe(".jpg")
txt_txt, txt_dt = probe(".txt")
jpg_names = names_of(jpg_txt)
txt_names = names_of(txt_txt)

check("JPG 枚举有结果", len(jpg_names) > 0, jpg_txt)
check("TXT 枚举有结果", len(txt_names) > 0, txt_txt)
print("  JPG 列表: " + "、".join(jpg_names))
print("  TXT 列表: " + "、".join(txt_names))
print()

print("=" * 64)
print("1) 不相干的程序不得出现在 JPG 列表")
print("=" * 64)
for bad in ("记事本", "Word", "写字板", "Windows Media Player",
            "Qianwen", "Visual Studio Code", "Internet Explorer"):
    check("JPG 无 [%s]" % bad, bad not in jpg_names)
print()

print("=" * 64)
print("2) 不相干的程序不得出现在 TXT 列表")
print("=" * 64)
for bad in ("画图", "画图 3D", "Windows Media Player"):
    check("TXT 无 [%s]" % bad, bad not in txt_names)
print()

print("=" * 64)
print("3) 相干的程序必须留在 TXT 列表（含绿色版 Notepad3）")
print("=" * 64)
for good in ("记事本", "Notepad3"):
    check("TXT 有 [%s]" % good, good in txt_names)
print()

print("=" * 64)
print("4) 图片程序必须留在 JPG 列表")
print("=" * 64)
img_ok = any(n in jpg_names for n in ("画图", "照片", "画图 3D"))
check("JPG 有图片类程序(画图/照片/画图3D)", img_ok)
print()

print("=" * 64)
print("5) 枚举性能不倒退（去掉 NONE 遍历后应更快）")
print("=" * 64)
check("JPG 枚举 < 3s", jpg_dt < 3.0, "%.2fs" % jpg_dt)
check("TXT 枚举 < 3s", txt_dt < 3.0, "%.2fs" % txt_dt)

print()
print("=" * 64)
print("结果: %d 通过, %d 失败" % (len(oks), len(fails)))
print("=" * 64)
raise SystemExit(1 if fails else 0)
