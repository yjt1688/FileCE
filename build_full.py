# -*- coding: utf-8 -*-
"""完整构建(工具链在 C:\\Program Files\\mingw64)。"""
import subprocess, os, glob

os.chdir(r"C:\Users\Administrator\WorkBuddy\2026-09-28-10-58-39\FileCE")
BINDIR = r"C:\mingw64\bin"
os.environ["PATH"] = BINDIR + ";" + os.environ.get("PATH", "")
GCC = os.path.join(BINDIR, "x86_64-w64-mingw32-gcc.exe")
WINDRES = os.path.join(BINDIR, "windres.exe")
CFLAGS = ("-std=c17 -Os -municode -mwindows -Wall -Wextra -Wno-unused-parameter "
          "-Wno-cast-function-type -DUNICODE -D_UNICODE -D_WIN32_WINNT=0x0601 "
          "-DWINVER=0x0601 -ffunction-sections -fdata-sections "
          "-fno-strict-aliasing -fno-asynchronous-unwind-tables -flto "
          "-fomit-frame-pointer -fno-stack-check -fno-stack-protector "
          "-fno-ident -fno-math-errno -fno-tree-vectorize "
          "-fno-align-functions -fno-align-loops -fno-align-jumps "
          "-fno-reorder-blocks -fno-peephole2 -c").split()
LDFLAGS = ("-municode -mwindows -static -static-libgcc -s -flto -Wl,--gc-sections "
           "-Wl,--nxcompat -Wl,--dynamicbase -Wl,-O1 -Wl,--sort-common "
           "-lcomctl32 -lshell32 -lshlwapi -lole32 -luuid -lgdi32 -luser32 "
           "-ladvapi32 -lcomdlg32 -luxtheme -lkernel32").split()

# windres(若 res 需要更新)
# --codepage=65001：.rc 是 UTF-8（无 BOM），windres 默认按系统 ANSI(GBK) 读，
# 会把中文版本信息编成乱码 —— 任务管理器里显示成"锛堝嚱"那种就是它。
r = subprocess.run([WINDRES, "--codepage=65001", "-I", "res", "-O", "coff",
                    "-o", os.path.join("build", "app.res"),
                    os.path.join("res", "app.rc")], capture_output=True, text=True, errors="replace")
print("windres rc=", r.returncode)

ok = True
objs = []
for f in sorted(glob.glob(os.path.join("src", "*.c"))):
    o = f.replace("src", "build").replace(".c", ".o")
    objs.append(o)
    cmd = [GCC, "-B", os.path.join(BINDIR)] + CFLAGS + [f, "-o", o]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode:
        ok = False
        print(os.path.basename(f), "FAILED:")
        print(r.stderr[-400:])
print("compiled:", ok)

EXE = os.path.join("build", "FileCE.exe")
if ok:
    # 先删掉旧的 exe：Windows 上程序正在运行时会锁定目标文件，
    # 链接器写不进去却仍可能返回 0 —— 于是"构建成功、exe 却没变"，
    # 改了半天代码测的全是旧版（踩过这个坑）。删掉能让失败暴露出来。
    if os.path.exists(EXE):
        try:
            os.remove(EXE)
        except OSError as e:
            print("!! 无法删除旧 exe（多半是程序还开着）:", e)
    r = subprocess.run([GCC, "-B", os.path.join(BINDIR)] + objs +
                       [os.path.join("build", "app.res"), "-o", EXE] + LDFLAGS,
                       capture_output=True, text=True, errors="replace")
    print("link rc=", r.returncode)
    if r.returncode:
        print(r.stderr[-400:])

if not os.path.exists(EXE):
    print("!! 构建失败：没有生成 exe")
    raise SystemExit(1)

# 校验 exe 确实比所有源码/头文件新，否则就是链接没生效
newest = 0.0
for pat in ("src/*.c", "src/*.h", "res/*.rc", "res/*.h"):
    for f in glob.glob(pat):
        newest = max(newest, os.path.getmtime(f))
if os.path.getmtime(EXE) < newest:
    print("!! exe 比源码旧 —— 链接没有真正生效（程序是不是正开着？先关掉再构建）")
    raise SystemExit(1)

print("exe:", os.path.getsize(EXE), "字节")
