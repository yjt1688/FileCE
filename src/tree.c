/* tree.c —— 左侧目录树：唯一根节点「此电脑」+ 驱动器 + 懒加载文件夹 */
#include "ff.h"

/* 节点 lParam 的布局在 ff.h 里公开为 FfTreeData（主窗口拖放命中测试要读它） */
typedef FfTreeData TreeData;

static bool s_syncing = false;

static TreeData *td_new(int kind, const wchar_t *path)
{
    TreeData *d = (TreeData *)calloc(1, sizeof(TreeData));
    if (!d) return NULL;
    d->kind = kind;
    ff_str_copy(d->path, FF_PATH_MAX, path);
    return d;
}

static HTREEITEM tv_insert(HWND tree, HTREEITEM parent, HTREEITEM after,
                           const wchar_t *text, int icon, TreeData *data, bool addDummy)
{
    TVINSERTSTRUCTW ins;
    ZeroMemory(&ins, sizeof(ins));
    ins.hParent = parent;
    ins.hInsertAfter = after ? after : TVI_LAST;
    ins.item.mask = TVIF_TEXT | TVIF_IMAGE | TVIF_SELECTEDIMAGE | TVIF_PARAM;
    ins.item.pszText = (LPWSTR)text;
    ins.item.iImage = icon;
    ins.item.iSelectedImage = icon;
    ins.item.lParam = (LPARAM)data;
    HTREEITEM h = (HTREEITEM)SendMessageW(tree, TVM_INSERTITEMW, 0, (LPARAM)&ins);
    if (h && addDummy) {
        TVINSERTSTRUCTW d2;
        ZeroMemory(&d2, sizeof(d2));
        d2.hParent = h;
        d2.hInsertAfter = TVI_LAST;
        d2.item.mask = TVIF_TEXT | TVIF_PARAM;
        d2.item.pszText = (LPWSTR)L"…";
        d2.item.lParam = 0;
        SendMessageW(tree, TVM_INSERTITEMW, 0, (LPARAM)&d2);
    }
    return h;
}

/* ---- 快速访问（shell 虚拟文件夹）----
 * 它没有文件系统路径，不能用 FindFirstFile 枚举，必须走 shell 命名空间：
 * SHParseDisplayName → SHBindToObject(IID_IShellFolder) → EnumObjects。
 * 每个子项再用 SHGetPathFromIDList 解析成真实路径 —— 有路径的才插进树（后续导航
 * 复用现有 ff_navigate），拿不到路径的（pin 的 UWP 应用等）直接跳过。 */
#define FF_KIND_QUICKACCESS  6
#define FF_QA_GUID           L"shell:::{679F85CB-0220-4080-B29B-5540CC05AAB6}"

static void fill_quick_access(HWND tree, HTREEITEM item)
{
    /* ILCreateFromPathW 与 SHParseDisplayName 对这条解析名实测返回**同一个 pidl**
     * （都是 22 字节），这里用前者，少一步 HRESULT 判断。 */
    PIDLIST_ABSOLUTE pidl = (PIDLIST_ABSOLUTE)ILCreateFromPathW(FF_QA_GUID);
    if (!pidl) {
        DBG(L"QA: ILCreateFromPathW 失败");
        return;
    }

    IShellFolder *psf = NULL;
    if (FAILED(SHBindToObject(NULL, pidl, NULL, &IID_IShellFolder, (void **)&psf)) || !psf) {
        DBG(L"QA: SHBindToObject 失败");
        CoTaskMemFree(pidl);
        return;
    }

    IEnumIDList *pe = NULL;
    int added = 0;
    if (SUCCEEDED(psf->lpVtbl->EnumObjects(psf, tree, SHCONTF_FOLDERS | SHCONTF_NONFOLDERS,
                                           &pe)) && pe) {
        LPITEMIDLIST child = NULL;
        while (pe->lpVtbl->Next(pe, 1, &child, NULL) == S_OK && child) {
            /* ★EnumObjects 给的是**相对** 快速访问 的子 pidl，
             *   SHGetPathFromIDListW 只认**绝对** pidl（拿它当绝对用会全部失败，
             *   表现就是"枚举到一堆项但一个都插不进去"）。
             *   直接问 psf 要 SHGDN_FORPARSING 的解析名最省事：文件系统项返回
             *   完整路径，UWP/虚拟项返回非路径字符串，后面 fs_is_dir 一筛就掉。 */
            wchar_t path[FF_PATH_MAX];
            path[0] = 0;
            STRRET srp;
            if (SUCCEEDED(psf->lpVtbl->GetDisplayNameOf(psf, child, SHGDN_FORPARSING, &srp)))
                StrRetToBufW(&srp, child, path, FF_PATH_MAX);

            if (path[0] && fs_is_dir(path)) {
                wchar_t name[260];
                name[0] = 0;
                STRRET sr;
                if (SUCCEEDED(psf->lpVtbl->GetDisplayNameOf(psf, child, SHGDN_INFOLDER, &sr)))
                    StrRetToBufW(&sr, child, name, 260);
                if (!name[0]) {
                    const wchar_t *nm = ff_path_name(path);
                    ff_str_copy(name, 260, nm ? nm : path);
                }

                int icon = -1;
                SHFILEINFOW sfi;
                ZeroMemory(&sfi, sizeof(sfi));
                if (SHGetFileInfoW(path, FILE_ATTRIBUTE_DIRECTORY, &sfi, sizeof(sfi),
                                   SHGFI_SYSICONINDEX | SHGFI_SMALLICON))
                    icon = (int)sfi.iIcon;

                TreeData *d = td_new(1, path);
                if (d) {
                    tv_insert(tree, item, TVI_LAST, name, icon, d, true);
                    ++added;
                }
            } else {
                DBG(L"QA: 跳过非文件系统项");
            }
            CoTaskMemFree(child);
            child = NULL;
        }
        pe->lpVtbl->Release(pe);
    }
    psf->lpVtbl->Release(psf);
    CoTaskMemFree(pidl);
    DBG(L"QA: 快速访问加入 %d 项", added);
    (void)added;                       /* 非 FFDBG 编译时 DBG 展开为空 */
}

static void fill_children(HWND tree, HTREEITEM item, const wchar_t *path, int kind)
{
    /* 清掉占位节点 */
    HTREEITEM c = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, (LPARAM)item);
    while (c) {
        HTREEITEM n = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, (LPARAM)c);
        SendMessageW(tree, TVM_DELETEITEM, 0, (LPARAM)c);
        c = n;
    }

    if (kind == FF_KIND_QUICKACCESS) {     /* 快速访问 → 交给 shell 枚举 */
        fill_quick_access(tree, item);
        return;
    }

    if (kind == 5) {                       /* 此电脑 → 驱动器 + 桌面/文档常用位置 */
        FfEntryList drives;
        ZeroMemory(&drives, sizeof(drives));
        fs_enum_drives(&drives);
        for (int i = 0; i < drives.count; ++i) {
            FfEntry *de = &drives.items[i];
            if (de->driveKind == DRIVE_DESKTOP_K || de->driveKind == DRIVE_DOCS_K) {
                wchar_t sp[FF_PATH_MAX];
                if (fs_special_path(de->driveKind, sp, FF_PATH_MAX))
                    tv_insert(tree, item, TVI_LAST, de->name, de->iconIndex,
                              td_new(2, sp), true);
                continue;
            }
            /* 显示名可能带卷标（如 "C: (系统)"），路径必须只用盘符构造 */
            wchar_t root[8];
            StringCchPrintfW(root, 8, L"%c:\\", de->name[0]);
            TreeData *d = td_new(1, root);
            if (!d) continue;
            tv_insert(tree, item, TVI_LAST, de->name, de->iconIndex, d, true);
        }
        fs_entry_list_free(&drives);
        return;
    }

    /* 目录 → 子目录（按名称自然排序） */
    wchar_t pat[FF_PATH_MAX];
    ff_path_join(pat, FF_PATH_MAX, path, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;

    wchar_t **names = NULL;
    int cap = 0, n = 0;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_SYSTEM) continue;
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_HIDDEN) continue;
        if (n >= cap) {
            int nc = cap ? cap * 2 : 32;
            wchar_t **nn = (wchar_t **)realloc(names, (size_t)nc * sizeof(wchar_t *));
            if (!nn) break;
            names = nn; cap = nc;
        }
        names[n] = _wcsdup(fd.cFileName);
        if (names[n]) ++n;
    } while (FindNextFileW(h, &fd));
    FindClose(h);

    /* 自然排序（插入排序，目录数量通常不大） */
    for (int i = 1; i < n; ++i) {
        wchar_t *key = names[i];
        int j = i - 1;
        while (j >= 0 && StrCmpLogicalW(names[j], key) > 0) { names[j + 1] = names[j]; --j; }
        names[j + 1] = key;
    }

    int icon = fs_get_icon_index(L"folder", FILE_ATTRIBUTE_DIRECTORY);
    for (int i = 0; i < n; ++i) {
        wchar_t full[FF_PATH_MAX];
        ff_path_join(full, FF_PATH_MAX, path, names[i]);
        TreeData *d = td_new(2, full);
        tv_insert(tree, item, TVI_LAST, names[i], icon, d, true);
        free(names[i]);
    }
    free(names);
}

/* 查找某个路径的现有节点(已展开时才存在) */
static HTREEITEM find_child_by_path(HWND tree, HTREEITEM parent, const wchar_t *path)
{
    HTREEITEM c = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, (LPARAM)parent);
    while (c) {
        TVITEMW ti;
        ZeroMemory(&ti, sizeof(ti));
        ti.mask = TVIF_PARAM | TVIF_HANDLE;
        ti.hItem = c;
        SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti);
        TreeData *d = (TreeData *)ti.lParam;
        if (d && _wcsicmp(d->path, path) == 0) return c;
        c = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, (LPARAM)c);
    }
    return NULL;
}

/* 刷新"当前目录"节点下的子目录（删除/新建子目录后让树跟着变）。
 * ★为什么不整棵树重建：树是惰性展开的，重建会把用户已展开的其他分支全收起来，
 *   解压/删除时反复触发会很难用。这里只重建当前节点下一层，
 *   代价小、也不动别的分支。当前节点没展开过（树里本就没有子节点）就直接跳过。 */
void ff_tree_refresh_current(HWND tree)
{
    if (!tree) return;
    HTREEITEM it = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CARET, 0);
    HTREEITEM ch = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, (LPARAM)it);
    DBG(L"tree_refresh_current: caret=%p child=%p", (void *)it, (void *)ch);
    if (!it) return;
    if (!ch) return;                              /* 没展开过：树里没有子节点 */

    TVITEMW ti;
    ZeroMemory(&ti, sizeof(ti));
    ti.mask = TVIF_PARAM | TVIF_HANDLE;
    ti.hItem = it;
    SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti);
    TreeData *d = (TreeData *)ti.lParam;
    if (!d || !d->path[0]) return;

    /* fill_children 自己会先清空现有子节点再重新枚举（kind=1 表示普通目录） */
    fill_children(tree, it, d->path, 1);
    DBG(L"tree_refresh_current: [%ls]", d->path);
}

/* 找「此电脑」根节点。
 * ★树根现在有两个（快速访问 + 此电脑），凡是"在根下找盘符/逐级下潜"的逻辑
 *   都必须先定位到这个节点 —— 直接拿 TVGN_ROOT 会得到「快速访问」，
 *   它下面没有盘符，于是展开和定位统统失败（表现：刷新后树全收起来了）。 */
static HTREEITEM tree_pc_root(HWND tree)
{
    HTREEITEM h = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0);
    while (h) {
        TVITEMW ti;
        ZeroMemory(&ti, sizeof(ti));
        ti.mask = TVIF_PARAM | TVIF_HANDLE;
        ti.hItem = h;
        if (SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti)) {
            TreeData *d = (TreeData *)ti.lParam;
            if (d && d->kind == 5) return h;
        }
        h = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, (LPARAM)h);
    }
    return (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0);   /* 兜底 */
}

/* 树的水平滚动位置归零。
 * TVM_ENSUREVISIBLE 为了让整个节点（含深层缩进）完整露出来，会**同时**做水平和
 * 垂直滚动 —— 目录层级一深，水平位置就跑到右边，左边一截被推出视野，看起来像
 * "树被裁掉了一半"（Downloads 显示成 ownloads）。垂直该滚就滚，水平一律回最左，
 * 用户真想横向看再自己拖。 */
static void tree_keep_left(HWND tree)
{
    if (tree) SendMessageW(tree, WM_HSCROLL, MAKEWPARAM(SB_LEFT, 0), 0);
}

void ff_tree_select_path(HWND tree, const wchar_t *path)
{
    if (!tree) return;
    DBG(L"select_path: [%ls]", path ? path : L"(null)");

    /* 空路径 = 此电脑视图（树里唯一根节点） */
    if (!path || !*path) {
        HTREEITEM root = tree_pc_root(tree);
        if (root) {
            s_syncing = true;
            SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, (LPARAM)root);
            s_syncing = false;
        }
        return;
    }

    HTREEITEM root = tree_pc_root(tree);
    if (!root) return;

    s_syncing = true;
    SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)root);

    wchar_t cur[FF_PATH_MAX];
    ff_str_copy(cur, FF_PATH_MAX, path);
    ff_path_normalize(cur);
    /* 8.3 短路径（ADMINI~1）逐段下潜必 MISS —— 树节点存的是磁盘长名。
     * 先展开成长路径再找；失败（网络路径/不存在）就保留原样。 */
    {
        wchar_t longp[FF_PATH_MAX];
        DWORD n = GetLongPathNameW(cur, longp, FF_PATH_MAX);
        if (n > 0 && n < FF_PATH_MAX) ff_str_copy(cur, FF_PATH_MAX, longp);
    }

    wchar_t rootDrive[8];
    StringCchPrintfW(rootDrive, 8, L"%c:\\", cur[0]);

    HTREEITEM node = find_child_by_path(tree, root, rootDrive);
    DBG(L"select_path: drive [%ls] -> %ls", rootDrive, node ? L"found" : L"MISS");
    if (!node) {
        s_syncing = false;
        return;
    }
    SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)node);

    /* 逐级向下展开 */
    wchar_t acc[FF_PATH_MAX];
    ff_str_copy(acc, FF_PATH_MAX, rootDrive);
    const wchar_t *p = cur + 3;
    while (*p) {
        wchar_t seg[512];
        int i = 0;
        while (*p && *p != L'\\' && i < 511) seg[i++] = *p++;
        seg[i] = 0;
        if (*p == L'\\') ++p;
        if (!seg[0]) break;
        ff_path_join(acc, FF_PATH_MAX, acc, seg);
        HTREEITEM nx = find_child_by_path(tree, node, acc);
        DBG(L"select_path: [%ls] -> %ls", acc, nx ? L"found" : L"MISS");
        if (!nx) break;
        SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)nx);
        node = nx;
    }

    SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, (LPARAM)node);
    SendMessageW(tree, TVM_ENSUREVISIBLE, 0, (LPARAM)node);
    tree_keep_left(tree);          /* ENSUREVISIBLE 会横向滚，这里拉回最左 */
    s_syncing = false;
}

/* 收集已展开节点的路径（递归；占位节点 lParam=0 会被跳过） */
static void collect_expanded(HWND tree, HTREEITEM h, wchar_t ***vec, int *n, int *cap)
{
    while (h) {
        TVITEMW ti;
        ZeroMemory(&ti, sizeof(ti));
        ti.mask = TVIF_PARAM | TVIF_STATE | TVIF_HANDLE;
        ti.hItem = h;
        ti.stateMask = TVIS_EXPANDED;
        if (SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti)
                && (ti.state & TVIS_EXPANDED)) {
            TreeData *d = (TreeData *)ti.lParam;
            if (d && d->path[0]) {                    /* 虚拟节点（快速访问）跳过 */
                if (*n == *cap) {
                    int nc = (*cap) ? (*cap) * 2 : 8;
                    wchar_t **nv = (wchar_t **)realloc(*vec, (size_t)nc * sizeof(wchar_t *));
                    if (!nv) return;
                    *vec = nv;
                    *cap = nc;
                }
                wchar_t *copy = _wcsdup(d->path);
                if (copy) (*vec)[(*n)++] = copy;
            }
        }
        HTREEITEM c = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, (LPARAM)h);
        if (c) collect_expanded(tree, c, vec, n, cap);
        h = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_NEXT, (LPARAM)h);
    }
}

void ff_tree_populate(HWND tree)
{
    if (!tree) return;
    /* 重建期间必须由我们"接管"选中通知：
     * 删掉当前选中项之后，TreeView 会自己另挑一个节点选中；插入首个根节点时
     * 同样会被自动选中。这些都是系统行为而不是用户点击，如果不挡住，
     * TVN_SELCHANGED 会把当前标签导航到那个被自动选中的节点上 ——
     * 表现就是"按一下 F5，当前目录莫名跳到别处"。 */
    s_syncing = true;

    /* 重建前先把"当前展开着的节点路径"记下来，重建后原样展开回去 ——
     * 否则每次自动刷新（目录监听）都会把用户展开的树全部收起来。 */
    wchar_t **expanded = NULL;
    int nExp = 0, capExp = 0;
    collect_expanded(tree, (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_ROOT, 0),
                     &expanded, &nExp, &capExp);

    SendMessageW(tree, TVM_DELETEITEM, 0, (LPARAM)TVI_ROOT);

    /* 「快速访问」根节点（Windows 资源管理器同款），放在「此电脑」之前。
     * 子节点由 shell 命名空间枚举（见 fill_quick_access）。 */
    {
        TVINSERTSTRUCTW qa;
        ZeroMemory(&qa, sizeof(qa));
        qa.hParent = TVI_ROOT;
        qa.hInsertAfter = TVI_FIRST;
        qa.item.mask = TVIF_TEXT | TVIF_IMAGE | TVIF_SELECTEDIMAGE | TVIF_PARAM;
        qa.item.pszText = (LPWSTR)L"快速访问";
        qa.item.iImage = fs_icon_quick_access();
        qa.item.iSelectedImage = qa.item.iImage;
        qa.item.lParam = (LPARAM)td_new(FF_KIND_QUICKACCESS, L"");
        HTREEITEM hqa = (HTREEITEM)SendMessageW(tree, TVM_INSERTITEMW, 0, (LPARAM)&qa);
        if (hqa) {
            TVINSERTSTRUCTW dp;
            ZeroMemory(&dp, sizeof(dp));
            dp.hParent = hqa;
            dp.hInsertAfter = TVI_LAST;
            dp.item.mask = TVIF_TEXT | TVIF_PARAM;
            dp.item.pszText = (LPWSTR)L"…";
            dp.item.lParam = 0;
            SendMessageW(tree, TVM_INSERTITEMW, 0, (LPARAM)&dp);
            SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)hqa);
        }
    }

    /* 唯一的文件系统根节点：「此电脑」。默认展开，子节点 = 驱动器 + 桌面/文档。
     * 顶层不再放计算机 / 桌面 / 文档 / 控制面板 / 网络这些并列节点。 */
    {
        TVINSERTSTRUCTW pc;
        ZeroMemory(&pc, sizeof(pc));
        pc.hParent = TVI_ROOT;
        pc.hInsertAfter = TVI_LAST;
        pc.item.mask = TVIF_TEXT | TVIF_IMAGE | TVIF_SELECTEDIMAGE | TVIF_PARAM;
        pc.item.pszText = (LPWSTR)L"此电脑";
        pc.item.iImage = fs_icon_this_pc();
        pc.item.iSelectedImage = pc.item.iImage;
        pc.item.lParam = (LPARAM)td_new(5, L"");
        HTREEITEM h = (HTREEITEM)SendMessageW(tree, TVM_INSERTITEMW, 0, (LPARAM)&pc);
        if (h) {
            TVINSERTSTRUCTW dp;
            ZeroMemory(&dp, sizeof(dp));
            dp.hParent = h;
            dp.hInsertAfter = TVI_LAST;
            dp.item.mask = TVIF_TEXT | TVIF_PARAM;
            dp.item.pszText = (LPWSTR)L"…";
            dp.item.lParam = 0;
            SendMessageW(tree, TVM_INSERTITEMW, 0, (LPARAM)&dp);
            SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)h);
        }
    }
    /* 恢复展开状态（ff_tree_reveal 内部自己会 s_syncing，不影响导航） */
    for (int i = 0; i < nExp; ++i) {
        ff_tree_reveal(tree, expanded[i]);
        free(expanded[i]);
    }
    free(expanded);
    if (nExp) DBG(L"populate: 恢复 %d 个已展开节点", nExp);

    s_syncing = false;
}

/* ===================================================== 通知（由主窗口转发） */
LRESULT ff_tree_notify(HWND tree, NMHDR *nh)
{
    if (nh->code == TVN_ITEMEXPANDINGW) {
        NMTREEVIEWW *nt = (NMTREEVIEWW *)nh;
        if (nt->action == TVE_EXPAND) {
            HTREEITEM c = (HTREEITEM)SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD,
                                                  (LPARAM)nt->itemNew.hItem);
            bool dummy = false;
            if (c) {
                TVITEMW ti;
                ZeroMemory(&ti, sizeof(ti));
                ti.mask = TVIF_PARAM | TVIF_HANDLE;
                ti.hItem = c;
                SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti);
                if (ti.lParam == 0) dummy = true;
            } else {
                dummy = true;
            }
            if (dummy) {
                TVITEMW ti;
                ZeroMemory(&ti, sizeof(ti));
                ti.mask = TVIF_PARAM | TVIF_HANDLE;
                ti.hItem = nt->itemNew.hItem;
                SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti);
                TreeData *d = (TreeData *)ti.lParam;
                if (d) fill_children(tree, nt->itemNew.hItem, d->path, d->kind);
            }
        }
        return 0;
    }
    if (nh->code == TVN_SELCHANGEDW) {
        if (!s_syncing) {
            NMTREEVIEWW *nt = (NMTREEVIEWW *)nh;
            TreeData *d = (TreeData *)nt->itemNew.lParam;
            if (d) {
                DBG(L"tree selchanged -> navigate [%ls] kind=%d", d->path, d->kind);
                if (d->kind == FF_KIND_QUICKACCESS) {
                    return 0;         /* 虚拟文件夹自身没有路径，选中只展开不导航 */
                }
                if (d->kind == 5) {
                    ff_navigate(L"", true);
                } else if (fs_is_dir(d->path)) {
                    ff_navigate(d->path, true);
                } else {
                    /* 这个节点对应的目录已经没了（在别处被删的）：重建树把失效节点
                     * 清掉、并回到当前目录，而不是弹一个"路径不存在"的错误框。 */
                    DBG(L"tree selchanged: [%ls] 已不存在，重建树", d->path);
                    /* 先复制父路径（populate 会释放节点数据），重建后选中父级 */
                    wchar_t par[FF_PATH_MAX];
                    ff_str_copy(par, FF_PATH_MAX, d->path);
                    ff_path_parent(par);
                    ff_tree_populate(tree);
                    ff_tree_select_path(tree, par);
                }
            }
        }
        return 0;
    }
    if (nh->code == TVN_DELETEITEMW) {
        NMTREEVIEWW *nt = (NMTREEVIEWW *)nh;
        if (nt->itemOld.lParam) {
            free((void *)nt->itemOld.lParam);
            nt->itemOld.lParam = 0;
        }
        return 0;
    }
    if (nh->code == NM_RCLICK) {
        /* 右键菜单交给主窗口（复用列表那套 build_menu）。
         * 先把命中节点设为选中项——和 Explorer 一致：右键哪个目录，
         * 后续操作就作用于哪个目录。 */
        POINT pt;
        GetCursorPos(&pt);
        TVHITTESTINFO ht;
        ZeroMemory(&ht, sizeof(ht));
        ht.pt = pt;
        ScreenToClient(tree, &ht.pt);
        HTREEITEM h = (HTREEITEM)SendMessageW(tree, TVM_HITTEST, 0, (LPARAM)&ht);
        if (h && !(ht.flags & TVHT_ONITEMBUTTON)) {
            SendMessageW(tree, TVM_SELECTITEM, TVGN_CARET, (LPARAM)h);
        }
        SendMessageW(GetParent(tree), WM_FF_TREE_RCLICK, 0, MAKELPARAM(pt.x, pt.y));
        return 1;                      /* 不让 TreeView 再弹它自己的提示 */
    }
    if (nh->code == TVN_BEGINDRAGA || nh->code == TVN_BEGINDRAGW) {
        /* 左键拖动目录：交给主窗口发起 OLE 拖拽（同一份数据对象/放落逻辑）。
         * TVN_BEGINDRAGW 的 itemNew.lParam 就是节点 TreeData，路径在其生命周期
         * 内有效（DoDragDrop 期间树不会重建——用户正按着鼠标）。 */
        DBG(L"tree BEGINDRAG");
        NMTREEVIEWW *nt = (NMTREEVIEWW *)nh;
        TreeData *d = (TreeData *)nt->itemNew.lParam;
        if (d && d->kind != 5 && d->path[0])
            SendMessageW(GetParent(tree), WM_FF_TREE_DRAG, 0, (LPARAM)d->path);
        return 0;
    }
    return 0;
}

static LRESULT CALLBACK tree_subclass(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                      UINT_PTR id, DWORD_PTR ref)
{
    (void)id; (void)ref;
    if (msg == WM_DROPFILES) {
        /* 从资源管理器拖文件到树的某个节点上：转给主窗口按节点目录落地 */
        SendMessageW(GetParent(hwnd), WM_DROPFILES, wp, lp);
        return 0;
    }
    return DefSubclassProc(hwnd, msg, wp, lp);
}

bool ff_tree_register(HINSTANCE inst) { (void)inst; return true; }

HWND ff_tree_create(HWND parent, HINSTANCE inst)
{
    HWND t = CreateWindowExW(WS_EX_CLIENTEDGE, WC_TREEVIEWW, L"",
                             WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_VSCROLL |
                             TVS_HASBUTTONS | TVS_HASLINES | TVS_LINESATROOT |
                             TVS_SHOWSELALWAYS | TVS_INFOTIP,
                             0, 0, 100, 100, parent, (HMENU)(INT_PTR)IDC_TREE, inst, NULL);
    if (!t) return NULL;
    if (g_app.sysSmall) TreeView_SetImageList(t, g_app.sysSmall, TVSIL_NORMAL);
    SendMessageW(t, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
    DragAcceptFiles(t, TRUE);        /* 从资源管理器拖文件到树节点上也能接收 */
    SetWindowSubclass(t, tree_subclass, 1, 0);
    return t;
}

/* 供 mainwin 调用：判断是否有真实子项 */
bool ff_tree_item_has_children(HWND tree, HTREEITEM item)
{
    return SendMessageW(tree, TVM_GETNEXTITEM, TVGN_CHILD, (LPARAM)item) != 0;
}

/* 展开 path 的每一级节点(不改变选中项)。
 * 树被 populate 重建后所有展开状态丢失;拖动落手后调用它让
 * 源/目标目录在树里立即可见(用户要求:移动/复制后刷新树结构)。 */
void ff_tree_reveal(HWND tree, const wchar_t *path)
{
    if (!tree || !path || !path[0]) return;
    s_syncing = true;
    HTREEITEM root = tree_pc_root(tree);
    if (!root) { s_syncing = false; return; }
    SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)root);

    wchar_t cur[FF_PATH_MAX];
    ff_str_copy(cur, FF_PATH_MAX, path);
    ff_path_normalize(cur);
    wchar_t longp[FF_PATH_MAX];
    DWORD n = GetLongPathNameW(cur, longp, FF_PATH_MAX);
    if (n > 0 && n < FF_PATH_MAX) ff_str_copy(cur, FF_PATH_MAX, longp);

    wchar_t rootDrive[8];
    StringCchPrintfW(rootDrive, 8, L"%c:\\", cur[0]);
    HTREEITEM node = find_child_by_path(tree, root, rootDrive);
    if (!node) { s_syncing = false; return; }
    SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)node);

    wchar_t acc[FF_PATH_MAX];
    ff_str_copy(acc, FF_PATH_MAX, rootDrive);
    const wchar_t *pp = cur + 3;
    while (*pp) {
        wchar_t seg[512];
        int i2 = 0;
        while (*pp && *pp != L'\\' && i2 < 511) seg[i2++] = *pp++;
        seg[i2] = 0;
        if (*pp == L'\\') ++pp;
        if (!seg[0]) break;
        ff_path_join(acc, FF_PATH_MAX, acc, seg);
        HTREEITEM nx = find_child_by_path(tree, node, acc);
        if (!nx) break;
        SendMessageW(tree, TVM_EXPAND, TVE_EXPAND, (LPARAM)nx);
        node = nx;
    }
    SendMessageW(tree, TVM_ENSUREVISIBLE, 0, (LPARAM)node);
    tree_keep_left(tree);          /* 同上：刷新后别让树横向跑掉 */
    s_syncing = false;
}

/* 命中测试：ptScreen 处是树节点时读出节点数据。
 * 折叠按钮（TVHT_ONITEMBUTTON）不算命中 —— 拖放/右键都不该作用在它上面。 */
bool ff_tree_hit_path(HWND tree, POINT ptScreen, FfTreeData *out)
{
    if (!tree || !out) return false;
    out->kind = 0;
    out->path[0] = 0;
    TVHITTESTINFO ht;
    ZeroMemory(&ht, sizeof(ht));
    ht.pt = ptScreen;
    ScreenToClient(tree, &ht.pt);
    HTREEITEM h = (HTREEITEM)SendMessageW(tree, TVM_HITTEST, 0, (LPARAM)&ht);
    if (!h || (ht.flags & TVHT_ONITEMBUTTON)) return false;
    TVITEMW ti;
    ZeroMemory(&ti, sizeof(ti));
    ti.mask = TVIF_PARAM | TVIF_HANDLE;
    ti.hItem = h;
    SendMessageW(tree, TVM_GETITEMW, 0, (LPARAM)&ti);
    TreeData *d = (TreeData *)ti.lParam;
    if (!d) return false;
    out->kind = d->kind;
    ff_str_copy(out->path, FF_PATH_MAX, d->path);
    return true;
}
