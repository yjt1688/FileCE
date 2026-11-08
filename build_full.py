# build_full.py —— 全量构建（-flto=1，产出约 204KB 的单文件 exe）
#
# 用法：python build_full.py
#
# 与 Makefile 的区别：Makefile 不带 -flto，编出来约 241KB；这里编译和链接都带
# -flto=1（单线程，省内存），能省 38KB 左右。两个都能用，看要体积还是标准流程。
import glob, os, subprocess, sys

BINDIR = r"C:\mingw64\bin"
GCC = os.path.join(BINDIR, "x86_64-w64-mingw32-gcc.exe")
WINDRES = os.path.join(BINDIR, "windres.exe")
EXE = os.path.join("build", "FileCE.exe")
RES = os.path.join("build", "app.res")

# gcc 在 LTO 模式下内存吃得多，--param 让它更积极地回收
CFLAGS = ["-std=c17", "-Os", "-municode", "-mwindows",
          "-Wall", "-Wextra", "-Wno-unused-parameter", "-Wno-cast-function-type",
          "-DUNICODE", "-D_UNICODE", "-D_WIN32_WINNT=0x0601", "-DWINVER=0x0601",
          "-ffunction-sections", "-fdata-sections", "-fno-strict-aliasing",
          # 关键：不加这个，x64 的 .pdata/.xdata 会从 3.9KB 涨到 9.4KB
          # （每函数一条 12 字节的 RUNTIME_FUNCTION）。实测 exe 直接多 2.5KB，
          # 而且会把 -flto 省下来的代码体积全部吃掉。
          # 本程序不用 __try/__except，删异步 unwind 表是安全的。
          "-fno-asynchronous-unwind-tables",
          # 注意：Makefile 里那套 -fno-peephole2 / -fno-reorder-blocks /
          # -fno-tree-vectorize 等**不要**加 —— 它们是禁用优化，实测会让
          # .text 涨 3.5KB（152,528 vs 149,008），反而更大。
          "-flto=1", "--param", "ggc-min-expand=20",
          "--param", "ggc-min-heapsize=65536"]
LDFLAGS = ["-municode", "-mwindows", "-static", "-static-libgcc", "-s", "-flto=1",
           "-Wl,--gc-sections", "-Wl,--nxcompat", "-Wl,--dynamicbase",
           "-Wl,-O1", "-Wl,--sort-common",
           "-lcomctl32", "-lshell32", "-lshlwapi", "-lole32", "-luuid",
           "-lgdi32", "-luser32", "-ladvapi32", "-lcomdlg32", "-luxtheme",
           "-lkernel32"]

os.makedirs("build", exist_ok=True)

# 资源：--codepage=65001 让中文版本信息正确（app.rc 里还有 #pragma 双保险）
r = subprocess.run([WINDRES, "--codepage=65001", "-I", "res", "-O", "coff",
                    "-o", RES, os.path.join("res", "app.rc")],
                   capture_output=True, text=True, errors="replace")
print("windres rc=", r.returncode)
if r.returncode:
    print(r.stderr[:400])
    sys.exit(1)

# 每次全量：先清旧的 .o（避免沿用上一轮不同参数编出来的对象）
for f in glob.glob(os.path.join("build", "*.o")):
    os.remove(f)

objs = []
fails = 0
for f in sorted(glob.glob(os.path.join("src", "*.c"))):
    o = os.path.join("build", os.path.basename(f)[:-2] + ".o")
    cmd = [GCC] + CFLAGS + ["-c", f, "-o", o]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    size = os.path.getsize(o) if os.path.exists(o) else 0
    if r.returncode != 0:
        fails += 1
        print("!! %s 失败 (rc=%d)" % (os.path.basename(f), r.returncode))
        print("   命令:", " ".join(cmd))
        print("   错误:", r.stderr.strip()[:300])
    else:
        objs.append(o)
        print("   %-14s -> %7d 字节%s" % (os.path.basename(f), size,
                                          "  (无LTO!)" if size > 100000 else ""))

print("compiled:", fails == 0, " 成功 %d / 失败 %d" % (len(objs), fails))
if fails:
    sys.exit(1)

# 先删旧 exe：程序正开着时链接写不进去却仍返回 0，会变成"构建成功但 exe 没变"
if os.path.exists(EXE):
    try:
        os.remove(EXE)
    except OSError as e:
        print("!! 无法删除旧 exe（多半是程序还开着）:", e)
        sys.exit(1)

r = subprocess.run([GCC] + objs + [RES, "-o", EXE] + LDFLAGS,
                   capture_output=True, text=True, errors="replace")
print("link rc=", r.returncode)
if r.returncode:
    print(r.stderr[-500:])
    sys.exit(1)

if not os.path.exists(EXE):
    print("!! 构建失败：没有生成 exe")
    sys.exit(1)

newest = 0.0
for pat in ("src/*.c", "src/*.h", "res/*.rc", "res/*.h"):
    for f in glob.glob(pat):
        newest = max(newest, os.path.getmtime(f))
if os.path.getmtime(EXE) < newest:
    print("!! exe 比源码旧 —— 链接没有真正生效")
    sys.exit(1)

print("exe:", os.path.getsize(EXE), "字节")
