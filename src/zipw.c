/* zipw.c —— 往 .zip 里加 / 替换文件（零依赖，只用 Win32）
 *
 * 为什么不用系统的：Windows 的 zip 是 shell 命名空间扩展，往里写要用
 * SHFileOperation(FO_COPY) 或 IFileOperation.CopyItem。这两个在本程序里都会
 * **卡死**——它们要泵消息等 UI 完成，而我们在窗口过程里调用时主线程还没回到
 * 消息循环；放工作线程也不行（同样的等待）。日志能证明：函数进去后没有下一行。
 * 所以这里自己读写 ZIP：新增条目用 stored（method 0，只需 CRC32，不需要 deflate），
 * 已有条目原样搬压缩数据，不会因为这次操作变大。 */
#include "ff.h"

#define ZIP_LOCAL_SIG   0x04034b50u
#define ZIP_CENTRAL_SIG 0x02014b50u
#define ZIP_EOCD_SIG    0x06054b50u

static DWORD s_crcTab[256];
static bool s_crcReady = false;

static void crc_init(void)
{
    if (s_crcReady) return;
    for (DWORD i = 0; i < 256; ++i) {
        DWORD c = i;
        for (int k = 0; k < 8; ++k) c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        s_crcTab[i] = c;
    }
    s_crcReady = true;
}

static DWORD crc32_calc(const BYTE *p, size_t n)
{
    crc_init();
    DWORD c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; ++i) c = s_crcTab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

static WORD rd16(const BYTE *p) { return (WORD)(p[0] | (p[1] << 8)); }
static DWORD rd32(const BYTE *p)
{
    return (DWORD)p[0] | ((DWORD)p[1] << 8) | ((DWORD)p[2] << 16) | ((DWORD)p[3] << 24);
}
static void wr16(BYTE *p, WORD v) { p[0] = (BYTE)v; p[1] = (BYTE)(v >> 8); }
static void wr32(BYTE *p, DWORD v)
{
    p[0] = (BYTE)v; p[1] = (BYTE)(v >> 8); p[2] = (BYTE)(v >> 16); p[3] = (BYTE)(v >> 24);
}

typedef struct { BYTE *p; size_t n, cap; } Buf;

static bool buf_need(Buf *b, size_t extra)
{
    if (b->n + extra <= b->cap) return true;
    size_t nc = b->cap ? b->cap : 65536;
    while (nc < b->n + extra) nc *= 2;
    BYTE *np = (BYTE *)realloc(b->p, nc);
    if (!np) return false;
    b->p = np;
    b->cap = nc;
    return true;
}
static bool buf_put(Buf *b, const void *src, size_t n)
{
    if (!buf_need(b, n)) return false;
    if (n) memcpy(b->p + b->n, src, n);
    b->n += n;
    return true;
}

typedef struct {
    char  *name;
    WORD   nameLen;
    DWORD  localOff;
    const BYTE *centralRaw;
    DWORD  centralRawLen;
} ZipEnt;

static BYTE *read_all(const wchar_t *path, size_t *sizeOut)
{
    *sizeOut = 0;
    HANDLE h = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return NULL;
    LARGE_INTEGER li;
    if (!GetFileSizeEx(h, &li) || li.QuadPart < 0 || li.QuadPart > (LONGLONG)(256 * 1024 * 1024)) {
        CloseHandle(h);
        return NULL;
    }
    size_t n = (size_t)li.QuadPart;
    BYTE *buf = (BYTE *)malloc(n ? n : 1);
    if (!buf) { CloseHandle(h); return NULL; }
    size_t got = 0;
    while (got < n) {
        DWORD chunk = (DWORD)((n - got) > 0x1000000 ? 0x1000000 : (n - got));
        DWORD rd = 0;
        if (!ReadFile(h, buf + got, chunk, &rd, NULL) || rd == 0) break;
        got += rd;
    }
    CloseHandle(h);
    if (got != n) { free(buf); return NULL; }
    *sizeOut = n;
    return buf;
}

static int name_to_utf8(const wchar_t *w, char *out, size_t cchOut)
{
    wchar_t tmp[520];
    ff_str_copy(tmp, 520, w);
    for (wchar_t *q = tmp; *q; ++q) if (*q == L'\\') *q = L'/';
    int n = WideCharToMultiByte(CP_UTF8, 0, tmp, -1, out, (int)cchOut - 1, NULL, NULL);
    if (n <= 0) { out[0] = 0; return 0; }
    return n - 1;
}

bool ff_zip_add_or_replace(const wchar_t *zipPath, const wchar_t **files, int count,
                           wchar_t *err, size_t cchErr)
{
    if (err && cchErr) err[0] = 0;
    if (!zipPath || !zipPath[0] || !files || count <= 0) return false;

    size_t oldLen = 0;
    BYTE *oldBuf = read_all(zipPath, &oldLen);

    DWORD cdOff = 0, cdSize = 0, entCount = 0;
    if (oldBuf && oldLen >= 22) {
        size_t lim = oldLen > 65557 ? oldLen - 65557 : 0;
        for (size_t i = oldLen - 21; i-- > lim;) {
            if (rd32(oldBuf + i) == ZIP_EOCD_SIG) {
                entCount = rd16(oldBuf + i + 10);
                cdSize = rd32(oldBuf + i + 12);
                cdOff = rd32(oldBuf + i + 16);
                break;
            }
        }
        if (cdOff + cdSize > oldLen) cdOff = cdSize = entCount = 0;
    }

    ZipEnt *ents = NULL;
    int nEnt = 0;
    if (entCount > 0 && entCount < 100000) {
        ents = (ZipEnt *)calloc(entCount, sizeof(ZipEnt));
        if (!ents) { free(oldBuf); return false; }
        size_t p = cdOff;
        for (DWORD i = 0; i < entCount; ++i) {
            if (p + 46 > oldLen || rd32(oldBuf + p) != ZIP_CENTRAL_SIG) break;
            const BYTE *e = oldBuf + p;
            ZipEnt *z = &ents[nEnt];
            z->nameLen = rd16(e + 28);
            z->localOff = rd32(e + 42);
            z->name = (char *)(e + 46);
            z->centralRaw = e;
            z->centralRawLen = 46u + z->nameLen + rd16(e + 30) + rd16(e + 32);
            p += z->centralRawLen;
            ++nEnt;
        }
    }

    typedef struct { char name[520]; int nameLen; BYTE *data; size_t size; DWORD crc; } NewF;
    NewF *nf = (NewF *)calloc((size_t)count, sizeof(NewF));
    if (!nf) { free(ents); free(oldBuf); return false; }

    int nNew = 0;
    for (int i = 0; i < count; ++i) {
        if (!files[i] || !files[i][0]) continue;
        NewF *f = &nf[nNew];
        f->nameLen = name_to_utf8(ff_path_name(files[i]), f->name, sizeof(f->name));
        if (f->nameLen <= 0) continue;
        size_t sz = 0;
        f->data = read_all(files[i], &sz);
        if (!f->data) continue;
        f->size = sz;
        f->crc = crc32_calc(f->data, sz);
        ++nNew;
    }
    if (nNew <= 0) {
        free(nf); free(ents); free(oldBuf);
        if (err && cchErr) ff_str_copy(err, cchErr, L"没有可写入的文件。");
        return false;
    }

    Buf out;
    ZeroMemory(&out, sizeof(out));
    int outCount = 0;
    DWORD *newOff = (DWORD *)calloc((size_t)(nEnt ? nEnt : 1), sizeof(DWORD));
    DWORD *newEntOff = (DWORD *)calloc((size_t)nNew, sizeof(DWORD));
    bool ok = newOff && newEntOff;

    if (ok) {
        for (int i = 0; i < nEnt && ok; ++i) {
            ZipEnt *z = &ents[i];
            bool replaced = false;
            for (int k = 0; k < nNew; ++k)
                if ((int)z->nameLen == nf[k].nameLen &&
                    memcmp(z->name, nf[k].name, z->nameLen) == 0) { replaced = true; break; }
            if (replaced) { newOff[i] = 0xFFFFFFFFu; continue; }

            DWORD next = cdOff;
            for (int j = 0; j < nEnt; ++j) {
                if (j == i) continue;
                DWORD o = ents[j].localOff;
                if (o > z->localOff && o < next) next = o;
            }
            if (z->localOff >= next || next > oldLen) { newOff[i] = 0xFFFFFFFFu; continue; }
            newOff[i] = (DWORD)out.n;
            ok = buf_put(&out, oldBuf + z->localOff, next - z->localOff);
            if (ok) ++outCount;
        }
    }

    if (ok) {
        for (int k = 0; k < nNew && ok; ++k) {
            NewF *f = &nf[k];
            newEntOff[k] = (DWORD)out.n;
            BYTE hdr[30];
            ZeroMemory(hdr, sizeof(hdr));
            wr32(hdr + 0, ZIP_LOCAL_SIG);
            wr16(hdr + 4, 20);
            wr16(hdr + 6, 0x0800);
            wr16(hdr + 8, 0);
            wr16(hdr + 10, 0);
            wr16(hdr + 12, 0x21);
            wr32(hdr + 14, f->crc);
            wr32(hdr + 18, (DWORD)f->size);
            wr32(hdr + 22, (DWORD)f->size);
            wr16(hdr + 26, (WORD)f->nameLen);
            wr16(hdr + 28, 0);
            ok = buf_put(&out, hdr, 30) && buf_put(&out, f->name, (size_t)f->nameLen)
                 && buf_put(&out, f->data, f->size);
            if (ok) ++outCount;
        }
    }

    DWORD cdStart = (DWORD)out.n;
    if (ok) {
        for (int i = 0; i < nEnt; ++i) {
            if (newOff[i] == 0xFFFFFFFFu) continue;
            if (!buf_need(&out, ents[i].centralRawLen)) { ok = false; break; }
            BYTE *dst = out.p + out.n;
            memcpy(dst, ents[i].centralRaw, ents[i].centralRawLen);
            wr32(dst + 42, newOff[i]);
            out.n += ents[i].centralRawLen;
        }
        for (int k = 0; k < nNew && ok; ++k) {
            NewF *f = &nf[k];
            BYTE e[46];
            ZeroMemory(e, sizeof(e));
            wr32(e + 0, ZIP_CENTRAL_SIG);
            wr16(e + 4, 20);
            wr16(e + 6, 20);
            wr16(e + 8, 0x0800);
            wr16(e + 10, 0);
            wr16(e + 12, 0);
            wr16(e + 14, 0x21);
            wr32(e + 16, f->crc);
            wr32(e + 20, (DWORD)f->size);
            wr32(e + 24, (DWORD)f->size);
            wr16(e + 28, (WORD)f->nameLen);
            wr16(e + 30, 0);
            wr16(e + 32, 0);
            wr16(e + 34, 0);
            wr16(e + 36, 0);
            wr32(e + 38, 0);
            wr32(e + 42, newEntOff[k]);
            ok = buf_put(&out, e, 46) && buf_put(&out, f->name, (size_t)f->nameLen);
        }
    }
    DWORD cdLen = (DWORD)out.n - cdStart;

    if (ok) {
        BYTE e[22];
        ZeroMemory(e, sizeof(e));
        wr32(e + 0, ZIP_EOCD_SIG);
        wr16(e + 8, (WORD)outCount);
        wr16(e + 10, (WORD)outCount);
        wr32(e + 12, cdLen);
        wr32(e + 16, cdStart);
        wr16(e + 20, 0);
        ok = buf_put(&out, e, 22);
    }

    if (ok) {
        wchar_t tmp[FF_PATH_MAX];
        StringCchPrintfW(tmp, FF_PATH_MAX, L"%s.ffce.tmp", zipPath);
        HANDLE h = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                               FILE_ATTRIBUTE_NORMAL, NULL);
        ok = (h != INVALID_HANDLE_VALUE);
        if (ok) {
            size_t put = 0;
            while (put < out.n) {
                DWORD chunk = (DWORD)((out.n - put) > 0x1000000 ? 0x1000000 : (out.n - put));
                DWORD wr = 0;
                if (!WriteFile(h, out.p + put, chunk, &wr, NULL) || wr == 0) { ok = false; break; }
                put += wr;
            }
            CloseHandle(h);
        }
        if (ok && !MoveFileExW(tmp, zipPath, MOVEFILE_REPLACE_EXISTING)) ok = false;
        if (!ok) DeleteFileW(tmp);
        if (!ok && err && cchErr) ff_str_copy(err, cchErr, L"写入压缩包失败。");
    }

    DBG(L"zipw: %d 个文件 -> %ls (旧条目 %d, 输出 %zu, ok=%d)", nNew, zipPath, nEnt,
        out.n, ok ? 1 : 0);

    for (int k = 0; k < nNew; ++k) free(nf[k].data);
    free(nf);
    free(newOff);
    free(newEntOff);
    free(ents);
    free(oldBuf);
    free(out.p);
    return ok;
}

/* ================================================================ 通用入口
 * .zip  → 本文件自己实现（零依赖，一定能用）
 * .rar  → RAR 是专有格式，任何人都不可能"自己写"，只能借机器上的 WinRAR
 * .7z   → 同理借 7-Zip
 * 找不到工具就返回 false 并给出明确原因，绝不假装成功。 */

/* 在 Program Files / Program Files(x86) 下找工具 */
static bool find_tool(const wchar_t *rel, wchar_t *out, size_t cchOut)
{
    wchar_t base[FF_PATH_MAX];
    const int ids[2] = { CSIDL_PROGRAM_FILES, CSIDL_PROGRAM_FILESX86 };
    for (int i = 0; i < 2; ++i) {
        base[0] = 0;
        if (FAILED(SHGetFolderPathW(NULL, ids[i] | CSIDL_FLAG_CREATE, NULL, 0, base)))
            continue;
        if (!base[0]) continue;
        ff_path_join(out, cchOut, base, rel);
        if (GetFileAttributesW(out) != INVALID_FILE_ATTRIBUTES) return true;
    }
    return false;
}

/* 跑一个命令行工具（不弹窗口），返回退出码是否 0 */
static bool run_tool(const wchar_t *exe, const wchar_t *args)
{
    wchar_t cmd[4096];
    StringCchPrintfW(cmd, 4096, L"\"%s\" %s", exe, args);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, NULL, &si, &pi))
        return false;
    WaitForSingleObject(pi.hProcess, 60000);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    DBG(L"run_tool: %ls -> exit=%lu", cmd, (unsigned long)code);
    return code == 0;
}

/* 拼一组带引号的参数（每个文件一个） */
static void append_quoted(wchar_t *buf, size_t cch, const wchar_t *item)
{
    size_t used = wcslen(buf);
    if (used + wcslen(item) + 4 >= cch) return;
    StringCchCatW(buf, cch, L" \"");
    StringCchCatW(buf, cch, item);
    StringCchCatW(buf, cch, L"\"");
}

bool ff_archive_insert(const wchar_t *archivePath, const wchar_t **files, int count,
                       wchar_t *err, size_t cchErr)
{
    if (err && cchErr) err[0] = 0;
    if (!archivePath || !files || count <= 0) return false;

    const wchar_t *ext = wcsrchr(archivePath, L'.');
    if (!ext) return false;

    /* zip：自己写，无外部依赖 */
    if (_wcsicmp(ext, L".zip") == 0)
        return ff_zip_add_or_replace(archivePath, files, count, err, cchErr);

    /* rar：借 WinRAR（Rar.exe a -y -ibck -ep1 <arc> <files...>） */
    if (_wcsicmp(ext, L".rar") == 0) {
        wchar_t exe[FF_PATH_MAX];
        if (!find_tool(L"WinRAR\\Rar.exe", exe, FF_PATH_MAX)) {
            if (err && cchErr)
                ff_str_copy(err, cchErr,
                            L"没找到 WinRAR（Rar.exe）。RAR 是专有格式，"
                            L"本程序无法自己写入，请先安装 WinRAR。");
            return false;
        }
        wchar_t args[4096];
        args[0] = 0;
        StringCchCatW(args, 4096, L"a -y -ibck -ep1");
        append_quoted(args, 4096, archivePath);
        for (int i = 0; i < count; ++i)
            if (files[i] && files[i][0]) append_quoted(args, 4096, files[i]);
        return run_tool(exe, args);
    }

    /* 7z / tar：借 7-Zip */
    {
        wchar_t exe[FF_PATH_MAX];
        if (!find_tool(L"7-Zip\\7z.exe", exe, FF_PATH_MAX)) {
            if (err && cchErr)
                ff_str_copy(err, cchErr,
                            L"这个压缩格式需要 7-Zip（没找到 7z.exe），本程序不能自己写入。");
            return false;
        }
        wchar_t args[4096];
        args[0] = 0;
        StringCchCatW(args, 4096, L"a -y");
        append_quoted(args, 4096, archivePath);
        for (int i = 0; i < count; ++i)
            if (files[i] && files[i][0]) append_quoted(args, 4096, files[i]);
        return run_tool(exe, args);
    }
}
