/*
 * shellmenu.c —— 把 Windows（资源管理器）自己的右键菜单接进本程序
 * ---------------------------------------------------------------
 * 入口：三处右键菜单（列表选中项 / 列表空白处 / 目录树节点）末尾的
 * 「更多选项…」。点它弹出来的才是系统那份菜单 —— WinRAR/7-Zip 的"解压到…"、
 * TortoiseGit、"通过 Code 打开"、发送到、还原以前的版本…… 这些第三方扩展
 * 只有 shell 能提供，本程序永远做不出来。
 *
 * ★关键认知：资源管理器的右键菜单不是"从 shell 拿一份"，而是
 *   "shell 给半成品 + Explorer 当宿主补全"。宿主要做三件事，缺一件就"差好多"：
 *     ① 补项：打开/打印/编辑/刷新/粘贴/撤消重命名… 这些 shell 自己不加，
 *        是宿主在 DFM_MERGECONTEXTMENU_TOP / _BOTTOM 里插进去的；
 *     ② 接管需要 UI 的命令：重命名（shell 自己弹不出框）走 DFM_INVOKECOMMAND；
 *     ③ 画图标：实测 Explorer 的 30 项【全部】是 MF_OWNERDRAW，图标是它自己画的；
 *        我们这些项拿不到 hbmpItem，图标列会空一大片 —— 必须自己补位图。
 *
 * 实测对照（本机 Win10 19045，同一目录同一文件）：
 *   资源管理器：文件菜单 30 项、空白处 19 项，全部有图标
 *   只拿 shell 半成品（GetUIObjectOf）：29 项但缺"重命名"，图标只覆盖第三方那 11 项
 *   换 CDefFolderMenu_Create2 但不给 callback：25 项，连"打开/打印/编辑"都丢
 *   SHCreateDefaultContextMenu 不带 callback（空白处）：0 项
 *   → 结论：没有宿主回调，换任何接口都凑不齐。
 *
 * 实现要点（每条都是踩过才知道的）：
 *  1. 用 CDefFolderMenu_Create2（不是 GetUIObjectOf）并传 LPFNDFMCALLBACK，
 *     它才会在 QueryContextMenu 过程中回调我们补项、并把需要宿主的命令交给我们。
 *  2. 空白处菜单也走 CDefFolderMenu_Create2（cidl=0）。
 *  3. 命令 ID 分两段：shell 用我们传进去的 0x7000~0x7FFF（InvokeCommand 要的是
 *     id - 0x7000），本程序自己插的项用 0x5000 起（见 ff.h 的 SM_CMD_*）。
 *     ★ID 是稀的、与菜单位置不连续（"属性"常是 0x7000 本身、扩展项是 0x7000+0x53），
 *     千万别按"菜单里第几项"去推。
 *  4. 菜单显示期间，TrackPopupMenu 的模态循环会把 WM_INITMENUPOPUP /
 *     WM_DRAWITEM / WM_MEASUREITEM / WM_MENUCHAR 派发给菜单属主窗口，
 *     必须转给 IContextMenu2/3 —— 否则扩展自绘的项是空白、它自己的二级
 *     子菜单（WinRAR 的"解压到 xxx\"）展不开。
 *  5. InvokeCommand 必须 CMINVOKECOMMANDINFOEX + CMIC_MASK_UNICODE，
 *     否则中文目录（D:\software\办公软件\…）里扩展拿到乱码工作目录。
 *  6. 图标：拿不到 hbmpItem 的项，用菜单命令的【verb】认语义（GetCommandString
 *     GCS_VERBW），再取系统图标做成 16×16 位图塞进 MIIM_BITMAP。
 *     菜单销毁时要 DeleteObject 回收这些位图。
 *  7. 剪切/复制/删除/粘贴/新建/创建快捷方式/属性 这些【不接管】：DFM_INVOKECOMMAND
 *     返回 E_NOTIMPL，让 shell 用它的原生实现执行 —— 行为与资源管理器完全一致，
 *     我们不重复实现（唯一必须接管的是"重命名"，shell 自己弹不出重命名框）。
 */
#include "ff.h"
#include <shobjidl.h>

/* 命令 ID 区间：shell 用这一段，本程序自己的项用 SM_CMD_*(0x5000 起) */
#define SM_ID_FIRST   0x7000
#define SM_ID_LAST    0x7FFF

#define SM_ICON_MAX   96

/* 菜单显示期间的扩展消息转发目标（非 NULL 时表示系统菜单正开着） */
static IContextMenu2 *s_icm2 = NULL;
static IContextMenu3 *s_icm3 = NULL;

/* 一个待显示的菜单的上下文 */
typedef struct {
    IContextMenu  *pcm;
    IShellFolder  *psf;
    LPITEMIDLIST   pidlFolder;    /* 父目录（选中项）/ 自身（空白处）的绝对 PIDL */
    LPITEMIDLIST  *fulls;         /* 每个选中路径的绝对 PIDL */
    LPITEMIDLIST  *children;      /* 相对父文件夹的子 PIDL（指进 fulls 里） */
    int            nfull;
    bool           isBackground;
    wchar_t        dir[FF_PATH_MAX];
    wchar_t      **selPaths;      /* 选中项完整路径（自有拷贝，回调里用） */
    int            selCount;
    HBITMAP        bmps[SM_ICON_MAX];   /* 给菜单项补的图标位图，销毁时要删 */
    int            nbmps;
} SmCtx;

/* 回调期间指向当前上下文（菜单是模态的，单线程，不会并发） */
static SmCtx *s_cbCtx = NULL;
static SmCtx *s_menuCtx = NULL;   /* 菜单弹出期间有效（WM_INITMENUPOPUP 用） */

static void sm_zero(SmCtx *c) { ZeroMemory(c, sizeof(*c)); }

static void sm_close(SmCtx *c)
{
    for (int i = 0; i < c->nbmps; ++i)
        if (c->bmps[i]) DeleteObject(c->bmps[i]);
    c->nbmps = 0;

    if (c->pcm) { c->pcm->lpVtbl->Release(c->pcm); c->pcm = NULL; }
    if (c->psf) { c->psf->lpVtbl->Release(c->psf); c->psf = NULL; }
    if (c->pidlFolder) { CoTaskMemFree(c->pidlFolder); c->pidlFolder = NULL; }
    if (c->fulls) {
        for (int i = 0; i < c->nfull; ++i)
            if (c->fulls[i]) CoTaskMemFree(c->fulls[i]);
        free(c->fulls);
        c->fulls = NULL;
    }
    free(c->children);
    c->children = NULL;
    if (c->selPaths) {
        for (int i = 0; i < c->selCount; ++i) free(c->selPaths[i]);
        free(c->selPaths);
        c->selPaths = NULL;
    }
    c->selCount = 0;
    c->nfull = 0;
}

static void sm_release_handlers(void)
{
    if (s_icm3) { s_icm3->lpVtbl->Release(s_icm3); s_icm3 = NULL; }
    if (s_icm2) { s_icm2->lpVtbl->Release(s_icm2); s_icm2 = NULL; }
}

/* 取父目录（PathRemoveFileSpecW 对 "C:\file.txt" 会正确留下 "C:\"） */
static void sm_parent_of(const wchar_t *path, wchar_t *out, size_t cch)
{
    ff_str_copy(out, cch, path);
    PathRemoveFileSpecW(out);
}

/* 该文件有没有某个 shell 动词（打印/编辑这类 shell 菜单不给，要宿主判断） */
static bool sm_has_verb(const wchar_t *path, const wchar_t *verb)
{
    const wchar_t *dot = wcsrchr(PathFindFileNameW(path), L'.');
    if (!dot || !dot[1]) return false;
    DWORD cch = 0;
    return AssocQueryStringW(ASSOCF_NONE, ASSOCSTR_COMMAND, dot, verb, NULL, &cch) == S_OK;
}

/* ------------------------------------------------------------------ 图标 */
/* HICON → 16×16 HBITMAP，背景填菜单底色（不填的话透明处是黑的） */
static HBITMAP sm_icon_bmp(HICON icon, int size)
{
    if (!icon || size <= 0) return NULL;
    HDC hdc = GetDC(NULL);
    if (!hdc) return NULL;
    HDC mem = CreateCompatibleDC(hdc);
    HBITMAP bmp = CreateCompatibleBitmap(hdc, size, size);
    if (mem && bmp) {
        HGDIOBJ old = SelectObject(mem, bmp);
        RECT r = { 0, 0, size, size };
        FillRect(mem, &r, GetSysColorBrush(COLOR_MENU));
        DrawIconEx(mem, 0, 0, icon, size, size, 0, NULL, DI_NORMAL);
        SelectObject(mem, old);
    }
    if (mem) DeleteDC(mem);
    ReleaseDC(NULL, hdc);
    return bmp;
}

static HBITMAP sm_bmp_from_stock(SHSTOCKICONID id, int size)
{
    SHSTOCKICONINFO si;
    ZeroMemory(&si, sizeof(si));
    si.cbSize = sizeof(si);
    if (FAILED(SHGetStockIconInfo(id, SHGSI_ICON | SHGSI_SMALLICON, &si))
            || !si.hIcon)
        return NULL;
    HBITMAP bmp = sm_icon_bmp(si.hIcon, size);
    DestroyIcon(si.hIcon);
    return bmp;
}

static HBITMAP sm_bmp_from_path(const wchar_t *path, DWORD attrs, int size)
{
    SHFILEINFOW sfi;
    ZeroMemory(&sfi, sizeof(sfi));
    if (!path || !path[0]) return NULL;
    if (!SHGetFileInfoW(path, attrs, &sfi, sizeof(sfi), SHGFI_ICON | SHGFI_SMALLICON)
            || !sfi.hIcon)
        return NULL;
    HBITMAP bmp = sm_icon_bmp(sfi.hIcon, size);
    DestroyIcon(sfi.hIcon);
    return bmp;
}

static void sm_add_bmp(SmCtx *c, HMENU m, int index, HBITMAP bmp)
{
    if (!bmp) return;
    if (c->nbmps >= SM_ICON_MAX) { DeleteObject(bmp); return; }
    MENUITEMINFOW mii;
    ZeroMemory(&mii, sizeof(mii));
    mii.cbSize = sizeof(mii);
    mii.fMask = MIIM_BITMAP;
    mii.hbmpItem = bmp;
    if (SetMenuItemInfoW(m, (UINT)index, TRUE, &mii))
        c->bmps[c->nbmps++] = bmp;
    else
        DeleteObject(bmp);
}

/* 按"菜单命令的 verb"认语义，补对应系统图标。
 * 只补语义明确的项（半张错的图标比没有更难看）；资源管理器里
 * "重命名/属性"本来就没有图标，"剪切/复制"没有可靠的系统图标来源，因此留空。 */
static void sm_apply_icons(SmCtx *c, HMENU m)
{
    int size = GetSystemMetrics(SM_CXSMICON);
    if (size <= 0) size = 16;

    const wchar_t *sample = (c->selCount > 0 && c->selPaths[0]) ? c->selPaths[0] : c->dir;
    DWORD sampleAttr = (c->selCount > 0)
        ? (fs_is_dir(sample) ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL)
        : FILE_ATTRIBUTE_DIRECTORY;

    int total = GetMenuItemCount(m);
    for (int i = 0; i < total; ++i) {
        MENUITEMINFOW mii;
        ZeroMemory(&mii, sizeof(mii));
        mii.cbSize = sizeof(mii);
        mii.fMask = MIIM_ID | MIIM_BITMAP | MIIM_FTYPE;
        if (!GetMenuItemInfoW(m, (UINT)i, TRUE, &mii)) continue;
        if (mii.hbmpItem) continue;                  /* 扩展自己给了图标，别覆盖 */
        if (mii.fType & MFT_SEPARATOR) continue;

        UINT id = mii.wID;
        HBITMAP bmp = NULL;

        if (id >= SM_CMD_BASE && id < SM_CMD_BASE + 0x100) {
            switch (id) {
            case SM_CMD_OPEN:
            case SM_CMD_EDIT:
                bmp = sm_bmp_from_path(sample, sampleAttr, size);
                break;
            case SM_CMD_PRINT:
                bmp = sm_bmp_from_stock(SIID_PRINTER, size);
                break;
            case SM_CMD_PASTE:
            case SM_CMD_PASTELINK:
                bmp = sm_bmp_from_stock(SIID_FOLDEROPEN, size);
                break;
            default:
                break;
            }
        } else if (id >= SM_ID_FIRST && id <= SM_ID_LAST) {
            wchar_t verb[64] = L"";
            if (SUCCEEDED(c->pcm->lpVtbl->GetCommandString(c->pcm,
                        id - SM_ID_FIRST, GCS_VERBW, NULL, (LPSTR)verb, 64))
                    && verb[0]) {
                if (!_wcsicmp(verb, L"open") || !_wcsicmp(verb, L"openas")
                        || !_wcsicmp(verb, L"openwith") || !_wcsicmp(verb, L"edit"))
                    bmp = sm_bmp_from_path(sample, sampleAttr, size);
                else if (!_wcsicmp(verb, L"print"))
                    bmp = sm_bmp_from_stock(SIID_PRINTER, size);
                else if (!_wcsicmp(verb, L"delete"))
                    bmp = sm_bmp_from_stock(SIID_RECYCLER, size);
                else if (!_wcsicmp(verb, L"link"))
                    bmp = sm_bmp_from_stock(SIID_LINK, size);
                else if (!_wcsicmp(verb, L"new") || !_wcsicmp(verb, L"newfolder")
                        || !_wcsicmp(verb, L"paste") || !_wcsicmp(verb, L"pasteaslink"))
                    bmp = sm_bmp_from_stock(SIID_FOLDEROPEN, size);
            }
        }
        if (bmp) sm_add_bmp(c, m, i, bmp);
    }
}

/* 用本程序的「打开方式」顶替 shell 那个：位置和文字都一样，但里面能列出
 * 没在注册表里注册过的绿色版程序 —— 资源管理器那份列不出来，而这是本程序
 * 的看家功能，不能因为"右键换成系统菜单"就丢掉。 */
/* ---- 「选择其他应用」由谁执行 ----
 * 0 = 完全交给系统（当前设置）
 * 1 = 接管：把它那一项的命令 id 改成 CMD_OPEN_WITH，点击弹本程序的 FFOpenWithDlg
 *
 * 注意 0 的后果：系统的 SHOpenWithDialog 在 Win10 1809+ 被微软降级成"去设置里改"，
 * 本机（Win10 19045）实测点下去 2.5 秒内没有任何窗口出现 —— 也就是说「选择其他应用」
 * 这条路等于是断的。若哪天要恢复，把这里改成 1 即可，代码都还在。 */
#define SM_TAKE_OVER_OPENWITH_PICK 0

#if SM_TAKE_OVER_OPENWITH_PICK
/* 系统的「打开方式」子菜单完全保持原样，只接管「选择其他应用」。
 * ★只改 id，不删项、不插项、不动文本和图标：
 *   早先试过 DeleteMenu + InsertMenuW，结果 shell 在下一轮 WM_INITMENUPOPUP 又把
 *   自己那项重建出来，菜单里同时出现两条「选择其他应用」。改 id 就没这个副作用，
 *   而且天然幂等（第二次进来发现 id 已经是我们的，直接返回）。 */
static void sm_patch_openwith(HMENU sub)
{
    if (!sub) return;
    int total = GetMenuItemCount(sub);
    if (total <= 0) return;

    for (int i = 0; i < total; ++i)
        if ((UINT)GetMenuItemID(sub, (int)i) == (UINT)CMD_OPEN_WITH)
            return;                        /* 已经接管过，别重复动 */

    for (int i = 0; i < total; ++i) {
        wchar_t t[192];
        t[0] = 0;
        if (!GetMenuStringW(sub, (UINT)i, t, 192, MF_BYPOSITION)) continue;
        if (!t[0] || !wcsstr(t, L"选择其他应用")) continue;

        MENUITEMINFOW mi;
        ZeroMemory(&mi, sizeof(mi));
        mi.cbSize = sizeof(mi);
        mi.fMask = MIIM_ID;
        mi.wID = (UINT)CMD_OPEN_WITH;
        BOOL ok = SetMenuItemInfoW(sub, (UINT)i, TRUE, &mi);
        DBG(L"SM: 接管「选择其他应用」idx=%d -> %d", i, ok ? 1 : 0);
        (void)ok;                      /* 非 FFDBG 编译时 DBG 展开为空 */
        return;
    }
}
#endif /* SM_TAKE_OVER_OPENWITH_PICK */

/* ------------------------------------------------------- DFM 宿主回调 */
static HRESULT CALLBACK sm_dfm_cb(IShellFolder *psf, HWND hwnd, IDataObject *pdtobj,
                                 UINT uMsg, WPARAM wp, LPARAM lp)
{
    SmCtx *c = s_cbCtx;
    DBG(L"SM_cb uMsg=%u wp=%p lp=%p ctx=%p bg=%d sel=%d",
        uMsg, (void *)wp, (void *)lp, (void *)c,
        c ? (c->isBackground ? 1 : 0) : -1, c ? c->selCount : -1);

    switch (uMsg) {
    case DFM_MERGECONTEXTMENU_TOP:
    case DFM_MERGECONTEXTMENU: {
        /* 资源管理器把"打开/打印/编辑"放在菜单最上面，shell 自己不加 */
        if (!c || c->selCount <= 0) return S_OK;
        HMENU m = (HMENU)wp;
        UINT pos = (uMsg == DFM_MERGECONTEXTMENU) ? (UINT)lp : 0;

        bool one = (c->selCount == 1);
        bool isFile = one && !fs_is_dir(c->selPaths[0]);
        InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_OPEN, L"打开(&O)");
        if (isFile && sm_has_verb(c->selPaths[0], L"print"))
            InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_PRINT, L"打印(&P)");
        if (isFile && sm_has_verb(c->selPaths[0], L"edit"))
            InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_EDIT, L"编辑(&E)");
        InsertMenuW(m, pos++, MF_BYPOSITION | MF_SEPARATOR, 0, NULL);
        return S_OK;
    }

    case DFM_INVOKECOMMAND:
    case DFM_INVOKECOMMANDEX: {
        UINT id = (UINT)wp;
        /* 先认 DFM_CMD_*（它们是 (UINT)-N，HIWORD 非 0，不能先按字符串判断） */
        if (id == (UINT)DFM_CMD_RENAME) {
            if (ff_shell_menu_invoke(id)) return S_OK;
        }
        if (id >= SM_CMD_BASE && id < SM_CMD_BASE + 0x100) {
            if (ff_shell_menu_invoke(id)) return S_OK;
        }
        /* 其余交给 shell 原生执行（剪切/复制/删除/粘贴/新建/属性 都是原生行为）。
         * ★必须返回 S_FALSE 而不是 E_NOTIMPL —— E_NOTIMPL 会被当成"宿主拒绝执行"，
         *   于是"属性"这类命令点了毫无反应（探针 D 段抓到过）。 */
        return S_FALSE;
    }

    case DFM_VALIDATECMD: {
        UINT id = (UINT)wp;
        if (id == (UINT)DFM_CMD_RENAME)
            return (c && c->selCount == 1) ? S_OK : S_FALSE;
        return S_FALSE;
    }

    default:
        return E_NOTIMPL;
    }
}

/* 选中项菜单：换成我们自己的「打开方式」，并把特色项插在「属性」之前。
 * ★这些插入都必须在 QueryContextMenu 【返回之后】做 —— 回调里（BOTTOM）
 * 做的时候 shell 还没把它自己的项填进菜单，插进去的东西会位置错乱甚至丢失。 */
static void sm_insert_selected_bottom(SmCtx *c, HMENU m)
{
    if (!c) return;
    /* 方案B：系统的「打开方式」项原样留着，等它的子菜单展开时再补（sm_patch_openwith） */

    int total = GetMenuItemCount(m);
    UINT pos = (total > 0) ? (UINT)total : 0;
    for (int i = 0; i < total; ++i) {   /* 尽量插在「属性」前面 */
        wchar_t text[160] = L"";
        GetMenuStringW(m, (UINT)i, text, 160, MF_BYPOSITION);
        if (text[0] && wcsstr(text, L"属性")) { pos = (UINT)i; break; }
    }
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_SEPARATOR, 0, NULL);
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_DELETE_HARD,
                L"永久删除\tShift+Delete");
    if (c->selCount == 1)
        InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_ADS,
                    L"备用数据流(&A)");
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_ATTR,
                L"批量设置属性(&B)");
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_COPY_PATH,
                L"复制完整路径(&Y)");
}

/* 空白处菜单：把资源管理器有、而"视图对象"菜单不给的项补到最上面。
 * 顺序照资源管理器：刷新 / 自定义文件夹 / ─ / 粘贴 / 粘贴快捷方式 / 撤消。 */
static void sm_insert_background_top(SmCtx *c, HMENU m)
{
    (void)c;
    UINT pos = 0;
    bool hasFiles = ff_shell_menu_clipboard_has_files();

    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_REFRESH, L"刷新(&E)\tF5");
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_CUSTOMIZE,
                L"自定义文件夹(&F)…");
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_SEPARATOR, 0, NULL);
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING | (hasFiles ? 0 : MF_GRAYED),
                SM_CMD_PASTE, L"粘贴(&P)\tCtrl+V");
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING | (hasFiles ? 0 : MF_GRAYED),
                SM_CMD_PASTELINK, L"粘贴快捷方式(&S)");
    if (ff_shell_menu_can_undo_rename())
        InsertMenuW(m, pos++, MF_BYPOSITION | MF_STRING, SM_CMD_UNDORENAME,
                    L"撤消 重命名(&U)\tCtrl+Z");
    InsertMenuW(m, pos++, MF_BYPOSITION | MF_SEPARATOR, 0, NULL);
}

/* 建立 IContextMenu（CDefFolderMenu_Create2 + 宿主回调） */
static bool sm_open(SmCtx *c, HWND owner, const wchar_t *dir,
                    const wchar_t **paths, int count)
{
    sm_zero(c);
    c->isBackground = (count <= 0);
    if (dir) ff_str_copy(c->dir, FF_PATH_MAX, dir);

    /* 选中项路径另存一份：DFM 回调里要用 */
    if (count > 0) {
        c->selPaths = (wchar_t **)calloc((size_t)count, sizeof(wchar_t *));
        if (!c->selPaths) return false;
        c->selCount = count;
        for (int i = 0; i < count; ++i)
            c->selPaths[i] = paths[i] ? _wcsdup(paths[i]) : NULL;
    }

    if (count <= 0) {
        /* --- 空白处：走"视图对象"的上下文菜单 ---
         * ★实测：CDefFolderMenu_Create2(cidl=0) 在本机上给 0 项（建不出背景菜单），
         * 所以空白处仍用 CreateViewObject，缺的那几项（刷新/粘贴/…）在 sm_build
         * 里手工补到菜单顶部（见 sm_insert_background_top）。 */
        if (!dir || !dir[0]) { DBG(L"SM: 空白处但 dir 为空"); return false; }
        if (SHParseDisplayName(dir, NULL, &c->pidlFolder, 0, NULL) != S_OK
                || !c->pidlFolder)
            return false;
        if (FAILED(SHBindToObject(NULL, (PCUIDLIST_RELATIVE)c->pidlFolder, NULL,
                                  &IID_IShellFolder, (void **)&c->psf)))
            return false;
        if (FAILED(c->psf->lpVtbl->CreateViewObject(c->psf, owner,
                                                    &IID_IContextMenu,
                                                    (void **)&c->pcm)))
            return false;
        return true;
    }

    /* --- 选中项 --- */
    c->fulls = (LPITEMIDLIST *)calloc((size_t)count, sizeof(LPITEMIDLIST));
    c->children = (LPITEMIDLIST *)calloc((size_t)count, sizeof(LPITEMIDLIST));
    if (!c->fulls || !c->children) { sm_close(c); return false; }

    wchar_t firstParent[FF_PATH_MAX];
    firstParent[0] = 0;
    for (int i = 0; i < count; ++i) {
        if (!paths[i] || !paths[i][0]) continue;
        LPITEMIDLIST pidl = NULL;
        if (SHParseDisplayName(paths[i], NULL, &pidl, 0, NULL) != S_OK || !pidl)
            continue;
        wchar_t parent[FF_PATH_MAX];
        sm_parent_of(paths[i], parent, FF_PATH_MAX);
        if (c->nfull == 0) {
            ff_str_copy(firstParent, FF_PATH_MAX, parent);
        } else if (_wcsicmp(parent, firstParent) != 0) {
            CoTaskMemFree(pidl);          /* 跨目录：本次只处理第一项 */
            continue;
        }
        c->fulls[c->nfull++] = pidl;
    }
    if (c->nfull == 0) { sm_close(c); return false; }

    PCUITEMID_CHILD ch0 = NULL;
    if (SHBindToParent(c->fulls[0], &IID_IShellFolder,
                       (void **)&c->psf, &ch0) != S_OK || !c->psf) {
        sm_close(c);
        return false;
    }
    c->children[0] = (LPITEMIDLIST)ch0;
    for (int i = 1; i < c->nfull; ++i) {
        IShellFolder *tmp = NULL;
        PCUITEMID_CHILD ch = NULL;
        if (SHBindToParent(c->fulls[i], &IID_IShellFolder,
                           (void **)&tmp, &ch) == S_OK && tmp) {
            c->children[i] = (LPITEMIDLIST)ch;   /* 指进 fulls[i]，不单独释放 */
            tmp->lpVtbl->Release(tmp);
        }
    }

    LPITEMIDLIST pidlParent = NULL;
    if (SHParseDisplayName(firstParent, NULL, &pidlParent, 0, NULL) != S_OK
            || !pidlParent) {
        sm_close(c);
        return false;
    }
    HRESULT hr = CDefFolderMenu_Create2(pidlParent, owner, (UINT)c->nfull,
                                        (PCUITEMID_CHILD_ARRAY)c->children,
                                        c->psf, sm_dfm_cb, 0, NULL, &c->pcm);
    CoTaskMemFree(pidlParent);
    if (FAILED(hr) || !c->pcm) {
        DBG(L"SM: CDefFolderMenu_Create2 失败 n=%d", c->nfull);
        sm_close(c);
        return false;
    }
    return true;
}

/* 建菜单并填 QueryContextMenu（回调会在这一步插项） */
static HMENU sm_build(SmCtx *c, int *countOut)
{
    HMENU m = CreatePopupMenu();
    if (!m) return NULL;

    UINT flags = CMF_EXPLORE | CMF_CANRENAME;   /* 有宿主回调了，重命名可以安全打开 */
    if (GetKeyState(VK_SHIFT) < 0) flags |= CMF_EXTENDEDVERBS;

    s_cbCtx = c;
    c->pcm->lpVtbl->QueryContextMenu(c->pcm, m, 0, SM_ID_FIRST, SM_ID_LAST, flags);
    s_cbCtx = NULL;

    /* ★我们的项都在这里插（QueryContextMenu 之后，菜单已完整） */
    if (c->isBackground) {
        sm_insert_background_top(c, m);   /* 刷新/自定义文件夹/粘贴/粘贴快捷方式 */
        ff_menu_append_extras(m, true);   /* 查看/排序/全选/反选 */
    } else {
        sm_insert_selected_bottom(c, m);  /* 打开方式替换 + 永久删除/ADS/属性/复制路径 */
    }

    int total = GetMenuItemCount(m);
    if (total <= 0) { DestroyMenu(m); return NULL; }

    sm_apply_icons(c, m);

    s_menuCtx = c;                 /* 子菜单展开时要用它枚举候选 */
    if (countOut) *countOut = total;
    return m;
}

/* 把菜单期间的扩展消息转给它。返回 true 表示已经处理，调用方直接 return。 */
bool ff_shell_menu_msg(UINT msg, WPARAM wp, LPARAM lp, LRESULT *out)
{
    if (!s_icm2 && !s_icm3) return false;

    if (msg == WM_INITMENUPOPUP || msg == WM_DRAWITEM || msg == WM_MEASUREITEM) {
        if (s_icm2) s_icm2->lpVtbl->HandleMenuMsg(s_icm2, msg, wp, lp);
        else if (s_icm3) {
            IContextMenu2 *i2 = NULL;
            if (SUCCEEDED(s_icm3->lpVtbl->QueryInterface(s_icm3, &IID_IContextMenu2,
                                                         (void **)&i2)) && i2) {
                i2->lpVtbl->HandleMenuMsg(i2, msg, wp, lp);
                i2->lpVtbl->Release(i2);
            }
        }
        /* 子菜单由 shell 自己填，我们不动它（「选择其他应用」也交给系统）。
         * 需要接管时把文件上方的 SM_TAKE_OVER_OPENWITH_PICK 改成 1。 */
#if SM_TAKE_OVER_OPENWITH_PICK
        if (msg == WM_INITMENUPOPUP) sm_patch_openwith((HMENU)wp);
#endif
        return true;
    }
    if (msg == WM_MENUCHAR) {
        if (s_icm3) {
            LRESULT r = 0;
            if (FAILED(s_icm3->lpVtbl->HandleMenuMsg2(s_icm3, msg, wp, lp, &r)))
                return false;                       /* 让菜单自己走默认处理 */
            if (out) *out = r;
            return true;
        }
        if (s_icm2) {
            s_icm2->lpVtbl->HandleMenuMsg(s_icm2, msg, wp, lp);
            if (out) *out = 0;
            return true;
        }
    }
    return false;
}

/* 弹出系统右键菜单。返回 true = 用户确实执行了某个命令 */
bool ff_shell_menu_show(HWND owner, const wchar_t *dir,
                        const wchar_t **paths, int count, POINT ptScreen)
{
    SmCtx c;
    bool invoked = false;

    DBG(L"SM: show count=%d dir=%ls", count, dir ? dir : L"(null)");
    if (!sm_open(&c, owner, dir, paths, count)) { DBG(L"SM: sm_open 失败"); return false; }

    int total = 0;
    HMENU m = sm_build(&c, &total);
    DBG(L"SM: build m=%p items=%d", (void *)m, total);
    if (!m) { sm_close(&c); return false; }

    s_icm2 = NULL;
    s_icm3 = NULL;
    if (FAILED(c.pcm->lpVtbl->QueryInterface(c.pcm, &IID_IContextMenu3,
                                             (void **)&s_icm3)) || !s_icm3)
        s_icm3 = NULL;
    if (FAILED(c.pcm->lpVtbl->QueryInterface(c.pcm, &IID_IContextMenu2,
                                             (void **)&s_icm2)) || !s_icm2)
        s_icm2 = NULL;

    SetForegroundWindow(owner);
    int cmd = (int)TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON | TPM_LEFTALIGN,
                                  ptScreen.x, ptScreen.y, 0, owner, NULL);
    PostMessageW(owner, WM_NULL, 0, 0);   /* 让菜单一定收掉 */
    DBG(L"SM: track cmd=%d", cmd);

    sm_release_handlers();
    s_menuCtx = NULL;

    if (cmd >= SM_CMD_BASE && cmd < SM_CMD_BASE + 0x100) {
        invoked = ff_shell_menu_invoke((UINT)cmd);       /* 本程序自己插的项 */
    } else if (cmd >= SM_ID_FIRST && cmd <= SM_ID_LAST) {
        int offset = cmd - SM_ID_FIRST;                  /* shell 的项 */
        CMINVOKECOMMANDINFOEX ci;
        ZeroMemory(&ci, sizeof(ci));
        ci.cbSize = sizeof(ci);
        ci.fMask = CMIC_MASK_UNICODE | CMIC_MASK_ASYNCOK | CMIC_MASK_PTINVOKE;
        ci.hwnd = owner;
        ci.lpVerb  = MAKEINTRESOURCEA((WORD)offset);
        ci.lpVerbW = MAKEINTRESOURCEW((WORD)offset);
        ci.lpDirectoryW = dir;
        ci.nShow = SW_SHOWNORMAL;
        ci.ptInvoke = ptScreen;
        s_cbCtx = &c;                     /* DFM_INVOKECOMMAND 里要用上下文 */
        if (SUCCEEDED(c.pcm->lpVtbl->InvokeCommand(c.pcm,
                                                   (CMINVOKECOMMANDINFO *)&ci)))
            invoked = true;
        s_cbCtx = NULL;
    } else if (cmd > 0) {
        /* ★本程序自己的普通命令（CMD_*）也要接住 ——
         * 它们既不在 SM_CMD_* 段、也不在 shell 的 0x7000 段：
         *   「打开方式」子菜单里的程序项（CMD_OPEN_WITH_APP+i）、
         *   「选择其他应用…」、查看 / 排序 / 全选 / 反选 全都在这里。
         * 漏掉这条分支的现象就是"菜单项点下去毫无反应"（用户实测报过）。 */
        invoked = ff_shell_menu_invoke((UINT)cmd);
    }

    DestroyMenu(m);
    sm_close(&c);       /* IContextMenu 在这里才 Release —— 必须在 Invoke 之后 */
    ff_ow_release();    /* 「打开方式」子菜单留的 handler/位图，命令执行完才放 */
    return invoked;
}

/*
 * 自检：把系统右键菜单的项（序号 / 命令 ID / 相对序号 / 有没有图标 / 文本）
 * 写进 %TEMP%\ffce_shellmenu.txt 然后退出。给 tests/shellmenu_probe.py 断言用。
 * path 是目录 → 出空白处菜单；是文件 → 出该文件的选中菜单。
 */
void ff_shell_menu_dump(const wchar_t *path)
{
    wchar_t tmp[MAX_PATH * 2], file[MAX_PATH * 2];
    GetTempPathW(MAX_PATH * 2, tmp);
    StringCchPrintfW(file, MAX_PATH * 2, L"%sffce_shellmenu.txt", tmp);

    HANDLE hf = CreateFileW(file, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hf == INVALID_HANDLE_VALUE) return;

    wchar_t buf[1024];
    DWORD wr = 0;
    int total = 0;
    bool isDir = (GetFileAttributesW(path) & FILE_ATTRIBUTE_DIRECTORY) != 0;

    SmCtx c;
    const wchar_t *paths[1];
    paths[0] = path;
    if (!sm_open(&c, NULL, path, isDir ? NULL : paths, isDir ? 0 : 1)) {
        StringCchPrintfW(buf, 1024, L"error=open failed (isdir=%d)\n", isDir ? 1 : 0);
        WriteFile(hf, buf, (DWORD)(wcslen(buf) * sizeof(wchar_t)), &wr, NULL);
        CloseHandle(hf);
        return;
    }
    HMENU m = sm_build(&c, &total);
    StringCchPrintfW(buf, 1024, L"isdir=%d\r\nitems=%d\r\nidcmd_first=%d\r\n",
                     isDir ? 1 : 0, total, SM_ID_FIRST);
    WriteFile(hf, buf, (DWORD)(wcslen(buf) * sizeof(wchar_t)), &wr, NULL);

    if (m) {
        for (int i = 0; i < total; ++i) {
            wchar_t text[256] = L"";
            GetMenuStringW(m, i, text, 256, MF_BYPOSITION);
            MENUITEMINFOW mii;
            ZeroMemory(&mii, sizeof(mii));
            mii.cbSize = sizeof(mii);
            mii.fMask = MIIM_ID | MIIM_BITMAP | MIIM_FTYPE | MIIM_SUBMENU;
            GetMenuItemInfoW(m, (UINT)i, TRUE, &mii);
            int off = ((int)mii.wID >= SM_ID_FIRST && (int)mii.wID <= SM_ID_LAST)
                          ? (int)mii.wID - SM_ID_FIRST : -1;
            StringCchPrintfW(buf, 1024, L"[%d] id=%u off=%d icon=%d sub=%d text=%s\r\n",
                             i, (unsigned)mii.wID, off, mii.hbmpItem ? 1 : 0,
                             mii.hSubMenu ? 1 : 0, text[0] ? text : L"(sep)");
            WriteFile(hf, buf, (DWORD)(wcslen(buf) * sizeof(wchar_t)), &wr, NULL);

            /* 子菜单内容也列出来：用来验「打开方式」到底是我们那份还是 shell 的 */
            if (mii.hSubMenu) {
                int sn = GetMenuItemCount(mii.hSubMenu);
                for (int k = 0; k < sn; ++k) {
                    wchar_t stext[160] = L"";
                    GetMenuStringW(mii.hSubMenu, (UINT)k, stext, 160, MF_BYPOSITION);
                    MENUITEMINFOW sm;
                    ZeroMemory(&sm, sizeof(sm));
                    sm.cbSize = sizeof(sm);
                    sm.fMask = MIIM_ID;
                    GetMenuItemInfoW(mii.hSubMenu, (UINT)k, TRUE, &sm);
                    StringCchPrintfW(buf, 1024, L"    sub[%d] id=%u text=%s\r\n",
                                     k, (unsigned)sm.wID, stext[0] ? stext : L"(sep)");
                    WriteFile(hf, buf, (DWORD)(wcslen(buf) * sizeof(wchar_t)),
                              &wr, NULL);
                }
            }
        }
        DestroyMenu(m);
    }
    sm_close(&c);
    ff_ow_release();
    CloseHandle(hf);
}
