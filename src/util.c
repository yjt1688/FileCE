/* util.c —— 字符串 / 路径 / 格式化 / 通用 UI 辅助 */
#include "ff.h"
#include <stdarg.h>

FfApp g_app;

/* 临时调试日志。DBG 宏只在 -DFFDBG 时展开为它，平时没有调用点，
 * --gc-sections 会把整个函数回收，不留体积负担。 */
void ff_dbg(const wchar_t *fmt, ...)
{
    FILE *f = fopen("C:\\Users\\Administrator\\AppData\\Local\\Temp\\ffce_dbg.log", "a");
    if (!f) return;
    va_list ap;
    va_start(ap, fmt);
    vfwprintf(f, fmt, ap);          /* 注意：msvcrt 的宽输出要用 %ls，%s 会截断 */
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

/* ---------------------------------------------------------------- 字符串 */
void ff_str_copy(wchar_t *dst, size_t cch, const wchar_t *src)
{
    if (!dst || cch == 0) return;
    if (!src) { dst[0] = 0; return; }
    size_t i = 0;
    while (i + 1 < cch && src[i]) { dst[i] = src[i]; ++i; }
    dst[i] = 0;
}

void ff_str_cat(wchar_t *dst, size_t cch, const wchar_t *src)
{
    if (!dst || !src || cch == 0) return;
    size_t n = wcslen(dst);
    if (n >= cch - 1) return;
    size_t i = 0;
    while (n + i + 1 < cch && src[i]) { dst[n + i] = src[i]; ++i; }
    dst[n + i] = 0;
}

void ff_trim(wchar_t *s)
{
    if (!s) return;
    size_t n = wcslen(s);
    while (n > 0 && (s[n - 1] == L' ' || s[n - 1] == L'\t' ||
                     s[n - 1] == L'\r' || s[n - 1] == L'\n')) s[--n] = 0;
    size_t i = 0;
    while (s[i] == L' ' || s[i] == L'\t') ++i;
    if (i) memmove(s, s + i, (n - i + 1) * sizeof(wchar_t));
}

/* ---------------------------------------------------------------- 路径 */
void ff_path_join(wchar_t *out, size_t cch, const wchar_t *dir, const wchar_t *name)
{
    if (!out || cch == 0) return;
    /* out 和 dir 允许是同一块缓冲（调用方会写 ff_path_join(acc, .., acc, seg)）。
     * 这种情况绝不能先 out[0]=0 —— 那会把 dir（也就是 acc 自己）一起清空，
     * 拼出来的就只剩光秃秃的 seg（"D:\Projects" 变成 "Projects"）。 */
    if (out != dir) {
        out[0] = 0;
        if (!dir) return;
        ff_str_copy(out, cch, dir);
    } else if (!dir) {
        out[0] = 0;
        return;
    }
    size_t n = wcslen(out);
    if (n > 0 && out[n - 1] != L'\\' && out[n - 1] != L'/') {
        if (n + 1 < cch) { out[n] = L'\\'; out[n + 1] = 0; }
    }
    if (name && *name) ff_str_cat(out, cch, name);
}

void ff_path_normalize(wchar_t *path)
{
    if (!path) return;
    size_t n = wcslen(path);
    /* 保留 "C:\" 这种根路径的尾反斜杠 */
    while (n > 3 && (path[n - 1] == L'\\' || path[n - 1] == L'/')) path[--n] = 0;
    if (n == 3 && path[1] == L':' && (path[2] == L'\\' || path[2] == L'/')) path[2] = L'\\';
    for (size_t i = 0; i < n; ++i) if (path[i] == L'/') path[i] = L'\\';
}

void ff_path_parent(wchar_t *path)
{
    if (!path) return;
    ff_path_normalize(path);
    size_t n = wcslen(path);

    /* UNC 必须先处理：它有自己的层级，而且长度可能 <= 3（"\\"），
     * 如果先走下面盘符路径那套"n<=3 就是根目录"的判断，\\ 会被当成根而永远上不去。
     *   \\                 的上一级 = 此电脑（空）
     *   \\SERVER          的上一级 = \\           （服务器 → 网络根）
     *   \\SERVER\SHARE    的上一级 = \\SERVER
     *   \\SERVER\SHARE\a  的上一级 = \\SERVER\SHARE
     * 任何一步都不能把前导的双反斜杠砍成单反斜杠。 */
    if (path[0] == L'\\' && path[1] == L'\\') {
        if (n == 2) { path[0] = 0; return; }              /* \\ → 此电脑 */
        int segs = ff_path_unc_segs(path);
        if (segs <= 1) { path[2] = 0; return; }           /* \\SERVER → \\ */
        while (n > 2 && path[n - 1] != L'\\') path[--n] = 0;
        if (n > 2 && path[n - 1] == L'\\') path[n - 1] = 0;
        return;
    }

    if (n == 2 && path[1] == L':') { path[2] = L'\\'; path[3] = 0; return; }
    if (n <= 3) return;                       /* 已是 "C:\" */
    while (n > 0 && path[n - 1] != L'\\') path[--n] = 0;   /* 砍掉末段 */
    if (n == 3) return;                                    /* "C:\" */
    if (n > 0) path[--n] = 0;                              /* 砍掉分隔符 */
}

bool ff_path_is_unc(const wchar_t *path)
{
    return path && path[0] == L'\\' && path[1] == L'\\';
}

/* UNC 路径里 "\\" 之后有几段：
 *   "\\"              -> 0   网络根
 *   "\\SERVER"        -> 1   服务器（下面挂共享）
 *   "\\SERVER\SHARE"  -> 2   真实共享根目录
 *   "\\SERVER\SHARE\a"-> 3
 * 非 UNC 返回 -1。 */
int ff_path_unc_segs(const wchar_t *path)
{
    if (!ff_path_is_unc(path)) return -1;
    size_t n = wcslen(path);
    if (n <= 2) return 0;
    int segs = 1;
    for (size_t i = 3; i < n; ++i) {
        if (path[i] == L'\\' && path[i - 1] != L'\\') ++segs;
    }
    /* 尾部的反斜杠不算新的一段 */
    if (n > 3 && path[n - 1] == L'\\') --segs;
    return segs;
}

const wchar_t *ff_path_name(const wchar_t *path)
{
    if (!path) return L"";
    const wchar_t *p = path, *last = path;
    for (; *p; ++p) if (*p == L'\\' || *p == L'/') last = p + 1;
    return last;
}

void ff_path_ext(const wchar_t *name, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!name) return;
    const wchar_t *dot = NULL, *p = name;
    for (; *p; ++p) {
        if (*p == L'.') dot = p;            /* .gitignore 之类按无扩展处理 */
        else if (*p == L'\\' || *p == L'/') dot = NULL;
    }
    if (!dot || dot == name) return;
    ff_str_copy(out, cch, dot);            /* 含点 */
}

bool ff_same_path(const wchar_t *a, const wchar_t *b)
{
    if (!a || !b) return false;
    wchar_t x[FF_PATH_MAX], y[FF_PATH_MAX];
    ff_str_copy(x, FF_PATH_MAX, a); ff_str_copy(y, FF_PATH_MAX, b);
    ff_path_normalize(x); ff_path_normalize(y);
    return _wcsicmp(x, y) == 0;
}

/* ---------------------------------------------------------------- 格式化 */
void ff_format_size(ULONGLONG bytes, wchar_t *out, size_t cch)
{
    static const wchar_t *u[] = { L"B", L"KB", L"MB", L"GB", L"TB", L"PB" };
    double v = (double)bytes;
    int i = 0;
    while (v >= 1024.0 && i < 5) { v /= 1024.0; ++i; }
    if (i == 0) StringCchPrintfW(out, cch, L"%llu %s", (unsigned long long)bytes, u[0]);
    else        StringCchPrintfW(out, cch, L"%.2f %s", v, u[i]);
}

void ff_format_dt(const FILETIME *ft, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!ft || (ft->dwLowDateTime == 0 && ft->dwHighDateTime == 0)) return;
    FILETIME local;
    SYSTEMTIME st;
    if (!FileTimeToLocalFileTime(ft, &local)) return;
    if (!FileTimeToSystemTime(&local, &st)) return;
    StringCchPrintfW(out, cch, L"%04u-%02u-%02u %02u:%02u",
             st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute);
}

void ff_format_attr(DWORD attrs, wchar_t *out, size_t cch)
{
    if (cch < 8) { out[0] = 0; return; }
    int n = 0;
    if (attrs & FILE_ATTRIBUTE_READONLY)  out[n++] = L'R';
    if (attrs & FILE_ATTRIBUTE_HIDDEN)    out[n++] = L'H';
    if (attrs & FILE_ATTRIBUTE_SYSTEM)    out[n++] = L'S';
    if (attrs & FILE_ATTRIBUTE_ARCHIVE)   out[n++] = L'A';
    if (attrs & FILE_ATTRIBUTE_COMPRESSED) out[n++] = L'C';
    if (attrs & FILE_ATTRIBUTE_ENCRYPTED) out[n++] = L'E';
    out[n] = 0;
}

void ff_format_count(int n, wchar_t *out, size_t cch)
{
    StringCchPrintfW(out, cch, L"%d 个对象", n);
}

/* ---------------------------------------------------------------- 消息框 */
int ff_msgbox(HWND owner, const wchar_t *text, const wchar_t *caption, UINT type)
{
    return MessageBoxW(owner, text, caption ? caption : FF_APP_TITLE, type | MB_TOPMOST);
}

void ff_msg_error(HWND owner, const wchar_t *fmt, ...)
{
    wchar_t buf[2048];
    va_list ap; va_start(ap, fmt);
    StringCchVPrintfW(buf, 2048, fmt, ap);
    va_end(ap);
    buf[2047] = 0;
    MessageBoxW(owner, buf, FF_APP_TITLE, MB_OK | MB_ICONWARNING);
}

bool ff_confirm(HWND owner, const wchar_t *fmt, ...)
{
    wchar_t buf[2048];
    va_list ap; va_start(ap, fmt);
    StringCchVPrintfW(buf, 2048, fmt, ap);
    va_end(ap);
    buf[2047] = 0;
    return MessageBoxW(owner, buf, FF_APP_TITLE,
                       MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) == IDYES;
}

/* ---------------------------------------------------------------- DPI/字体 */
int ff_scale(int v)
{
    int dpi = g_app.dpi ? g_app.dpi : 96;
    return MulDiv(v, dpi, 96);
}

int ff_dpi_scale(int v) { return ff_scale(v); }

HFONT ff_ui_font(void)
{
    if (g_app.fontUI) return g_app.fontUI;
    NONCLIENTMETRICSW ncm;
    ZeroMemory(&ncm, sizeof(ncm));
    ncm.cbSize = sizeof(ncm);
    LOGFONTW lf;
    if (SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(ncm), &ncm, 0)) {
        lf = ncm.lfMessageFont;
    } else {
        ZeroMemory(&lf, sizeof(lf));
        lf.lfHeight = -MulDiv(9, g_app.dpi ? g_app.dpi : 96, 72);
        ff_str_copy(lf.lfFaceName, 32, L"Microsoft YaHei UI");
    }
    g_app.fontUI = CreateFontIndirectW(&lf);
    if (!g_app.fontUI) g_app.fontUI = (HFONT)GetStockObject(DEFAULT_GUI_FONT);

    LOGFONTW lbf = lf;
    lbf.lfWeight = FW_SEMIBOLD;
    g_app.fontBold = CreateFontIndirectW(&lbf);
    if (!g_app.fontBold) g_app.fontBold = g_app.fontUI;
    return g_app.fontUI;
}

/* ---------------------------------------------------------------- 导航历史 */
void ff_hist_push(FfHistory *h, const wchar_t *dir)
{
    if (!h || !dir) return;
    if (h->stack && h->count > 0 && _wcsicmp(h->stack[h->top], dir) == 0) return;

    if (h->cap < FF_UNDO_STACK) {
        wchar_t (*ns)[FF_PATH_MAX] = (wchar_t (*)[FF_PATH_MAX])
            realloc(h->stack, (size_t)FF_UNDO_STACK * FF_PATH_MAX * sizeof(wchar_t));
        if (!ns) return;
        h->stack = ns;
        h->cap = FF_UNDO_STACK;
    }
    if (h->count > 0) h->count = h->top + 1;      /* 丢弃前进分支 */
    if (h->count >= FF_UNDO_STACK) {
        memmove(h->stack, h->stack + 1,
                (size_t)(FF_UNDO_STACK - 1) * FF_PATH_MAX * sizeof(wchar_t));
        h->count = FF_UNDO_STACK - 1;
    }
    ff_str_copy(h->stack[h->count], FF_PATH_MAX, dir);
    h->count++;
    h->top = h->count - 1;
}

void ff_hist_free(FfHistory *h)
{
    if (!h) return;
    free(h->stack);
    h->stack = NULL;
    h->top = h->count = h->cap = 0;
}

/* ---------------------------------------------------------------- 剪贴板文件列表 */
wchar_t *g_clipFiles = NULL;
int      g_clipCount = 0;

void ff_clear_clip_files(void)
{
    if (g_clipFiles) { free(g_clipFiles); g_clipFiles = NULL; }
    g_clipCount = 0;
}

void ff_set_clip_files(const wchar_t **files, int count)
{
    ff_clear_clip_files();
    if (count <= 0) return;
    size_t total = 1;
    for (int i = 0; i < count; ++i) total += wcslen(files[i]) + 1;
    g_clipFiles = (wchar_t *)calloc(total, sizeof(wchar_t));
    if (!g_clipFiles) return;
    wchar_t *p = g_clipFiles;
    for (int i = 0; i < count; ++i) {
        size_t n = wcslen(files[i]);
        memcpy(p, files[i], n * sizeof(wchar_t));
        p += n + 1;
    }
    g_clipCount = count;
}

DWORD ff_flags_from_check(int state)
{
    return (state == BST_CHECKED) ? 1u : 0u;
}

HBITMAP ff_make_icon_bmp(HICON icon, int size)
{
    if (!icon) return NULL;
    HDC hdc = GetDC(NULL);
    HDC mem = CreateCompatibleDC(hdc);
    BITMAPV5HEADER bi;
    ZeroMemory(&bi, sizeof(bi));
    bi.bV5Size = sizeof(bi);
    bi.bV5Width = size; bi.bV5Height = -size;
    bi.bV5Planes = 1; bi.bV5BitCount = 32; bi.bV5Compression = BI_BITFIELDS;
    bi.bV5RedMask = 0x00FF0000; bi.bV5GreenMask = 0x0000FF00; bi.bV5BlueMask = 0x000000FF;
    void *bits = NULL;
    HBITMAP bmp = CreateDIBSection(hdc, (BITMAPINFO *)&bi, DIB_RGB_COLORS, &bits, NULL, 0);
    if (bmp) {
        HBITMAP old = (HBITMAP)SelectObject(mem, bmp);
        PatBlt(mem, 0, 0, size, size, BLACKNESS);
        DrawIconEx(mem, 0, 0, icon, size, size, 0, NULL, DI_NORMAL);
        SelectObject(mem, old);
    }
    DeleteDC(mem);
    ReleaseDC(NULL, hdc);
    return bmp;
}
