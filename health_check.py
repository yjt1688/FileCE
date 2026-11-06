# -*- coding: utf-8 -*-
"""全面体检:1) 源码反斜杠残留 2) 未初始化/可疑模式 3) 调试残留 4) 大数组回归"""
import os, re, glob

os.chdir(r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE")
issues = []

# 1) 编译器会抓转义,但检查明显残留(如 L'\ 单字符)
for f in glob.glob("src/*.c"):
    s = open(f, encoding="utf-8", errors="replace").read()
    for i, line in enumerate(s.splitlines(), 1):
        if re.search(r"L'\\'[^\\]", line) or re.search(r"'\\'", line):
            issues.append("%s:%d 可疑单反斜杠字符字面量: %s" % (f, i, line.strip()[:80]))

# 2) 调试残留
for f in glob.glob("src/*.c"):
    s = open(f, encoding="utf-8", errors="replace").read()
    for pat, desc in ((r"RED TEST|DECISIVE TEST|YELLOW", "实验标记"),
                      (r"ff_dbg\(L\"crumb_paint", "paint DBG"),
                      (r"ff_dbg\(L\"crumb_parse", "parse DBG")):
        for m in re.finditer(pat, s):
            ln = s[:m.start()].count("\n") + 1
            issues.append("%s:%d 调试残留(%s)" % (f, ln, desc))

# 3) 堆化完整性:静态大数组是否清零(会进 .data 撑体积)
for f in glob.glob("src/*.c"):
    s = open(f, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"static\s+\w+[\w\s\*]*\s+(\w+)\[(\d{3,})\]\s*;", s):
        name, cnt = m.group(1), int(m.group(2))
        ln = s[:m.start()].count("\n") + 1
        if cnt >= 256:
            issues.append("%s:%d 大静态数组 %s[%d](若为零初始化,会占 exe 体积)"
                          % (f, ln, name, cnt))

# 4) FFDBG 条件:DBG 宏在非 FFDBG 时为空(正常),但确认没有无条件 ff_dbg 调用
for f in glob.glob("src/*.c"):
    s = open(f, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"(?<!Def )\bff_dbg\(", s):
        ln = s[:m.start()].count("\n") + 1
        line = s.splitlines()[ln - 1].strip()
        if "void ff_dbg" not in line and "extern void ff_dbg" not in line:
            issues.append("%s:%d 无条件 ff_dbg 调用(应使用 DBG 宏): %s"
                          % (f, ln, line[:70]))

if issues:
    print("发现 %d 项:" % len(issues))
    for i in issues:
        print("  -", i)
else:
    print("体检通过:无反斜杠残留/调试残留/大静态数组/无条件 DBG")
