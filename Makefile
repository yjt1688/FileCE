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

# 体积优先：-Os + 函数/数据分段 + 链接期回收死段（--gc-sections），
# 再配合 LDFLAGS 里的 -s（strip）。不要用 -O2/-O3，会明显撑大 exe。
CFLAGS := -std=c17 -Os -municode -mwindows \
          -Wall -Wextra -Wno-unused-parameter -Wno-cast-function-type \
          -DUNICODE -D_UNICODE -D_WIN32_WINNT=0x0601 -DWINVER=0x0601 \
          -ffunction-sections -fdata-sections -fno-strict-aliasing \
          -fno-asynchronous-unwind-tables -fomit-frame-pointer \
          -fno-stack-check -fno-stack-protector -fno-ident \
          -fno-math-errno -fno-tree-vectorize \
          -fno-align-functions -fno-align-loops -fno-align-jumps \
          -fno-reorder-blocks -fno-peephole2

LDFLAGS := -municode -mwindows -static -static-libgcc -s \
           -Wl,--gc-sections -Wl,--nxcompat -Wl,--dynamicbase \
           -Wl,-O1 -Wl,--sort-common \
           -lcomctl32 -lshell32 -lshlwapi -lole32 -luuid \
           -lgdi32 -luser32 -ladvapi32 -lcomdlg32 -luxtheme -lkernel32

SRCS := $(wildcard $(SRCDIR)/*.c)
OBJS := $(patsubst $(SRCDIR)/%.c,$(BUILDDIR)/%.o,$(SRCS))
RES  := $(BUILDDIR)/app.res

.PHONY: all clean icon run

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

icon:
	python $(RESDIR)/make_icon.py || python3 $(RESDIR)/make_icon.py

run: all
	./$(BUILDDIR)/FileCE.exe

clean:
	@rm -rf $(BUILDDIR)
	@echo "==> cleaned"
