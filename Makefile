# FileCE —— 纯 C / Win32 文件管理器
# 目标：Windows 7 SP1 x64 ~ Windows 11，静态链接，单一 exe
#
# 用法：
#   make            生成 build/FileCE.exe
#   make clean      清理中间产物
#
# 依赖：x86_64-w64-mingw32-gcc (MSYS2 / MinGW-w64)，自带 windres

CC       := x86_64-w64-mingw32-gcc
WINDRES  := windres

SRCDIR   := src
RESDIR   := res
BUILDDIR := build
TARGET   := $(BUILDDIR)/FileCE.exe

# 体积优先：-Os + 函数/数据分段 + 链接期回收死段（--gc-sections）+ LTO，
# 再配合 LDFLAGS 里的 -s（strip）。不要用 -O2/-O3，会明显撑大 exe。
#
# 【-fno-asynchronous-unwind-tables 必须留着】
# x64 上每个函数都要一条 RUNTIME_FUNCTION（12 字节）进 .pdata，
# UNWIND_INFO 进 .xdata。不加这个开关，这两节从 3.9KB 涨到 9.4KB，
# exe 直接多 2.5KB，能把 LTO 省下来的代码体积全吃掉。
# 本程序不用 __try/__except，删异步 unwind 表是安全的。
#
# 【别加 -fno-peephole2 / -fno-reorder-blocks / -fno-tree-vectorize】
# 这些是"禁用优化"，实测 .text 反而涨 3.5KB（152,528 vs 149,008），
# 禁用对齐省下的那点字节远不够赔。当前配置实测 205KB。
CFLAGS := -std=c17 -Os -municode -mwindows \
          -Wall -Wextra -Wno-unused-parameter -Wno-cast-function-type \
          -DUNICODE -D_UNICODE -D_WIN32_WINNT=0x0601 -DWINVER=0x0601 \
          -ffunction-sections -fdata-sections -fno-strict-aliasing \
          -fno-asynchronous-unwind-tables \
          -flto=1

LDFLAGS := -municode -mwindows -static -static-libgcc -s -flto=1 \
           -Wl,--gc-sections -Wl,--nxcompat -Wl,--dynamicbase \
           -Wl,-O1 -Wl,--sort-common \
           -lcomctl32 -lshell32 -lshlwapi -lole32 -luuid \
           -lgdi32 -luser32 -ladvapi32 -lcomdlg32 -luxtheme -lkernel32

SRCS := $(wildcard $(SRCDIR)/*.c)
OBJS := $(patsubst $(SRCDIR)/%.c,$(BUILDDIR)/%.o,$(SRCS))
RES  := $(BUILDDIR)/app.res

.PHONY: all clean run

all: $(TARGET)

$(TARGET): $(OBJS) $(RES)
	$(CC) $(OBJS) $(RES) -o $@ $(LDFLAGS)
	@echo "==> build ok: $@"

$(BUILDDIR)/%.o: $(SRCDIR)/%.c $(SRCDIR)/ff.h | $(BUILDDIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(RES): $(RESDIR)/app.rc $(RESDIR)/app.manifest $(RESDIR)/app.ico | $(BUILDDIR)
	$(WINDRES) -I $(RESDIR) -O coff -o $@ $<

$(BUILDDIR):
	@mkdir -p $(BUILDDIR)

run: all
	./$(BUILDDIR)/FileCE.exe

clean:
	@rm -rf $(BUILDDIR)
	@echo "==> cleaned"
