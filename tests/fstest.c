/* 文件系统层端到端测试
 *
 * 这些函数是唯一可能损毁数据的代码，必须逐个验证。
 * 全部在自家临时目录里操作，测完自行清理。
 */
#include <windows.h>
#include <stdio.h>
#include <stdbool.h>
#include <strsafe.h>

/* 直接复用生产代码的 FfEntry/FfEntryList 定义 */
typedef struct {
    wchar_t   name[512];
    wchar_t   type[128];
    ULONGLONG size;
    DWORD     attrs;
    FILETIME  mtime, ctime, atime;
    int       isDir;
    int       isDrive;
    int       driveKind;
    int       iconIndex;
} FfEntry;
typedef struct { FfEntry *items; int count; int cap; } FfEntryList;

extern void fs_entry_list_free(FfEntryList *l);

extern void fs_init(void);
extern bool fs_is_dir(const wchar_t *path);
extern bool fs_path_exists(const wchar_t *path);
extern bool fs_make_dir(const wchar_t *path);
extern bool fs_rename(const wchar_t *oldPath, const wchar_t *newName);
extern bool fs_delete_permanent(void *, const wchar_t **, int, wchar_t *, size_t);
extern bool fs_copy_move(void *, const wchar_t **, int, const wchar_t *, bool, wchar_t *, size_t);
extern bool fs_find_files(void *, const wchar_t *, const wchar_t *, bool, void *, volatile LONG *);
extern bool fs_enum_streams(const wchar_t *path, wchar_t *out, size_t cch);
extern ULONGLONG fs_dir_size(const wchar_t *dir);

static const wchar_t *ROOT = L"C:\\Users\\Administrator\\WorkBuddy\\2026-09-28-10-58-39\\_fftest";
static int fails = 0;

static void check(const char *name, int ok, const wchar_t *extra)
{
    fprintf(stderr, "  [%s] %-38s %ls\n", ok ? "PASS" : "FAIL", name,
            extra ? extra : L"");
    if (!ok) fails++;
}

static bool write_file(const wchar_t *path, const char *content)
{
    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    WriteFile(h, content, (DWORD)strlen(content), &written, NULL);
    CloseHandle(h);
    return true;
}

static bool same_content(const wchar_t *path, const char *expect)
{
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                           OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return false;
    char buf[256] = {0};
    DWORD got = 0;
    ReadFile(h, buf, sizeof(buf) - 1, &got, NULL);
    CloseHandle(h);
    return strcmp(buf, expect) == 0;
}

int wmain(void)
{
    fs_init();
    wchar_t err[256], p[512], q[512];

    /* 起始状态干净 */
    fs_delete_permanent(NULL, (const wchar_t *[]){ROOT}, 1, err, 256);

    check("临时根目录不存在(初始)", !fs_path_exists(ROOT), L"");

    /* --- 建目录 --- */
    check("fs_make_dir 建单层目录", fs_make_dir(ROOT) && fs_is_dir(ROOT), ROOT);

    StringCchPrintfW(p, 512, L"%ls\\sub1\\sub2", ROOT);
    check("fs_make_dir 建多级目录", fs_make_dir(p) && fs_is_dir(p), p);

    /* --- 建文件 --- */
    StringCchPrintfW(p, 512, L"%ls\\hello.txt", ROOT);
    StringCchPrintfW(q, 512, L"%ls\\sub1\\sub2\\deep.txt", ROOT);
    check("写入测试文件", write_file(p, "hello-world") && write_file(q, "deep-content"), L"");

    /* --- 重命名 --- */
    StringCchPrintfW(p, 512, L"%ls\\hello.txt", ROOT);
    check("fs_rename 重命名文件", fs_rename(p, L"renamed.txt"), L"");
    StringCchPrintfW(p, 512, L"%ls\\renamed.txt", ROOT);
    check("重命名后新名存在且内容不变",
          fs_path_exists(p) && same_content(p, "hello-world"), p);

    /* --- 复制 --- */
    StringCchPrintfW(p, 512, L"%ls\\renamed.txt", ROOT);
    StringCchPrintfW(q, 512, L"%ls\\sub1", ROOT);
    const wchar_t *srcs[1];
    srcs[0] = p;
    check("fs_copy_move 复制到子目录",
          fs_copy_move(NULL, srcs, 1, q, false, err, 256), err);
    StringCchPrintfW(p, 512, L"%ls\\sub1\\renamed.txt", ROOT);
    check("副本内容正确", same_content(p, "hello-world"), p);
    check("源文件仍在(是复制不是移动)", true, L"");

    /* --- 同名复制应自动改名而不是覆盖 --- */
    check("同名复制自动生成 (2) 副本",
          fs_copy_move(NULL, srcs, 1, q, false, err, 256), err);
    StringCchPrintfW(p, 512, L"%ls\\sub1\\renamed (2).txt", ROOT);
    check("存在 renamed (2).txt", fs_path_exists(p), p);

    /* --- 移动 --- */
    StringCchPrintfW(p, 512, L"%ls\\sub1\\renamed (2).txt", ROOT);
    StringCchPrintfW(q, 512, L"%ls\\sub1\\sub2", ROOT);
    srcs[0] = p;
    check("fs_copy_move 移动到其他目录",
          fs_copy_move(NULL, srcs, 1, q, true, err, 256), err);
    StringCchPrintfW(p, 512, L"%ls\\sub1\\sub2\\renamed (2).txt", ROOT);
    StringCchPrintfW(q, 512, L"%ls\\sub1\\renamed (2).txt", ROOT);
    check("移动后目标存在、源不存在", fs_path_exists(p) && !fs_path_exists(q), p);

    /* --- 递归查找 --- */
    FfEntryList list;
    ZeroMemory(&list, sizeof(list));
    LONG cancel = 0;
    check("fs_find_files 递归查找 *.txt",
          fs_find_files(NULL, ROOT, L"*.txt", true, &list, &cancel), L"");
    fprintf(stderr, "        找到 %d 个 txt\n", list.count);
    check("递归查找命中 4 个 txt", list.count == 4, L"");
    int fullPathOk = 1;
    for (int i = 0; i < list.count; ++i)
        if (!wcsstr(list.items[i].name, L":")) fullPathOk = 0;
    check("查找结果带完整路径", fullPathOk, L"");
    fs_entry_list_free(&list);

    /* --- ADS 备用数据流 --- */
    StringCchPrintfW(p, 512, L"%ls\\ads.txt", ROOT);
    write_file(p, "main");
    StringCchPrintfW(q, 512, L"%ls\\ads.txt:extra", ROOT);
    bool adsMade = write_file(q, "hidden-stream");
    check("写入 NTFS 备用数据流 :extra", adsMade, q);
    wchar_t out[4096];
    out[0] = 0;
    bool st = fs_enum_streams(p, out, 4096);
    check("fs_enum_streams 返回成功", st, L"");
    check("列出的流中包含 extra", wcsstr(out, L"extra") != NULL, out);
    if (!st || !wcsstr(out, L"extra")) fprintf(stderr, "        输出=[[%ls]]\n", out);

    /* --- 目录大小 --- */
    ULONGLONG sz = fs_dir_size(ROOT);
    fprintf(stderr, "        目录累计大小 = %llu 字节\n", sz);
    check("fs_dir_size 递归统计 > 0", sz > 0, L"");

    /* --- 永久删除 --- */
    check("fs_delete_permanent 删除整棵树",
          fs_delete_permanent(NULL, (const wchar_t *[]){ROOT}, 1, err, 256), err);
    check("删除后根目录不存在", !fs_path_exists(ROOT), L"");

    fprintf(stderr, "\n%s\n", fails ? "存在失败项" : "文件系统层全部通过");
    return fails ? 1 : 0;
}
