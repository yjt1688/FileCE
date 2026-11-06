/* fs.c —— 文件系统层：枚举、类型识别、图标、复制/移动/删除、查找、数据流 */
#include "ff.h"

#define COPY_BUF (256 * 1024)

static bool s_fsInited = false;

void fs_init(void)
{
    if (s_fsInited) return;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);
    s_fsInited = true;
}

/* ================================================================ 路径判定 */
bool fs_is_dir(const wchar_t *path)
{
    if (!path || !*path) return false;

    DWORD a = GetFileAttributesW(path);
    if (a == INVALID_FILE_ATTRIBUTES) {
        /* 可能是无介质的光驱/软驱：C:\ 形式仍视为目录 */
        size_t n = wcslen(path);
        if (n == 3 && path[1] == L':' && path[2] == L'\\') return true;
        return false;
    }
    return (a & FILE_ATTRIBUTE_DIRECTORY) != 0;
}

bool fs_path_exists(const wchar_t *path)
{
    if (!path || !*path) return false;
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

bool fs_make_dir(const wchar_t *path)
{
    if (!path || !*path) return false;

    /* CreateDirectoryW 只能建最后一级，中间路径不存在时直接失败
     * （ERROR_PATH_NOT_FOUND）。这里逐级补齐，语义和 mkdir -p 一致。 */
    wchar_t p[FF_PATH_MAX];
    ff_str_copy(p, FF_PATH_MAX, path);

    size_t len = wcslen(p);
    size_t start = 0;
    if (len >= 2 && p[1] == L':') {
        start = 2;                                  /* C:\ */
    } else if (len >= 2 && p[0] == L'\\' && p[1] == L'\\') {
        int segs = 0;                               /* \\server\share\ */
        for (size_t i = 2; i <= len; ++i) {
            if (p[i] == L'\\' || p[i] == 0) {
                if (++segs == 3) { start = i; break; }
            }
        }
    }
    if (start >= len) return fs_path_exists(p);

    for (size_t i = start + 1; i <= len; ++i) {
        if (p[i] != L'\\' && p[i] != L'/' && p[i] != 0) continue;
        wchar_t save = p[i];
        p[i] = 0;
        if (!fs_path_exists(p)) {
            if (!CreateDirectoryW(p, NULL) &&
                GetLastError() != ERROR_ALREADY_EXISTS)
                return false;
        }
        p[i] = save;
    }
    return fs_path_exists(p);
}

bool fs_rename(const wchar_t *oldPath, const wchar_t *newName)
{
    if (!oldPath || !newName || !*newName) return false;
    wchar_t dir[FF_PATH_MAX], target[FF_PATH_MAX];
    ff_str_copy(dir, FF_PATH_MAX, oldPath);
    ff_path_parent(dir);
    ff_path_join(target, FF_PATH_MAX, dir, newName);
    if (_wcsicmp(oldPath, target) == 0) return true;

    /* 先试直接重命名 */
    if (MoveFileExW(oldPath, target, MOVEFILE_REPLACE_EXISTING)) return true;

    /* 只读属性会导致失败，清掉再试 */
    DWORD a = GetFileAttributesW(oldPath);
    if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_READONLY)) {
        SetFileAttributesW(oldPath, a & ~FILE_ATTRIBUTE_READONLY);
        if (MoveFileExW(oldPath, target, MOVEFILE_REPLACE_EXISTING)) {
            SetFileAttributesW(target, a);
            return true;
        }
    }
    return false;
}

/* ================================================================ 驱动器 */
const wchar_t *fs_drive_kind_name(int kind)
{
    switch (kind) {
    case DRIVE_FIXED_K:     return L"本地硬盘";
    case DRIVE_REMOVABLE_K: return L"可移动磁盘";
    case DRIVE_REMOTE_K:    return L"网络驱动器";
    case DRIVE_CDROM_K:     return L"CD 驱动器";
    case DRIVE_RAMDISK_K:   return L"RAM 磁盘";
    case DRIVE_SPECIAL_K:   return L"虚拟目录";
    default:                return L"未知设备";
    }
}

int fs_drive_kind(const wchar_t *root)
{
    if (!root || !*root) return DRIVE_UNKNOWN_K;
    if (wcslen(root) >= 2 && root[1] == L':') {
        switch (GetDriveTypeW(root)) {
        case DRIVE_REMOVABLE: return DRIVE_REMOVABLE_K;
        case DRIVE_FIXED:     return DRIVE_FIXED_K;
        case DRIVE_REMOTE:    return DRIVE_REMOTE_K;
        case DRIVE_CDROM:     return DRIVE_CDROM_K;
        case DRIVE_RAMDISK:   return DRIVE_RAMDISK_K;
        default:              return DRIVE_UNKNOWN_K;
        }
    }
    return DRIVE_SPECIAL_K;
}

void fs_describe_drive(const wchar_t *root, wchar_t *label, size_t cch,
                       wchar_t *fsname, size_t cch2)
{
    if (label && cch) label[0] = 0;
    if (fsname && cch2) fsname[0] = 0;
    if (!root || !*root) return;

    /* 先探测介质，避免空光驱/软驱把界面卡住 */
    UINT type = GetDriveTypeW(root);
    if (type == DRIVE_CDROM || type == DRIVE_REMOVABLE) {
        wchar_t probe[8];
        StringCchPrintfW(probe, 8, L"%c:\\", root[0]);
        HANDLE h = CreateFileW(probe, GENERIC_READ,
                               FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                               OPEN_EXISTING, 0, NULL);
        if (h == INVALID_HANDLE_VALUE) return;
        CloseHandle(h);
    }
    if (label) GetVolumeInformationW(root, label, (DWORD)cch, NULL, NULL, NULL,
                                     fsname, (DWORD)cch2);
}

static ULONGLONG drive_capacity(const wchar_t *root)
{
    ULARGE_INTEGER total;
    total.QuadPart = 0;
    if (!GetDiskFreeSpaceExW(root, NULL, &total, NULL)) return 0;
    return total.QuadPart;
}

void fs_enum_drives(FfEntryList *out)
{
    DWORD mask = GetLogicalDrives();
    for (int i = 0; i < 26; ++i) {
        if (!(mask & (1u << i))) continue;
        wchar_t root[8];
        StringCchPrintfW(root, 8, L"%c:\\", L'A' + i);

        FfEntry e;
        ZeroMemory(&e, sizeof(e));
        e.name[0] = (wchar_t)(L'A' + i);
        e.name[1] = L':'; e.name[2] = 0;
        e.isDir = 1; e.isDrive = 1;
        e.driveKind = fs_drive_kind(root);
        e.attrs = FILE_ATTRIBUTE_DIRECTORY;

        wchar_t label[128] = L"";
        wchar_t fsname[64] = L"";
        fs_describe_drive(root, label, 128, fsname, 64);
        if (label[0]) {
            wchar_t tmp[512];
            StringCchPrintfW(tmp, 512, L"%c: (%s)", L'A' + i, label);
            ff_str_copy(e.name, 512, tmp);
        }
        ff_str_copy(e.type, 128, fs_drive_kind_name(e.driveKind));
        e.size = drive_capacity(root);
        e.iconIndex = fs_get_icon_index(root, FILE_ATTRIBUTE_DIRECTORY);

        if (out->count >= out->cap) {
            int nc = out->cap ? out->cap * 2 : 16;
            FfEntry *ni = (FfEntry *)realloc(out->items, nc * sizeof(FfEntry));
            if (!ni) return;
            out->items = ni; out->cap = nc;
        }
        out->items[out->count++] = e;
    }

    /* 目录树「此电脑」下面和驱动器并列的常用位置：桌面 / 文档（真实目录）。 */
    {
        static const struct {
            int kind; const wchar_t *name; const wchar_t *type;
        } sp[] = {
            { DRIVE_DESKTOP_K, L"桌面", L"系统文件夹" },
            { DRIVE_DOCS_K,    L"文档", L"系统文件夹" },
        };
        for (int s = 0; s < 2; ++s) {
            wchar_t path[FF_PATH_MAX];
            if (!fs_special_path(sp[s].kind, path, FF_PATH_MAX))
                continue;                       /* 取不到路径就不显示这个节点 */
            FfEntry e;
            ZeroMemory(&e, sizeof(e));
            ff_str_copy(e.name, 512, sp[s].name);
            ff_str_copy(e.type, 128, sp[s].type);
            e.isDir = 1;
            e.isDrive = 1;
            e.driveKind = sp[s].kind;
            e.attrs = FILE_ATTRIBUTE_DIRECTORY;
            e.iconIndex = fs_icon_special_folder(sp[s].kind, path);
            if (out->count >= out->cap) {
                int nc = out->cap ? out->cap * 2 : 16;
                FfEntry *ni = (FfEntry *)realloc(out->items, nc * sizeof(FfEntry));
                if (!ni) return;
                out->items = ni; out->cap = nc;
            }
            out->items[out->count++] = e;
        }
    }
}

/* ================================================================ 此电脑页
 * Win10「此电脑」页布局（对照系统截图）：
 *   顶部：视频 / 图片 / 文档 / 下载 / 音乐 / 桌面（六个常用文件夹，无组头）
 *   「设备和驱动器 (n)」组：C:~G:
 * 每条记录带 groupId（PCGRP_*），filelist 据此挂组头行。 */
void fs_enum_this_pc(FfEntryList *out)
{
    if (!out) return;
    out->count = 0;
    if (!out->items) out->cap = 0;

    /* 顶部六个常用文件夹（顺序与 Win10 一致），groupId = PCGRP_NONE */
    {
        static const struct { int kind; const wchar_t *name; } sp[] = {
            { DRIVE_VIDEO_K,   L"视频" },
            { DRIVE_PICS_K,    L"图片" },
            { DRIVE_DOCS_K,    L"文档" },
            { DRIVE_DL_K,      L"下载" },
            { DRIVE_MUSIC_K,   L"音乐" },
            { DRIVE_DESKTOP_K, L"桌面" },
        };
        for (int s = 0; s < 6; ++s) {
            wchar_t path[FF_PATH_MAX];
            if (!fs_special_path(sp[s].kind, path, FF_PATH_MAX))
                continue;                       /* 取不到路径就不显示 */
            FfEntry e;
            ZeroMemory(&e, sizeof(e));
            ff_str_copy(e.name, 512, sp[s].name);
            ff_str_copy(e.type, 128, L"系统文件夹");
            e.isDir = 1;
            e.isDrive = 1;
            e.driveKind = sp[s].kind;
            e.attrs = FILE_ATTRIBUTE_DIRECTORY;
            e.iconIndex = fs_icon_special_folder(sp[s].kind, path);
            e.groupId = PCGRP_NONE;
            if (out->count >= out->cap) {
                int nc = out->cap ? out->cap * 2 : 16;
                FfEntry *ni = (FfEntry *)realloc(out->items, nc * sizeof(FfEntry));
                if (!ni) return;
                out->items = ni; out->cap = nc;
            }
            out->items[out->count++] = e;
        }
    }

    /* 驱动器：复用 fs_enum_drives，只保留真实盘符条目，groupId = PCGRP_DRIVE。
     * 桌面/文档这类虚拟节点在上面已经作为常用文件夹列出，这里跳过。 */
    {
        FfEntryList drives;
        ZeroMemory(&drives, sizeof(drives));
        fs_enum_drives(&drives);
        for (int i = 0; i < drives.count; ++i) {
            FfEntry *de = &drives.items[i];
            switch (de->driveKind) {
            case DRIVE_DESKTOP_K: case DRIVE_DOCS_K:
                continue;
            default:
                break;
            }
            de->groupId = PCGRP_DRIVE;
            if (out->count >= out->cap) {
                int nc = out->cap ? out->cap * 2 : 16;
                FfEntry *ni = (FfEntry *)realloc(out->items, nc * sizeof(FfEntry));
                if (!ni) break;
                out->items = ni; out->cap = nc;
            }
            out->items[out->count++] = *de;
        }
        fs_entry_list_free(&drives);
    }
}

/* ================================================================ 类型名 / 图标 */
typedef struct { wchar_t ext[40]; wchar_t type[104]; } TypeCacheEnt;
static TypeCacheEnt *s_typeCache;     /* 懒分配堆(72KB):静态零数组会进 .data 撑大 exe */
static TypeCacheEnt *type_cache(void)
{
    if (!s_typeCache) s_typeCache = (TypeCacheEnt *)calloc(256, sizeof(TypeCacheEnt));
    return s_typeCache;
}

bool fs_get_file_type(const wchar_t *name, DWORD attrs, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (attrs & FILE_ATTRIBUTE_DIRECTORY) {
        ff_str_copy(out, cch, L"文件夹");
        return true;
    }
    wchar_t ext[40];
    ff_path_ext(name, ext, 40);
    if (!ext[0]) { ff_str_copy(out, cch, L"文件"); return true; }
    CharLowerW(ext);

    unsigned h = 2166136261u;
    for (const wchar_t *p = ext; *p; ++p) h = (h ^ (unsigned)*p) * 16777619u;
    unsigned slot = h & 255;
    if (type_cache()[slot].ext[0] && _wcsicmp(type_cache()[slot].ext, ext) == 0) {
        ff_str_copy(out, cch, type_cache()[slot].type);
        return true;
    }

    SHFILEINFOW sfi;
    ZeroMemory(&sfi, sizeof(sfi));
    wchar_t probe[64];
    StringCchPrintfW(probe, 64, L"file%s", ext);
    if (SHGetFileInfoW(probe, FILE_ATTRIBUTE_NORMAL, &sfi, sizeof(sfi),
                       SHGFI_TYPENAME | SHGFI_USEFILEATTRIBUTES) && sfi.szTypeName[0]) {
        ff_str_copy(out, cch, sfi.szTypeName);
    } else {
        wchar_t up[40];
        ff_str_copy(up, 40, ext + 1);
        CharUpperW(up);
        ff_str_copy(out, cch, up);
        ff_str_cat(out, cch, L" 文件");
    }
    if (sfi.szTypeName[0]) {
        ff_str_copy(type_cache()[slot].ext, 40, ext);
        ff_str_copy(type_cache()[slot].type, 104, sfi.szTypeName);
    }
    return true;
}

/* 图标索引缓存：按扩展名/目录类别缓存，避免逐文件调用 shell（性能关键） */
typedef struct { bool valid; wchar_t key[40]; int icon; } IconCacheEnt;
static IconCacheEnt *s_iconCache;     /* 懒分配堆(44KB) */
static IconCacheEnt *icon_cache(void)
{
    if (!s_iconCache) s_iconCache = (IconCacheEnt *)calloc(512, sizeof(IconCacheEnt));
    return s_iconCache;
}

static void cache_key_for(const wchar_t *path, DWORD attrs, wchar_t *key, size_t cch)
{
    key[0] = 0;
    if (attrs & FILE_ATTRIBUTE_DIRECTORY) {
        size_t n = path ? wcslen(path) : 0;
        if (n == 3 && path[1] == L':') {
            /* 按盘符分别缓存：否则 C:\ D:\ E:\ 会共用同一个索引，
             * 所有驱动器都显示成第一个盘的图标 */
            wchar_t drv = path[0];
            if (drv >= L'a' && drv <= L'z') drv = (wchar_t)(drv - L'a' + L'A');
            StringCchPrintfW(key, cch, L"<drv:%c>", drv);
            return;
        }
        ff_str_copy(key, cch, L"<dir>");
        return;
    }
    wchar_t ext[40];
    ff_path_ext(path ? path : L"", ext, 40);
    if (!ext[0]) ff_str_copy(key, cch, L"<noext>");
    else { ff_str_copy(key, cch, ext); CharLowerW(key); }
}

int fs_get_icon_index(const wchar_t *path, DWORD attrs)
{
    if (attrs == INVALID_FILE_ATTRIBUTES) attrs = FILE_ATTRIBUTE_NORMAL;
    if (attrs == 0) attrs = FILE_ATTRIBUTE_NORMAL;

    wchar_t key[40];
    cache_key_for(path, attrs, key, 40);

    unsigned h = 2166136261u;
    for (const wchar_t *p = key; *p; ++p) h = (h ^ (unsigned)*p) * 16777619u;
    unsigned slot = h & 511;
    if (icon_cache()[slot].valid && _wcsicmp(icon_cache()[slot].key, key) == 0)
        return icon_cache()[slot].icon;

    SHFILEINFOW sfi;
    ZeroMemory(&sfi, sizeof(sfi));
    const wchar_t *probe = path ? path : L"";
    wchar_t synth[64] = L"";
    DWORD flags = SHGFI_SYSICONINDEX | SHGFI_SMALLICON;
    DWORD fa = attrs;

    if (wcsncmp(key, L"<drv:", 5) == 0) {
        /* 驱动器必须用真实根路径查询（不带 SHGFI_USEFILEATTRIBUTES），
         * 否则 Shell 取不到真实介质类型，只会返回通用文件夹图标。
         * 实测 C:\ -> 110（硬盘），可移动盘 -> 8，索引随介质变化。 */
        fa = FILE_ATTRIBUTE_DIRECTORY;
    } else if (attrs & FILE_ATTRIBUTE_DIRECTORY) {
        probe = L"folder";
        fa = FILE_ATTRIBUTE_DIRECTORY;
        flags |= SHGFI_USEFILEATTRIBUTES;
    } else {
        StringCchPrintfW(synth, 64, L"file%s", (key[0] == L'<') ? L".unk" : key);
        probe = synth;
        fa = FILE_ATTRIBUTE_NORMAL;
        flags |= SHGFI_USEFILEATTRIBUTES;
    }
    int icon = 0;
    if (SHGetFileInfoW(probe, fa, &sfi, sizeof(sfi), flags))
        icon = sfi.iIcon;

    icon_cache()[slot].valid = true;
    ff_str_copy(icon_cache()[slot].key, 40, key);
    icon_cache()[slot].icon = icon;
    return icon;
}

/* ================================================================ 自带图标
 * 上面那个 fs_get_icon_index 是"按扩展名"问 Shell 的（file.exe / file.rar / folder），
 * 好处是零磁盘 I/O、一个目录里同类型文件共用一次查询。但对**图标就长在文件自己身上**
 * 的类型（.exe/.dll/.ico/.lnk…），合成文件名拿到的永远是「通用应用程序」图标 ——
 * 资源管理器里 FileCE.exe 是它自带的橙色图标，我们这边却是个灰白通用图标。
 * 这类文件必须拿**真实路径**再问一次 Shell（Shell 会打开文件读图标资源）。
 * 读盘有代价，所以三条约束：
 *   1. 只对「自带图标」的扩展名走这条路，其余仍走扩展名缓存（零 I/O，速度不变）；
 *   2. 结果按完整路径缓存，翻回来 / F5 都不再读盘；
 *   3. UNC 路径（\\server\share）直接跳过 —— 网络不通时绝不能让一次重绘卡住 UI。 */
static bool ext_self_icon(const wchar_t *ext)     /* ext 已小写、含点 */
{
    static const wchar_t *kSelf[] = {
        L".exe", L".com", L".scr", L".pif", L".cpl", L".dll", L".ocx",
        L".sys", L".drv", L".acm", L".ax",  L".ico", L".lnk", L".url", L".msi",
        NULL
    };
    for (int i = 0; kSelf[i]; ++i) if (wcscmp(ext, kSelf[i]) == 0) return true;
    return false;
}

#define ICON_SELF_SLOTS   256
/* 键用堆上按需分配的小串，而不是 wchar_t key[520] 的定长数组：
 * 那个写法会被链接器整块塞进 .data（本工具链的 .bss 几乎为空），
 * 256×520×2 字节 = 270 KB 直接进 exe —— 对"体积敏感"的项目不可接受。
 * 这里 256 个槽只有 4 KB，键串总共也就几十 KB 堆内存。 */
typedef struct { wchar_t *key; int icon; } IconSelfEnt;
static IconSelfEnt s_iconSelf[ICON_SELF_SLOTS];

static int icon_by_real_path(const wchar_t *full, DWORD attrs)
{
    unsigned h = 2166136261u;
    for (const wchar_t *p = full; *p; ++p) {
        wchar_t c = *p;
        if (c >= L'A' && c <= L'Z') c = (wchar_t)(c + 32);   /* 路径比较忽略大小写 */
        h = (h ^ (unsigned)c) * 16777619u;
    }
    unsigned slot = h & (ICON_SELF_SLOTS - 1);
    if (s_iconSelf[slot].key && _wcsicmp(s_iconSelf[slot].key, full) == 0)
        return s_iconSelf[slot].icon;

    SHFILEINFOW sfi;
    ZeroMemory(&sfi, sizeof(sfi));
    int icon = -1;
    if (SHGetFileInfoW(full, attrs, &sfi, sizeof(sfi),
                       SHGFI_SYSICONINDEX | SHGFI_SMALLICON))
        icon = (int)sfi.iIcon;
    if (icon < 0) return -1;                 /* 读不到就让调用方回退到扩展名图标 */

    size_t cch = wcslen(full) + 1;
    wchar_t *dup = (wchar_t *)malloc(cch * sizeof(wchar_t));
    if (dup) {
        memcpy(dup, full, cch * sizeof(wchar_t));
        free(s_iconSelf[slot].key);          /* 覆盖旧键（哈希冲突时） */
        s_iconSelf[slot].key = dup;
        s_iconSelf[slot].icon = icon;
    }
    return icon;
}

/* 列表条目取图标：dir 为当前目录，name 为条目名（搜索结果里是完整路径） */
int fs_icon_for_entry(const wchar_t *dir, const wchar_t *name, DWORD attrs)
{
    if (!name || !*name) return fs_get_icon_index(name, attrs);
    /* 文件夹一律走扩展名缓存：通用文件夹图标与真实文件夹一致（实测都是索引 3），
     * 没必要为了极少数 desktop.ini 自定义图标去逐个读目录。 */
    if (attrs & FILE_ATTRIBUTE_DIRECTORY) return fs_get_icon_index(name, attrs);

    wchar_t ext[40];
    ff_path_ext(name, ext, 40);
    CharLowerW(ext);
    if (!ext_self_icon(ext)) return fs_get_icon_index(name, attrs);

    wchar_t full[FF_PATH_MAX];
    /* 搜索结果里的条目，name 本身就是完整路径（与 mainwin 的 entry_full_path 同一判据） */
    bool absPath = (name[1] == L':' && name[2] == L'\\') || ff_path_is_unc(name);
    if (absPath)          ff_str_copy(full, FF_PATH_MAX, name);
    else if (dir && *dir) ff_path_join(full, FF_PATH_MAX, dir, name);
    else                  return fs_get_icon_index(name, attrs);

    if (ff_path_is_unc(full)) return fs_get_icon_index(name, attrs);

    int icon = icon_by_real_path(full, attrs);
    return icon >= 0 ? icon : fs_get_icon_index(name, attrs);
}

/* ================================================================ 常用位置
 * 桌面 / 文档 是「此电脑」里的虚拟节点，但背后就是真实的用户目录。 */
bool fs_special_path(int kind, wchar_t *out, size_t cch)
{
    if (!out || cch == 0) return false;
    out[0] = 0;

    /* 下载没有老 CSIDL（Vista 才有的已知文件夹），单独走 SHGetKnownFolderPath */
    if (kind == DRIVE_DL_K) {
        static const GUID kFidDownloads =
            { 0x374DE290, 0x123F, 0x4565, { 0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B } };
        PWSTR p = NULL;
        if (SUCCEEDED(SHGetKnownFolderPath(&kFidDownloads, 0, NULL, &p)) && p) {
            ff_str_copy(out, cch, p);
            CoTaskMemFree(p);
            return out[0] != 0;
        }
        return false;
    }

    int csidl = (kind == DRIVE_DESKTOP_K) ? CSIDL_DESKTOP
              : (kind == DRIVE_DOCS_K)    ? CSIDL_PERSONAL
              : (kind == DRIVE_VIDEO_K)   ? CSIDL_MYVIDEO
              : (kind == DRIVE_PICS_K)    ? CSIDL_MYPICTURES
              : (kind == DRIVE_MUSIC_K)   ? CSIDL_MYMUSIC
              : -1;
    if (csidl < 0) return false;
    return SHGetFolderPathW(NULL, csidl, NULL, 0, out) == S_OK;
}

/* 特殊文件夹（桌面/文档/视频/图片/音乐/下载）的图标必须拿真实路径问 shell，
 * 不能像普通目录那样用 "folder" 假路径查（那样只会得到通用文件夹图标）。
 * 按 kind 各缓存一份。 */
int fs_icon_special_folder(int kind, const wchar_t *path)
{
    static int s_cache[16];                 /* 下标 = DRIVE_* kind（9~15） */
    static bool s_inited = false;
    if (!s_inited) {
        for (int i = 0; i < 16; ++i) s_cache[i] = -1;
        s_inited = true;
    }
    int *slot = (kind >= 0 && kind < 16) ? &s_cache[kind] : NULL;
    if (slot && *slot >= 0) return *slot;

    SHFILEINFOW sfi;
    ZeroMemory(&sfi, sizeof(sfi));
    int icon = -1;
    if (path && SHGetFileInfoW(path, FILE_ATTRIBUTE_DIRECTORY, &sfi, sizeof(sfi),
                               SHGFI_SYSICONINDEX | SHGFI_SMALLICON))
        icon = (int)sfi.iIcon;
    if (slot) *slot = icon;
    return icon;
}

/* 此电脑：拿 This PC 的 CLSID PIDL 问 shell 要图标。
 * 不能走 fs_get_icon_index：attrs 带 DIRECTORY 时会用 "folder" 假路径，
 * 只会得到通用文件夹图标。 */
/* 快速访问的图标（shell:::{679F85CB-0220-4080-B29B-5540CC05AAB6}） */
int fs_icon_quick_access(void)
{
    static int s_iconQA = -2;
    if (s_iconQA != -2) return s_iconQA;
    s_iconQA = -1;

    PIDLIST_ABSOLUTE pidl = NULL;
    if (SUCCEEDED(SHParseDisplayName(L"shell:::{679F85CB-0220-4080-B29B-5540CC05AAB6}",
                                     NULL, &pidl, 0, NULL)) && pidl) {
        SHFILEINFOW sfi;
        ZeroMemory(&sfi, sizeof(sfi));
        if (SHGetFileInfoW((LPCWSTR)pidl, FILE_ATTRIBUTE_DIRECTORY, &sfi, sizeof(sfi),
                           SHGFI_PIDL | SHGFI_SYSICONINDEX | SHGFI_SMALLICON))
            s_iconQA = (int)sfi.iIcon;
        CoTaskMemFree(pidl);
    }
    return s_iconQA;
}

int fs_icon_this_pc(void)
{
    static int s_iconThisPC = -1;
    if (s_iconThisPC >= 0) return s_iconThisPC;

    int icon = -1;
    PIDLIST_ABSOLUTE pidl = NULL;
    if (SUCCEEDED(SHParseDisplayName(L"::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
                                     NULL, &pidl, 0, NULL)) && pidl) {
        SHFILEINFOW sfi;
        ZeroMemory(&sfi, sizeof(sfi));
        if (SHGetFileInfoW((LPCWSTR)pidl, FILE_ATTRIBUTE_DIRECTORY, &sfi, sizeof(sfi),
                           SHGFI_PIDL | SHGFI_SYSICONINDEX | SHGFI_SMALLICON))
            icon = (int)sfi.iIcon;
        CoTaskMemFree(pidl);
    }
    s_iconThisPC = icon;
    return icon;
}

/* ================================================================ 目录枚举 */
static bool push_entry(FfEntryList *out, const FfEntry *e)
{
    if (out->count >= out->cap) {
        int nc = out->cap ? out->cap * 2 : 128;
        FfEntry *ni = (FfEntry *)realloc(out->items, (size_t)nc * sizeof(FfEntry));
        if (!ni) return false;
        out->items = ni; out->cap = nc;
    }
    out->items[out->count++] = *e;
    return true;
}

void fs_entry_list_free(FfEntryList *l)
{
    if (!l) return;
    if (l->items) free(l->items);
    l->items = NULL; l->count = 0; l->cap = 0;
}

bool fs_list_dir(const wchar_t *dir, FfEntryList *out)
{
    if (!out) return false;

    /* 复用已有容量，只清 count。
     * 原先这里会把列表整块 free 再从 128 倍增分配到实际条数——
     * 一个 1.5 万条的目录 F5 一次就是几十 MB 的 malloc/free 周转，
     * 既慢，又会让堆碎化把工作集越刷越高。 */
    int keepCount = out->count;
    out->count = 0;
    if (!out->items) out->cap = 0;

    /* 空路径 = "此电脑" 视图：6 常用位置 + 驱动器 + 网络（带分组信息） */
    if (!dir || !*dir) { fs_enum_this_pc(out); return true; }

    wchar_t pattern[FF_PATH_MAX];
    ff_path_join(pattern, FF_PATH_MAX, dir, L"*");

    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileExW(pattern, FindExInfoBasic, &fd,
                                FindExSearchNameMatch, NULL,
                                FIND_FIRST_EX_LARGE_FETCH);
    if (h == INVALID_HANDLE_VALUE) {
        h = FindFirstFileW(pattern, &fd);
    }
    if (h == INVALID_HANDLE_VALUE) {
        out->count = keepCount;     /* 打不开就保留原列表，不要清空当前目录 */
        return false;
    }

    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        FfEntry e;
        ZeroMemory(&e, sizeof(e));
        ff_str_copy(e.name, 512, fd.cFileName);
        e.attrs = fd.dwFileAttributes;
        e.isDir = (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? 1 : 0;
        e.size = ((ULONGLONG)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
        e.mtime = fd.ftLastWriteTime;
        e.ctime = fd.ftCreationTime;
        e.atime = fd.ftLastAccessTime;
        /* 类型名与图标延迟到真正显示时再解析（大目录打开速度的关键） */
        e.type[0] = 0;
        e.iconIndex = -1;
        if (!push_entry(out, &e)) break;
    } while (FindNextFileW(h, &fd));

    FindClose(h);
    return true;
}

/* ================================================================ 删除 */
static bool build_double_list(const wchar_t **paths, int count,
                              wchar_t *buf, size_t cch)
{
    size_t pos = 0;
    buf[0] = 0;
    for (int i = 0; i < count; ++i) {
        size_t n = wcslen(paths[i]) + 1;
        if (pos + n + 1 >= cch) return false;
        memcpy(buf + pos, paths[i], n * sizeof(wchar_t));
        pos += n;
        buf[pos] = 0;
    }
    buf[pos + 1] = 0;                 /* 双 null 结尾 */
    return true;
}

bool fs_delete_to_recycle(HWND owner, const wchar_t **paths, int count,
                          wchar_t *err, size_t cch)
{
    static wchar_t *buf;              /* 堆(64KB):静态零数组会进 .data */
    if (!buf) buf = (wchar_t *)calloc(32768, sizeof(wchar_t));
    if (!build_double_list(paths, count, buf, 32768)) {
        if (err) ff_str_copy(err, cch, L"一次删除的文件过多，请分批操作。");
        return false;
    }
    SHFILEOPSTRUCTW op;
    ZeroMemory(&op, sizeof(op));
    op.hwnd = owner;
    op.wFunc = FO_DELETE;
    op.pFrom = buf;
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT;
    int r = SHFileOperationW(&op);
    if (r != 0 || op.fAnyOperationsAborted) {
        if (err) StringCchPrintfW(err, cch, L"删除失败（错误码 %d）。", r);
        return false;
    }
    return true;
}

static bool delete_recursive(const wchar_t *path, wchar_t *err, size_t cch)
{
    DWORD a = GetFileAttributesW(path);
    if (a == INVALID_FILE_ATTRIBUTES) {
        if (err) StringCchPrintfW(err, cch, L"找不到文件：%s", path);
        return false;
    }
    if (a & FILE_ATTRIBUTE_READONLY)
        SetFileAttributesW(path, a & ~FILE_ATTRIBUTE_READONLY);

    if (!(a & FILE_ATTRIBUTE_DIRECTORY)) {
        if (!DeleteFileW(path)) {
            if (err) StringCchPrintfW(err, cch, L"无法删除文件：%s", path);
            return false;
        }
        return true;
    }

    wchar_t pat[FF_PATH_MAX];
    ff_path_join(pat, FF_PATH_MAX, path, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
                continue;
            wchar_t child[FF_PATH_MAX];
            ff_path_join(child, FF_PATH_MAX, path, fd.cFileName);
            if (!delete_recursive(child, err, cch)) { FindClose(h); return false; }
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    if (!RemoveDirectoryW(path)) {
        if (err) StringCchPrintfW(err, cch, L"无法删除目录：%s", path);
        return false;
    }
    return true;
}

bool fs_delete_permanent(HWND owner, const wchar_t **paths, int count,
                         wchar_t *err, size_t cch)
{
    (void)owner;
    for (int i = 0; i < count; ++i)
        if (!delete_recursive(paths[i], err, cch)) return false;
    return true;
}

/* ================================================================ 属性 */
bool fs_set_attrs(const wchar_t *path, DWORD setMask, DWORD clearMask, bool recurse)
{
    DWORD a = GetFileAttributesW(path);
    if (a == INVALID_FILE_ATTRIBUTES) return false;
    DWORD na = (a | setMask) & ~clearMask;
    bool ok = true;
    if (na != a) ok = SetFileAttributesW(path, na) != 0;

    if (recurse && (a & FILE_ATTRIBUTE_DIRECTORY)) {
        wchar_t pat[FF_PATH_MAX];
        ff_path_join(pat, FF_PATH_MAX, path, L"*");
        WIN32_FIND_DATAW fd;
        HANDLE h = FindFirstFileW(pat, &fd);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
                    continue;
                wchar_t child[FF_PATH_MAX];
                ff_path_join(child, FF_PATH_MAX, path, fd.cFileName);
                if (!fs_set_attrs(child, setMask, clearMask, true)) ok = false;
            } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
    }
    return ok;
}

static ULONGLONG dir_total_size(const wchar_t *dir, int *files)
{
    ULONGLONG total = 0;
    wchar_t pat[FF_PATH_MAX];
    ff_path_join(pat, FF_PATH_MAX, dir, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        wchar_t child[FF_PATH_MAX];
        ff_path_join(child, FF_PATH_MAX, dir, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            total += dir_total_size(child, files);
        else {
            total += ((ULONGLONG)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
            if (files) ++*files;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return total;
}

/* 全局取消标志：复制进度对话框可随时置位 */
static volatile LONG s_copyCancel = 0;
void fs_cancel_copy(void) { InterlockedExchange(&s_copyCancel, 1); }
void fs_reset_copy_cancel(void) { InterlockedExchange(&s_copyCancel, 0); }

/* ---------------- 复制 / 移动 ----------------
 * ★试过用 shell 的 SHFileOperationW 当唯一引擎（flags 0xC1 与 0xC1|NOCONFIRMATION、
 *   pTo 传目录与传完整路径、主线程直接调、独立线程 + hwnd=NULL —— 全部组合都试过）：
 *   调用后**永远不返回**。日志能证明：BEFORE 那行打印了，AFTER 那行再也出不来，
 *   进程只能被杀掉。同样的参数在独立进程里却完全正常，所以不是参数写错。
 *   → 这个程序里用不了，只能自己执行复制。
 *
 * 冲突策略（用户要求）：
 *   · 同目录复制（源 = 目标）→ **不打扰**，直接生成 "名字 (2).ext"
 *   · 目标已有同名文件    → 问一次：替换 / 两者都保留 / 取消 */
typedef enum { CF_ASK = 0, CF_OVERWRITE, CF_KEEP_BOTH, CF_STOP } ConflictAct;

static bool conflict_delete_target(const wchar_t *path)
{
    DWORD a = GetFileAttributesW(path);
    if (a == INVALID_FILE_ATTRIBUTES) return true;
    if (a & FILE_ATTRIBUTE_DIRECTORY) {
        wchar_t buf[FF_PATH_MAX * 2];
        size_t n = wcslen(path);
        if (n + 2 > FF_PATH_MAX * 2) return false;
        memcpy(buf, path, (n + 1) * sizeof(wchar_t));
        buf[n + 1] = 0;
        SHFILEOPSTRUCTW op;
        ZeroMemory(&op, sizeof(op));
        op.hwnd = NULL;
        op.wFunc = FO_DELETE;
        op.pFrom = buf;
        op.fFlags = FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT;
        return SHFileOperationW(&op) == 0;
    }
    SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL);
    return DeleteFileW(path) != 0;
}

static ConflictAct conflict_ask(HWND owner, const wchar_t *name, int total, bool isMove)
{
    wchar_t msg[1024];
    StringCchPrintfW(msg, 1024,
        L"目标文件夹中已存在同名项目：\n%s\n\n"
        L"【是】替换目标中的项目\n"
        L"【否】两个都保留（自动改名）\n"
        L"【取消】停止%s%s",
        name, isMove ? L"移动" : L"复制",
        total > 1 ? L"\n\n（本次选择将应用到剩余的全部项目）" : L"");
    int r = MessageBoxW(owner, msg, L"确认文件替换", MB_YESNOCANCEL | MB_ICONWARNING);
    if (r == IDYES) return CF_OVERWRITE;
    if (r == IDNO)  return CF_KEEP_BOTH;
    return CF_STOP;
}

static void conflict_unique_name(const wchar_t *dstDir, const wchar_t *name,
                                 wchar_t *out, size_t cchOut)
{
    wchar_t stem[512], ext[40], tmp[FF_PATH_MAX];
    ff_str_copy(stem, 512, name);
    ff_path_ext(stem, ext, 40);
    if (ext[0]) {
        size_t sl = wcslen(stem), el = wcslen(ext);
        if (sl > el) stem[sl - el] = 0;
    }
    int n = 2;
    do {
        if (ext[0]) StringCchPrintfW(tmp, FF_PATH_MAX, L"%s (%d)%s", stem, n++, ext);
        else        StringCchPrintfW(tmp, FF_PATH_MAX, L"%s (%d)", stem, n++);
        ff_path_join(out, cchOut, dstDir, tmp);
    } while (fs_path_exists(out) && n < 999);
}

static bool copy_tree_plain(const wchar_t *src, const wchar_t *dst)
{
    if (!CreateDirectoryW(dst, NULL) && GetLastError() != ERROR_ALREADY_EXISTS)
        return false;
    wchar_t pat[FF_PATH_MAX];
    ff_path_join(pat, FF_PATH_MAX, src, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return true;
    bool ok = true;
    do {
        if (!wcscmp(fd.cFileName, L".") || !wcscmp(fd.cFileName, L"..")) continue;
        wchar_t s2[FF_PATH_MAX], d2[FF_PATH_MAX];
        ff_path_join(s2, FF_PATH_MAX, src, fd.cFileName);
        ff_path_join(d2, FF_PATH_MAX, dst, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (!copy_tree_plain(s2, d2)) ok = false;
        } else {
            SetFileAttributesW(d2, FILE_ATTRIBUTE_NORMAL);
            if (!CopyFileExW(s2, d2, NULL, NULL, NULL, 0)) ok = false;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return ok;
}

bool fs_copy_move(HWND owner, const wchar_t **src, int count, const wchar_t *dstDir,
                  bool isMove, wchar_t *err, size_t cchErr)
{
    if (err && cchErr) err[0] = 0;
    if (!src || count <= 0 || !dstDir || !dstDir[0]) return false;

    ConflictAct policy = CF_ASK;
    bool ok = true;
    int done = 0;

    for (int i = 0; i < count; ++i) {
        if (!src[i] || !src[i][0]) continue;
        if (InterlockedCompareExchange(&s_copyCancel, 0, 0)) {
            ok = false;
            if (err && cchErr) ff_str_copy(err, cchErr, L"操作已取消。");
            break;
        }

        const wchar_t *name = ff_path_name(src[i]);
        wchar_t final[FF_PATH_MAX];
        ff_path_join(final, FF_PATH_MAX, dstDir, name);

        size_t sl = wcslen(src[i]);
        if (_wcsnicmp(src[i], dstDir, sl) == 0 &&
            (dstDir[sl] == L'\\' || dstDir[sl] == 0)) {
            ff_msg_error(owner, L"不能把文件夹放入它自己的子目录中：\n%s", src[i]);
            ok = false;
            continue;
        }

        DWORD a = GetFileAttributesW(src[i]);
        if (a == INVALID_FILE_ATTRIBUTES) {
            ff_msg_error(owner, L"找不到对象：\n%s", src[i]);
            ok = false;
            continue;
        }
        bool isDir = (a & FILE_ATTRIBUTE_DIRECTORY) != 0;

        /* 同目录复制：不打扰，直接出 "名字 (2).ext" */
        if (ff_same_path(src[i], final)) {
            conflict_unique_name(dstDir, name, final, FF_PATH_MAX);
        } else if (fs_path_exists(final)) {
            if (policy == CF_ASK) policy = conflict_ask(owner, name, count, isMove);
            if (policy == CF_STOP) {
                ok = false;
                if (err && cchErr) ff_str_copy(err, cchErr, L"操作已取消。");
                break;
            }
            if (policy == CF_OVERWRITE) {
                if (!conflict_delete_target(final)) {
                    ff_msg_error(owner, L"无法替换已存在的项目：\n%s", final);
                    ok = false;
                    continue;
                }
            } else {
                conflict_unique_name(dstDir, name, final, FF_PATH_MAX);
            }
        }

        if (isMove) {
            if (MoveFileExW(src[i], final, MOVEFILE_COPY_ALLOWED)) { ++done; continue; }
            ok = false;
            if (err && cchErr) StringCchPrintfW(err, cchErr, L"移动失败（错误码 %lu）。",
                                                (unsigned long)GetLastError());
            continue;
        }
        bool r = isDir ? copy_tree_plain(src[i], final)
                       : (CopyFileExW(src[i], final, NULL, NULL, NULL, 0) != 0);
        if (r) { ++done; continue; }
        ok = false;
        if (err && cchErr) StringCchPrintfW(err, cchErr, L"复制失败（错误码 %lu）。",
                                            (unsigned long)GetLastError());
    }

    DBG(L"fs_copy_move: 完成 %d/%d ok=%d", done, count, ok ? 1 : 0);
    return ok && done > 0;
}

/* ================================================================ 查找 */
static bool match_pattern(const wchar_t *name, const wchar_t *pattern)
{
    if (!pattern || !*pattern) return true;
    /* 支持多模式，以 ';' 分隔 */
    wchar_t buf[512];
    ff_str_copy(buf, 512, pattern);
    wchar_t *ctx = NULL;
    for (wchar_t *t = wcstok(buf, L";", &ctx); t; t = wcstok(NULL, L";", &ctx)) {
        ff_trim(t);
        if (!*t) continue;
        if (PathMatchSpecW(name, t)) return true;
    }
    return false;
}

static void find_walk(const wchar_t *dir, const wchar_t *pattern, bool recurse,
                      FfEntryList *out, volatile LONG *cancel, int depth)
{
    if (depth > 40) return;
    if (cancel && InterlockedCompareExchange(cancel, 0, 0)) return;

    wchar_t pat[FF_PATH_MAX];
    ff_path_join(pat, FF_PATH_MAX, dir, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (cancel && InterlockedCompareExchange(cancel, 0, 0)) break;
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        wchar_t child[FF_PATH_MAX];
        ff_path_join(child, FF_PATH_MAX, dir, fd.cFileName);
        bool isDir = (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;

        if (match_pattern(fd.cFileName, pattern)) {
            FfEntry e;
            ZeroMemory(&e, sizeof(e));
            ff_str_copy(e.name, 512, child);
            e.attrs = fd.dwFileAttributes;
            e.isDir = isDir ? 1 : 0;
            e.size = ((ULONGLONG)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
            e.mtime = fd.ftLastWriteTime;
            e.ctime = fd.ftCreationTime;
            e.atime = fd.ftLastAccessTime;
            ff_str_copy(e.type, 128, isDir ? L"文件夹" : L"");
            e.iconIndex = -1;
            if (!push_entry(out, &e)) { FindClose(h); return; }
        }
        if (recurse && isDir && !(fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
            find_walk(child, pattern, recurse, out, cancel, depth + 1);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

bool fs_find_files(HWND owner, const wchar_t *root, const wchar_t *pattern,
                   bool recurse, FfEntryList *out, volatile LONG *cancel)
{
    (void)owner;
    if (!out) return false;
    out->items = NULL; out->count = 0; out->cap = 0;
    if (!root || !*root) return false;
    find_walk(root, pattern, recurse, out, cancel, 0);
    return true;
}

ULONGLONG fs_dir_size(const wchar_t *dir)
{
    int f = 0;
    return dir_total_size(dir, &f);
}

/* ================================================================ 打开 / 属性 */
bool fs_open_path(HWND owner, const wchar_t *path)
{
    if (!path || !*path) return false;
    HINSTANCE r = ShellExecuteW(owner, L"open", path, NULL, NULL, SW_SHOWNORMAL);
    return (INT_PTR)r > 32;
}

bool fs_show_properties(HWND owner, const wchar_t *path)
{
    if (!path || !*path) return false;
    return SHObjectProperties(owner, SHOP_FILEPATH, path, NULL) != 0;
}

bool fs_show_properties_multi(HWND owner, const wchar_t **paths, int count)
{
    if (count <= 0) return false;
    /* 资源管理器对多选也只在属性页中汇总，这里对首个对象调用系统属性页 */
    return fs_show_properties(owner, paths[0]);
}

/* ================================================================ NTFS 数据流 */
bool fs_enum_streams(const wchar_t *path, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!path || !*path) return false;

    /* 注意参数顺序必须是 (文件名, InfoLevel, 数据缓冲, ...)。
     * 早期这里把第 2、3 个参数写反了，实际等于用缓冲区地址当 InfoLevel，
     * 而真正的数据缓冲传成了 NULL，调用必然失败。 */
    typedef HANDLE (WINAPI *PFN_FFSW)(LPCWSTR, DWORD, LPVOID, DWORD, DWORD, LPHANDLE);
    typedef BOOL   (WINAPI *PFN_FNSW)(HANDLE, LPVOID);

    HMODULE k = GetModuleHandleW(L"kernel32.dll");
    PFN_FFSW pFirst = (PFN_FFSW)(void *)GetProcAddress(k, "FindFirstStreamW");
    PFN_FNSW pNext  = (PFN_FNSW)(void *)GetProcAddress(k, "FindNextStreamW");
    if (!pFirst || !pNext) {
        ff_str_copy(out, cch, L"当前系统不支持数据流查询。");
        return false;
    }
    wchar_t file[FF_PATH_MAX];
    ff_str_copy(file, FF_PATH_MAX, path);
    for (wchar_t *p = file; *p; ++p) if (*p == L'/') *p = L'\\';

    WIN32_FIND_STREAM_DATA sd;
    HANDLE h = pFirst(file, 0 /* FindStreamInfoStandard */, &sd, 0, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        DWORD e = GetLastError();
        if (e == ERROR_HANDLE_EOF || e == ERROR_INVALID_FUNCTION)
            ff_str_copy(out, cch, L"该对象不含备用数据流。");
        else if (e == ERROR_INVALID_PARAMETER)
            ff_str_copy(out, cch, L"仅 NTFS 卷支持备用数据流。");
        else
            StringCchPrintfW(out, cch, L"读取数据流失败（错误码 %lu）。", (unsigned long)e);
        return false;
    }
    size_t used = 0;
    int n = 0;
    do {
        wchar_t line[512];
        StringCchPrintfW(line, 512, L"%-30s %10.2f KB\n", sd.cStreamName,
                 (double)sd.StreamSize.QuadPart / 1024.0);
        size_t l = wcslen(line);
        if (used + l + 1 >= cch) break;
        memcpy(out + used, line, (l + 1) * sizeof(wchar_t));
        used += l;
        ++n;
    } while (pNext(h, &sd));
    FindClose(h);
    if (n == 0) ff_str_copy(out, cch, L"该对象不含备用数据流。");
    return n > 0;
}

/* ------------------------------------------------------------------ 快捷方式 */
/* 建一个 .lnk —— 资源管理器右键"创建快捷方式 / 粘贴快捷方式"就是它 */
static bool s_make_shortcut(const wchar_t *target, const wchar_t *lnkPath)
{
    IShellLinkW *psl = NULL;
    if (FAILED(CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER,
                                &IID_IShellLinkW, (void **)&psl)) || !psl)
        return false;

    wchar_t dir[FF_PATH_MAX];
    ff_str_copy(dir, FF_PATH_MAX, target);
    PathRemoveFileSpecW(dir);

    psl->lpVtbl->SetPath(psl, target);
    psl->lpVtbl->SetWorkingDirectory(psl, dir);

    bool ok = false;
    IPersistFile *ppf = NULL;
    if (SUCCEEDED(psl->lpVtbl->QueryInterface(psl, &IID_IPersistFile, (void **)&ppf))
            && ppf) {
        ok = SUCCEEDED(ppf->lpVtbl->Save(ppf, lnkPath, TRUE));
        ppf->lpVtbl->Release(ppf);
    }
    psl->lpVtbl->Release(psl);
    return ok;
}

/* 在 dir 里给剪贴板中的每个文件建快捷方式（"粘贴快捷方式"）。
 * 目标是 dir\原名.lnk，重名时依次试 "原名 (2).lnk"、"原名 (3).lnk"… */
bool fs_paste_shortcut(HWND owner, const wchar_t *dir, wchar_t *err, size_t cchErr)
{
    if (err && cchErr) err[0] = 0;
    if (!dir || !dir[0]) return false;

    if (!OpenClipboard(owner)) {
        if (err && cchErr) ff_str_copy(err, cchErr, L"打不开剪贴板。");
        return false;
    }
    HDROP drop = (HDROP)GetClipboardData(CF_HDROP);
    if (!drop) {
        CloseClipboard();
        if (err && cchErr) ff_str_copy(err, cchErr, L"剪贴板里没有文件。");
        return false;
    }

    /* dir 可能带尾部反斜杠（如 C:\），避免拼出双斜杠 */
    wchar_t base[FF_PATH_MAX];
    ff_str_copy(base, FF_PATH_MAX, dir);
    size_t bl = wcslen(base);
    if (bl > 3 && base[bl - 1] == L'\\') base[bl - 1] = 0;

    UINT n = DragQueryFileW(drop, 0xFFFFFFFFu, NULL, 0);
    int made = 0;
    wchar_t firstErr[FF_PATH_MAX] = L"";
    for (UINT i = 0; i < n; ++i) {
        wchar_t src[FF_PATH_MAX];
        if (!DragQueryFileW(drop, i, src, FF_PATH_MAX)) continue;

        wchar_t stem[260];
        ff_str_copy(stem, 260, PathFindFileNameW(src));
        PathRemoveExtensionW(stem);
        if (!stem[0]) ff_str_copy(stem, 260, L"快捷方式");

        wchar_t lnk[FF_PATH_MAX];
        for (int k = 1; k < 1000; ++k) {
            if (k == 1)
                StringCchPrintfW(lnk, FF_PATH_MAX, L"%s\\%s.lnk", base, stem);
            else
                StringCchPrintfW(lnk, FF_PATH_MAX, L"%s\\%s (%d).lnk", base, stem, k);
            if (GetFileAttributesW(lnk) == INVALID_FILE_ATTRIBUTES) break;
        }
        if (s_make_shortcut(src, lnk)) {
            ++made;
        } else if (!firstErr[0]) {
            ff_str_copy(firstErr, FF_PATH_MAX, src);
        }
    }
    CloseClipboard();          /* ★必须在用完 HDROP 之后才能关 */

    if (made == 0 && err && cchErr) {
        if (firstErr[0])
            StringCchPrintfW(err, cchErr, L"创建快捷方式失败：%s", firstErr);
        else
            ff_str_copy(err, cchErr, L"没有创建任何快捷方式。");
    }
    return made > 0;
}

/* ------------------------------------------------------------ 目录变化监听 */
/* 为什么需要：WinRAR 解压、shell 的删除、别的程序改名…… 这些都在**别的进程**
 * 里完成，本程序事后无从得知，于是列表里看不到变化（用户实测："删除、解压到
 * 当前目录以后不刷新"）。监听当前目录，一有风吹草动就通知主窗口去刷新。 */
static HANDLE  s_watchDir   = INVALID_HANDLE_VALUE;
static HANDLE  s_watchStop  = NULL;
static HANDLE  s_watchEvent = NULL;      /* 线程真正等的 OVERLAPPED 事件 */
static HANDLE  s_watchThread = NULL;
static HWND    s_watchHwnd  = NULL;
static wchar_t *s_watchPath = NULL;   /* 按需分配：定长数组会整块进 .data */

static DWORD WINAPI watch_thread(LPVOID arg)
{
    (void)arg;
    BYTE buf[4096];

    for (;;) {
        OVERLAPPED ov;
        ZeroMemory(&ov, sizeof(ov));
        ov.hEvent = s_watchEvent;

        DWORD ret = 0;
        BOOL ok = ReadDirectoryChangesW(s_watchDir, buf, sizeof(buf), FALSE,
                                        FILE_NOTIFY_CHANGE_FILE_NAME |
                                        FILE_NOTIFY_CHANGE_DIR_NAME |
                                        FILE_NOTIFY_CHANGE_SIZE |
                                        FILE_NOTIFY_CHANGE_LAST_WRITE |
                                        FILE_NOTIFY_CHANGE_CREATION,
                                        &ret, &ov, NULL);
        if (!ok && GetLastError() != ERROR_IO_PENDING)
            break;                       /* 目录没了/句柄关了：线程退出 */

        /* 等"有变化"或者"该收工" */
        HANDLE waits[2];
        waits[0] = s_watchEvent;
        waits[1] = s_watchStop;
        DWORD w = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
        if (w == WAIT_OBJECT_0 + 1) break;            /* stop */
        if (w != WAIT_OBJECT_0) break;

        /* 读走本次结果（错误也无所谓，下一次重新挂） */
        DWORD got = 0;
        if (!GetOverlappedResult(s_watchDir, &ov, &got, FALSE))
            break;

        if (WaitForSingleObject(s_watchStop, 0) == WAIT_OBJECT_0) break;
        DBG(L"watch: 有变化，通知主窗口");
        if (s_watchHwnd) PostMessageW(s_watchHwnd, WM_FF_WATCH, 0, 0);
    }
    return 0;
}

void fs_watch_stop(void)
{
    if (s_watchStop) SetEvent(s_watchStop);
    if (s_watchThread) {
        WaitForSingleObject(s_watchThread, 2000);     /* 先让线程退出，再关句柄 */
        CloseHandle(s_watchThread);
        s_watchThread = NULL;
    }
    if (s_watchEvent) { CloseHandle(s_watchEvent); s_watchEvent = NULL; }
    if (s_watchStop)  { CloseHandle(s_watchStop);  s_watchStop = NULL; }
    if (s_watchDir != INVALID_HANDLE_VALUE) {
        CloseHandle(s_watchDir);
        s_watchDir = INVALID_HANDLE_VALUE;
    }
    s_watchHwnd = NULL;
    free(s_watchPath);
    s_watchPath = NULL;
}

bool fs_watch_set(HWND notify, const wchar_t *dir)
{
    if (!notify || !dir || !dir[0]) { fs_watch_stop(); return false; }
    /* 目录没变、线程还活着 → 什么都不用做（否则每次刷新都会重建线程） */
    if (s_watchThread && s_watchPath && !_wcsicmp(s_watchPath, dir)
            && s_watchDir != INVALID_HANDLE_VALUE)
        return true;

    fs_watch_stop();

    s_watchDir = CreateFileW(dir, FILE_LIST_DIRECTORY,
                             FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                             NULL, OPEN_EXISTING,
                             FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED,
                             NULL);
    if (s_watchDir == INVALID_HANDLE_VALUE) { s_watchDir = INVALID_HANDLE_VALUE; return false; }

    s_watchStop  = CreateEventW(NULL, TRUE, FALSE, NULL);
    s_watchEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!s_watchStop || !s_watchEvent) { fs_watch_stop(); return false; }

    s_watchHwnd = notify;
    free(s_watchPath);
    s_watchPath = _wcsdup(dir);
    s_watchThread = CreateThread(NULL, 0, watch_thread, NULL, 0, NULL);
    DBG(L"watch_set: dir=%ls thread=%p", dir, (void *)s_watchThread);
    if (!s_watchThread) { fs_watch_stop(); return false; }
    return true;
}
