# -*- coding: utf-8 -*-
"""等价 make：按 Makefile 的参数全量重编（make 本机不存在）"""
import os, sys, glob, subprocess, time

BASE = r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE"
os.chdir(BASE)
CC = r"C:\mingw64\bin\x86_64-w64-mingw32-gcc.exe"
WINDRES = r"C:\mingw64\bin\windres.exe"

CFLAGS = ("-std=c17 -Os -municode -mwindows "
          "-Wall -Wextra -Wno-unused-parameter -Wno-cast-function-type "
          "-DUNICODE -D_UNICODE -D_WIN32_WINNT=0x0601 -DWINVER=0x0601 "
          "-ffunction-sections -fdata-sections -fno-strict-aliasing "
          "-fno-asynchronous-unwind-tables -fomit-frame-pointer "
          "-fno-stack-check -fno-stack-protector -fno-ident "
          "-fno-math-errno -fno-tree-vectorize "
          "-fno-align-functions -fno-align-loops -fno-align-jumps "
          "-fno-reorder-blocks -fno-peephole2").split()
LDFLAGS = ("-municode -mwindows -static -static-libgcc -s "
           "-Wl,--gc-sections -Wl,--nxcompat -Wl,--dynamicbase "
           "-Wl,-O1 -Wl,--sort-common "
           "-lcomctl32 -lshell32 -lshlwapi -lole32 -luuid "
           "-lgdi32 -luser32 -ladvapi32 -lcomdlg32 -luxtheme -lkernel32").split()

os.makedirs("build", exist_ok=True)
exe = os.path.join("build", "FileCE.exe")
res = os.path.join("build", "app.res")

# 1) 资源
r = subprocess.run([WINDRES, "-I", "res", "-O", "coff", "-o", res, "res/app.rc"],
                   capture_output=True, text=True, errors="replace")
print("windres rc=", r.returncode)
if r.returncode:
    print(r.stderr[:400]); sys.exit(1)

# 2) 全量编译（先删旧 .o，避免增量残留）
for f in glob.glob("build/*.o"):
    os.remove(f)
objs, warns, errs = [], 0, 0
for f in sorted(glob.glob("src/*.c")):
    o = os.path.join("build", os.path.basename(f)[:-2] + ".o")
    objs.append(o)
    r = subprocess.run([CC] + CFLAGS + ["-c", f, "-o", o],
                       capture_output=True, text=True, errors="replace")
    w = r.stderr.count("warning:")
    e = r.stderr.count("error:")
    warns += w; errs += e
    if e:
        print("!! %s 编译失败:" % f)
        print(r.stderr[-500:])
        sys.exit(1)
    if w:
        print("   %s: %d 个告警" % (os.path.basename(f), w))
print("编译: %d 个 .o，错误 %d，告警 %d" % (len(objs), errs, warns))

# 3) 链接（先删旧 exe —— 被占用的进程会让链接静默失败）
if os.path.exists(exe):
    os.remove(exe)
r = subprocess.run([CC] + objs + [res, "-o", exe] + LDFLAGS,
                   capture_output=True, text=True, errors="replace")
print("link rc=", r.returncode)
if r.returncode:
    print(r.stderr[-500:]); sys.exit(1)

if not os.path.exists(exe):
    print("!! 没有生成 exe"); sys.exit(1)

newest = max(os.path.getmtime(f) for pat in ("src/*.c", "src/*.h", "res/*")
             for f in glob.glob(pat))
if os.path.getmtime(exe) < newest:
    print("!! exe 比源码旧 —— 链接没生效（程序是不是还开着？）"); sys.exit(1)

print("exe:", os.path.getsize(exe), "字节  ", time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(exe))))
