/* mainwin.c —— 主窗口：多标签、导航、命令分发、右键菜单、地址栏、状态栏 */
#include "ff.h"

#define MAX_TABS     32
#define MAX_SEL      8192

typedef struct {
    wchar_t      dir[FF_PATH_MAX];
    FfEntryList  raw;
    int         *order;
    int          orderCount;
    FfHistory    hist;
    int          sortCol;
    BOOL         sortAsc;
    wchar_t      title[160];
    bool         searchMode;
    int          viewMode;
} FfTab;

static FfTab *s_tabs;                 /* 堆:78KB 静态零数组会进 .data */
static int    s_tabCount = 0;
static int    s_active = 0;

/* 剪贴板格式 */
static UINT   s_cfDropEffect = 0;

/* 地址栏面包屑层（盖在地址编辑框上，点路径段直达目录） */
static HWND   s_crumb = NULL;        /* FFCrumb 覆盖窗 */
static HWND   s_addrEdit = NULL;     /* 组合框里的 Edit 子控件 */
static bool   s_editMode = false;    /* 编辑态:只有单击空白/双击才置位(常驻面包屑) */
static wchar_t s_crumbPath[FF_PATH_MAX] = L"";
static void   crumb_reposition(void);

/* 分隔条状态 */
static bool s_dragSplit = false;
static int  s_dragStartX = 0, s_dragStartW = 0;
static int  s_splitX = 0, s_splitTop = 0, s_splitBottom = 0;
static bool s_splitVisible = false;

/* 前向声明 */
static void filter_clear(void);
static void build_address_list(void);
static void layout_children(HWND hwnd);

/* ===================================================== 排序 / 筛选 */
static bool pass_filter(const FfEntry *e, const FfFilter *f)
{
    if (!f || !f->enabled) return true;
    if (f->kind == 1 && e->isDir && !e->isDrive) return false;
    if (f->kind == 2 && !e->isDir) return false;
    if (f->driveKind && e->driveKind != f->driveKind) return false;
    if (!e->isDir) {
        if (f->hasMtime) {
            if (CompareFileTime(&e->mtime, &f->mtimeFrom) < 0) return false;
            if (CompareFileTime(&e->mtime, &f->mtimeTo) > 0) return false;
        }
        if (f->hasSize) {
            if (f->sizeMin && e->size < f->sizeMin) return false;
            if (f->sizeMax && e->size > f->sizeMax) return false;
        }
    }
    return true;
}

static FfEntry *s_cmpRaw = NULL;
static int      s_cmpCol = COL_NAME;
static BOOL     s_cmpAsc = TRUE;

static int cmp_by_col(const FfEntry *a, const FfEntry *b)
{
    int r = 0;
    switch (s_cmpCol) {
    case COL_TYPE:
        r = StrCmpLogicalW(a->type[0] ? a->type : L"文件夹", b->type[0] ? b->type : L"文件夹");
        break;
    case COL_SIZE:
        r = (a->size < b->size) ? -1 : (a->size > b->size ? 1 : 0);
        break;
    case COL_ATTR: {
        wchar_t x[16], y[16];
        ff_format_attr(a->attrs, x, 16);
        ff_format_attr(b->attrs, y, 16);
        r = wcscmp(x, y);
        break;
    }
    case COL_MTIME:
        r = CompareFileTime(&a->mtime, &b->mtime);
        break;
    case COL_CTIME:
        r = CompareFileTime(&a->ctime, &b->ctime);
        break;
    default:
        break;
    }
    if (r == 0) r = StrCmpLogicalW(a->name, b->name);
    return r;
}

static int order_cmp(const void *pa, const void *pb)
{
    int ia = *(const int *)pa, ib = *(const int *)pb;
    const FfEntry *a = &s_cmpRaw[ia], *b = &s_cmpRaw[ib];
    if (a->isDir != b->isDir) return a->isDir ? -1 : 1;
    int r = cmp_by_col(a, b);
    return s_cmpAsc ? r : -r;
}

static int order_cmp_nodir(const void *pa, const void *pb)
{
    int ia = *(const int *)pa, ib = *(const int *)pb;
    int r = cmp_by_col(&s_cmpRaw[ia], &s_cmpRaw[ib]);
    return s_cmpAsc ? r : -r;
}

static void build_order(FfTab *t)
{
    if (t->order) { free(t->order); t->order = NULL; }
    t->orderCount = 0;
    if (t->raw.count <= 0) return;

    /* 此电脑视图要多放一个组头行，多给一个槽位 */
    t->order = (int *)malloc((size_t)(t->raw.count + 1) * sizeof(int));
    if (!t->order) return;

    /* "此电脑"视图：固定两段布局（Win10 同款），组头行以负数下标插入
     * [常用文件夹 | 设备和驱动器头 | 驱动器] */
    if (!t->dir[0] && !t->searchMode) {
        int n = 0;
        for (int i = 0; i < t->raw.count; ++i)
            if (t->raw.items[i].groupId == PCGRP_NONE) t->order[n++] = i;
        t->order[n++] = FF_ORDER_HDR_DRIVE;
        for (int i = 0; i < t->raw.count; ++i)
            if (t->raw.items[i].groupId == PCGRP_DRIVE) t->order[n++] = i;
        t->orderCount = n;
        return;
    }

    int n = 0;
    for (int i = 0; i < t->raw.count; ++i)
        if (pass_filter(&t->raw.items[i], &g_app.filter)) t->order[n++] = i;

    s_cmpRaw = t->raw.items;
    s_cmpCol = t->sortCol;
    s_cmpAsc = t->sortAsc;
    if (n > 1) {
        /* "此电脑"视图与查找结果视图不再把目录提前，其余保持目录优先 */
        bool keepDirFirst = (t->dir[0] != 0) && !t->searchMode;
        qsort(t->order, (size_t)n, sizeof(int), keepDirFirst ? order_cmp : order_cmp_nodir);
    }
    t->orderCount = n;
}

/* ===================================================== 界面辅助 */
static FfTab *cur_tab(void)
{
    if (!s_tabs) s_tabs = (FfTab *)calloc(MAX_TABS, sizeof(FfTab));
    return &s_tabs[s_active];
}

void ff_set_status(const wchar_t *text)
{
    if (g_app.status) SendMessageW(g_app.status, SB_SETTEXTW, 0, (LPARAM)text);
}

HWND ff_get_list(void) { return g_app.list; }

static void set_address_text(const wchar_t *dir)
{
    if (!g_app.addr) return;
    SetWindowTextW(g_app.addr, dir && *dir ? dir : L"此电脑");
    /* 同步面包屑层：路径变化时重绘各段（"此电脑"画成单个不可点段） */
    ff_str_copy(s_crumbPath, FF_PATH_MAX, dir && *dir ? dir : L"");
    /* 用 reposition 而非 sync_text:后者只在【已可见】时重绘,
     * 面包屑因编辑态/初始化处于隐藏时导航后没人 SHOW —— 表现为
     * "要鼠标移过去才出现"。reposition 含显示判定,导航后立即常驻。 */
    crumb_reposition();
    /* 光标停在末尾，避免整段文本呈现被选中态 */
    int n = GetWindowTextLengthW(g_app.addr);
    SendMessageW(g_app.addr, CB_SETEDITSEL, 0, MAKELPARAM(n, n));
}

static void update_title(void)
{
    FfTab *t = cur_tab();
    wchar_t title[256];
    if (t->searchMode) StringCchPrintfW(title, 256, L"查找结果");
    else if (!t->dir[0]) StringCchPrintfW(title, 256, L"此电脑");
    else ff_str_copy(title, 256, ff_path_name(t->dir));
    if (!title[0]) ff_str_copy(title, 256, t->dir);
    ff_str_copy(t->title, 160, title);
    ff_tabs_set_title(g_app.tabs, s_active, title);

    wchar_t cap[512];
    StringCchPrintfW(cap, 512, L"%s - %s [%s]", title, FF_APP_TITLE, FF_APP_SUBTITLE);
    SetWindowTextW(g_app.main, cap);
}

static void update_status(void)
{
    if (!g_app.status) return;
    FfTab *t = cur_tab();
    int rows[MAX_SEL];
    int nsel = ff_list_selected(g_app.list, rows, MAX_SEL);

    wchar_t p0[512];
    if (nsel > 0) {
        ULONGLONG sz = 0;
        for (int i = 0; i < nsel; ++i) {
            const FfEntry *e = ff_list_row_entry(g_app.list, rows[i]);
            if (e && !e->isDir) sz += e->size;
        }
        wchar_t a[64];
        ff_format_size(sz, a, 64);
        StringCchPrintfW(p0, 512, L"已选中 %d 个对象，共 %s", nsel, a);
    } else if (t->searchMode) {
        StringCchPrintfW(p0, 512, L"查找结果：%d 项", t->orderCount);
    } else if (!t->dir[0]) {
        StringCchPrintfW(p0, 512, L"此电脑");
    } else {
        ff_str_copy(p0, 512, t->dir);
    }
    SendMessageW(g_app.status, SB_SETTEXTW, 0, (LPARAM)p0);

    /* "此电脑"视图的 order 里含一条自绘组头行，不算对象 */
    int shown = t->orderCount;
    if (!t->searchMode && !t->dir[0] && shown > 0) --shown;
    wchar_t p1[128];
    if (shown != t->raw.count)
        StringCchPrintfW(p1, 128, L"%d / %d 个对象（已筛选）", shown, t->raw.count);
    else
        StringCchPrintfW(p1, 128, L"%d 个对象", t->raw.count);
    SendMessageW(g_app.status, SB_SETTEXTW, 1, (LPARAM)p1);

    wchar_t p2[128] = L"";
    if (g_app.filter.enabled) ff_str_copy(p2, 128, L"筛选：开启");
    else ff_str_copy(p2, 128, L"筛选：关闭");
    SendMessageW(g_app.status, SB_SETTEXTW, 2, (LPARAM)p2);
}

void ff_update_ui_state(void)
{
    FfTab *t = cur_tab();

    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_BACK, t->hist.top > 0);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_FORWARD, t->hist.top < t->hist.count - 1);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_UP, t->dir[0] != 0);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_HOME, true);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_REFRESH, true);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_FIND, t->dir[0] != 0);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_FILTER, true);
    ff_toolbar_set_enabled(g_app.addrBar, FF_TB_VIEW, true);
    ff_toolbar_set_checked(g_app.addrBar, FF_TB_FILTER, g_app.filterVisible);
    ff_toolbar_set_checked(g_app.addrBar, FF_TB_HOME, !t->dir[0]);
    update_status();
}

static void refresh_list(void)
{
    FfTab *t = cur_tab();
    /* filelist 在解析图标时要拼完整路径（.exe/.lnk 这类"图标长在文件里"的
     * 必须拿真实路径问 Shell，见 fs_icon_for_entry），所以先把"列表当前显示的
     * 目录"同步过去；搜索结果里条目名本身就是完整路径，这里给空串即可。 */
    ff_str_copy(g_app.curDir, FF_PATH_MAX, t->searchMode ? L"" : t->dir);
    ff_list_set_data(g_app.list, t->raw.items, t->raw.count,
                     t->order, t->orderCount, t->sortCol, t->sortAsc);

    /* "此电脑"视图：组头行已由 build_order 插入，这里只把组内条数
     * 交给 filelist 生成组头标题；其他视图清掉，组头行不出现 */
    if (!t->searchMode && !t->dir[0]) {
        int drv = 0;
        for (int i = 0; i < t->raw.count; ++i)
            if (t->raw.items[i].groupId == PCGRP_DRIVE) ++drv;
        ff_list_set_group_counts(drv);
    } else {
        ff_list_set_group_counts(0);
    }
}

/* ===================================================== 布局 */
static void layout_children(HWND hwnd)
{
    RECT rc;
    GetClientRect(hwnd, &rc);
    /* 自上而下：菜单栏(非客户区) → 地址栏条 → 标签栏。
     * 条带隐藏时高度归零，下面的整体上移。 */
    int barH = ff_scale(36);
    int adH = g_app.addrBarVisible ? barH : 0;
    int tabH = ff_tabs_height(g_app.tabs);
    int stH = ff_scale(23);
    int pad = ff_scale(6);
    int addrH = ff_scale(26);
    int y = 0;

    /* 显隐两条规则，缺哪一条都会出问题：
     * 1) 隐藏前必须先把条带移出客户区（喂一个零高度矩形），让它原来占的那块被系统
     *    重绘掉，之后才 ShowWindow(SW_HIDE)。反过来"先隐藏再移动"的话，窗口在隐藏
     *    状态下收到 WM_WINDOWPOSCHANGED，自己那块不会被擦除，屏幕上会残留下旧的
     *    一排按钮像素（残影）。
     * 2) 显示分支必须显式 ShowWindow(SW_SHOW)。MoveWindow 只会搬位置，不会把已经
     *    SW_HIDE 的窗口变回可见 —— 漏了它的后果是：布局照旧给条带留了一行高度，
     *    但条带本身没显示，那一整行露出主窗口底色，看起来就是"一条白的"。 */
    if (g_app.addrBar) {
        if (g_app.addrBarVisible) {
            MoveWindow(g_app.addrBar, 0, y, rc.right, adH, TRUE);
            ShowWindow(g_app.addrBar, SW_SHOW);
        } else {
            MoveWindow(g_app.addrBar, 0, rc.bottom, rc.right, 0, TRUE);
            ShowWindow(g_app.addrBar, SW_HIDE);
        }
    }

    /* 地址输入框紧跟在地址栏条全部按钮（导航 5 + 查找/筛选/查看 3）后面 */
    if (g_app.addr) {
        if (g_app.addrBarVisible) {
            int ax = ff_toolbar_width(g_app.addrBar);
            int addrW = rc.right - ax - pad * 2;
            if (addrW < ff_scale(120)) addrW = ff_scale(120);
            MoveWindow(g_app.addr, ax, y + (adH - addrH) / 2, addrW, ff_scale(260), TRUE);
            ShowWindow(g_app.addr, SW_SHOW);
        } else {
            ShowWindow(g_app.addr, SW_HIDE);
        }
    }
    crumb_reposition();      /* 面包屑层跟随地址编辑框矩形 */
    y += adH;

    if (g_app.tabs) MoveWindow(g_app.tabs, 0, y, rc.right, tabH, TRUE);

    int cy = y + tabH;
    int ch = rc.bottom - cy - stH;
    if (ch < 0) ch = 0;
    int split = g_app.treeVisible ? ff_scale(4) : 0;
    int treeW = g_app.treeVisible ? g_app.treeWidth : 0;
    int filterW = g_app.filterVisible ? ff_scale(252) : 0;
    int listX = treeW + split;
    int listW = rc.right - listX - filterW;
    if (listW < 0) listW = 0;

    if (g_app.tree) {
        MoveWindow(g_app.tree, 0, cy, treeW, ch, TRUE);
        ShowWindow(g_app.tree, g_app.treeVisible ? SW_SHOW : SW_HIDE);
    }
    if (g_app.list) MoveWindow(g_app.list, listX, cy, listW, ch, TRUE);
    if (g_app.filterPanel) {
        MoveWindow(g_app.filterPanel, listX + listW, cy, filterW, ch, TRUE);
        ShowWindow(g_app.filterPanel, g_app.filterVisible ? SW_SHOW : SW_HIDE);
    }
    if (g_app.status) {
        MoveWindow(g_app.status, 0, rc.bottom - stH, rc.right, stH, TRUE);
        int parts[3];
        parts[0] = rc.right - ff_scale(330);
        parts[1] = rc.right - ff_scale(160);
        parts[2] = -1;
        SendMessageW(g_app.status, SB_SETPARTS, 3, (LPARAM)parts);
    }

    /* 记录列分隔条位置，供自绘与命中测试使用 */
    s_splitVisible = g_app.treeVisible;
    s_splitX = treeW + split / 2;
    s_splitTop = cy;
    s_splitBottom = cy + ch;
    if (s_splitVisible) InvalidateRect(hwnd, NULL, FALSE);

    /* 顶部条带（工具栏条 / 地址栏条）显隐之后，原来被它们占住的那几行必须整片重画：
     * 子窗口 ShowWindow(HIDE) 只擦掉自己那一块，MoveWindow 把列表下移/上移时也未必
     * 覆盖到全部旧像素，结果是屏幕上残留一排"重复画出来的按钮"（残影）。
     * 这里做三步：刷新主窗口背景 -> 强制列表整片重绘 -> 立刻同步绘制，
     * 保证条带显隐后画面立即一致。 */
    if (g_app.list) {
        InvalidateRect(hwnd, NULL, TRUE);
        RedrawWindow(hwnd, NULL, NULL,
                     RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW);
        RedrawWindow(g_app.list, NULL, NULL,
                     RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW);
    }
}

/* ===================================================== 历史 */
void ff_navigate(const wchar_t *dir, bool addHistory)
{
    FfTab *t = cur_tab();
    wchar_t target[FF_PATH_MAX];
    ff_str_copy(target, FF_PATH_MAX, dir ? dir : L"");
    ff_path_normalize(target);
    DBG(L"navigate: [%ls]", target);

    if (target[0] && !fs_is_dir(target)) {
        ff_msg_error(g_app.main, L"路径不存在或不是文件夹：\n%s", target);
        return;
    }

    FfEntryList list;
    ZeroMemory(&list, sizeof(list));
    if (!fs_list_dir(target, &list)) {
        DWORD e = GetLastError();
        if (e == ERROR_ACCESS_DENIED) ff_msg_error(g_app.main, L"拒绝访问：\n%s", target);
        else ff_msg_error(g_app.main, L"无法打开文件夹：\n%s", target);
        return;
    }

    fs_entry_list_free(&t->raw);
    t->raw = list;
    ff_str_copy(t->dir, FF_PATH_MAX, target);
    t->searchMode = false;

    if (addHistory) ff_hist_push(&t->hist, target);

    build_order(t);
    update_title();
    set_address_text(target);
    ff_tabs_update(g_app.tabs, s_tabCount, s_active);
    ff_tree_select_path(g_app.tree, target);
    refresh_list();
    ff_update_ui_state();
    /* 标签图标:每个标签按各自目录取 HICON。★导航路径也要填 ——
     * 之前只填在 ff_refresh(F5) 里,导航后标签全停在默认白纸/空(用户实测)。 */
    for (int ti = 0; ti < s_tabCount; ++ti) {
        if (s_tabs[ti].dir[0]) {
            SHFILEINFOW sfi;
            ZeroMemory(&sfi, sizeof(sfi));
            if (SHGetFileInfoW(s_tabs[ti].dir, FILE_ATTRIBUTE_DIRECTORY, &sfi,
                               sizeof(sfi), SHGFI_ICON | SHGFI_SMALLICON)) {
                ff_tabs_set_hicon(g_app.tabs, ti, sfi.hIcon);
                DestroyIcon(sfi.hIcon);      /* set_hicon 内部已 CopyIcon，原件必须还回去 */
            }
            continue;
        }
        /* 此电脑/搜索视图(dir 空):用"此电脑"的索引从 sysSmall 取 HICON。
         * ★SHGetFileInfoW 的字符串形式拿不到"此电脑"图标(实测全失败),
         * fs_icon_this_pc 用 PIDL 方式才行。 */
        int idx = fs_icon_this_pc();
        if (idx >= 0 && g_app.sysSmall) {
            HICON ic = ImageList_GetIcon(g_app.sysSmall, idx, ILD_TRANSPARENT);
            if (ic) { ff_tabs_set_hicon(g_app.tabs, ti, ic); DestroyIcon(ic); }
        }
    }
    fs_watch_set(g_app.main, target);   /* 导航后监听新目录（同目录不重建） */
}

void ff_go_up(void)
{
    FfTab *t = cur_tab();
    if (!t->dir[0]) return;
    wchar_t up[FF_PATH_MAX];
    ff_str_copy(up, FF_PATH_MAX, t->dir);
    wchar_t before[FF_PATH_MAX];
    ff_str_copy(before, FF_PATH_MAX, up);
    ff_path_parent(up);
    if (_wcsicmp(up, before) == 0) return;
    ff_navigate(up, true);
}

void ff_go_back(void)
{
    FfTab *t = cur_tab();
    if (t->hist.top <= 0) return;
    t->hist.top--;
    ff_navigate(t->hist.stack[t->hist.top], false);
}

void ff_go_forward(void)
{
    FfTab *t = cur_tab();
    if (t->hist.top >= t->hist.count - 1) return;
    t->hist.top++;
    ff_navigate(t->hist.stack[t->hist.top], false);
}

void ff_refresh(bool keepSelection)
{
    FfTab *t = cur_tab();
    (void)keepSelection;
    DBG(L"refresh: dir=[%ls]", t->dir);
    if (t->searchMode) { refresh_list(); return; }

    /* ★当前目录自己被删掉了（自己删的、或者在别处删的）：逐级上溯到还存在的祖先。
     *   不处理的话下面 fs_list_dir 会失败、整个刷新静默返回 ——
     *   表现就是"删掉目录后列表还停在那个已经没了的目录里，点什么操作都报错"。 */
    if (t->dir[0] && !fs_is_dir(t->dir)) {
        wchar_t up[FF_PATH_MAX];
        wchar_t gone[FF_PATH_MAX];
        ff_str_copy(gone, FF_PATH_MAX, t->dir);
        ff_str_copy(up, FF_PATH_MAX, gone);
        while (up[0] && !fs_is_dir(up)) ff_path_parent(up);
        DBG(L"refresh: 目录没了 [%ls] → 退到 [%ls]", gone, up);
        ff_navigate(up[0] ? up : L"", true);
        return;
    }

    /* 直接枚举进当前列表：fs_list_dir 会复用已分配的条目缓冲区，
     * 省掉一次"新建 + 释放"的大块内存周转 */
    if (!fs_list_dir(t->dir, &t->raw)) return;
    build_order(t);
    refresh_list();
    update_title();
    ff_update_ui_state();
    ff_tree_populate(g_app.tree);
    ff_tree_select_path(g_app.tree, t->dir);
    /* 标签图标:每个标签按各自目录取 HICON(SHGFI_ICON|SMALLICON)。
     * 之前用 SHGFI_SYSICONINDEX 的索引 + sysSmall 列表画出来全是白纸 ——
     * 该模式下目录返回的 iIcon=0 在 sysSmall 里是白纸文档(用户实测);
     * 直接要 HICON 则返回正确的黄文件夹。 */
    for (int ti = 0; ti < s_tabCount; ++ti) {
        if (!s_tabs[ti].dir[0]) continue;
        SHFILEINFOW sfi;
        ZeroMemory(&sfi, sizeof(sfi));
        if (SHGetFileInfoW(s_tabs[ti].dir, FILE_ATTRIBUTE_DIRECTORY, &sfi,
                           sizeof(sfi), SHGFI_ICON | SHGFI_SMALLICON)) {
            ff_tabs_set_hicon(g_app.tabs, ti, sfi.hIcon);
            DestroyIcon(sfi.hIcon);          /* 同上：原件用完即还 */
        }
    }
    fs_watch_set(g_app.main, t->dir);   /* 跟着当前目录走（同目录时什么都不做） */
}

/* 外部变化触发的轻量刷新：只重读列表，不重建目录树
 * （树重建会闪、还会丢掉展开状态；解压几百个文件时尤其明显）。 */
static void refresh_from_watch(void)
{
    FfTab *t = cur_tab();
    if (!t->dir[0] || t->searchMode) return;

    /* 当前目录本身被删掉了：逐级上溯到还存在的祖先，别停在一个空壳上 */
    if (!fs_is_dir(t->dir)) {
        wchar_t up[FF_PATH_MAX];
        ff_str_copy(up, FF_PATH_MAX, t->dir);
        while (up[0] && !fs_is_dir(up)) ff_path_parent(up);
        DBG(L"watch: 当前目录没了，退到 [%ls]", up);
        ff_navigate(up[0] ? up : L"", true);
        return;
    }

    FfEntryList list;
    ZeroMemory(&list, sizeof(list));
    if (!fs_list_dir(t->dir, &list)) return;
    fs_entry_list_free(&t->raw);
    t->raw = list;

    build_order(t);
    refresh_list();
    update_title();
    ff_update_ui_state();

    /* 目录树：整树重建 + 重新展开到当前路径。
     * （用"只重建当前节点"会踩 TVM_GETNEXTITEM/TVGN_CARET 的短路径错位坑，
     *   实测会去重建 C:\Users\Administrator 这种不相干的节点。） */
    ff_tree_populate(g_app.tree);
    ff_tree_select_path(g_app.tree, t->dir);

    DBG(L"watch refresh: dir=[%ls] rows=%d", t->dir, (int)t->raw.count);
}

void ff_apply_filter(void)
{
    for (int i = 0; i < s_tabCount; ++i) build_order(&s_tabs[i]);
    refresh_list();
    ff_update_ui_state();
}

/* ===================================================== 选中 → 路径 */
/* 把一条记录还原成完整路径（驱动器显示名可能带卷标，必须单独处理） */
static void entry_full_path(const FfTab *t, const FfEntry *e, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!e || !t) return;
    if (e->isDrive) {
        /* 桌面 / 文档 / 视频 / 图片 / 音乐 / 下载 都是虚拟节点，
         * 背后就是真实的用户目录 */
        if (e->driveKind == DRIVE_DESKTOP_K || e->driveKind == DRIVE_DOCS_K ||
            e->driveKind == DRIVE_VIDEO_K   || e->driveKind == DRIVE_PICS_K ||
            e->driveKind == DRIVE_MUSIC_K   || e->driveKind == DRIVE_DL_K) {
            fs_special_path(e->driveKind, out, cch);
            return;
        }
        out[0] = e->name[0];
        out[1] = L':';
        out[2] = L'\\';
        out[3] = 0;
        return;
    }
    if (t->searchMode || (e->name[1] == L':' && e->name[2] == L'\\')) {
        ff_str_copy(out, cch, e->name);
        return;
    }
    ff_path_join(out, cch, t->dir, e->name);
}

/* 树右键菜单期间的非空选中集：树节点目录。
 * 树的 NM_RCLICK 已把节点设为 caret 并导航（t->dir = 节点目录），
 * 但列表里没有选中项，build_menu 的复制/剪切/删除按 ff_selected_paths
 * 置灰 —— 用户实测"树右键里复制是灰的"。菜单 track 期间置上它，
 * ff_selected_paths / build_menu 的 nsel 就都返回这个节点。 */
static wchar_t s_treeMenuSel[FF_PATH_MAX];

int ff_selected_paths(wchar_t ***outPaths)
{
    *outPaths = NULL;
    if (s_treeMenuSel[0]) {
        wchar_t **arr = (wchar_t **)calloc(1, sizeof(wchar_t *));
        if (!arr) return 0;
        arr[0] = _wcsdup(s_treeMenuSel);
        if (!arr[0]) { free(arr); return 0; }
        *outPaths = arr;
        return 1;
    }
    int rows[MAX_SEL];
    int n = ff_list_selected(g_app.list, rows, MAX_SEL);
    if (n <= 0) return 0;

    wchar_t **arr = (wchar_t **)calloc((size_t)n, sizeof(wchar_t *));
    if (!arr) return 0;
    FfTab *t = cur_tab();
    int m = 0;
    for (int i = 0; i < n; ++i) {
        const FfEntry *e = ff_list_row_entry(g_app.list, rows[i]);
        if (!e) continue;
        arr[m] = (wchar_t *)calloc(FF_PATH_MAX, sizeof(wchar_t));
        if (!arr[m]) continue;
        entry_full_path(t, e, arr[m], FF_PATH_MAX);
        ++m;
    }
    *outPaths = arr;
    return m;
}

void ff_free_paths(wchar_t **paths, int count)
{
    if (!paths) return;
    for (int i = 0; i < count; ++i) free(paths[i]);
    free(paths);
}

/* ===================================================== 剪贴板 */
static void put_clipboard_files(const wchar_t **files, int count, bool cut)
{
    if (count <= 0) return;
    size_t bytes = sizeof(DROPFILES);
    for (int i = 0; i < count; ++i) bytes += (wcslen(files[i]) + 1) * sizeof(wchar_t);
    bytes += sizeof(wchar_t);

    HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, bytes);
    if (!h) return;
    DROPFILES *df = (DROPFILES *)GlobalLock(h);
    if (!df) { GlobalFree(h); return; }
    df->pFiles = sizeof(DROPFILES);
    df->fWide = TRUE;
    wchar_t *p = (wchar_t *)((BYTE *)df + sizeof(DROPFILES));
    for (int i = 0; i < count; ++i) {
        size_t n = wcslen(files[i]);
        memcpy(p, files[i], n * sizeof(wchar_t));
        p += n + 1;
    }
    *p = 0;
    GlobalUnlock(h);

    if (!OpenClipboard(g_app.main)) { GlobalFree(h); return; }
    EmptyClipboard();
    SetClipboardData(CF_HDROP, h);

    if (s_cfDropEffect) {
        HGLOBAL he = GlobalAlloc(GMEM_MOVEABLE, sizeof(DWORD));
        if (he) {
            DWORD *pe = (DWORD *)GlobalLock(he);
            if (pe) {
                *pe = cut ? DROPEFFECT_MOVE : DROPEFFECT_COPY;
                GlobalUnlock(he);
                SetClipboardData(s_cfDropEffect, he);
            }
        }
    }
    CloseClipboard();
}

static int get_clipboard_files(wchar_t ***out, bool *cut)
{
    *out = NULL;
    if (cut) *cut = false;
    if (!IsClipboardFormatAvailable(CF_HDROP)) return 0;
    if (!OpenClipboard(g_app.main)) return 0;

    int n = 0;
    HDROP hd = (HDROP)GetClipboardData(CF_HDROP);
    if (hd) {
        UINT cnt = DragQueryFileW(hd, 0xFFFFFFFF, NULL, 0);
        if (cnt > 0) {
            wchar_t **arr = (wchar_t **)calloc(cnt, sizeof(wchar_t *));
            if (arr) {
                for (UINT i = 0; i < cnt; ++i) {
                    arr[i] = (wchar_t *)calloc(FF_PATH_MAX, sizeof(wchar_t));
                    if (arr[i]) DragQueryFileW(hd, i, arr[i], FF_PATH_MAX);
                }
                *out = arr;
                n = (int)cnt;
            }
        }
    }
    if (cut && s_cfDropEffect && IsClipboardFormatAvailable(s_cfDropEffect)) {
        HGLOBAL he = GetClipboardData(s_cfDropEffect);
        if (he) {
            DWORD *pe = (DWORD *)GlobalLock(he);
            if (pe) { *cut = (*pe == DROPEFFECT_MOVE); GlobalUnlock(he); }
        }
    }
    CloseClipboard();
    return n;
}

/* ===================================================== 拖放
 * 拖出：把选中的文件拖到 桌面程序图标 / 资源管理器 / 任意接收拖放的窗口。
 *   用真实 PIDL 建 Shell 数据对象（IShellItemArray → BHID_DataObject）——
 *   它和资源管理器拖拽用的是同一种对象（自带 CF_HDROP 及全部 Shell 扩展格式），
 *   所以拖到程序图标上=用该程序打开，拖到文件夹/盘符上=复制或移动，
 *   与从 Win10 资源管理器里拖出去完全一致。
 * 拖入：别的程序把文件拖到本程序列表 = 复制到当前正在浏览的目录。
 *   规则（按用户约定）：
 *   - 拖到当前目录（文件本来就在这里）→ 什么都不做，不提示复制；
 *   - 拖到其它目录 → 放开鼠标立即开始复制（重名自动改名，不弹确认框）；
 *   - 在"此电脑"/搜索结果里（没有实体目录）→ 直接进入文件所在目录。 */

/* —— IDropSource 最小实现：松开左键=放下，Esc=取消，其余用系统默认光标 —— */
static HRESULT STDMETHODCALLTYPE dsrc_QueryInterface(IDropSource *This, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IDropSource)) {
        *ppv = This;
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}
static ULONG  STDMETHODCALLTYPE dsrc_AddRef(IDropSource *This)   { (void)This; return 2; }
static ULONG  STDMETHODCALLTYPE dsrc_Release(IDropSource *This)  { (void)This; return 1; }
static HRESULT STDMETHODCALLTYPE dsrc_Continue(IDropSource *This, BOOL fEscape, DWORD grfKeyState)
{
    (void)This;
    if (fEscape) return DRAGDROP_S_CANCEL;
    if (!(grfKeyState & MK_LBUTTON)) return DRAGDROP_S_DROP;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE dsrc_Feedback(IDropSource *This, DWORD dwEffect)
{ (void)This; (void)dwEffect; return DRAGDROP_S_USEDEFAULTCURSORS; }

static IDropSourceVtbl dsrc_vtbl = {
    dsrc_QueryInterface, dsrc_AddRef, dsrc_Release, dsrc_Continue, dsrc_Feedback
};
static IDropSource s_dragSrc = { &dsrc_vtbl };

/* —— 树/列表的 IDropTarget：拖动悬停时显示 复制/移动 光标（不再出现"禁止"），
 * 松手弹"复制/移动/取消"菜单 —— 用户要求的效果。
 * 只认【本程序拖出的数据对象】：自己拖给自己 = 确认菜单；
 * 外部程序拖进来 = 不接受（DragAcceptFiles 那条 WM_DROPFILES 路径照旧）。
 * 判别法：拖出时把被拖路径存进 s_treeDragPath，且数据对象是我们
 * shell_data_object 建的（包一个自定义 FORMATETC 标记位最可靠 —— 用
 * 注册格式 "FileCE.DragSource" 存一个 DWORD 魔数）。 */
static UINT s_cfDragSrc;                 /* 注册格式号（懒注册） */
static bool s_dropOwnDrag;               /* 当前拖入是否本程序拖出（DragEnter 时判定） */
static void handle_drop_files(HDROP hd); /* 定义在后面：外部拖入的落地 */
#define FF_DRAGSRC_MAGIC 0x46434531u     /* "FCE1" */

static bool drop_is_own_drag(IDataObject *pdo)
{
    if (!s_cfDragSrc)
        s_cfDragSrc = RegisterClipboardFormatW(L"FileCE.DragSource");
    FORMATETC fe;
    ZeroMemory(&fe, sizeof(fe));
    fe.cfFormat = (CLIPFORMAT)s_cfDragSrc;
    fe.dwAspect = DVASPECT_CONTENT;
    fe.lindex = -1;
    fe.tymed = TYMED_HGLOBAL;
    if (FAILED(pdo->lpVtbl->QueryGetData(pdo, &fe)) || fe.cfFormat == 0)
        return false;
    STGMEDIUM stm;
    if (FAILED(pdo->lpVtbl->GetData(pdo, &fe, &stm)))
        return false;
    bool own = false;
    if (stm.hGlobal) {
        DWORD *v = (DWORD *)GlobalLock(stm.hGlobal);
        own = v && *v == FF_DRAGSRC_MAGIC;
        if (v) GlobalUnlock(stm.hGlobal);
    }
    if (stm.pUnkForRelease) stm.pUnkForRelease->lpVtbl->Release(stm.pUnkForRelease);
    return own;
}

/* 拖动落手确认的挂起上下文：Drop 只存不弹（见 WM_FF_TREE_CONFIRM）。 */
static bool s_treeDropHandled = false;
static wchar_t s_pendingDropSrc[FF_PATH_MAX];
static wchar_t s_pendingDropDst[FF_PATH_MAX];
static POINT   s_pendingDropPt;

/* 被拖动节点的路径。DoDragDrop 阻塞期间拖放目标（本程序）会在同线程重入，
 * 用完立即清空；堆上拷贝，防止树在拖动期间重建悬空指针。 */
static wchar_t *s_treeDragPath = NULL;

/* —— 最小 IDropTarget：DragEnter/DragOver 返回 COPY|MOVE（光标带 +/移动样式），
 * Drop 时弹确认菜单；DragLeave 清空。只服务【本程序拖出】的数据。 —— */
static bool tree_drag_hit_target(POINT pt, wchar_t *out, size_t cch);   /* 定义在后面 */
static void tree_drop_confirm(const wchar_t *src, const wchar_t *dstDir, POINT pt);
static IDropTarget s_dropTarget;                                        /* 定义在 vtbl 后 */

static HRESULT STDMETHODCALLTYPE dtgt_QueryInterface(IDropTarget *This, REFIID riid, void **ppv)
{
    (void)This;
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IDropTarget)) {
        *ppv = &s_dropTarget;
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}
static ULONG  STDMETHODCALLTYPE dtgt_AddRef(IDropTarget *This)  { (void)This; return 2; }
static ULONG  STDMETHODCALLTYPE dtgt_Release(IDropTarget *This) { (void)This; return 1; }
static HRESULT STDMETHODCALLTYPE dtgt_DragEnter(IDropTarget *This, IDataObject *pdo,
                                                DWORD keys, POINTL pt, DWORD *effect)
{
    (void)This; (void)keys; (void)pt;
    s_dropOwnDrag = drop_is_own_drag(pdo);
    /* 自己拖给自己 = 复制/移动 光标（松手弹确认菜单）；
     * 外部程序拖进来 = 复制 光标（松手复制到当前目录，替代 WM_DROPFILES） */
    *effect = (*effect & (DROPEFFECT_COPY | DROPEFFECT_MOVE));
    if (!s_dropOwnDrag) *effect &= DROPEFFECT_COPY;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE dtgt_DragOver(IDropTarget *This, DWORD keys,
                                               POINTL pt, DWORD *effect)
{
    (void)This; (void)keys; (void)pt;
    *effect = (*effect & (DROPEFFECT_COPY | DROPEFFECT_MOVE));
    if (!s_dropOwnDrag) *effect &= DROPEFFECT_COPY;
    return S_OK;
}
static HRESULT STDMETHODCALLTYPE dtgt_DragLeave(IDropTarget *This)
{
    (void)This;
    return S_OK;
}
/* 外部程序拖进来的 HDROP：把文件复制到当前浏览目录（原 WM_DROPFILES 语义）。
 * 主窗口注册 IDropTarget 后，DragAcceptFiles 的消息通道不再触发，落在这里。 */
static void drop_external_hdrop(IDataObject *pdo, POINTL ptl)
{
    FORMATETC fe;
    ZeroMemory(&fe, sizeof(fe));
    fe.cfFormat = CF_HDROP;
    fe.dwAspect = DVASPECT_CONTENT;
    fe.lindex = -1;
    fe.tymed = TYMED_HGLOBAL;
    STGMEDIUM stm;
    if (FAILED(pdo->lpVtbl->GetData(pdo, &fe, &stm)))
        return;
    if (stm.hGlobal) {
        /* 主窗口尺寸内松手 = 当前目录（与旧 WM_DROPFILES 约定一致） */
        handle_drop_files((HDROP)stm.hGlobal);
    }
    if (stm.pUnkForRelease) stm.pUnkForRelease->lpVtbl->Release(stm.pUnkForRelease);
    else ReleaseStgMedium(&stm);
    (void)ptl;
}
static HRESULT STDMETHODCALLTYPE dtgt_Drop(IDropTarget *This, IDataObject *pdo,
                                           DWORD keys, POINTL ptl, DWORD *effect)
{
    (void)This; (void)keys;
    POINT pt = { ptl.x, ptl.y };
    if (!drop_is_own_drag(pdo)) {
        /* 外部拖入：复制到当前目录（原 WM_DROPFILES 语义） */
        drop_external_hdrop(pdo, ptl);
        *effect = DROPEFFECT_COPY;
        return S_OK;
    }
    if (!s_treeDragPath) {
        *effect = DROPEFFECT_NONE;
        return S_OK;
    }
    /* 松手落点：树节点目录 > 当前浏览目录 */
    wchar_t dst[FF_PATH_MAX];
    if (!tree_drag_hit_target(pt, dst, FF_PATH_MAX)) {
        *effect = DROPEFFECT_NONE;
        return S_OK;
    }
    *effect = DROPEFFECT_COPY;
    /* ★不在这里弹确认菜单：Drop 处于 OLE 拖放循环内部，TrackPopupMenu 的
     * 模态泵会把鼠标事件重放回循环导致 Drop 重入 —— 同一次松手执行两遍
     * （移动成功后又对原路径"找不到对象"，用户实测）。
     * 存上下文 + PostMessage，等 DoDragDrop 返回、主窗口消息循环里再弹。 */
    ff_str_copy(s_pendingDropSrc, FF_PATH_MAX, s_treeDragPath);
    ff_str_copy(s_pendingDropDst, FF_PATH_MAX, dst);
    s_pendingDropPt = pt;
    free(s_treeDragPath);
    s_treeDragPath = NULL;
    s_treeDropHandled = true;
    PostMessageW(g_app.main, WM_FF_TREE_CONFIRM, 0, 0);
    *effect = DROPEFFECT_COPY;
    return S_OK;
}
static IDropTargetVtbl dtgt_vtbl = {
    dtgt_QueryInterface, dtgt_AddRef, dtgt_Release,
    dtgt_DragEnter, dtgt_DragOver, dtgt_DragLeave, dtgt_Drop
};
static IDropTarget s_dropTarget = { &dtgt_vtbl };

/* 树/列表/主窗口挂上拖放目标（子窗口创建完成后由 main.c 调一次）。
 * 树拖动悬停时显示 复制/移动 光标，松手在 Drop 里弹确认菜单。
 * ★主窗口也必须注册：否则树拖动松手在树上时，我们的 IDropTarget 执行了
 * 移动，而 OLE 对【只 DragAcceptFiles、没有 IDropTarget 的主窗口】又会
 * 自动生成 HDROP 投第二份 WM_DROPFILES —— 同一次松手"移动一次+复制一次"，
 * 文件已移走时就弹"找不到对象"（用户实测）。注册后 OLE 统一走一个目标，
 * 不再触发 DragAcceptFiles 那条消息级通道；外部拖入仍走各窗口的
 * WM_DROPFILES（子窗口没注册 IDropTarget 的只有主窗口——它的
 * dtgt_Drop 里 drop_is_own_drag=false 直接 NONE，外部 HDROP 拖入靠
 * 【子窗口的 DragAcceptFiles】照常工作）。 */
void ff_register_droptarget(void)
{
    if (g_app.tree && SUCCEEDED(RegisterDragDrop(g_app.tree, &s_dropTarget)))
        DBG(L"droptarget: tree registered");
    if (g_app.list && SUCCEEDED(RegisterDragDrop(g_app.list, &s_dropTarget)))
        DBG(L"droptarget: list registered");
    /* 主窗口暂不注册(排查全黑) */

}

/* 一批完整路径 → Shell 数据对象（真实 PIDL → IShellItemArray → BHID_DataObject）。
 * 拖出和"打开方式"都用它：拿到的对象和资源管理器自己用的完全一样。 */
/* 给本程序拖出的数据对象盖"自家出产"标记（自定义格式存一个魔数 DWORD）。
 * 树/列表的 IDropTarget 用它区分"自己拖给自己"（弹确认菜单）与外部拖入。
 * shell 的 CF_HDROP 数据对象支持 SetData 追加私有格式。 */
static void mark_own_drag(IDataObject *pdo)
{
    if (!s_cfDragSrc)
        s_cfDragSrc = RegisterClipboardFormatW(L"FileCE.DragSource");
    if (!s_cfDragSrc) return;
    HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, sizeof(DWORD));
    if (!h) return;
    DWORD *v = (DWORD *)GlobalLock(h);
    if (v) *v = FF_DRAGSRC_MAGIC;
    GlobalUnlock(h);
    FORMATETC fe;
    ZeroMemory(&fe, sizeof(fe));
    fe.cfFormat = (CLIPFORMAT)s_cfDragSrc;
    fe.dwAspect = DVASPECT_CONTENT;
    fe.lindex = -1;
    fe.tymed = TYMED_HGLOBAL;
    STGMEDIUM stm;
    ZeroMemory(&stm, sizeof(stm));
    stm.tymed = TYMED_HGLOBAL;
    stm.hGlobal = h;
    if (FAILED(pdo->lpVtbl->SetData(pdo, &fe, &stm, TRUE)))   /* TRUE=对象接管释放 */
        GlobalFree(h);
}

static IDataObject *shell_data_object(const wchar_t **paths, int n)
{
    if (n <= 0) return NULL;

    /* 逐项建 PIDL：搜索结果可能来自不同目录。 */
    PIDLIST_ABSOLUTE *pidls = (PIDLIST_ABSOLUTE *)calloc((size_t)n, sizeof(PIDLIST_ABSOLUTE));
    if (!pidls) return NULL;
    int got = 0;
    for (int i = 0; i < n; ++i) {
        if (SHParseDisplayName(paths[i], NULL, &pidls[got], 0, NULL) == S_OK && pidls[got])
            ++got;
    }

    IDataObject *pdo = NULL;
    if (got > 0) {
        IShellItemArray *arr = NULL;
        if (SUCCEEDED(SHCreateShellItemArrayFromIDLists((UINT)got,
                (PCIDLIST_ABSOLUTE_ARRAY)pidls, &arr)) && arr) {
            arr->lpVtbl->BindToHandler(arr, NULL, &BHID_DataObject,
                                       &IID_IDataObject, (void **)&pdo);
            arr->lpVtbl->Release(arr);
        }
    }
    for (int i = 0; i < got; ++i) ILFree(pidls[i]);
    free(pidls);
    if (pdo) mark_own_drag(pdo);
    return pdo;
}

/* 左键拖出选中的文件（LVN_BEGINDRAG 转发而来；阻塞到松开鼠标为止） */
static void drag_out_selected(void)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    DBG(L"DRAGOUT begin n=%d", n);
    if (n <= 0) { ff_free_paths(paths, n); return; }

    IDataObject *pdo = shell_data_object((const wchar_t **)paths, n);
    DBG(L"DRAGOUT pdo=%p", (void *)pdo);
    if (!pdo) { ff_free_paths(paths, n); return; }

    DWORD effect = 0;
    HRESULT dhr = DoDragDrop(pdo, &s_dragSrc,
                             DROPEFFECT_COPY | DROPEFFECT_MOVE | DROPEFFECT_LINK, &effect);
    (void)dhr;                       /* 仅 FFDBG 日志使用 */
    DBG(L"DRAGOUT hr=0x%08lX effect=%lu", (unsigned long)dhr, (unsigned long)effect);
    pdo->lpVtbl->Release(pdo);

    /* 拖到回收站=删除、拖到 U 盘/其它盘=移动——目标程序不会通知我们，
     * 列表会一直显示旧条目，非得手动 F5 才对。这里主动核对源文件还在不在：
     * 少了一个就立刻刷新（普通复制一个不少，不会白刷）。 */
    bool gone = false;
    for (int i = 0; i < n; ++i) {
        if (GetFileAttributesW(paths[i]) == INVALID_FILE_ATTRIBUTES) { gone = true; break; }
    }
    ff_free_paths(paths, n);
    if (gone) {
        DBG(L"DRAGOUT source gone -> refresh");
        ff_refresh(true);
        ff_update_ui_state();
    }
}

/* ---------------- 目录树的右键菜单 + 树内拖动 ---------------- */

static HMENU build_menu(bool context);          /* 定义在后面 */
static void popup_menu(HMENU m, POINT pt);
static void request_shell_menu(void);           /* 弹出 Windows 系统右键菜单 */
static void do_command(int cmd);

/* 树节点右键：与列表右键同一套菜单（打开/复制/剪切/粘贴/删除/重命名/属性…），
 * 但作用对象是节点目录本身；粘贴/新建文件夹落在该目录下。
 * TVN_SELCHANGED 先于 NM_RCLICK 完成选中导航，所以此刻 t->dir 已是节点目录；
 * 再把 s_treeMenuSel 置成节点路径，"复制/剪切/删除/重命名/属性"就不会因
 * 列表没有选中项而全部置灰（用户实测："树右键里复制是灰的"）。
 * ★清除必须延后：菜单命令是 TrackPopupMenu 返回【之后】才被处理的（与
 * "打开方式"的 IAssocHandler 生命周期同款坑），当场清掉命令就拿到空选中集
 * —— 用户实测"树右键复制点了没反应"。改投 WM_FF_TREE_MENU_END 排队清除。 */
static void tree_context_menu(POINT pt)
{
    FfTab *t = cur_tab();
    if (t->dir[0])
        ff_str_copy(s_treeMenuSel, FF_PATH_MAX, t->dir);

    if (GetKeyState(VK_CONTROL) < 0) {
        /* Ctrl+右键：本程序自己那份菜单（老习惯 + shell 菜单万一出问题时的退路） */
        HMENU m = build_menu(true);
        popup_menu(m, pt);
    } else {
        /* 普通右键：直接就是 Windows 那份菜单（本程序补的项已经插在里面） */
        request_shell_menu();
    }
    PostMessageW(g_app.main, WM_FF_TREE_MENU_END, 0, 0);
}

/* 树节点拖动落手后的确认菜单：复制 / 移动 / 取消。
 * ★菜单不能在 IDropTarget::Drop 里直接弹：Drop 处于 OLE 拖放循环内部，
 * TrackPopupMenu 的模态泵会把鼠标 up/down 重放回循环，OLE 判定第二次 Drop
 * —— 同一次松手执行两遍（移动成功后又对原路径"找不到对象"，用户实测）。
 * 标准做法：Drop 只把上下文存进 s_pendingDrop 并 PostMessage(WM_FF_TREE_CONFIRM)，
 * 等主窗口消息循环（DoDragDrop 已返回）再弹菜单执行。 */
#define TREEOP_COPY   1
#define TREEOP_MOVE   2
#define TREEOP_CANCEL 0
static void tree_drop_confirm(const wchar_t *src, const wchar_t *dstDir, POINT pt)
{
    s_treeDropHandled = true;
    /* 拖到自己下面：不动 */
    if (_wcsicmp(src, dstDir) == 0) return;
    /* 拖进自己的子目录：拒绝（会造成循环移动） */
    size_t sl = wcslen(src);
    if (_wcsnicmp(src, dstDir, sl) == 0 && (dstDir[sl] == L'\\' || dstDir[sl] == 0)) {
        ff_msg_error(g_app.main, L"不能把目录移动到它自己的子目录里。");
        return;
    }

    HMENU m = CreatePopupMenu();
    AppendMenuW(m, MF_STRING, TREEOP_COPY,   L"复制到此处(&C)");
    AppendMenuW(m, MF_STRING, TREEOP_MOVE,   L"移动到此处(&M)");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING, TREEOP_CANCEL, L"取消(&O)");
    SetForegroundWindow(g_app.main);
    int cmd = TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_LEFTALIGN | TPM_RETURNCMD | TPM_NONOTIFY,
                             pt.x, pt.y, 0, g_app.main, NULL);
    PostMessageW(g_app.main, WM_NULL, 0, 0);
    DestroyMenu(m);
    DBG(L"TREECONFIRM cmd=%d src=%ls dst=%ls", cmd, src, dstDir);
    if (cmd != TREEOP_COPY && cmd != TREEOP_MOVE) return;   /* 取消 / 点外面 */

    wchar_t err[512] = L"";
    const wchar_t *one = src;
    bool r = fs_copy_move(g_app.main, &one, 1, dstDir, cmd == TREEOP_MOVE, err, 512);
    if (!r && err[0]) ff_msg_error(g_app.main, L"%s", err);
    /* 刷新列表 + 重建目录树并重新定位。两处坑:
     * 1) 拖走的是当前浏览目录本身(或其祖先)时,目录已消失,
     *    ff_refresh 里 fs_list_dir 失败会提前 return —— 树完全不重建,
     *    "目录下面的第一个目录"移动后不刷新正是这个路径(用户实测):
     *    浏览 projA 时把 projA 拖走。此时改导航到目标目录再刷新。
     * 2) 树重建后全折叠,reveal 源父 + 目标让两处都可见。 */
    {
        FfTab *t = cur_tab();
        if (t->dir[0] && GetFileAttributesW(t->dir) == INVALID_FILE_ATTRIBUTES)
            ff_navigate(dstDir, true);
    }
    ff_refresh(true);
    {
        wchar_t srcParent[FF_PATH_MAX];
        ff_str_copy(srcParent, FF_PATH_MAX, src);
        wchar_t *sl2 = wcsrchr(srcParent, L'\\');
        if (sl2 && sl2 >= srcParent + 2) *sl2 = 0;
        ff_tree_reveal(g_app.tree, srcParent);
        ff_tree_reveal(g_app.tree, dstDir);
    }
    ff_tree_select_path(g_app.tree, cur_tab()->dir);
    ff_update_ui_state();
}

/* 被拖动节点的路径。DoDragDrop 阻塞期间拖放目标（本程序）会在同线程重入，
 * 用完立即清空；堆上拷贝，防止树在拖动期间重建悬空指针。 */
/* 松手时命中的落点目录：树节点目录 / 树空白=当前浏览目录 / 列表=当前目录。
 * 找不到（此电脑根、命中折叠按钮、主窗口外）返回 false。 */
static bool tree_drag_hit_target(POINT pt, wchar_t *out, size_t cch)
{
    /* 1) 命中树节点？ */
    FfTreeData td;
    if (g_app.tree && ff_tree_hit_path(g_app.tree, pt, &td)) {
        if (td.kind != 5 && td.path[0]) { ff_str_copy(out, cch, td.path); return true; }
        return false;                                     /* 此电脑根没有实体路径 */
    }
    /* 2) 树窗口内但没节点（空白处）：落点 = 当前浏览目录 */
    RECT tr;
    if (g_app.tree && GetClientRect(g_app.tree, &tr)) {
        POINT tp = pt;
        ScreenToClient(g_app.tree, &tp);
        if (PtInRect(&tr, tp)) {
            FfTab *t = cur_tab();
            if (t->dir[0]) { ff_str_copy(out, cch, t->dir); return true; }
            return false;
        }
    }
    /* 3) 命中列表？落点 = 当前浏览目录 */
    RECT lr;
    if (g_app.list && GetClientRect(g_app.list, &lr)) {
        POINT lp2 = pt;
        ScreenToClient(g_app.list, &lp2);
        if (PtInRect(&lr, lp2)) {
            FfTab *t = cur_tab();
            if (t->dir[0]) { ff_str_copy(out, cch, t->dir); return true; }
            return false;
        }
    }
    return false;
}

/* 树节点左键拖动（TVN_BEGINDRAG 转发而来）。拖到别的程序 = 交给 shell；
 * 悬停在本程序自己的树/列表上 = 已注册的 IDropTarget 给出 复制/移动 光标
 * （不再出现"禁止"符），松手在其 Drop 里弹"复制/移动/取消"菜单执行。
 * 阻塞到松开鼠标为止（与 drag_out_selected 相同）。 */
static void tree_drag_out(const wchar_t *path)
{
    DBG(L"TREEDRAG begin path=[%ls]", path ? path : L"(null)");
    if (!path || !path[0]) return;
    IDataObject *pdo = shell_data_object((const wchar_t **)&path, 1);
    DBG(L"TREEDRAG pdo=%p", (void *)pdo);
    if (!pdo) return;

    free(s_treeDragPath);
    s_treeDragPath = _wcsdup(path);
    s_treeDropHandled = false;      /* 每次拖动一轮：Drop 处理过就不再走兜底 */
    DWORD effect = 0;
    HRESULT hr = DoDragDrop(pdo, &s_dragSrc, DROPEFFECT_COPY | DROPEFFECT_MOVE, &effect);
    pdo->lpVtbl->Release(pdo);
    DBG(L"TREEDRAG hr=0x%08lX effect=%lu", (unsigned long)hr, (unsigned long)effect);

    /* 松手没落在已注册的树/列表上（本程序空白处/窗口外但没被别的程序接受）
     * —— 兜底命中测试，能找到落点目录仍弹确认菜单（同样走 PostMessage 延后）。
     * ★IDropTarget::Drop 已经取走 s_treeDragPath（=NULL）时绝不再来：
     *   那时目录已经换位，二次确认会对着已移走的旧路径执行复制/移动 ——
     *   表现为复制出第二份、或弹"找不到对象"（用户实测）。 */
    if (!s_treeDropHandled && s_treeDragPath &&
        (hr == DRAGDROP_S_CANCEL || effect == 0)) {
        POINT pt;
        GetCursorPos(&pt);
        wchar_t dst[FF_PATH_MAX];
        if (tree_drag_hit_target(pt, dst, FF_PATH_MAX)) {
            ff_str_copy(s_pendingDropSrc, FF_PATH_MAX, s_treeDragPath);
            ff_str_copy(s_pendingDropDst, FF_PATH_MAX, dst);
            s_pendingDropPt = pt;
            PostMessageW(g_app.main, WM_FF_TREE_CONFIRM, 0, 0);
        }
    }
    free(s_treeDragPath);
    s_treeDragPath = NULL;
    /* 落在别处（回收站/别的程序）：源目录若没了（被移动），刷新一次。
     * ★注意这行要在 WM_FF_TREE_CONFIRM 处理【之前】的状态下跑 —— confirm
     * 是 PostMessage 排队的，源还在时这里的 GetFileAttributes 判断的是
     * 【移动前的旧状态】；confirm 执行移动后自己会刷新。 */
    if (GetFileAttributesW(path) == INVALID_FILE_ATTRIBUTES) {
        ff_refresh(true);
        ff_update_ui_state();
    }
}

/* 取完整路径的父目录："D:\a\b.txt"→"D:\a"；"C:\x.txt"→"C:\"；
 * "\\srv\share\f"→"\\srv\share"；本身就是盘根时原样返回 */
static void parent_dir_of(const wchar_t *path, wchar_t *out, size_t cch)
{
    ff_str_copy(out, cch, path);
    wchar_t *slash = wcsrchr(out, L'\\');
    if (slash && slash >= out + 2) {
        if (slash == out + 2 && out[1] == L':') out[3] = 0;   /* C:\x → C:\ */
        else *slash = 0;
    }
}

/* 规范化成磁盘上的长路径形式。shell 投递的 CF_HDROP 一律是长路径（PIDL 用
 * 磁盘上的真实名字），而 t->dir 可能还是启动参数里的 8.3 短形式（ADMINI~1），
 * 直接按字符串比会漏判"拖到当前目录"，把文件复制成 "xxx (2)"。 */
static void canon_path(const wchar_t *in, wchar_t *out, size_t cch)
{
    DWORD n = GetLongPathNameW(in, out, (DWORD)cch);
    if (n == 0 || n >= cch) ff_str_copy(out, cch, in);
}

/* 拖放落地（本程序拖给自己时也会走到这里）：按上面的约定处理。
 * 落点优先级：命中树节点 > 当前浏览目录（WM_DROPFILES 不带坐标，
 * 用当前光标位置对树做命中测试）。 */
static void handle_drop_files(HDROP hd)
{
    FfTab *t = cur_tab();
    UINT n = DragQueryFileW(hd, 0xFFFFFFFF, NULL, 0);
    DBG(L"DROPFILES n=%u dest=%ls", (unsigned)n, t->dir);
    wchar_t first[FF_PATH_MAX];
    bool haveFirst = n > 0 && DragQueryFileW(hd, 0, first, FF_PATH_MAX);
    if (!haveFirst) { DragFinish(hd); return; }

    /* 落点：光标处命中树节点 = 拖到那个目录；否则 = 当前浏览目录 */
    wchar_t destDir[FF_PATH_MAX];
    POINT dp;
    GetCursorPos(&dp);
    FfTreeData td;
    if (g_app.tree && ff_tree_hit_path(g_app.tree, dp, &td) && td.kind != 5 && td.path[0])
        ff_str_copy(destDir, FF_PATH_MAX, td.path);
    else
        ff_str_copy(destDir, FF_PATH_MAX, t->dir);

    /* 落到列表里的某个 .zip 上 → 记下它，稍后把拖进来的文件写进压缩包
     * （没有同名就加、有同名就替换、全程不弹框）。 */
    wchar_t zipTarget[FF_PATH_MAX];
    zipTarget[0] = 0;
    if (g_app.list) {
        POINT cp = dp;
        ScreenToClient(g_app.list, &cp);
        LVHITTESTINFO ht;
        ZeroMemory(&ht, sizeof(ht));
        ht.pt = cp;
        int row = (int)SendMessageW(g_app.list, LVM_HITTEST, 0, (LPARAM)&ht);
        if (row >= 0) {
            const FfEntry *ent = ff_list_row_entry(g_app.list, row);
            if (ent && ent->name[0] && !(ent->attrs & FILE_ATTRIBUTE_DIRECTORY)) {
                const wchar_t *ext = wcsrchr(ent->name, L'.');
                if (ext) {
                    static const wchar_t *kArc[] = {
                        L".zip", L".rar", L".7z", L".tar", L".gz", L".tgz", L".cab"
                    };
                    for (size_t k = 0; k < sizeof(kArc) / sizeof(kArc[0]); ++k) {
                        if (_wcsicmp(ext, kArc[k]) == 0) {
                            ff_path_join(zipTarget, FF_PATH_MAX, t->dir, ent->name);
                            break;
                        }
                    }
                }
            }
        }
    }

    /* 没有实体落点目录（此电脑/搜索 + 没命中树节点）→ 进入文件所在目录 */
    if (!destDir[0]) {
        if (PathIsDirectoryW(first)) ff_navigate(first, true);
        else {
            wchar_t dir[FF_PATH_MAX];
            parent_dir_of(first, dir, FF_PATH_MAX);
            ff_navigate(dir, true);
        }
        DragFinish(hd);
        return;
    }

    /* 把拖进来的文件复制到落点目录。
     * 走与"粘贴"同一条 fs_copy_move：进度对话框、重名自动改名、失败提示全部一致。 */
    wchar_t curCanon[FF_PATH_MAX];
    canon_path(destDir, curCanon, FF_PATH_MAX);  /* 与 shell 投递的路径同形后再比 */
    wchar_t **paths = (wchar_t **)calloc((size_t)n, sizeof(wchar_t *));
    int m = 0;
    if (paths) {
        for (UINT i = 0; i < n; ++i) {
            wchar_t *p = (wchar_t *)calloc(FF_PATH_MAX, sizeof(wchar_t));
            if (!p) continue;
            if (!DragQueryFileW(hd, i, p, FF_PATH_MAX)) { free(p); continue; }
            wchar_t dir[FF_PATH_MAX], dirCanon[FF_PATH_MAX];
            parent_dir_of(p, dir, FF_PATH_MAX);
            canon_path(dir, dirCanon, FF_PATH_MAX);
            /* 拖到压缩包上时，源正好在当前目录是常态（拖的就是眼前的文件），不能跳过 */
            if (!zipTarget[0] && _wcsicmp(dirCanon, curCanon) == 0) { free(p); continue; }
            paths[m++] = p;
        }
    }
    DragFinish(hd);

    if (m > 0 && zipTarget[0]) {
        /* 拖进压缩包：自己读写 ZIP（系统的 SHFileOperation / IFileOperation
         * 在本程序里会卡死，详见 zipw.c 顶部注释）。同名直接替换、不弹框。 */
        wchar_t zerr[512] = L"";
        bool r = ff_archive_insert(zipTarget, (const wchar_t **)paths, m, zerr, 512);
        DBG(L"DROPFILES -> zip [%ls] m=%d r=%d err=%ls", zipTarget, m, (int)r, zerr);
        if (!r && zerr[0]) ff_msg_error(g_app.main, L"%s", zerr);
        ff_refresh(true);
        ff_update_ui_state();
        ff_free_paths(paths, m);
        return;
    }
    if (m > 0) {
        wchar_t err[512] = L"";
        bool r = fs_copy_move(g_app.main, (const wchar_t **)paths, m, destDir, false, err, 512);
        DBG(L"DROPFILES copy m=%d r=%d err=%ls", m, (int)r, err);
        if (!r && err[0]) ff_msg_error(g_app.main, L"%s", err);
        ff_refresh(true);
        ff_update_ui_state();
    }
    DBG(L"DROPFILES done m=%d", m);
    ff_free_paths(paths, m);
}

/* ===================================================== 标签 */
static void tab_select(int idx)
{
    if (idx < 0 || idx >= s_tabCount || idx == s_active) return;
    s_active = idx;
    FfTab *t = cur_tab();
    ff_tabs_update(g_app.tabs, s_tabCount, s_active);
    ff_list_apply_view(g_app.list, t->viewMode);
    build_order(t);
    refresh_list();
    update_title();
    set_address_text(t->dir);
    ff_tree_select_path(g_app.tree, t->dir);
    ff_update_ui_state();
}

static void tab_new(const wchar_t *dir)
{
    if (s_tabCount >= MAX_TABS) {
        ff_msg_error(g_app.main, L"标签数量已达上限（%d 个）。", MAX_TABS);
        return;
    }
    int idx = s_tabCount++;
    ZeroMemory(&s_tabs[idx], sizeof(FfTab));
    s_tabs[idx].sortCol = COL_NAME;
    s_tabs[idx].sortAsc = TRUE;
    s_tabs[idx].viewMode = LVS_REPORT;
    s_active = idx;
    ff_tabs_update(g_app.tabs, s_tabCount, s_active);
    ff_navigate(dir ? dir : L"", true);
}

static void tab_close(int idx)
{
    if (idx < 0 || idx >= s_tabCount) return;
    FfTab *t = &s_tabs[idx];
    fs_entry_list_free(&t->raw);
    if (t->order) { free(t->order); t->order = NULL; }
    t->orderCount = 0;
    ff_hist_free(&t->hist);

    if (s_tabCount == 1) {
        ZeroMemory(t, sizeof(FfTab));
        t->sortCol = COL_NAME;
        t->sortAsc = TRUE;
        t->viewMode = LVS_REPORT;
        ff_navigate(L"", true);
        return;
    }
    for (int i = idx; i < s_tabCount - 1; ++i) s_tabs[i] = s_tabs[i + 1];
    s_tabCount--;
    ZeroMemory(&s_tabs[s_tabCount], sizeof(FfTab));

    if (s_active >= s_tabCount) s_active = s_tabCount - 1;
    else if (s_active > idx) s_active--;
    ff_tabs_update(g_app.tabs, s_tabCount, s_active);
    tab_select(s_active == idx ? (idx > 0 ? idx - 1 : 0) : s_active);
    /* tab_select 对相同索引会直接返回，这里强制刷新一次 */
    {
        FfTab *nt = cur_tab();
        ff_list_apply_view(g_app.list, nt->viewMode);
        build_order(nt);
        refresh_list();
        update_title();
        set_address_text(nt->dir);
        ff_tree_select_path(g_app.tree, nt->dir);
        ff_update_ui_state();
    }
}

/* ===================================================== 命令实现 */
static void cmd_open(void)
{
    FfTab *t = cur_tab();
    int rows[MAX_SEL];
    int n = ff_list_selected(g_app.list, rows, MAX_SEL);
    if (n <= 0) {
        /* 无选中时打开焦点项 */
        int f = ListView_GetNextItem(g_app.list, -1, LVNI_FOCUSED);
        if (f >= 0) { rows[0] = f; n = 1; }
    }
    if (n <= 0) return;

    if (n > 1) {
        wchar_t msg[256];
        StringCchPrintfW(msg, 256, L"将同时打开 %d 个对象，是否继续？", n);
        if (!ff_confirm(g_app.main, L"%s", msg)) return;
    }
    for (int i = 0; i < n; ++i) {
        const FfEntry *e = ff_list_row_entry(g_app.list, rows[i]);
        if (!e) continue;

        wchar_t path[FF_PATH_MAX];
        entry_full_path(t, e, path, FF_PATH_MAX);

        if (e->isDir) {
            if (i == 0) ff_navigate(path, true);
        } else {
            if (!fs_open_path(g_app.main, path))
                ff_msg_error(g_app.main, L"无法打开文件：\n%s", path);
        }
    }
    ff_update_ui_state();
}

static void cmd_new_folder(void)
{
    FfTab *t = cur_tab();
    if (!t->dir[0]) return;
    wchar_t name[512] = L"新建文件夹";
    wchar_t path[FF_PATH_MAX];
    ff_path_join(path, FF_PATH_MAX, t->dir, name);
    int k = 2;
    while (fs_path_exists(path)) {
        StringCchPrintfW(name, 512, L"新建文件夹 (%d)", k++);
        ff_path_join(path, FF_PATH_MAX, t->dir, name);
        if (k > 500) break;
    }
    if (!fs_make_dir(path)) {
        ff_msg_error(g_app.main, L"创建文件夹失败，请检查权限或磁盘空间。");
        return;
    }
    ff_refresh(true);
    /* 定位到新目录并进入重命名 */
    for (int i = 0; i < t->orderCount; ++i) {
        const FfEntry *e = ff_list_row_entry(g_app.list, i);
        if (e && _wcsicmp(e->name, name) == 0) {
            ff_list_focus_item(g_app.list, i);
            SetFocus(g_app.list);
            ListView_EditLabel(g_app.list, i);
            break;
        }
    }
}

static void cmd_rename(void)
{
    int rows[MAX_SEL];
    if (ff_list_selected(g_app.list, rows, MAX_SEL) != 1) {
        ff_msg_error(g_app.main, L"请选中一个对象后再重命名。");
        return;
    }
    const FfEntry *e = ff_list_row_entry(g_app.list, rows[0]);
    if (!e) return;

    /* 走自己的输入框而不是列表内联编辑：虚拟列表（LVS_OWNERDATA）上
     * ListView_EditLabel 建立不了真正的编辑会话（详见 dialogs.c 的说明）。 */
    wchar_t newName[260];
    DBG(L"cmd_rename: 准备弹框 old=[%ls]", e->name);
    bool okdlg = ff_dlg_rename(g_app.main, e->name, newName, 260);
    DBG(L"cmd_rename: dlg=%d name=%ls", okdlg ? 1 : 0, newName);
    if (!okdlg) return;
    if (_wcsicmp(newName, e->name) == 0) return;

    /* 复用 WM_FF_RENAME：里面的非法字符校验、fs_rename、撤消记录都现成 */
    SendMessageW(g_app.main, WM_FF_RENAME, 1, (LPARAM)newName);
}

static void cmd_delete(bool hard)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) return;

    wchar_t first[512];
    ff_str_copy(first, 512, ff_path_name(paths[0]));
    const wchar_t *what = (n == 1) ? first : L"这些对象";
    int ok;
    if (hard) {
        ok = ff_confirm(g_app.main,
            L"确定要【永久删除】%s 吗？\n\n此操作不可撤销，不会进入回收站。", what);
    } else {
        ok = ff_confirm(g_app.main, L"确定要把 %s 移入回收站吗？", what);
    }
    if (!ok) { ff_free_paths(paths, n); return; }

    wchar_t err[512] = L"";
    bool r = hard ? fs_delete_permanent(g_app.main, (const wchar_t **)paths, n, err, 512)
                  : fs_delete_to_recycle(g_app.main, (const wchar_t **)paths, n, err, 512);
    /* 记住被删项的父目录:删除后树要展开到这一级,让"没了"看得见
       (ff_free_paths 会释放 paths,父目录先拷出来) */
    wchar_t delParent[FF_PATH_MAX];
    if (n > 0) {
        ff_str_copy(delParent, FF_PATH_MAX, paths[0]);
        wchar_t *sl = wcsrchr(delParent, L'\\');
        if (sl && sl >= delParent + 2) *sl = 0;
    }
    ff_free_paths(paths, n);
    if (!r) { ff_msg_error(g_app.main, L"%s", err[0] ? err : L"删除失败。"); return; }
    /* 树右键删除时,右键选中已把当前浏览目录导航到被删目录本身 ——
     * 目录没了,ff_refresh 里 fs_list_dir 失败会直接 return,树不重建,
     * 被删节点就还挂在树上(用户实测"树右键删除后不刷新")。
     * 先退到还存在的最近祖先再刷新。 */
    {
        FfTab *t = cur_tab();
        if (t->dir[0] && GetFileAttributesW(t->dir) == INVALID_FILE_ATTRIBUTES) {
            wchar_t walk[FF_PATH_MAX];
            ff_str_copy(walk, FF_PATH_MAX, t->dir);
            while (walk[0]) {
                wchar_t *sl2 = wcsrchr(walk, L'\\');
                if (!sl2) break;
                *sl2 = 0;
                if (sl2 >= walk + 2 && GetFileAttributesW(walk) != INVALID_FILE_ATTRIBUTES)
                    break;
            }
            ff_navigate(walk, true);
        }
    }
    ff_refresh(true);
    if (n > 0) ff_tree_reveal(g_app.tree, delParent);
    ff_update_ui_state();
}

static void cmd_paste(void)
{
    FfTab *t = cur_tab();
    if (!t->dir[0]) return;

    wchar_t **src = NULL;
    bool cut = false;
    int n = get_clipboard_files(&src, &cut);
    DBG(L"paste: clipboard n=%d cut=%d dir=[%ls]", n, cut ? 1 : 0, t->dir);
    if (n <= 0) {
        ff_msg_error(g_app.main, L"剪贴板中没有可粘贴的文件。");
        return;
    }
    for (int i = 0; i < n; ++i) DBG(L"paste:   src[%d]=[%ls]", i, src[i]);
    wchar_t err[512] = L"";
    bool r = fs_copy_move(g_app.main, (const wchar_t **)src, n, t->dir, cut, err, 512);
    DBG(L"paste: fs_copy_move -> r=%d err=[%ls]", r ? 1 : 0, err);
    if (!r && err[0]) ff_msg_error(g_app.main, L"%s", err);
    if (r && cut) {
        /* 剪切粘贴成功后清空剪贴板 */
        if (OpenClipboard(g_app.main)) { EmptyClipboard(); CloseClipboard(); }
    }
    ff_free_paths(src, n);
    ff_refresh(true);
    ff_update_ui_state();
}

static void cmd_copy_cut(bool cut)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) return;
    put_clipboard_files((const wchar_t **)paths, n, cut);
    ff_free_paths(paths, n);
    ff_set_status(cut ? L"已剪切到剪贴板" : L"已复制到剪贴板");
    ff_update_ui_state();
}

static void cmd_copy_path(void)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) return;
    static wchar_t *buf;              /* 堆(32KB) */
    if (!buf) buf = (wchar_t *)calloc(16384, sizeof(wchar_t));
    buf[0] = 0;
    for (int i = 0; i < n; ++i) {
        ff_str_cat(buf, 16384, paths[i]);
        if (i + 1 < n) ff_str_cat(buf, 16384, L"\r\n");
    }
    ff_free_paths(paths, n);
    if (OpenClipboard(g_app.main)) {
        EmptyClipboard();
        size_t bytes = (wcslen(buf) + 1) * sizeof(wchar_t);
        HGLOBAL h = GlobalAlloc(GMEM_MOVEABLE, bytes);
        if (h) {
            void *p = GlobalLock(h);
            if (p) { memcpy(p, buf, bytes); GlobalUnlock(h); SetClipboardData(CF_UNICODETEXT, h); }
        }
        CloseClipboard();
    }
    ff_set_status(L"完整路径已复制到剪贴板");
}

static void cmd_properties(void)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) { ff_free_paths(paths, n); return; }
    fs_show_properties_multi(g_app.main, (const wchar_t **)paths, n);
    ff_free_paths(paths, n);
}

/* ===================================================== 打开方式（Win10 风格）
 * Win10 的右键"打开方式"不是直接弹对话框，而是先展开一层子菜单，列出这台
 * 机器上所有能打开该文件的程序（默认程序排最前），最后两项才是
 * "搜索 Microsoft Store" / "选择其他应用…"。
 *
 * 程序清单不去自己翻注册表猜，直接用系统给资源管理器用的那套接口
 * SHAssocEnumHandlers：列表内容、先后顺序、图标、本地化名字都和系统一致。
 * 每个处理程序（IAssocHandler）保留引用到菜单关闭为止 —— 用户选中的那一刻
 * 还要拿它去 Invoke。 */

static IAssocHandler *s_owHandler[OPEN_WITH_MAX];
static HBITMAP        s_owBitmap [OPEN_WITH_MAX];
static wchar_t      (*s_owLabel)[128]        = NULL;  /* 懒分配堆(32+64KB) */
static wchar_t      (*s_owExe)[FF_PATH_MAX]  = NULL;
static int            s_owCount;
static wchar_t        s_owExt[32];          /* 当前文件的扩展名，如 ".txt" */

/* 释放上一轮枚举出来的处理程序与图标位图（在菜单关闭后调用） */
static void open_with_clear(void)
{
    if (!s_owExe) {
        s_owExe   = (wchar_t (*)[FF_PATH_MAX])calloc(OPEN_WITH_MAX, sizeof(*s_owExe));
        s_owLabel = (wchar_t (*)[128])calloc(OPEN_WITH_MAX, sizeof(*s_owLabel));
    }
    for (int i = 0; i < s_owCount; ++i) {
        if (s_owHandler[i]) { s_owHandler[i]->lpVtbl->Release(s_owHandler[i]); s_owHandler[i] = NULL; }
        if (s_owBitmap[i])  { DeleteObject(s_owBitmap[i]); s_owBitmap[i] = NULL; }
        s_owExe[i][0] = 0;
    }
    s_owCount = 0;
}

/* 菜单位图：先用菜单底色打底再画图标，否则 32 位图标的透明区在菜单里是黑块 */
static HBITMAP menu_icon_bmp(HICON ic, int cx, int cy)
{
    if (!ic || cx <= 0 || cy <= 0) return NULL;
    HDC hdc = GetDC(NULL);
    HDC mem = CreateCompatibleDC(hdc);
    HBITMAP bmp = CreateCompatibleBitmap(hdc, cx, cy);
    if (bmp) {
        HGDIOBJ old = SelectObject(mem, bmp);
        RECT rc = { 0, 0, cx, cy };
        FillRect(mem, &rc, GetSysColorBrush(COLOR_MENU));
        DrawIconEx(mem, 0, 0, ic, cx, cy, 0, NULL, DI_NORMAL);
        SelectObject(mem, old);
    }
    DeleteDC(mem);
    ReleaseDC(NULL, hdc);
    return bmp;
}

/* 读字符串值（name 传 NULL = 默认值） */
static bool reg_str(HKEY root, const wchar_t *sub, const wchar_t *name,
                    wchar_t *out, DWORD cch)
{
    out[0] = 0;
    HKEY k;
    if (RegOpenKeyExW(root, sub, 0, KEY_QUERY_VALUE, &k) != ERROR_SUCCESS) return false;
    DWORD type = 0, cb = cch * sizeof(wchar_t);
    LONG r = RegQueryValueExW(k, name, NULL, &type, (BYTE *)out, &cb);
    RegCloseKey(k);
    if (r != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ)) { out[0] = 0; return false; }
    out[cch - 1] = 0;
    return out[0] != 0;
}

/* 展开环境变量；若是 "@xxx.exe,-123" 这种间接字符串，交给系统解出本地化文本
 * （"记事本""写字板"这类名字就藏在这里面） */
static void indirect_expand(wchar_t *s, DWORD cch)
{
    if (!s[0]) return;
    wchar_t tmp[512];
    DWORD n = ExpandEnvironmentStringsW(s, tmp, 512);
    if (n && n <= 512) StringCchCopyW(s, cch, tmp);
    if (s[0] == L'@') {
        wchar_t out[512];
        out[0] = 0;
        if (SUCCEEDED(SHLoadIndirectString(s, out, 512, NULL)) && out[0])
            StringCchCopyW(s, cch, out);
    }
}

/* 从命令行里抠出 exe 完整路径（去引号；无引号时截到 .exe 或第一个空格） */
static void cmd_to_exe(const wchar_t *cmd, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!cmd) return;
    while (*cmd == L' ' || *cmd == L'\t') ++cmd;
    if (*cmd == L'"') {
        ++cmd;
        const wchar_t *e = wcschr(cmd, L'"');
        size_t n = e ? (size_t)(e - cmd) : wcslen(cmd);
        if (n >= cch) n = cch - 1;
        memcpy(out, cmd, n * sizeof(wchar_t));
        out[n] = 0;
        return;
    }
    const wchar_t *e = cmd;
    while (*e && *e != L' ') {
        if (e[0] == L'.' &&
            (e[1] == L'e' || e[1] == L'E') &&
            (e[2] == L'x' || e[2] == L'X') &&
            (e[3] == L'e' || e[3] == L'E')) { e += 4; break; }
        ++e;
    }
    size_t n = (size_t)(e - cmd);
    if (n >= cch) n = cch - 1;
    memcpy(out, cmd, n * sizeof(wchar_t));
    out[n] = 0;
}

/* 在扩展名的候选 progID 里找"open 命令就是拿这个 exe 打开"的那个，
 * 取它的友好名 —— 老式程序（记事本、写字板）只有这条路能拿到中文名。 */
static bool progid_name_for(const wchar_t *ext, const wchar_t *exe,
                            wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!ext[0] || !exe[0]) return false;

    wchar_t sub[640], val[512], cmd[512], pexe[FF_PATH_MAX];
    const wchar_t *srcFmt[3] = {
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\%s\\OpenWithProgids",
        L"%s\\OpenWithProgids",
        NULL                                    /* HKCR\<ext> 的默认值 = 默认 progID */
    };
    const HKEY srcRoot[3] = { HKEY_CURRENT_USER, HKEY_CLASSES_ROOT, HKEY_CLASSES_ROOT };

    for (int s = 0; s < 3; ++s) {
        HKEY root = srcRoot[s];
        wchar_t progIDs[8][64];
        int np = 0;

        if (srcFmt[s]) {
            StringCchPrintfW(sub, 640, srcFmt[s], ext);
            HKEY k;
            if (RegOpenKeyExW(root, sub, 0, KEY_QUERY_VALUE, &k) != ERROR_SUCCESS) continue;
            for (DWORD i = 0; np < 8; ++i) {
                wchar_t name[64]; DWORD nlen = 64;
                if (RegEnumValueW(k, i, name, &nlen, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
                StringCchCopyW(progIDs[np++], 64, name);
            }
            RegCloseKey(k);
        } else {
            if (reg_str(HKEY_CLASSES_ROOT, ext, NULL, progIDs[0], 64)) np = 1;
        }

        for (int i = 0; i < np; ++i) {
            StringCchPrintfW(sub, 640, L"%s\\shell\\open\\command", progIDs[i]);
            if (!reg_str(HKEY_CLASSES_ROOT, sub, NULL, cmd, 512)) continue;
            cmd_to_exe(cmd, pexe, FF_PATH_MAX);
            if (!pexe[0] || _wcsicmp(PathFindFileNameW(pexe), PathFindFileNameW(exe)) != 0)
                continue;
            /* 命中：progID 的 FriendlyTypeName 优先（通常是 @exe,-id，本地化） */
            StringCchPrintfW(sub, 640, L"%s", progIDs[i]);
            if (reg_str(HKEY_CLASSES_ROOT, sub, L"FriendlyTypeName", val, 512)) {
                indirect_expand(val, 512);
                if (val[0]) { StringCchCopyW(out, cch, val); return true; }
            }
            if (reg_str(HKEY_CLASSES_ROOT, sub, L"FriendlyAppName", val, 512)) {
                indirect_expand(val, 512);
                if (val[0]) { StringCchCopyW(out, cch, val); return true; }
            }
            if (reg_str(HKEY_CLASSES_ROOT, sub, NULL, val, 512)) {
                indirect_expand(val, 512);
                if (val[0]) { StringCchCopyW(out, cch, val); return true; }
            }
        }
    }
    return false;
}

/* 处理程序的显示名：优先系统给的 UIName，其次注册表里的友好名，
 * 最差也得有个能认的 exe 名，绝不能是空白菜单项 */
static void handler_label(IAssocHandler *h, const wchar_t *ext,
                          wchar_t *out, size_t cch)
{
    out[0] = 0;

    LPWSTR ui = NULL;
    if (SUCCEEDED(h->lpVtbl->GetUIName(h, &ui)) && ui && ui[0])
        StringCchCopyW(out, cch, ui);
    if (ui) CoTaskMemFree(ui);

    LPWSTR nm = NULL;
    wchar_t exe[FF_PATH_MAX];
    exe[0] = 0;
    if (SUCCEEDED(h->lpVtbl->GetName(h, &nm)) && nm) {
        StringCchCopyW(exe, FF_PATH_MAX, nm);
        CoTaskMemFree(nm);
    }
    if (out[0] || !exe[0]) goto done;

    wchar_t sub[640], val[512];
    StringCchPrintfW(sub, 640, L"Applications\\%s", PathFindFileNameW(exe));

    if (reg_str(HKEY_CLASSES_ROOT, sub, L"FriendlyAppName", val, 512)) {
        indirect_expand(val, 512);
        if (val[0]) StringCchCopyW(out, cch, val);
    }
    if (!out[0] && reg_str(HKEY_CLASSES_ROOT, sub, NULL, val, 512)) {
        indirect_expand(val, 512);
        if (val[0]) StringCchCopyW(out, cch, val);
    }
    if (!out[0]) {
        DWORD c = 512;
        val[0] = 0;
        if (SUCCEEDED(AssocQueryStringW(ASSOCF_INIT_BYEXENAME, ASSOCSTR_FRIENDLYAPPNAME,
                                        exe, NULL, val, &c)) && val[0])
            StringCchCopyW(out, cch, val);
    }
    if (!out[0]) progid_name_for(ext, exe, out, cch);
    if (!out[0]) {
        StringCchCopyW(out, cch, PathFindFileNameW(exe));
        wchar_t *dot = wcsrchr(out, L'.');
        if (dot && dot != out) *dot = 0;
    }

done:
    if (!out[0]) StringCchCopyW(out, cch, L"(未命名程序)");
}

/* 打开方式相关的小工具 -------------------------------------------------
 *
 * SHAssocEnumHandlers 只认"正式注册过的程序"。而用户实际勾选过的程序
 * 可能压根没注册：绿色版 Notepad3 之类只解压不安装，Explorer 那边只在
 * FileExts\<ext>\OpenWithList 里留了个文件名条目（还是裸的"notepad3.exe"，
 * 没有路径），注册表里找不到 Applications\notepad3.exe、也��在
 * OpenWithProgids 里，于是系统枚举出来一个都没有，列表就永远看不到它。
 * 所以候选来源要自己补三处。 */

/* 本程序私有的"某扩展名最近用过哪些程序"列表。
 * 存完整路径而不是文件名 —— 只有文件名的话，路径丢了就再也点不开。 */
void ff_open_with_remember(const wchar_t *ext, const wchar_t *exe)
{
    if (!ext || !ext[0] || !exe || !exe[0]) return;

    wchar_t sub[256];
    StringCchPrintfW(sub, 256, L"Software\\FileCE\\OpenWith\\%s", ext);
    HKEY k = NULL;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, sub, 0, NULL, 0,
                        KEY_QUERY_VALUE | KEY_SET_VALUE, NULL, &k, NULL)
        != ERROR_SUCCESS) return;

    /* 把已经在列表里的挪走，再从头插 —— 免得同一个程序出现两次。
     * cb 每次循环都要重算：RegQueryValueExW 的 cb 是 in/out 参数，
     * 复用同一个 cb 会越读越短，最后只剩首字符，后面几个槽位全丢。 */
    int np = 0;
    wchar_t(*names)[FF_PATH_MAX] = calloc(8, sizeof(wchar_t) * FF_PATH_MAX);
    if (names) {
        for (int i = 0; i < 8; ++i) {
            wchar_t slot[8];
            StringCchPrintfW(slot, 8, L"%c", L'a' + i);
            DWORD cb = FF_PATH_MAX * sizeof(wchar_t);   /* 每轮重新给足 */
            if (RegQueryValueExW(k, slot, NULL, NULL, (BYTE *)names[np], &cb)
                    != ERROR_SUCCESS || !names[np][0]) break;
            if (_wcsicmp(names[np], exe) != 0) ++np;
        }
        for (int i = np; i > 0; --i) {
            wchar_t slot[8];
            StringCchPrintfW(slot, 8, L"%c", L'a' + i);
            RegSetValueExW(k, slot, 0, REG_SZ, (const BYTE *)names[i - 1],
                           (DWORD)((wcslen(names[i - 1]) + 1) * sizeof(wchar_t)));
        }
    }
    RegSetValueExW(k, L"a", 0, REG_SZ, (const BYTE *)exe,
                   (DWORD)((wcslen(exe) + 1) * sizeof(wchar_t)));
    free(names);
    /* MRUList 就是槽位名按使用顺序拼起来：新的在a，老的依次后移 */
    wchar_t mru[16];
    mru[0] = 0;
    for (int i = 0; i < np && i < 7; ++i) {
        wchar_t one[8];
        StringCchPrintfW(one, 8, L"%c", L'b' + i);
        StringCchCatW(mru, 16, one);
    }
    RegSetValueExW(k, L"MRUList", 0, REG_SZ, (const BYTE *)mru,
                   (DWORD)((wcslen(mru) + 1) * sizeof(wchar_t)));
    RegCloseKey(k);
}

/* 这个程序和扩展名"门当户对"吗？Explorer 的 FileExts\<ext>\OpenWithList
 * 会把用户曾拿任何程序打开过该扩展名的记录全存下来（拿画图开过 txt、
 * 拿记事本开过 jpg 都记），照单全收列表里就全是风马牛不相及的程序。
 * 规则：HKCR\Applications\<exe>\SupportedTypes 存在时，只有声明支持
 * 该扩展名的才算数（画图只报图片、WMP 只报媒体，txt 里就该踢掉）；
 * 键不存在（绿色版程序多半没写，记事本/写字板/Everything 都没有）
 * 视为无法判断，照收 —— 不能因此又把 Notepad3 挡回门外。 */
static bool ow_relevant(const wchar_t *ext, const wchar_t *exe)
{
    const wchar_t *fn = wcsrchr(exe, L'\\');
    fn = fn ? fn + 1 : exe;
    if (!fn[0] || !ext || !ext[0]) return true;
    wchar_t sub[512];
    StringCchPrintfW(sub, 512, L"Applications\\%s\\SupportedTypes", fn);
    HKEY k = NULL;
    if (RegOpenKeyExW(HKEY_CLASSES_ROOT, sub, 0, KEY_QUERY_VALUE, &k)
            != ERROR_SUCCESS)
        return true;                         /* 没有声明 → 不设卡 */
    bool ok = false;
    for (DWORD i = 0; i < 128 && !ok; ++i) {
        wchar_t nm[64]; DWORD nl = 64;
        if (RegEnumValueW(k, i, nm, &nl, NULL, NULL, NULL, NULL)
                != ERROR_SUCCESS) break;
        if (_wcsicmp(nm, ext) == 0) ok = true;
    }
    /* 老版本把扩展名写成 SupportedTypes 的子键而不是值（Windows 自己的
     * 惯例是值），子键也得认，否则老用户注册过的程序会被误杀。 */
    for (DWORD i = 0; i < 128 && !ok; ++i) {
        wchar_t nm[64]; DWORD nl = 64;
        if (RegEnumKeyExW(k, i, nm, &nl, NULL, NULL, NULL, NULL)
                != ERROR_SUCCESS) break;
        if (_wcsicmp(nm, ext) == 0) ok = true;
    }
    RegCloseKey(k);
    return ok;
}

/* 把一个候选塞进数组（去重 + 填 label/progid）。返回新条数，满了就原样返回。
 * need_rel = true 时先做"门当户对"检查（画图开过 txt 这类历史就不列了）。 */
static int ow_push(FfOpenWithChoice *arr, int n, int cap,
                   const wchar_t *ext, const wchar_t *exe, bool need_rel)
{
    if (!exe || !exe[0]) return n;
    if (need_rel && !ow_relevant(ext, exe)) return n;
    /* 私有历史里存的路径必须真的还在磁盘上。早先只查了"非空"，
     * 于是程序被删掉/移动之后，历史里的旧路径照样进列表 ——
     * 用户点下去没有任何反应（"列出来点不动"）。
     * Explorer 那个 OpenWithList 的路径要经 exe_resolve 才会做存在性
     * 校验，私有历史是完整路径，反而漏了这道关。 */
    if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES) return n;
    for (int i = 0; i < n; ++i)
        if (_wcsicmp(arr[i].exe, exe) == 0) return n;
    if (n >= cap) return n;

    StringCchCopyW(arr[n].exe, FF_PATH_MAX, exe);

    /* 显示名：先问系统这个 exe 叫什么（记事本→"记事本"），问不到就用文件名 */
    arr[n].label[0] = 0;
    DWORD need = 0;
    if (SUCCEEDED(AssocQueryStringW(ASSOCF_INIT_BYEXENAME, ASSOCSTR_FRIENDLYAPPNAME,
                                    exe, NULL, NULL, &need)) && need > 1) {
        wchar_t nm[128];
        if (need < 128 && SUCCEEDED(AssocQueryStringW(ASSOCF_INIT_BYEXENAME,
                                        ASSOCSTR_FRIENDLYAPPNAME, exe, NULL, nm, &need)))
            StringCchCopyW(arr[n].label, 128, nm);
    }
    if (!arr[n].label[0]) {
        StringCchCopyW(arr[n].label, 128, PathFindFileNameW(exe));
        wchar_t *d = wcsrchr(arr[n].label, L'.');
        if (d && d != arr[n].label) *d = 0;
    }
    progid_name_for(ext, exe, arr[n].progid, 64);
    return n + 1;
}

/* 光知道一个 exe 文件名（"notepad3.exe"）时反查完整路径。依次试：
 * 1) 已经是路径就直接用；2) App Paths；3) PATH 里的目录；
 * 4) 常见安装目录浅扫一层。全找不到就返回 false（宁可少列一个，
 * 也不能列出来点不动）。 */
static bool exe_resolve(const wchar_t *name, wchar_t *out, size_t cch)
{
    out[0] = 0;
    if (!name || !name[0]) return false;
    const wchar_t *nm = wcsrchr(name, L'\\');
    nm = nm ? nm + 1 : name;
    if (!nm[0]) return false;

    /* 本身已经带路径 */
    if (wcschr(name, L'\\') || wcschr(name, L':')) {
        StringCchCopyW(out, cch, name);
        if (GetFileAttributesW(out) != INVALID_FILE_ATTRIBUTES) return true;
        out[0] = 0;
    }

    wchar_t sub[512], val[FF_PATH_MAX];
    /* App Paths\foo.exe 的默认值就是完整路径 */
    StringCchPrintfW(sub, 512,
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\%s", nm);
    if (reg_str(HKEY_LOCAL_MACHINE, sub, NULL, val, FF_PATH_MAX) && val[0]) {
        StringCchCopyW(out, cch, val);
        return true;
    }
    if (reg_str(HKEY_CURRENT_USER, sub, NULL, val, FF_PATH_MAX) && val[0]) {
        StringCchCopyW(out, cch, val);
        return true;
    }

    /* PATH 里的目录逐个拼 */
    wchar_t path[4096];
    DWORD n = GetEnvironmentVariableW(L"PATH", path, 4096);
    if (n > 0 && n < 4096) {
        const wchar_t *s = path;
        while (*s) {
            const wchar_t *e = wcschr(s, L';');
            if (!e) e = s + wcslen(s);
            size_t dl = (size_t)(e - s);
            if (dl > 0 && dl < 512) {
                wchar_t cand[FF_PATH_MAX];
                StringCchCopyN(cand, FF_PATH_MAX, s, dl);
                size_t l = wcslen(cand);
                if (l && cand[l - 1] != L'\\')
                    StringCchCatW(cand, FF_PATH_MAX, L"\\");
                StringCchCatW(cand, FF_PATH_MAX, nm);
                if (GetFileAttributesW(cand) != INVALID_FILE_ATTRIBUTES) {
                    StringCchCopyW(out, cch, cand);
                    return true;
                }
            }
            s = *e ? e + 1 : e;
        }
    }

    /* PATH 里没有，就在各盘 Program Files 下扫两层。
     * 绿色版程序常被丢进Program Files\某个自建文件夹（用户这台就是
     * D:\Program Files\(Notepad3)5.21.227.1.x64\Notepad3.exe），固定写死
     * C 盘会漏掉，所以盘符要枚举。 */
    WIN32_FIND_DATAW fd;
    wchar_t roots[8][FF_PATH_MAX];
    int nr = 0;
    const wchar_t *rel[] = { L"\\Program Files", L"\\Program Files (x86)", NULL };
    for (int b = 0; b < 26 && nr < 8; ++b) {
        if (!(GetLogicalDrives() & (1u << b))) continue;
        for (int i = 0; rel[i] && nr < 8; ++i) {
            StringCchPrintfW(roots[nr], FF_PATH_MAX, L"%c:%s", L'A' + b, rel[i]);
            ++nr;
        }
    }

    for (int r = 0; r < nr; ++r) {
        /* 第 1 层：<root>\<子目录>\<exe> */
        wchar_t pat[FF_PATH_MAX];
        StringCchPrintfW(pat, FF_PATH_MAX, L"%s\\*", roots[r]);
        pat[FF_PATH_MAX - 1] = 0;
        HANDLE hf = FindFirstFileW(pat, &fd);
        if (hf == INVALID_HANDLE_VALUE) continue;
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
            if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
                continue;
            wchar_t cand[FF_PATH_MAX];
            StringCchPrintfW(cand, FF_PATH_MAX, L"%s\\%s\\%s",
                             roots[r], fd.cFileName, nm);
            if (GetFileAttributesW(cand) != INVALID_FILE_ATTRIBUTES) {
                FindClose(hf);
                StringCchCopyW(out, cch, cand);
                return true;
            }
            /* 第 2 层：再往下找一层，应付"A\B\C\exe.exe"这种嵌套 */
            wchar_t sub[FF_PATH_MAX], pat2[FF_PATH_MAX];
            StringCchPrintfW(sub, FF_PATH_MAX, L"%s\\%s", roots[r], fd.cFileName);
            StringCchPrintfW(pat2, FF_PATH_MAX, L"%s\\*", sub);
            pat2[FF_PATH_MAX - 1] = 0;
            HANDLE h2 = FindFirstFileW(pat2, &fd);
            if (h2 == INVALID_HANDLE_VALUE) continue;
            do {
                if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
                if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
                    continue;
                StringCchPrintfW(cand, FF_PATH_MAX, L"%s\\%s\\%s",
                                 sub, fd.cFileName, nm);
                if (GetFileAttributesW(cand) != INVALID_FILE_ATTRIBUTES) {
                    FindClose(h2);
                    FindClose(hf);
                    StringCchCopyW(out, cch, cand);
                    return true;
                }
            } while (FindNextFileW(h2, &fd));
            FindClose(h2);
        } while (FindNextFileW(hf, &fd));
        FindClose(hf);
    }
    return false;
}

/* 从三处补齐SHAssocEnumHandlers 漏掉的候选：
 *   1) 本程序私有的使用历史（完整路径，最可靠）
 *   2) Explorer 的 FileExts\<ext>\OpenWithList（裸文件名，靠反查路径）
 *   3) 扩展名的 OpenWithProgids（progID → open 命令 → exe）
 * 追加在系统枚举结果之后，所以顺序上"系统推荐的"仍在前面。 */
/* 从三处补齐 SHAssocEnumHandlers 漏掉的候选：
 *   1) 本程序私有的使用历史（完整路径，最可靠）
 *   2) Explorer 的FileExts\<ext>\OpenWithList（裸文件名，靠反查路径）
 *   3) 扩展名的 OpenWithProgids（progID → open命令 → exe）
 * 追加在系统枚举结果之后，所以顺序上"系统推荐的"仍在前面。
 *
 * 返回补齐后的总条数。必须返回值而不是只改调用方的 n ——
 * ow_supplement 早先写成 void，调用处也把结果丢了，于是补进来的
 * 程序虽然写进了数组，条数却没变，末尾被截掉（Notepad3 就这样
 * 一次次"明明解析成功却列不出来"）。 */
static int ow_supplement(const wchar_t *ext, FfOpenWithChoice *arr,
                         int n, int cap)
{
    wchar_t sub[512], val[FF_PATH_MAX], mru[64];

    /* --- 1) 本程序私有的历史：值就是完整路径 ---
     * 先按 MRUList 的顺序读（体现最近使用），再兜底扫一遍 a..h：
     * MRUList 可能因为异常缺项，光认它会漏掉槽位里真实存在的程序。
     * 这些是用户在本软件里亲手选过的程序（点过的必须还能出现），
     * 不做"门当户对"过滤。 */
    StringCchPrintfW(sub, 512, L"Software\\FileCE\\OpenWith\\%s", ext);
    bool seen[8] = { false };
    if (reg_str(HKEY_CURRENT_USER, sub, L"MRUList", mru, 64)) {
        for (const wchar_t *p = mru; *p && n < cap; ++p) {
            if (*p < L'a' || *p > L'h') continue;
            int si = *p - L'a';
            if (seen[si]) continue;
            seen[si] = true;
            wchar_t slot[8];
            StringCchPrintfW(slot, 8, L"%c", *p);
            if (reg_str(HKEY_CURRENT_USER, sub, slot, val, FF_PATH_MAX) && val[0])
                n = ow_push(arr, n, cap, ext, val, false);
        }
    }
    for (int i = 0; i < 8 && n < cap; ++i) {
        if (seen[i]) continue;
        wchar_t slot[8];
        StringCchPrintfW(slot, 8, L"%c", L'a' + i);
        if (reg_str(HKEY_CURRENT_USER, sub, slot, val, FF_PATH_MAX) && val[0])
            n = ow_push(arr, n, cap, ext, val, false);
    }

    /* --- 2) Explorer 的使用历史：值多半只是文件名 --- */
    StringCchPrintfW(sub, 512,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\"
        L"FileExts\\%s\\OpenWithList", ext);
    {
        /* 槽位名是 a..h。用 reg_str 而不是裸 RegQueryValueExW：后者的 cb
         * 是 in/out 参数，循环里不复位就会越读越短，最后只剩首字符
         * （症状是 val='N'，然后解析出 "C:\..." 这种荒唐结果）。 */
        for (int i = 0; i < 8 && n < cap; ++i) {
            wchar_t slot[8];
            StringCchPrintfW(slot, 8, L"%c", L'a' + i);
            bool got = reg_str(HKEY_CURRENT_USER, sub, slot, val, FF_PATH_MAX);
            if (!got || !val[0]) continue;
            /* 去掉 Explorer 有时带的尾随空格 */
            size_t l = wcslen(val);
            while (l && val[l - 1] == L' ') val[--l] = 0;
            wchar_t full[FF_PATH_MAX];
            if (exe_resolve(val, full, FF_PATH_MAX))
                n = ow_push(arr, n, cap, ext, full, true);
        }
    }

    /* --- 3) OpenWithProgids：每个 progID 取 open 命令里的 exe --- */
    StringCchPrintfW(sub, 512,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\"
        L"FileExts\\%s\\OpenWithProgids", ext);
    const HKEY roots[2] = { HKEY_CURRENT_USER, HKEY_CLASSES_ROOT };
    for (int r = 0; r < 2 && n < cap; ++r) {
        if (r == 1)
            StringCchPrintfW(sub, 512, L"Software\\Classes\\%s\\OpenWithProgids", ext);
        HKEY pk = NULL;
        if (RegOpenKeyExW(roots[r], sub, 0, KEY_QUERY_VALUE, &pk) != ERROR_SUCCESS)
            continue;
        for (DWORD i = 0; i < 32 && n < cap; ++i) {
            wchar_t progid[64]; DWORD pl = 64;
            if (RegEnumValueW(pk, i, progid, &pl, NULL, NULL, NULL, NULL)
                    != ERROR_SUCCESS) break;
            wchar_t ps[512], cmd[512], pexe[FF_PATH_MAX];
            StringCchPrintfW(ps, 512, L"%s\\shell\\open\\command", progid);
            if (!reg_str(HKEY_CLASSES_ROOT, ps, NULL, cmd, 512)) continue;
            cmd_to_exe(cmd, pexe, FF_PATH_MAX);
            if (pexe[0]) n = ow_push(arr, n, cap, ext, pexe, true);
        }
        RegCloseKey(pk);
    }

    return n;
}

/* 找出"用这个 exe 打开该扩展名"的候选程序（系统接口，顺序和图标与
 * 资源管理器一致），并把 exe / 本地化名 / progID 都填好。
 * progID 取自扩展名的 OpenWithProgids 候选里 open 命令指向该 exe 的那个，
 * 后面写"始终使用此应用"关联时要用。 */
int ff_open_with_choices(const wchar_t *ext, FfOpenWithChoice **out)
{
    *out = NULL;
    if (!ext || !ext[0]) return 0;

    /* 容量比 OPEN_WITH_MAX宽裕：后面 ow_supplement 还要往里补程序，
     * 只按菜单项数分配会把绿色版程序挡在门外。 */
    const int cap = OPEN_WITH_MAX * 3;
    FfOpenWithChoice *arr = (FfOpenWithChoice *)calloc((size_t)cap,
                                                      sizeof(FfOpenWithChoice));
    if (!arr) return 0;
    int n = 0;

    /* 只取 RECOMMENDED：真正为该扩展名注册过的程序，顺序和图标与
     * 资源管理器一致，第一个就是当前默认程序。
     * 早先再加一遍 ASSOC_FILTER_NONE（= 系统里注册过的所有程序，
     * 不分扩展名），结果 jpg 的列表里混进记事本/Word/写字板/WMP/IE ——
     * "是什么扩展名用什么程序打"，这遍必须砍掉。 */
    {
        IEnumAssocHandlers *en = NULL;
        if (SHAssocEnumHandlers(ext, ASSOC_FILTER_RECOMMENDED, &en) == S_OK && en) {
            IAssocHandler *h = NULL;
            ULONG got = 0;
            while (n < cap && en->lpVtbl->Next(en, 1, &h, &got) == S_OK && got == 1) {
                wchar_t label[128], exe[FF_PATH_MAX];
                handler_label(h, ext, label, 128);
                exe[0] = 0;
                LPWSTR nm = NULL;
                if (SUCCEEDED(h->lpVtbl->GetName(h, &nm)) && nm) {
                    StringCchCopyW(exe, FF_PATH_MAX, nm);
                    CoTaskMemFree(nm);
                }
                if (!exe[0]) {                       /* 拿不到可执行文件路径就跳过 */
                    h->lpVtbl->Release(h); h = NULL;
                    continue;
                }
                bool dup = false;
                for (int i = 0; i < n; ++i)
                    if (_wcsicmp(arr[i].exe, exe) == 0) { dup = true; break; }
                if (dup) { h->lpVtbl->Release(h); h = NULL; continue; }

                StringCchCopyW(arr[n].exe, FF_PATH_MAX, exe);
                StringCchCopyW(arr[n].label, 128, label);
                progid_name_for(ext, exe, arr[n].progid, 64);
                h->lpVtbl->Release(h); h = NULL;
                ++n;
            }
            en->lpVtbl->Release(en);
        }
    }

    /* 系统枚举不到的（没注册的绿色版程序、Explorer 历史里用过的）
     * 补在后面。用户点过的程序必须能出现在列表里。
     * 一定要接住返回值：ow_supplement 是值传递 n，不接的话补进来的
     * 条数会被丢掉，末尾按旧条数截断。 */
    n = ow_supplement(ext, arr, n, cap);

    if (!n) { free(arr); return 0; }
    *out = arr;
    return n;
}

/* 建"打开方式"子菜单并挂到父菜单上（file = 用来决定候选程序的样例文件） */
/* 造一个「打开方式」子菜单并返回它（挂到哪里由调用方决定）。
 * 里面既有系统已注册的处理程序，也有本程序从私有历史/扫描里找出来的
 * 未注册绿色版程序 —— 这是资源管理器那份菜单给不了的。用完调 ff_ow_release()。 */
static HMENU make_open_with_submenu(const wchar_t *file)
{
    open_with_clear();
    HMENU sub = CreatePopupMenu();
    if (!sub) return NULL;

    s_owExt[0] = 0;
    if (file) {
        const wchar_t *dot = wcsrchr(PathFindFileNameW(file), L'.');
        if (dot && dot[1]) StringCchCopyW(s_owExt, 32, dot);
    }

    /* 图标用系统小图标尺寸（16x16，和资源管理器一致）。
     * 注意不能用 SM_CXMENUCHECK/SM_CYMENUCHECK —— 它们在现代 Windows 上
     * 已废弃、返回 0，会让所有图标都画不出来。 */
    int cx = GetSystemMetrics(SM_CXSMICON);
    int cy = GetSystemMetrics(SM_CYSMICON);
    if (cx <= 0) cx = 16;
    if (cy <= 0) cy = 16;
    IEnumAssocHandlers *en = NULL;
    if (SHAssocEnumHandlers(s_owExt[0] ? s_owExt : file, ASSOC_FILTER_RECOMMENDED, &en) == S_OK && en) {
        IAssocHandler *h = NULL;
        ULONG got = 0;
        while (s_owCount < OPEN_WITH_MAX &&
               en->lpVtbl->Next(en, 1, &h, &got) == S_OK && got == 1) {
            wchar_t label[128];
            handler_label(h, s_owExt, label, 128);

            bool dup = false;
            for (int i = 0; i < s_owCount; ++i)
                if (_wcsicmp(s_owLabel[i], label) == 0) { dup = true; break; }
            if (dup) { h->lpVtbl->Release(h); h = NULL; continue; }

            int id = CMD_OPEN_WITH_APP + s_owCount;
            AppendMenuW(sub, MF_STRING, id, label);
            StringCchCopyW(s_owLabel[s_owCount], 128, label);
            s_owHandler[s_owCount] = h;      /* 保留引用：选中时要用它 Invoke */
            /* 也存一份 exe 路径：万一 GetName 拿不到，open_with_app 还能用 */
            LPWSTR nm0 = NULL;
            s_owExe[s_owCount][0] = 0;
            if (SUCCEEDED(h->lpVtbl->GetName(h, &nm0)) && nm0) {
                StringCchCopyW(s_owExe[s_owCount], FF_PATH_MAX, nm0);
                CoTaskMemFree(nm0);
            }
            h = NULL;

            LPWSTR iloc = NULL;
            int iidx = 0;
            if (SUCCEEDED(s_owHandler[s_owCount]->lpVtbl->GetIconLocation(s_owHandler[s_owCount], &iloc, &iidx)) && iloc) {
                HICON ic = NULL;
                if (ExtractIconExW(iloc, iidx < 0 ? 0 : iidx, NULL, &ic, 1) && ic) {
                    HBITMAP bm = menu_icon_bmp(ic, cx, cy);
                    if (bm) {
                        SetMenuItemBitmaps(sub, id, MF_BYCOMMAND, bm, bm);
                        s_owBitmap[s_owCount] = bm;
                    }
                    DestroyIcon(ic);
                }
                CoTaskMemFree(iloc);
            }
            ++s_owCount;
        }
        en->lpVtbl->Release(en);
    }

    /* 系统枚举不到的（没注册的绿色版程序、用户用过的历史）也得列出来，
     * 否则右键菜单里压根看不到它们。子菜单只认 IAssocHandler，所以这几项
     * handler 为空，改走 s_owExe 直接 ShellExecute。 */
    if (s_owExt[0] && s_owCount < OPEN_WITH_MAX) {
        FfOpenWithChoice *ex = NULL;
        int ec = ff_open_with_choices(s_owExt, &ex);
        for (int i = 0; ec > 0 && i < ec && s_owCount < OPEN_WITH_MAX; ++i) {
            bool dup = false;
            for (int j = 0; j < s_owCount; ++j)
                if (_wcsicmp(s_owLabel[j], ex[i].label) == 0 ||
                    _wcsicmp(s_owExe[j], ex[i].exe) == 0) { dup = true; break; }
            if (dup) continue;

            int idx = s_owCount++;
            s_owHandler[idx] = NULL;
            StringCchCopyW(s_owExe[idx], FF_PATH_MAX, ex[i].exe);
            StringCchCopyW(s_owLabel[idx], 128, ex[i].label);
            int id = CMD_OPEN_WITH_APP + idx;
            AppendMenuW(sub, MF_STRING, id, s_owLabel[idx]);

            /* 图标直接从 exe 文件取 */
            SHFILEINFOW sfi;
            if (SHGetFileInfoW(ex[i].exe, 0, &sfi, sizeof(sfi),
                               SHGFI_ICON | SHGFI_USEFILEATTRIBUTES)) {
                HBITMAP bm = menu_icon_bmp(sfi.hIcon, cx, cy);
                if (bm) {
                    SetMenuItemBitmaps(sub, id, MF_BYCOMMAND, bm, bm);
                    s_owBitmap[idx] = bm;
                }
                DestroyIcon(sfi.hIcon);
            }
        }
        free(ex);
    }

    if (s_owCount) AppendMenuW(sub, MF_SEPARATOR, 0, NULL);
    AppendMenuW(sub, MF_STRING, CMD_OPEN_WITH_STORE, L"搜索 Microsoft Store(&S)");
    AppendMenuW(sub, MF_STRING, CMD_OPEN_WITH, L"选择其他应用(&C)…");
    return sub;
}

HMENU ff_ow_make_menu(const wchar_t *file)
{
    return make_open_with_submenu(file);
}

void ff_ow_release(void)
{
    open_with_clear();
}

/* 用某个已关联程序打开选中的文件 */
static void open_with_app(int idx)
{
    if (idx < 0 || idx >= s_owCount) return;
    IAssocHandler *h = s_owHandler[idx];
    const wchar_t *exe = s_owExe[idx];

    /* 系统没注册的补充项没有 handler，只能自己启动 */
    if (!h) {
        if (!exe || !exe[0]) return;
        wchar_t **paths = NULL;
        int n = ff_selected_paths(&paths);
        if (n > 0 && !PathIsDirectoryW(paths[0])) {
            wchar_t arg[FF_PATH_MAX * 2];
            StringCchPrintfW(arg, FF_PATH_MAX * 2, L"\"%s\"", paths[0]);
            SHELLEXECUTEINFOW ei;
            ZeroMemory(&ei, sizeof(ei));
            ei.cbSize = sizeof(ei);
            ei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC;
            ei.hwnd = g_app.main;
            ei.lpVerb = L"open";
            ei.lpFile = exe;
            ei.lpParameters = arg;
            ei.nShow = SW_SHOWNORMAL;
            ShellExecuteExW(&ei);
            if (ei.hProcess) CloseHandle(ei.hProcess);
            if (s_owExt[0]) ff_open_with_remember(s_owExt, exe);
        }
        ff_free_paths(paths, n);
        return;
    }

    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n > 0) {
        IDataObject *pdo = shell_data_object((const wchar_t **)paths, n);
        if (pdo) {
            h->lpVtbl->Invoke(h, pdo);
            pdo->lpVtbl->Release(pdo);
        }
        /* 记进私有历史：这个扩展名刚用这个程序打开过，
         * 下次"选择其他应用"的列表里要还能看到它。 */
        if (s_owExt[0]) {
            LPWSTR nm = NULL;
            if (SUCCEEDED(h->lpVtbl->GetName(h, &nm)) && nm) {
                ff_open_with_remember(s_owExt, nm);
                CoTaskMemFree(nm);
            }
        }
    }
    ff_free_paths(paths, n);
}

/* "搜索 Microsoft Store"：去商店里按扩展名找能打开它的应用 */
static void open_with_store(void)
{
    wchar_t uri[64];
    StringCchPrintfW(uri, 64, L"ms-windows-store:search?query=%s",
                     s_owExt[0] ? s_owExt : L"*");
    ShellExecuteW(g_app.main, L"open", uri, NULL, NULL, SW_SHOWNORMAL);
}

/* "选择其他应用…"：弹 Win10 那个"你要如何打开这个文件?"列表。
 *
 * 之前这里调SHOpenWithDialog，但 Win10 1809 起它被系统降级成一条橙色横幅
 * "若要更改默认应用，请转到设置>应用>默认应用"（实测 22H2 不管传什么 flag
 * 都一样，弹出的 Shell_Dialog 只有 680x118 高、里面一个列表都没有）——
 * 这就是"点了选择其他应用没反应/只出一句提示"的原因。Explorer 走的是 shell
 * 内部未公开的另一条路径拿不到，所以改用自己实现的 ff_dlg_open_with。*/
static void cmd_open_with(void)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) { ff_free_paths(paths, n); return; }

    /* 对文件夹不加处理（与资源管理器一致），只对文件弹选择框。 */
    if (!PathIsDirectoryW(paths[0])) {
        const wchar_t *dot = wcsrchr(PathFindFileNameW(paths[0]), L'.');
        if (dot && dot[1]) {
            FfOpenWithChoice *ch = NULL;
            int cnt = ff_open_with_choices(dot, &ch);
            /* cnt 可能为 0（冷门扩展名 / 只装了 UWP 应用），照样弹框：
             * 框里还有"浏览其它应用程序…"，用户可以自己挑程序。 */
            int pick = -1;
            wchar_t exe[FF_PATH_MAX];
            exe[0] = 0;
            if (ff_dlg_open_with(g_app.main, paths[0], ch, cnt, &pick,
                                 exe, FF_PATH_MAX) && exe[0]) {
                /* 确定：用选中的程序打开选中项 */
                wchar_t fileArg[FF_PATH_MAX * 2];
                StringCchPrintfW(fileArg, FF_PATH_MAX * 2, L"\"%s\"", paths[0]);
                SHELLEXECUTEINFOW ei;
                ZeroMemory(&ei, sizeof(ei));
                ei.cbSize = sizeof(ei);
                ei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC;
                ei.hwnd = g_app.main;
                ei.lpVerb = L"open";
                ei.lpFile = exe;
                ei.lpParameters = fileArg;
                ei.nShow = SW_SHOWNORMAL;
                ShellExecuteExW(&ei);
                if (ei.hProcess) CloseHandle(ei.hProcess);
                /* 用过了就记住：下次"打开方式"列表里必须有它，
                 * 否则绿色版程序（压根没注册过）用完一次就又找不着了。 */
                ff_open_with_remember(dot, exe);
            }
            free(ch);
        }
    }
    ff_free_paths(paths, n);
}

static void cmd_open_terminal(void)
{
    FfTab *t = cur_tab();
    const wchar_t *dir = t->dir[0] ? t->dir : NULL;
    if (dir) {
        wchar_t cmd[FF_PATH_MAX + 32];
        StringCchPrintfW(cmd, FF_PATH_MAX + 32, L"/K cd /d \"%s\"", dir);
        ShellExecuteW(g_app.main, L"open", L"cmd.exe", cmd, NULL, SW_SHOWNORMAL);
    } else {
        ShellExecuteW(g_app.main, L"open", L"cmd.exe", NULL, NULL, SW_SHOWNORMAL);
    }
}

static void cmd_select_all(void)
{
    ListView_SetItemState(g_app.list, -1, LVIS_SELECTED, LVIS_SELECTED);
    ff_update_ui_state();
}

static void cmd_invert_sel(void)
{
    int n = ff_list_count(g_app.list);
    for (int i = 0; i < n; ++i) {
        UINT st = ListView_GetItemState(g_app.list, i, LVIS_SELECTED);
        ListView_SetItemState(g_app.list, i,
                              st & LVIS_SELECTED ? 0 : LVIS_SELECTED, LVIS_SELECTED);
    }
    ff_update_ui_state();
}

static void cmd_set_view(int mode)
{
    FfTab *t = cur_tab();
    t->viewMode = mode;
    ff_list_apply_view(g_app.list, mode);
}

/* ===================================================== 菜单 */
static HMENU build_menu(bool context)
{
    HMENU m = CreatePopupMenu();
    FfTab *t = cur_tab();
    int rows[MAX_SEL];
    /* 树右键菜单期间选中集 = 树节点（s_treeMenuSel），见 ff_selected_paths */
    int nsel = s_treeMenuSel[0] ? 1 : ff_list_selected(g_app.list, rows, MAX_SEL);
    bool has = nsel > 0;
    bool one = nsel == 1;
    bool inDir = t->dir[0] != 0;

    if (context) {
        /* 文件夹没有"打开方式"（与资源管理器一致），选中项全是文件夹时置灰。
         * 只要有一个文件，就按它的扩展名展开程序子菜单。 */
        const wchar_t *probe = NULL;
        wchar_t probePath[FF_PATH_MAX];
        for (int i = 0; i < nsel; ++i) {
            const FfEntry *e = ff_list_row_entry(g_app.list, rows[i]);
            if (e && !e->isDir) {
                entry_full_path(t, e, probePath, FF_PATH_MAX);
                probe = probePath;
                break;
            }
        }
        AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_OPEN, L"打开(&O)");
        if (probe) {
            HMENU osub = make_open_with_submenu(probe);
            AppendMenuW(m, MF_POPUP, (UINT_PTR)osub, L"打开方式(&H)");
        } else {
            AppendMenuW(m, MF_STRING | MF_GRAYED, CMD_OPEN_WITH, L"打开方式(&H)");
        }
        AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    }
    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_COPY, L"复制(&C)\tCtrl+C");
    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_CUT, L"剪切(&T)\tCtrl+X");
    AppendMenuW(m, MF_STRING | (inDir ? 0 : MF_GRAYED), CMD_PASTE, L"粘贴(&P)\tCtrl+V");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_DELETE, L"删除(&D)\tDelete");
    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_DELETE_HARD, L"永久删除\tShift+Delete");
    AppendMenuW(m, MF_STRING | (one ? 0 : MF_GRAYED), CMD_RENAME, L"重命名(&M)\tF2");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    AppendMenuW(m, MF_STRING | (inDir ? 0 : MF_GRAYED), CMD_NEWFOLDER, L"新建文件夹(&N)");
    AppendMenuW(m, MF_SEPARATOR, 0, NULL);

    if (context) {
        HMENU mv = CreatePopupMenu();
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_REPORT ? MF_CHECKED : 0),
                    CMD_VIEW_DETAIL, L"详细信息(&D)");
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_ICON ? MF_CHECKED : 0),
                    CMD_VIEW_LARGE, L"大图标(&L)");
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_SMALLICON ? MF_CHECKED : 0),
                    CMD_VIEW_SMALL, L"小图标(&S)");
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_LIST ? MF_CHECKED : 0),
                    CMD_VIEW_LIST, L"列表(&I)");
        AppendMenuW(m, MF_POPUP, (UINT_PTR)mv, L"查看(&V)");

        HMENU ms = CreatePopupMenu();
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_NAME ? MF_CHECKED : 0), CMD_SORT_NAME, L"名称");
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_TYPE ? MF_CHECKED : 0), CMD_SORT_TYPE, L"类型");
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_SIZE ? MF_CHECKED : 0), CMD_SORT_SIZE, L"大小");
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_MTIME ? MF_CHECKED : 0), CMD_SORT_MTIME, L"修改时间");
        AppendMenuW(m, MF_POPUP, (UINT_PTR)ms, L"排序(&S)");
        AppendMenuW(m, MF_SEPARATOR, 0, NULL);
    }

    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_PROPERTIES, L"属性(&R)\tAlt+Enter");
    AppendMenuW(m, MF_STRING | (one ? 0 : MF_GRAYED), CMD_STREAMS, L"备用数据流(&A)");
    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_ATTR, L"批量设置属性(&B)");
    AppendMenuW(m, MF_STRING | (has ? 0 : MF_GRAYED), CMD_COPY_PATH, L"复制完整路径(&Y)");
    if (context) {
        AppendMenuW(m, MF_SEPARATOR, 0, NULL);
        AppendMenuW(m, MF_STRING, CMD_SELECT_ALL, L"全选(&A)\tCtrl+A");
        AppendMenuW(m, MF_STRING, CMD_INVERT_SEL, L"反选(&I)");
        AppendMenuW(m, MF_SEPARATOR, 0, NULL);
        AppendMenuW(m, MF_STRING, CMD_REFRESH, L"刷新(&E)\tF5");
        /* 系统菜单入口。本程序自己做不出来的东西（压缩/解压、版本控制、
         * 发送到、固定到"快速访问"、还原以前的版本……）全在系统那份菜单里，
         * 只有 shell 扩展能提供，所以留一条官方通道过去。 */
        AppendMenuW(m, MF_SEPARATOR, 0, NULL);
        AppendMenuW(m, MF_STRING, CMD_MORE_OPTIONS, L"更多选项(&W)…");
    }
    return m;
}

/* 给 Windows 系统菜单补上本程序独有的"查看/排序/全选/反选"。
 * 只在空白处菜单用（资源管理器 Win10 把这些放进了功能区 Ribbon，右键里没有，
 * 但本程序用户习惯在右键切视图，所以作为增强项追加在末尾）。
 * 命令 ID 用本程序原有的 CMD_*，由 ff_shell_menu_invoke 转给 do_command。 */
void ff_menu_append_extras(HMENU m, bool background)
{
    if (!m) return;
    FfTab *t = cur_tab();

    if (background) {
        HMENU mv = CreatePopupMenu();
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_REPORT ? MF_CHECKED : 0),
                    CMD_VIEW_DETAIL, L"详细信息(&D)");
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_ICON ? MF_CHECKED : 0),
                    CMD_VIEW_LARGE, L"大图标(&L)");
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_SMALLICON ? MF_CHECKED : 0),
                    CMD_VIEW_SMALL, L"小图标(&S)");
        AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_LIST ? MF_CHECKED : 0),
                    CMD_VIEW_LIST, L"列表(&I)");
        AppendMenuW(m, MF_POPUP, (UINT_PTR)mv, L"查看(&V)");

        HMENU ms = CreatePopupMenu();
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_NAME ? MF_CHECKED : 0),
                    CMD_SORT_NAME, L"名称");
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_TYPE ? MF_CHECKED : 0),
                    CMD_SORT_TYPE, L"类型");
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_SIZE ? MF_CHECKED : 0),
                    CMD_SORT_SIZE, L"大小");
        AppendMenuW(ms, MF_STRING | (t->sortCol == COL_MTIME ? MF_CHECKED : 0),
                    CMD_SORT_MTIME, L"修改时间");
        AppendMenuW(m, MF_POPUP, (UINT_PTR)ms, L"排序(&S)");

        AppendMenuW(m, MF_STRING, CMD_SELECT_ALL, L"全选(&A)\tCtrl+A");
        AppendMenuW(m, MF_STRING, CMD_INVERT_SEL, L"反选(&I)");
    }
}

/* 菜单栏（挂在标题栏下方）与它的两个需要动态打勾的子菜单 */
static HMENU s_menuBar  = NULL;
static HMENU s_menuGo   = NULL;   /* 转到 */
static HMENU s_menuView = NULL;   /* 查看 */

/* 视图模式 -> 菜单命令 ID（用于 WM_INITMENUPOPUP 时刷新打勾） */
static UINT view_cmd_from_mode(DWORD mode)
{
    switch (mode) {
    case LVS_ICON:      return CMD_VIEW_LARGE;
    case LVS_SMALLICON: return CMD_VIEW_SMALL;
    case LVS_LIST:      return CMD_VIEW_LIST;
    default:            return CMD_VIEW_DETAIL;
    }
}

static HMENU build_main_menu(void)
{
    /* 作为菜单栏挂到窗口上必须用 CreateMenu()（CreatePopupMenu 建出来的
     * SetMenu 会失败，GetMenu 返回 NULL）。 */
    HMENU m = CreateMenu();
    FfTab *t = cur_tab();

    HMENU mf = CreatePopupMenu();
    AppendMenuW(mf, MF_STRING, CMD_NEWFOLDER, L"新建文件夹(&N)\tCtrl+Shift+N");
    AppendMenuW(mf, MF_SEPARATOR, 0, NULL);
    AppendMenuW(mf, MF_STRING, CMD_FIND, L"查找文件(&F)\tCtrl+F");
    AppendMenuW(mf, MF_STRING, CMD_OPEN_TERM, L"在此处打开命令提示符");
    AppendMenuW(mf, MF_SEPARATOR, 0, NULL);
    AppendMenuW(mf, MF_STRING, CMD_EXIT, L"退出(&X)\tAlt+F4");
    AppendMenuW(m, MF_POPUP, (UINT_PTR)mf, L"文件(&F)");

    HMENU me = CreatePopupMenu();
    AppendMenuW(me, MF_STRING, CMD_BACK, L"后退\tAlt+←");
    AppendMenuW(me, MF_STRING, CMD_FORWARD, L"前进\tAlt+→");
    AppendMenuW(me, MF_STRING, CMD_UP, L"上级目录\tBackspace");
    AppendMenuW(me, MF_STRING, CMD_HOME, L"此电脑\tAlt+Home");
    AppendMenuW(me, MF_STRING, CMD_REFRESH, L"刷新\tF5");
    AppendMenuW(me, MF_SEPARATOR, 0, NULL);
    AppendMenuW(me, MF_STRING, CMD_FOCUS_ADDR, L"定位到地址栏\tCtrl+L");
    AppendMenuW(me, MF_STRING | (g_app.treeVisible ? MF_CHECKED : 0), CMD_TOGGLE_TREE,
                L"显示目录树\tCtrl+Shift+T");
    s_menuGo = me;
    AppendMenuW(m, MF_POPUP, (UINT_PTR)me, L"转到(&G)");

    HMENU mv = CreatePopupMenu();
    AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_REPORT ? MF_CHECKED : 0),
                CMD_VIEW_DETAIL, L"详细信息");
    AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_ICON ? MF_CHECKED : 0),
                CMD_VIEW_LARGE, L"大图标");
    AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_SMALLICON ? MF_CHECKED : 0),
                CMD_VIEW_SMALL, L"小图标");
    AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_LIST ? MF_CHECKED : 0),
                CMD_VIEW_LIST, L"列表");
    s_menuView = mv;
    AppendMenuW(mv, MF_SEPARATOR, 0, NULL);
    AppendMenuW(mv, MF_STRING | (g_app.addrBarVisible ? MF_CHECKED : 0),
                CMD_TOGGLE_ADDRBAR, L"地址栏(&A)");
    AppendMenuW(m, MF_POPUP, (UINT_PTR)mv, L"查看(&V)");

    HMENU mt = CreatePopupMenu();
    AppendMenuW(mt, MF_STRING, CMD_TOGGLE_FILTER, L"筛选面板\tCtrl+L");
    AppendMenuW(mt, MF_STRING, CMD_ATTR, L"批量设置属性");
    AppendMenuW(mt, MF_STRING, CMD_STREAMS, L"查看备用数据流");
    AppendMenuW(m, MF_POPUP, (UINT_PTR)mt, L"工具(&T)");

    HMENU mh = CreatePopupMenu();
    AppendMenuW(mh, MF_STRING, CMD_HELP, L"帮助(&H)\tF1");
    AppendMenuW(mh, MF_STRING, CMD_ABOUT, L"关于 FileCE(&A)");
    AppendMenuW(m, MF_POPUP, (UINT_PTR)mh, L"帮助(&H)");
    return m;
}

static void popup_menu(HMENU m, POINT pt)
{
    if (!m) return;
    SetForegroundWindow(g_app.main);
    TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_LEFTALIGN, pt.x, pt.y, 0, g_app.main, NULL);
    PostMessageW(g_app.main, WM_NULL, 0, 0);
    /* "打开方式"子菜单里的处理程序/图标位图在这里释放，但必须延后：
     * 菜单命令是以消息形式发给窗口的，可能排在 TrackPopupMenu 返回之后才被
     * 处理，而那一刻还要拿 IAssocHandler 去 Invoke 打开文件。所以发一条自定义
     * 消息排队，等它轮到时命令必然已经处理完了。 */
    PostMessageW(g_app.main, WM_FF_OW_CLEANUP, 0, 0);
}

/* ===================================================== 地址栏
 * 下拉项 = 显示文本 + 真实路径（路径单独存在 itemdata 里）。
 * 千万别靠"反解显示文本"拿路径：CBN_SELENDOK 发出的那一刻编辑框里还是用户
 * 自己敲的旧内容，GetWindowTextW 会读到旧串，表现就是"点一次没反应 / 拿旧串
 * 去跳转然后报错，点第二次才对"。点选一律走 CB_GETCURSEL + itemdata。 */
static void addr_combo_reset(void)
{
    int n = (int)SendMessageW(g_app.addr, CB_GETCOUNT, 0, 0);
    for (int i = 0; i < n; ++i) {
        wchar_t *p = (wchar_t *)SendMessageW(g_app.addr, CB_GETITEMDATA, i, 0);
        free(p);                       /* CB_RESETCONTENT 不会帮我们释放 */
    }
    SendMessageW(g_app.addr, CB_RESETCONTENT, 0, 0);
}

static void addr_combo_add(const wchar_t *display, const wchar_t *path)
{
    int idx = (int)SendMessageW(g_app.addr, CB_ADDSTRING, 0, (LPARAM)display);
    if (idx < 0) return;
    size_t cb = (wcslen(path) + 1) * sizeof(wchar_t);
    wchar_t *dup = (wchar_t *)malloc(cb);
    if (!dup) return;                  /* 内存不足就让该项退回按文本解析 */
    memcpy(dup, path, cb);
    SendMessageW(g_app.addr, CB_SETITEMDATA, idx, (LPARAM)dup);
}

static void build_address_list(void)
{
    addr_combo_reset();

    /* 此电脑：路径留空串（itemdata 指针非空即可，空串由解析处认成"回此电脑"） */
    addr_combo_add(L"此电脑", L"");

    FfEntryList drives;
    ZeroMemory(&drives, sizeof(drives));
    fs_enum_drives(&drives);
    for (int i = 0; i < drives.count; ++i) {
        FfEntry *de = &drives.items[i];
        /* fs_enum_drives 里还混着桌面/文档这类虚拟节点（树要用）。
         * 这里只认真盘符：否则会拼出 "桌:\" "文:\" 这种假根目录，
         * 点下去必然报"路径不存在或不是文件夹"。 */
        switch (de->driveKind) {
        case DRIVE_DESKTOP_K: case DRIVE_DOCS_K: case DRIVE_VIDEO_K:
        case DRIVE_PICS_K:    case DRIVE_MUSIC_K: case DRIVE_DL_K:
            continue;
        default:
            break;
        }
        wchar_t root[8];
        if (!((de->name[0] >= L'A' && de->name[0] <= L'Z') ||
              (de->name[0] >= L'a' && de->name[0] <= L'z')) || de->name[1] != L':')
            continue;
        StringCchPrintfW(root, 8, L"%c:\\", de->name[0]);
        addr_combo_add(root, root);
    }
    fs_entry_list_free(&drives);

    /* 常用位置：显示"名称    [真实路径]"，点进去用的是 itemdata 里的路径 */
    static const struct { const wchar_t *name; int kind; } places[] = {
        { L"桌面", DRIVE_DESKTOP_K },
        { L"文档", DRIVE_DOCS_K    },
        { L"下载", DRIVE_DL_K      },
        { L"图片", DRIVE_PICS_K    },
        { L"视频", DRIVE_VIDEO_K   },
        { L"音乐", DRIVE_MUSIC_K   },
    };
    for (int i = 0; i < (int)(sizeof(places) / sizeof(places[0])); ++i) {
        wchar_t path[FF_PATH_MAX];
        if (!fs_special_path(places[i].kind, path, FF_PATH_MAX) || !path[0]) continue;
        wchar_t item[FF_PATH_MAX + 32];
        StringCchPrintfW(item, FF_PATH_MAX + 32, L"%s    [%s]", places[i].name, path);
        addr_combo_add(item, path);
    }
}

/* 地址栏直接敲中文名也能进：完整名优先，其次唯一前缀匹配（"桌"→桌面）。 */
static bool addr_resolve_place(const wchar_t *in, wchar_t *out, size_t cch)
{
    static const struct { const wchar_t *name; int kind; } places[] = {
        { L"桌面",     DRIVE_DESKTOP_K },
        { L"文档",     DRIVE_DOCS_K    },
        { L"我的文档", DRIVE_DOCS_K    },
        { L"下载",     DRIVE_DL_K      },
        { L"图片",     DRIVE_PICS_K    },
        { L"视频",     DRIVE_VIDEO_K   },
        { L"音乐",     DRIVE_MUSIC_K   },
    };
    const int n = (int)(sizeof(places) / sizeof(places[0]));
    size_t len = wcslen(in);
    if (!len) return false;

    for (int i = 0; i < n; ++i)
        if (_wcsicmp(in, places[i].name) == 0)
            return fs_special_path(places[i].kind, out, cch);

    int hit = -1, hits = 0;
    for (int i = 0; i < n; ++i) {
        if (wcslen(places[i].name) < len) continue;
        if (_wcsnicmp(in, places[i].name, len) != 0) continue;
        ++hits;
        hit = (hits == 1) ? i : -1;    /* 多个命中就不猜，免得跳错地方 */
    }
    if (hits == 1) return fs_special_path(places[hit].kind, out, cch);
    return false;
}

/* selIdx >= 0：用户在下拉列表里点选的项；< 0：编辑框里敲的内容 */
static void addr_goto_from_combo(int selIdx)
{
    wchar_t buf[FF_PATH_MAX] = L"";
    bool fromList = false;

    if (selIdx >= 0) {
        wchar_t *p = (wchar_t *)SendMessageW(g_app.addr, CB_GETITEMDATA, selIdx, 0);
        if (p) {
            ff_str_copy(buf, FF_PATH_MAX, p);
            fromList = true;
        } else if (SendMessageW(g_app.addr, CB_GETLBTEXT, selIdx, (LPARAM)buf) <= 0) {
            buf[0] = 0;
        }
    }
    if (!fromList) GetWindowTextW(g_app.addr, buf, FF_PATH_MAX);

    /* itemdata 为空串 = 列表里的"此电脑"项 */
    if (fromList && !buf[0]) {
        ff_navigate(L"", true);
        return;
    }

    ff_trim(buf);
    if (!buf[0]) return;

    /* 纯文本里带的中文标注 "路径    [名称]"（没走 itemdata 的老路子兜底） */
    {
        wchar_t *sp = wcsstr(buf, L"    [");
        if (sp) *sp = 0;
        ff_trim(buf);
    }
    if (!buf[0]) return;

    if (_wcsicmp(buf, L"此电脑") == 0 || _wcsicmp(buf, L"计算机") == 0) {
        ff_navigate(L"", true);
        return;
    }

    /* 中文常用位置名 / 前缀简写 */
    wchar_t place[FF_PATH_MAX];
    if (addr_resolve_place(buf, place, FF_PATH_MAX) && place[0]) {
        ff_navigate(place, true);
        return;
    }

    /* 相对路径：补全为当前目录下的子目录 */
    if (!(buf[1] == L':' || (buf[0] == L'\\' && buf[1] == L'\\'))) {
        FfTab *t = cur_tab();
        if (t->dir[0]) {
            wchar_t full[FF_PATH_MAX];
            ff_path_join(full, FF_PATH_MAX, t->dir, buf);
            if (fs_is_dir(full)) {
                ff_navigate(full, true);
                return;
            }
        }
        /* 尝试环境变量展开 */
        wchar_t exp[FF_PATH_MAX];
        DWORD r = ExpandEnvironmentStringsW(buf, exp, FF_PATH_MAX);
        if (r > 0 && r < FF_PATH_MAX && fs_is_dir(exp)) {
            ff_navigate(exp, true);
            return;
        }
    }
    ff_navigate(buf, true);
}

/* 当前应该按"下拉列表选中项"还是"编辑框文本"来跳转 */
static int addr_current_sel(void)
{
    if (SendMessageW(g_app.addr, CB_GETDROPPEDSTATE, 0, 0)) {
        int i = (int)SendMessageW(g_app.addr, CB_GETCURSEL, 0, 0);
        if (i >= 0) return i;
    }
    return -1;
}

/* 进入编辑模式：整层让位露出输入框，全选整段路径（可复制/改写） */
static void crumb_enter_edit(void)
{
    if (!s_addrEdit || !IsWindow(s_addrEdit))
        s_addrEdit = FindWindowExW(g_app.addr, NULL, L"Edit", NULL);
    if (s_addrEdit) {
        s_editMode = true;
        SetWindowPos(s_crumb, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
        SetFocus(s_addrEdit);
        PostMessageW(s_addrEdit, EM_SETSEL, 0, -1);
    }
}

/* 退出编辑模式：面包屑恢复显示，焦点交回列表 */
static void crumb_leave_edit(void)
{
    s_editMode = false;
    if (s_crumb) ShowWindow(s_crumb, SW_SHOW);
    SetFocus(g_app.list);
}

static LRESULT CALLBACK addr_edit_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                       UINT_PTR id, DWORD_PTR ref)
{
    (void)id; (void)ref;
    if (msg == WM_KEYDOWN) {
        if (wp == VK_RETURN) {
            /* 下拉列表开着时回车 = 选中高亮项，这时要按列表项走，
             * 不能拿编辑框里敲了一半的文本去跳转 */
            addr_goto_from_combo(addr_current_sel());
            crumb_leave_edit();
            return 0;
        }
        if (wp == VK_ESCAPE) {
            FfTab *t = cur_tab();
            set_address_text(t->dir);
            crumb_leave_edit();
            return 0;
        }
    }
    if (msg == WM_CHAR && wp == VK_RETURN) return 0;
    if (msg == WM_SETFOCUS) {
        /* 常驻面包屑：只有用户显式请求（单击空白/双击，s_editMode=true）才
         * 让位进编辑态；Tab/Ctrl+L 等其它焦点路径一律转回列表，面包屑保持。 */
        if (s_editMode) {
            if (s_crumb) ShowWindow(s_crumb, SW_HIDE);
        } else {
            SetFocus(g_app.list);
            return 0;
        }
    }
    if (msg == WM_KILLFOCUS) {
        crumb_reposition();      /* 焦点离开编辑框：恢复显示面包屑 */
        s_editMode = false;
    }
    return DefSubclassProc(hwnd, msg, wp, lp);
}

/* ===================================================== 地址栏面包屑
 * 平时盖在地址编辑框上，把路径画成一串可点击的目录段：
 *   c:\  ▸  c  ▸  d  ▸  f  ▸  g
 * 点祖先段直接跳到那一级目录（点 "d" → c:\c\d）；点当前段/"…"不动作；
 * 点路径右侧空白处或【双击】任意处 → 进入编辑模式（整段选中，可复制/改写路径）。
 * 路径太长时从左折叠成 "…"（最深的段优先保留，Explorer 同款）。
 * 没有实体路径（此电脑/搜索）时画成单个不可点段"此电脑"。
 * 编辑框获得焦点时整层隐藏（见 addr_edit_proc 的 WM_SETFOCUS）。 */

#define CRUMB_MAX_SEG 48
typedef struct {
    RECT rc;                    /* 覆盖窗客户区坐标 */
    const wchar_t *text;        /* 显示文本（指向 s_crumbRoot / "…" / s_segp[i]） */
    int   seg;                  /* -2=根(seg 路径=s_crumbRoot)  >=0=段号  -1=不可点 */
} CrumbHit;
static CrumbHit s_hits[CRUMB_MAX_SEG + 2];
static int      s_hitCount = 0;
static int      s_crumbHover = -1;

/* 拆段数据（全部就地指针，避免大数组进 .data——mingw 会把大静态数组
 * 整块塞进 exe，之前一版 s_hits 带 FF_PATH_MAX 路径数组直接 +160KB） */
static wchar_t  s_crumbWork[FF_PATH_MAX];   /* 工作副本（段分隔符就地改 0） */
static wchar_t  s_crumbRoot[520];           /* "C:\" 或 "\\srv\share"，或 "" */
static wchar_t *s_segp[CRUMB_MAX_SEG];      /* 各段指针（指向 s_crumbWork 内） */
static int      s_segN = 0;

static bool crumb_navigable(const CrumbHit *h) { return h->seg != -1; }

/* 把 s_crumbPath 拆成根 + 段（指针就地指向工作副本，段内 '\' 改 0） */
static void crumb_parse(void)
{
    ff_str_copy(s_crumbWork, FF_PATH_MAX, s_crumbPath);
    wchar_t *p = s_crumbWork;
    wchar_t *rest = p;
    s_crumbRoot[0] = 0;
    s_segN = 0;
    if (p[0] == L'\\' && p[1] == L'\\') {                /* UNC：\\server\share 为根 */
        wchar_t *q = wcschr(p + 2, L'\\');
        if (q) q = wcschr(q + 1, L'\\');
        if (!q) { ff_str_copy(s_crumbRoot, 520, p); return; }
        *q = 0;
        ff_str_copy(s_crumbRoot, 520, p);
        rest = q + 1;
    } else if (p[1] == L':' && p[2] == L'\\') {          /* 盘符根 */
        s_crumbRoot[0] = p[0]; s_crumbRoot[1] = L':';
        s_crumbRoot[2] = L'\\'; s_crumbRoot[3] = 0;
        rest = p + 3;
    }
    while (*rest && s_segN < CRUMB_MAX_SEG) {
        while (*rest == L'\\') ++rest;
        if (!*rest) break;
        s_segp[s_segN++] = rest;
        wchar_t *q = wcschr(rest, L'\\');
        if (!q) break;
        *q = 0;
        rest = q + 1;
    }
}

/* 根 + 前 upto 段拼回完整目录："C:\" + a + b → "C:\a\b" */
static void crumb_prefix(wchar_t *out, size_t cch, int upto)
{
    out[0] = 0;
    if (!s_crumbRoot[0]) return;
    ff_str_copy(out, cch, s_crumbRoot);
    for (int i = 0; i <= upto; ++i) {
        size_t l = wcslen(out);
        if (l && out[l - 1] != L'\\') StringCchCatW(out, cch, L"\\");
        StringCchCatW(out, cch, s_segp[i]);
    }
    size_t l = wcslen(out);
    if (l > 3 && out[l - 1] == L'\\') out[l - 1] = 0;   /* "C:\a\"→"C:\a"；根 "C:\" 保留 */
}

static void crumb_add_hit(int x, int w, int top, int bot,
                          const wchar_t *text, int seg)
{
    if (s_hitCount >= CRUMB_MAX_SEG + 2) return;
    CrumbHit *h = &s_hits[s_hitCount++];
    h->rc.left = x; h->rc.right = x + w; h->rc.top = top; h->rc.bottom = bot;
    h->text = text;
    h->seg = seg;
}

/* 计算/缓存各段的矩形（绘制与鼠标命中共用）。
 * 宽度不够时从左折叠成 "…"：根 + "…" + 能放下的最深几段。 */
static void crumb_layout(HWND hwnd)
{
    HDC dc = GetDC(hwnd);
    HFONT oldf = (HFONT)SelectObject(dc, ff_ui_font());
    RECT rc;
    GetClientRect(hwnd, &rc);
    const int pad  = ff_scale(3);
    const int hpad = ff_scale(7);
    const int sepW = ff_scale(20);   /* 图2:段间留足空隙给大箭头 */

    crumb_parse();
    int n = s_segN;

    SIZE sz;
    int rootW = 0;
    if (s_crumbRoot[0]) {
        GetTextExtentPoint32W(dc, s_crumbRoot, (int)wcslen(s_crumbRoot), &sz);
        rootW = sz.cx + hpad * 2;
    }
    GetTextExtentPoint32W(dc, L"…", 1, &sz);
    int dotsW = sz.cx + hpad * 2;
    int segW[CRUMB_MAX_SEG];
    for (int i = 0; i < n; ++i) {
        GetTextExtentPoint32W(dc, s_segp[i], (int)wcslen(s_segp[i]), &sz);
        segW[i] = sz.cx + hpad * 2;
    }

    int avail = rc.right - pad * 2;
    bool collapsed = false;
    int keepFrom = 0;
    if (s_crumbRoot[0] && n > 0) {
        int total = rootW;
        for (int i = 0; i < n; ++i) total += sepW + segW[i];
        if (total > avail) {
            collapsed = true;
            keepFrom = n;                        /* 默认一段都放不下 */
            int acc = dotsW;
            for (int i = n - 1; i >= 0; --i) {
                acc += sepW + segW[i];
                if (rootW + acc > avail) break;
                keepFrom = i;
            }
        }
    }

    s_hitCount = 0;
    int x = pad;
    int top = ff_scale(1), bot = rc.bottom - ff_scale(1);

    if (s_crumbRoot[0]) {
        crumb_add_hit(x, rootW, top, bot, s_crumbRoot, -2);
        x += rootW;
    }
    if (collapsed) {
        crumb_add_hit(x, dotsW, top, bot, L"…", -1);
        x += dotsW;
    }
    for (int i = collapsed ? keepFrom : 0; i < n; ++i) {
        /* 最深一段就是当前目录：不可点（点了不动作），其余段可点 */
        crumb_add_hit(x, segW[i], top, bot, s_segp[i], i == n - 1 ? -1 : i);
        x += segW[i];
        if (i < n - 1) x += sepW;
    }
    if (!s_crumbRoot[0] && n == 0) {
        /* 此电脑/搜索视图没有实体路径：画成单个不可点段，别让地址栏白一片 */
        GetTextExtentPoint32W(dc, L"此电脑", 3, &sz);
        crumb_add_hit(x, sz.cx + hpad * 2, top, bot, L"此电脑", -1);
    }
    SelectObject(dc, oldf);
    ReleaseDC(hwnd, dc);
}

static int crumb_hit_test(HWND hwnd, int x, int y)
{
    crumb_layout(hwnd);
    for (int i = 0; i < s_hitCount; ++i)
        if (x >= s_hits[i].rc.left && x < s_hits[i].rc.right &&
            y >= s_hits[i].rc.top && y < s_hits[i].rc.bottom)
            return i;
    return -1;
}

static void crumb_paint(HWND hwnd, HDC dc)
{
    RECT rc;
    GetClientRect(hwnd, &rc);
    FillRect(dc, &rc, (HBRUSH)GetSysColorBrush(COLOR_WINDOW));
    SetBkMode(dc, TRANSPARENT);
    HFONT oldf = (HFONT)SelectObject(dc, ff_ui_font());

    crumb_layout(hwnd);

    const int hpad = ff_scale(7);
    for (int i = 0; i < s_hitCount; ++i) {
        CrumbHit *h = &s_hits[i];
        bool clickable = crumb_navigable(h);
        /* 分段背景:可点段淡灰圆角、当前段白底,与编辑框一眼区分 */
        if (h->text && h->text[0] && h->seg != -1) {       /* 跳过 "…" 与当前段 */
            RECT bg = h->rc;
            HBRUSH b = CreateSolidBrush(i == s_crumbHover && clickable
                                        ? RGB(0xDA, 0xEA, 0xFB)  /* 悬停:浅蓝 */
                                        : RGB(0xF0, 0xF0, 0xF0)); /* 平时:淡灰 */
            FillRect(dc, &bg, b);
            DeleteObject(b);
        } else if (i == s_crumbHover && clickable) {
            RECT hb = h->rc;
            HBRUSH b = CreateSolidBrush(RGB(0xDA, 0xEA, 0xFB));
            FillRect(dc, &hb, b);
            DeleteObject(b);
        }
        RECT tr = h->rc;
        tr.left += hpad; tr.right -= hpad;
        SetTextColor(dc, clickable ? RGB(0x1B, 0x1B, 0x1B) : RGB(0x69, 0x69, 0x69));
        DrawTextW(dc, h->text, -1, &tr, DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS);
        /* 段间大箭头 ▸(图2 同款:实心、约 10px 高、中灰) */
        if (i + 1 < s_hitCount) {
            int cx = (h->rc.right + s_hits[i + 1].rc.left) / 2;
            int cy = (h->rc.top + h->rc.bottom) / 2;
            POINT tri[3] = { { cx - ff_scale(2), cy - ff_scale(5) },
                             { cx + ff_scale(3), cy },
                             { cx - ff_scale(2), cy + ff_scale(5) } };
            HBRUSH b = CreateSolidBrush(RGB(0x76, 0x76, 0x76));
            HBRUSH ob = (HBRUSH)SelectObject(dc, b);
            HPEN np = (HPEN)GetStockObject(NULL_PEN);
            HPEN op = (HPEN)SelectObject(dc, np);
            Polygon(dc, tri, 3);
            SelectObject(dc, ob);
            SelectObject(dc, op);
            DeleteObject(b);
        }
    }
    SelectObject(dc, oldf);
}


/* 是否点在路径右侧空白处（最后一段矩形之外）——单击进编辑、I 形光标的判据。
 * 段间的箭头空隙 hit_test 也返回 -1，但那属于面包屑本体，不算空白。 */
static bool crumb_on_blank(int x)
{
    return s_hitCount > 0 && x >= s_hits[s_hitCount - 1].rc.right;
}

static LRESULT CALLBACK crumb_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        crumb_paint(hwnd, dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_SETCURSOR:
        if (LOWORD(lp) == HTCLIENT) {
            POINT pt;
            GetCursorPos(&pt);
            ScreenToClient(hwnd, &pt);
            /* 空白处是编辑入口：I 形光标提示；段上（含段间空隙）仍是箭头 */
            int i = crumb_hit_test(hwnd, pt.x, pt.y);
            SetCursor(LoadCursorW(NULL,
                        (i < 0 && crumb_on_blank(pt.x)) ? IDC_IBEAM : IDC_ARROW));
            return TRUE;
        }
        break;
    case WM_LBUTTONDOWN: {
        int i = crumb_hit_test(hwnd, GET_X_LPARAM(lp), GET_Y_LPARAM(lp));
        if (i >= 0 && crumb_navigable(&s_hits[i])) {
            wchar_t target[FF_PATH_MAX];
            if (s_hits[i].seg == -2)                 /* 根段："C:\" / "\\srv\share" */
                ff_str_copy(target, FF_PATH_MAX, s_crumbRoot);
            else                                     /* 普通段：拼到该段的前缀路径 */
                crumb_prefix(target, FF_PATH_MAX, s_hits[i].seg);
            if (target[0]) {
                ff_navigate(target, true);
                SetFocus(g_app.list);
            }
            return 0;
        }
        if (i >= 0) return 0;    /* 当前段 / "…"：单击不动作，面包屑保持 */
        /* 点在路径右侧空白处：单击即进编辑模式（与双击同效），顺手就能
         * 复制/改写整个路径。段本身仍然随便点都不会丢。 */
        if (crumb_on_blank(GET_X_LPARAM(lp))) crumb_enter_edit();
        return 0;
    }
    case WM_LBUTTONDBLCLK:
        crumb_enter_edit();      /* 双击进编辑模式：整段选中 */
        return 0;
    case WM_MOUSEMOVE: {
        int i = crumb_hit_test(hwnd, GET_X_LPARAM(lp), GET_Y_LPARAM(lp));
        int ni = (i >= 0 && crumb_navigable(&s_hits[i])) ? i : -1;
        if (ni != s_crumbHover) {
            s_crumbHover = ni;
            InvalidateRect(hwnd, NULL, TRUE);
        }
        TRACKMOUSEEVENT tme = { sizeof(tme), TME_LEAVE, hwnd, 0 };
        TrackMouseEvent(&tme);
        return 0;
    }
    case WM_MOUSELEAVE:
        if (s_crumbHover != -1) {
            s_crumbHover = -1;
            InvalidateRect(hwnd, NULL, TRUE);
        }
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

/* 跟随地址编辑框的位置/可见性；编辑框有焦点时不显示 */
static void crumb_reposition(void)
{
    if (!s_crumb) return;
    if (!g_app.addrBarVisible || !g_app.addr || !IsWindowVisible(g_app.addr)) {
        ShowWindow(s_crumb, SW_HIDE);
        return;
    }
    if (!s_addrEdit || !IsWindow(s_addrEdit))
        s_addrEdit = FindWindowExW(g_app.addr, NULL, L"Edit", NULL);
    if (!s_addrEdit) return;
    RECT rc;
    /* 盖住【整个组合框】而不是只盖 Edit:组合框比 Edit 高(边框+下拉箭头),
     * 只盖 Edit 的话边框和箭头露在外面,用户看到的就是"编辑框"(实测差 10px)。 */
    GetWindowRect(g_app.addr, &rc);
    POINT tl = { rc.left, rc.top }, br = { rc.right, rc.bottom };
    ScreenToClient(g_app.main, &tl);
    ScreenToClient(g_app.main, &br);
    int e = ff_scale(2);                 /* 只露组合框自己的 1px 外框线 */
    MoveWindow(s_crumb, tl.x + e, tl.y + e,
               (br.x - tl.x) - 2 * e, (br.y - tl.y) - 2 * e, FALSE);
    /* 关键：覆盖层必须在地址工具栏（及其组合框/编辑框）之上，否则真实的鼠标
     * 点击会落到原生编辑框上（WindowFromPoint 证实此前编辑框压在覆盖层上面），
     * 表现为"鼠标移上去有高亮、但点了没反应"。把它置为父窗口子窗口的顶层。 */
    SetWindowPos(s_crumb, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
    DBG(L"crumb_reposition: editMode=%d visible=%d -> %s",
        (int)s_editMode, (int)IsWindowVisible(s_crumb),
        (s_editMode && GetFocus() == s_addrEdit) ? L"HIDE" : L"SHOW");
    if (s_editMode && GetFocus() == s_addrEdit) ShowWindow(s_crumb, SW_HIDE);
    else ShowWindow(s_crumb, SW_SHOW);
    /* RedrawWindow + RDW_UPDATENOW 立即同步重绘:
     * InvalidateRect 只排队,WM_PAINT 要等消息循环空闲才跑;期间面包屑是
     * 一条空白,看起来像"没出现",要等鼠标划过触发重绘才有内容(用户实测)。 */
    RedrawWindow(s_crumb, NULL, NULL, RDW_INVALIDATE | RDW_UPDATENOW);
}

/* ===================================================== 筛选面板 */
static void filter_apply_from_ui(void)
{
    HWND p = g_app.filterPanel;
    if (!p) return;
    FfFilter f;
    ZeroMemory(&f, sizeof(f));
    f.enabled = IsDlgButtonChecked(p, IDC_FILTER_CHK) == BST_CHECKED;

    SYSTEMTIME st;
    ZeroMemory(&st, sizeof(st));
    DateTime_GetSystemtime(GetDlgItem(p, IDC_FILTER_FROM), &st);
    st.wHour = 0; st.wMinute = 0; st.wSecond = 0;
    SystemTimeToFileTime(&st, &f.mtimeFrom);
    LocalFileTimeToFileTime(&f.mtimeFrom, &f.mtimeFrom);

    ZeroMemory(&st, sizeof(st));
    DateTime_GetSystemtime(GetDlgItem(p, IDC_FILTER_TO), &st);
    st.wHour = 23; st.wMinute = 59; st.wSecond = 59;
    SystemTimeToFileTime(&st, &f.mtimeTo);
    LocalFileTimeToFileTime(&f.mtimeTo, &f.mtimeTo);

    f.hasMtime = true;
    wchar_t buf[64];
    GetWindowTextW(GetDlgItem(p, IDC_FILTER_SIZE), buf, 64);
    ff_trim(buf);
    if (buf[0]) {
        ULONGLONG v = _wtoi64(buf);
        int unit = (int)SendDlgItemMessageW(p, IDC_FILTER_SIZEU, CB_GETCURSEL, 0, 0);
        ULONGLONG mul = 1;
        switch (unit) {
        case 1: mul = 1024ULL; break;
        case 2: mul = 1024ULL * 1024; break;
        case 3: mul = 1024ULL * 1024 * 1024; break;
        default: break;
        }
        f.sizeMin = v * mul;
        f.hasSize = true;
    }
    f.kind = (int)SendDlgItemMessageW(p, IDC_FILTER_DIR, CB_GETCURSEL, 0, 0);

    g_app.filter = f;
    ff_apply_filter();
}

static LRESULT CALLBACK filter_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                    UINT_PTR id, DWORD_PTR ref)
{
    (void)id; (void)ref;
    switch (msg) {
    case WM_COMMAND:
        if (LOWORD(wp) == IDC_FILTER_CLEAR && HIWORD(wp) == BN_CLICKED) {
            filter_clear();
            return 0;
        }
        if (HIWORD(wp) == BN_CLICKED || HIWORD(wp) == CBN_SELCHANGE)
            filter_apply_from_ui();
        return 0;
    case WM_NOTIFY: {
        NMHDR *nh = (NMHDR *)lp;
        if (nh->code == DTN_DATETIMECHANGE) { filter_apply_from_ui(); return 0; }
        break;
    }
    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLORBTN: {
        SetBkMode((HDC)wp, TRANSPARENT);
        return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
    }
    case WM_ERASEBKGND: {
        RECT rc;
        GetClientRect(hwnd, &rc);
        FillRect((HDC)wp, &rc, GetSysColorBrush(COLOR_BTNFACE));
        return 1;
    }
    }
    return DefSubclassProc(hwnd, msg, wp, lp);
}

static HWND filter_panel_create(HWND parent)
{
    HWND p = CreateWindowExW(WS_EX_CLIENTEDGE, L"STATIC", L"",
                             WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                             0, 0, 100, 100, parent, (HMENU)(INT_PTR)IDC_FILTER_CHK,
                             g_app.inst, NULL);
    if (!p) return NULL;
    HFONT f = ff_ui_font();
    int y = ff_scale(12), pad = ff_scale(12), w = ff_scale(220);

    HWND c = CreateWindowExW(0, L"BUTTON", L"启用筛选", WS_CHILD | WS_VISIBLE |
                             BS_AUTOCHECKBOX | WS_TABSTOP,
                             pad, y, w, ff_scale(22), p,
                             (HMENU)(INT_PTR)IDC_FILTER_CHK, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(34);

    c = CreateWindowExW(0, L"STATIC", L"修改时间 从", WS_CHILD | WS_VISIBLE,
                        pad, y, w, ff_scale(18), p, NULL, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(20);
    c = CreateWindowExW(0, DATETIMEPICK_CLASSW, L"", WS_CHILD | WS_VISIBLE |
                        DTS_SHORTDATEFORMAT | WS_TABSTOP,
                        pad, y, w, ff_scale(24), p,
                        (HMENU)(INT_PTR)IDC_FILTER_FROM, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(32);

    c = CreateWindowExW(0, L"STATIC", L"修改时间 到", WS_CHILD | WS_VISIBLE,
                        pad, y, w, ff_scale(18), p, NULL, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(20);
    c = CreateWindowExW(0, DATETIMEPICK_CLASSW, L"", WS_CHILD | WS_VISIBLE |
                        DTS_SHORTDATEFORMAT | WS_TABSTOP,
                        pad, y, w, ff_scale(24), p,
                        (HMENU)(INT_PTR)IDC_FILTER_TO, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(32);

    c = CreateWindowExW(0, L"STATIC", L"最小大小", WS_CHILD | WS_VISIBLE,
                        pad, y, w, ff_scale(18), p, NULL, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(20);
    c = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE |
                        ES_NUMBER | WS_TABSTOP,
                        pad, y, ff_scale(120), ff_scale(24), p,
                        (HMENU)(INT_PTR)IDC_FILTER_SIZE, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    c = CreateWindowExW(0, L"COMBOBOX", L"", WS_CHILD | WS_VISIBLE |
                        CBS_DROPDOWNLIST | WS_TABSTOP,
                        pad + ff_scale(126), y, ff_scale(94), ff_scale(120), p,
                        (HMENU)(INT_PTR)IDC_FILTER_SIZEU, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"字节");
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"KB");
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"MB");
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"GB");
    SendMessageW(c, CB_SETCURSEL, 2, 0);
    y += ff_scale(34);

    c = CreateWindowExW(0, L"STATIC", L"对象类型", WS_CHILD | WS_VISIBLE,
                        pad, y, w, ff_scale(18), p, NULL, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    y += ff_scale(20);
    c = CreateWindowExW(0, L"COMBOBOX", L"", WS_CHILD | WS_VISIBLE |
                        CBS_DROPDOWNLIST | WS_TABSTOP,
                        pad, y, w, ff_scale(140), p,
                        (HMENU)(INT_PTR)IDC_FILTER_DIR, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"全部");
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"仅文件");
    SendMessageW(c, CB_ADDSTRING, 0, (LPARAM)L"仅文件夹");
    SendMessageW(c, CB_SETCURSEL, 0, 0);
    y += ff_scale(34);

    c = CreateWindowExW(0, L"BUTTON", L"清除筛选条件", WS_CHILD | WS_VISIBLE |
                        BS_PUSHBUTTON | WS_TABSTOP,
                        pad, y, ff_scale(130), ff_scale(26), p,
                        (HMENU)(INT_PTR)IDC_FILTER_CLEAR, g_app.inst, NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)f, TRUE);

    /* 默认日期：今天往前推 30 天 ~ 今天 */
    {
        SYSTEMTIME now;
        GetLocalTime(&now);
        HWND from = GetDlgItem(p, IDC_FILTER_FROM);
        SYSTEMTIME f2 = now;
        FILETIME ft;
        SystemTimeToFileTime(&f2, &ft);
        ULARGE_INTEGER u;
        u.LowPart = ft.dwLowDateTime; u.HighPart = ft.dwHighDateTime;
        u.QuadPart -= 30ULL * 24 * 3600 * 10000000ULL;
        ft.dwLowDateTime = u.LowPart; ft.dwHighDateTime = u.HighPart;
        FileTimeToSystemTime(&ft, &f2);
        DateTime_SetSystemtime(from, GDT_VALID, &f2);
        DateTime_SetSystemtime(GetDlgItem(p, IDC_FILTER_TO), GDT_VALID, &now);
    }

    SetWindowSubclass(p, filter_proc, 1, 0);
    return p;
}

/* ===================================================== 筛选清除 */
static void filter_clear(void)
{
    HWND p = g_app.filterPanel;
    if (!p) return;
    CheckDlgButton(p, IDC_FILTER_CHK, BST_UNCHECKED);
    SetWindowTextW(GetDlgItem(p, IDC_FILTER_SIZE), L"");
    SendDlgItemMessageW(p, IDC_FILTER_DIR, CB_SETCURSEL, 0, 0);
    SendDlgItemMessageW(p, IDC_FILTER_SIZEU, CB_SETCURSEL, 2, 0);
    ZeroMemory(&g_app.filter, sizeof(g_app.filter));
    ff_apply_filter();
}

/* ===================================================== 命令分发 */
/* 「更多选项…」待弹出的系统菜单上下文：命令处理时只存下来，
 * 真正 TrackPopupMenu 在 WM_FF_SHELL_MENU 里做（理由见 CMD_MORE_OPTIONS）。
 * ★菜单弹出的整个过程中这份 paths 必须活着 —— shellmenu.c 的回调要靠它
 *   知道"当前操作的是谁"（尤其是树右键：它不等于列表选中项）。 */
static wchar_t **s_shellPaths = NULL;
static int       s_shellCount = 0;

/* 右键入口：把当前选中项抓下来，投消息让主循环去弹 Windows 系统菜单。
 * 之所以"抓下来再弹"而不是当场弹：本函数可能是从菜单命令里被调用的
 * （上一份菜单还没收干净），当场 TrackPopupMenu 会被系统立刻收掉。 */
static void request_shell_menu(void)
{
    ff_free_paths(s_shellPaths, s_shellCount);
    s_shellPaths = NULL;
    s_shellCount = ff_selected_paths(&s_shellPaths);
    PostMessageW(g_app.main, WM_FF_SHELL_MENU, 0, 0);
}

/* 撤消重命名：只记最近一次。资源管理器里"撤消 重命名"也只在刚重命名过才出现，
 * 没有可撤消的操作时菜单里不该有这一项。 */
static wchar_t s_undoFrom[FF_PATH_MAX];
static wchar_t s_undoTo[FF_PATH_MAX];

bool ff_shell_menu_can_undo_rename(void)
{
    return s_undoTo[0] != 0 &&
           GetFileAttributesW(s_undoTo) != INVALID_FILE_ATTRIBUTES;
}

bool ff_shell_menu_clipboard_has_files(void)
{
    return IsClipboardFormatAvailable(CF_HDROP) != FALSE;
}

/* 用某个 shell 动词执行（打开 / 打印 / 编辑） */
static void shell_verb_exec(const wchar_t *path, const wchar_t *verb)
{
    if (!path || !path[0]) return;
    SHELLEXECUTEINFOW ei;
    ZeroMemory(&ei, sizeof(ei));
    ei.cbSize = sizeof(ei);
    ei.fMask = SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI;
    ei.hwnd = g_app.main;
    ei.lpVerb = verb;
    ei.lpFile = path;
    ei.nShow = SW_SHOWNORMAL;
    ShellExecuteExW(&ei);
}

/* 把若干路径按 CRLF 拼成一段文本放进剪贴板（"复制完整路径"用） */
static void copy_paths_text(const wchar_t **paths, int n)
{
    if (n <= 0) return;
    size_t cap = (size_t)n * (FF_PATH_MAX + 2) + 2;
    wchar_t *buf = (wchar_t *)calloc(cap, sizeof(wchar_t));
    if (!buf) return;
    for (int i = 0; i < n; ++i) {
        if (i) StringCchCatW(buf, cap, L"\r\n");
        StringCchCatW(buf, cap, paths[i]);
    }
    size_t bytes = (wcslen(buf) + 1) * sizeof(wchar_t);
    HGLOBAL hg = GlobalAlloc(GMEM_MOVEABLE, bytes);
    if (hg) {
        void *p = GlobalLock(hg);
        if (p) {
            memcpy(p, buf, bytes);
            GlobalUnlock(hg);
            if (OpenClipboard(g_app.main)) {
                EmptyClipboard();
                SetClipboardData(CF_UNICODETEXT, hg);
                CloseClipboard();
                hg = NULL;              /* 所有权已交给剪贴板 */
            }
        }
        if (hg) GlobalFree(hg);
    }
    free(buf);
}

/* 系统右键菜单（shellmenu.c）里"本程序插的项"和"需要宿主的动词"的落点。
 * 返回 false = 不认识，调用方把命令交回 shell。 */
bool ff_shell_menu_invoke(UINT id)
{
    /* 优先用"菜单弹出那一刻的选中项"（树右键时它不等于列表选中项） */
    wchar_t **paths = s_shellPaths;
    int n = s_shellCount;
    bool own = false;
    if (!paths || n <= 0) { n = ff_selected_paths(&paths); own = true; }

    bool handled = true;
    switch (id) {
    case SM_CMD_OPEN:   if (n > 0) shell_verb_exec(paths[0], L"open"); break;
    case SM_CMD_PRINT:  if (n > 0) shell_verb_exec(paths[0], L"print"); break;
    case SM_CMD_EDIT:   if (n > 0) shell_verb_exec(paths[0], L"edit"); break;
    case SM_CMD_REFRESH: ff_refresh(true); break;

    case SM_CMD_UNDORENAME:
        if (ff_shell_menu_can_undo_rename()) {
            if (MoveFileW(s_undoTo, s_undoFrom)) {
                s_undoFrom[0] = 0;
                s_undoTo[0] = 0;
                ff_refresh(true);
            } else {
                ff_msg_error(g_app.main, L"撤消重命名失败：原名称可能已被占用。");
            }
        }
        break;

    case SM_CMD_CUSTOMIZE:
        /* 资源管理器那个"自定义文件夹"是 desktop.ini 的专用对话框，第三方拿不到
         * 同款；这里退一步打开该目录的属性页（入口位置一致，能力不完全等价）。 */
        if (g_app.curDir[0])
            SHObjectProperties(g_app.main, SHOP_FILEPATH, g_app.curDir, NULL);
        break;

    case SM_CMD_DELETE_HARD: {
        if (n > 0) {
            wchar_t first[256];
            ff_str_copy(first, 256, ff_path_name(paths[0]));
            if (ff_confirm(g_app.main,
                    L"确定要【永久删除】%s 吗？\n\n此操作不可撤销，不会进入回收站。",
                    n == 1 ? first : L"这些对象")) {
                wchar_t err[512] = L"";
                if (!fs_delete_permanent(g_app.main, (const wchar_t **)paths, n, err, 512))
                    ff_msg_error(g_app.main, L"%s", err[0] ? err : L"删除失败。");
                else
                    ff_refresh(true);
            }
        }
        break;
    }

    case SM_CMD_COPY_PATH:  copy_paths_text((const wchar_t **)paths, n); break;
    case SM_CMD_ADS:        ff_dlg_streams(g_app.main); break;
    case SM_CMD_ATTR:       ff_dlg_attr(g_app.main); break;

    case SM_CMD_PASTE:      cmd_paste(); break;
    case SM_CMD_PASTELINK: {
        wchar_t err[512] = L"";
        if (!fs_paste_shortcut(g_app.main, g_app.curDir, err, 512))
            ff_msg_error(g_app.main, L"%s", err[0] ? err : L"粘贴快捷方式失败。");
        else
            ff_refresh(true);
        break;
    }

    /* 需要宿主的 shell 动词：重命名（shell 自己弹不出重命名框）。
     * ★必须延后：此刻系统菜单还在关闭过程中，焦点还被菜单持有，
     *   当场 SetFocus + ListView_EditLabel 建出来的编辑框会被随后的焦点
     *   切换立刻取消（实测 EditLabel 返回了句柄，但窗口转眼就没了）。
     *   投一条消息，等菜单彻底收完再开。 */
    case (UINT)DFM_CMD_RENAME:
        /* 等菜单彻底收尾（含它自己的重绘/激活消息）再开编辑框。
         * 实测"菜单刚销毁那一瞬"建立的内联编辑会话会被立刻取消：
         * ListView_EditLabel 明明返回了句柄，框却没了、打字也进不去。
         * 定时器能保证消息循环真正空转过一段，比连投两条消息更稳。 */
        SetTimer(g_app.main, FF_TIMER_RENAME, 120, NULL);
        /* 别让调用方当成"改动过文件"去 ff_refresh —— 刷新会重建列表，
         * 把刚建好的编辑框一起带走（实测 EditLabel 成功、随后消失）。
         * 重命名真正成功时 WM_FF_RENAME 自己会刷新。 */
        handled = false;
        break;

    default:
        /* 本程序的普通命令（查看/排序/全选/反选…）也能从系统菜单里触发 */
        if (id >= 20000 && id < 22000) { do_command((int)id); break; }
        handled = false;
        break;
    }

    if (own) ff_free_paths(paths, n);
    return handled;
}

static void do_command(int cmd)
{
    FfTab *t = cur_tab();

    /* "打开方式"子菜单里动态列出的那些程序：ID 连续，按下标取回处理程序 */
    if (cmd >= CMD_OPEN_WITH_APP && cmd < CMD_OPEN_WITH_APP + OPEN_WITH_MAX) {
        open_with_app(cmd - CMD_OPEN_WITH_APP);
        return;
    }

    switch (cmd) {
    case CMD_BACK:      ff_go_back(); break;
    case CMD_FORWARD:   ff_go_forward(); break;
    case CMD_UP:        ff_go_up(); break;
    case CMD_HOME:      ff_navigate(L"", true); break;
    case CMD_REFRESH:   ff_refresh(true); break;
    case CMD_OPEN:      cmd_open(); break;
    case CMD_OPEN_WITH: cmd_open_with(); break;
    case CMD_OPEN_WITH_STORE: open_with_store(); break;
    case CMD_NEWFOLDER: cmd_new_folder(); break;
    case CMD_RENAME:    cmd_rename(); break;
    case CMD_DELETE:    cmd_delete(false); break;
    case CMD_DELETE_HARD: cmd_delete(true); break;
    case CMD_COPY:      cmd_copy_cut(false); break;
    case CMD_CUT:       cmd_copy_cut(true); break;
    case CMD_PASTE:     cmd_paste(); break;
    case CMD_PROPERTIES: cmd_properties(); break;
    case CMD_ATTR:      ff_dlg_attr(g_app.main); break;
    case CMD_STREAMS:   ff_dlg_streams(g_app.main); break;
    case CMD_FIND:      ff_dlg_find(g_app.main); break;
    case CMD_ABOUT:     ff_dlg_about(g_app.main); break;
    case CMD_HELP:      ff_dlg_help(g_app.main); break;
    case CMD_OPEN_TERM: cmd_open_terminal(); break;
    case CMD_SELECT_ALL: cmd_select_all(); break;
    case CMD_INVERT_SEL: cmd_invert_sel(); break;
    case CMD_COPY_PATH: cmd_copy_path(); break;
    case CMD_MORE_OPTIONS: {
        /* 弹 Windows 自己那份右键菜单（含全部 shell 扩展）。
         * ★不能在这里直接弹：本命令是在"上一份菜单关闭的收尾过程"里被派发的，
         * 那一刻再 TrackPopupMenu，新菜单会被系统立刻收掉（实测现象：闪一下就
         * 没了，探针 C 段就是这么抓到它的）。和拖动落手要投 WM_FF_TREE_CONFIRM
         * 是同一个道理 —— 只把上下文存下来、投一条消息，等输入队列清干净再弹。 */
        ff_free_paths(s_shellPaths, s_shellCount);
        s_shellPaths = NULL;
        s_shellCount = ff_selected_paths(&s_shellPaths);
        PostMessageW(g_app.main, WM_FF_SHELL_MENU, 0, 0);
        break;
    }
    case CMD_VIEW_DETAIL: cmd_set_view(LVS_REPORT); break;
    case CMD_VIEW_LARGE:  cmd_set_view(LVS_ICON); break;
    case CMD_VIEW_SMALL:  cmd_set_view(LVS_SMALLICON); break;
    case CMD_VIEW_LIST:   cmd_set_view(LVS_LIST); break;
    case CMD_SORT_NAME:   t->sortCol = COL_NAME; t->sortAsc = TRUE; build_order(t); refresh_list(); update_status(); break;
    case CMD_SORT_TYPE:   t->sortCol = COL_TYPE; t->sortAsc = TRUE; build_order(t); refresh_list(); update_status(); break;
    case CMD_SORT_SIZE:   t->sortCol = COL_SIZE; t->sortAsc = FALSE; build_order(t); refresh_list(); update_status(); break;
    case CMD_SORT_MTIME:  t->sortCol = COL_MTIME; t->sortAsc = FALSE; build_order(t); refresh_list(); update_status(); break;
    case CMD_TOGGLE_FILTER:
        g_app.filterVisible = !g_app.filterVisible;
        layout_children(g_app.main);
        ff_update_ui_state();
        break;
    case CMD_TOGGLE_TREE:
        g_app.treeVisible = !g_app.treeVisible;
        layout_children(g_app.main);
        ff_update_ui_state();
        break;
    case CMD_TOGGLE_ADDRBAR:
        g_app.addrBarVisible = !g_app.addrBarVisible;
        ff_toolbar_clear_hot(g_app.addrBar);
        layout_children(g_app.main);
        ff_update_ui_state();
        break;
    case CMD_FOCUS_ADDR:
        /* 地址栏条隐藏时先恢复，否则定位到一个看不见的控件 */
        if (!g_app.addrBarVisible) {
            g_app.addrBarVisible = true;
            layout_children(g_app.main);
        }
        SetFocus(g_app.addr);
        SendMessageW(g_app.addr, CB_SETEDITSEL, 0, MAKELPARAM(0, -1));
        break;
    case CMD_VIEWMENU: {
        /* 工具栏"查看方式"下拉：弹出视图切换菜单 */
        RECT r;
        if (ff_toolbar_button_rect(g_app.addrBar, FF_TB_VIEW, &r)) {
            POINT pt = { r.left, r.bottom + 2 };
            ClientToScreen(g_app.addrBar, &pt);
            FfTab *t = cur_tab();
            HMENU mv = CreatePopupMenu();
            AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_REPORT ? MF_CHECKED : 0),
                        CMD_VIEW_DETAIL, L"详细信息");
            AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_ICON ? MF_CHECKED : 0),
                        CMD_VIEW_LARGE, L"大图标");
            AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_SMALLICON ? MF_CHECKED : 0),
                        CMD_VIEW_SMALL, L"小图标");
            AppendMenuW(mv, MF_STRING | (t->viewMode == LVS_LIST ? MF_CHECKED : 0),
                        CMD_VIEW_LIST, L"列表");
            popup_menu(mv, pt);
        }
        break;
    }
    case CMD_MAINMENU:
        /* 主菜单已经常驻标题栏下方，这里只是把键盘焦点交到菜单栏（等同按 Alt） */
        SendMessageW(g_app.main, WM_SYSCOMMAND, SC_KEYMENU, 0);
        break;
    case CMD_EXIT:
        PostMessageW(g_app.main, WM_CLOSE, 0, 0);
        break;
    case CMD_TAB_NEW:
        tab_new(t->dir[0] ? t->dir : L"");
        break;
    case CMD_TAB_CLOSE:
        if (s_tabCount > 1) tab_close(s_active);
        break;
    case CMD_TAB_NEXT:
        if (s_tabCount > 1) tab_select((s_active + 1) % s_tabCount);
        break;
    case CMD_TAB_PREV:
        if (s_tabCount > 1) tab_select((s_active + s_tabCount - 1) % s_tabCount);
        break;
    default:
        break;
    }
}

/* ===================================================== 分隔条 */
static bool on_splitter(HWND hwnd, int x, int y)
{
    if (!s_splitVisible) return false;
    (void)hwnd;
    int t = ff_scale(3);
    return x >= s_splitX - t && x <= s_splitX + t &&
           y >= s_splitTop && y <= s_splitBottom;
}

/* ===================================================== 主窗口过程 */
LRESULT CALLBACK ff_main_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE: {
        DragAcceptFiles(hwnd, TRUE);     /* 拖到主窗口空白处也能接收 */
        /* 树/列表注册 OLE 拖放目标：树内拖动悬停显示 复制/移动 光标，
         * 松手在 Drop 里弹"复制/移动/取消"（树/列表句柄在子窗口创建后有效，
         * 因此注册挪到 main.c 的 create_child_windows 之后 —— 见 ff_register_droptarget） */
        return 0;
    }

    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        if (s_splitVisible) {
            RECT r;
            r.left = s_splitX - ff_scale(2);
            r.right = s_splitX + ff_scale(2);
            r.top = s_splitTop;
            r.bottom = s_splitBottom;
            HBRUSH b = CreateSolidBrush(RGB(233, 233, 233));
            FillRect(dc, &r, b);
            DeleteObject(b);
        }
        EndPaint(hwnd, &ps);
        return 0;
    }

    case WM_SETCURSOR: {
        if (LOWORD(lp) == HTCLIENT) {
            POINT pt;
            GetCursorPos(&pt);
            ScreenToClient(hwnd, &pt);
            if (on_splitter(hwnd, pt.x, pt.y)) {
                SetCursor(LoadCursorW(NULL, IDC_SIZEWE));
                return TRUE;
            }
        }
        break;
    }

    case WM_LBUTTONDOWN: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        if (on_splitter(hwnd, x, y)) {
            s_dragSplit = true;
            s_dragStartX = x;
            s_dragStartW = g_app.treeWidth;
            SetCapture(hwnd);
            return 0;
        }
        break;
    }

    case WM_MOUSEMOVE:
        if (s_dragSplit) {
            int x = GET_X_LPARAM(lp);
            int nw = s_dragStartW + (x - s_dragStartX);
            if (nw < ff_scale(120)) nw = ff_scale(120);
            if (nw > ff_scale(520)) nw = ff_scale(520);
            g_app.treeWidth = nw;
            layout_children(hwnd);
            return 0;
        }
        break;

    case WM_LBUTTONUP:
        if (s_dragSplit) {
            s_dragSplit = false;
            ReleaseCapture();
            return 0;
        }
        break;

    case WM_SIZE:
        layout_children(hwnd);
        return 0;

    case WM_GETMINMAXINFO: {
        MINMAXINFO *mm = (MINMAXINFO *)lp;
        mm->ptMinTrackSize.x = ff_scale(700);
        mm->ptMinTrackSize.y = ff_scale(420);
        return 0;
    }

    case WM_COMMAND: {
        int id = LOWORD(wp);
        int code = HIWORD(wp);

        /* 组合框通知必须优先判断：CBN_SELCHANGE 的取值恰好也是 1，
         * 若先落到下面的通用分支，会被当成普通命令吞掉，下拉点选就永远不跳转。
         * 这里只认 CBN_SELENDOK（用户在下拉列表里显式点选/回车提交），
         * 不用 CBN_SELCHANGE —— 后者在编辑框打字时会被自动匹配项不断触发，
         * 会导致每敲一个字符都跳转一次。 */
        if ((HWND)lp == g_app.addr) {
            if (code == CBN_SELENDOK) {
                /* 必须取列表选中项（CB_GETCURSEL），不能读编辑框：
                 * 此刻编辑框里还是用户敲的旧内容，读它会跳到旧路径，
                 * 于是"点一次没反应、点两次才对" */
                addr_goto_from_combo((int)SendMessageW(g_app.addr, CB_GETCURSEL, 0, 0));
                SetFocus(g_app.list);
            }
            return 0;
        }

        if (code == 0 || code == 1) {
            do_command(id);
            return 0;
        }
        break;
    }

    case WM_FF_SELCHANGED:
        ff_list_take_sel_flag();
        ff_update_ui_state();
        return 0;

    case WM_FF_OW_CLEANUP:
        open_with_clear();
        return 0;

    case WM_FF_TAB_SEL:
        tab_select((int)wp);
        return 0;
    case WM_FF_TAB_CLOSE:
        tab_close((int)wp);
        return 0;
    case WM_FF_TAB_NEW:
        tab_new(cur_tab()->dir);
        return 0;
    case WM_FF_TAB_RCLICK: {
        HMENU m = CreatePopupMenu();
        int idx = s_active;
        AppendMenuW(m, MF_STRING, CMD_NEWFOLDER + 1000, L"新建标签页\tCtrl+T");
        if (s_tabCount > 1)
            AppendMenuW(m, MF_STRING, CMD_NEWFOLDER + 1001, L"关闭当前标签页\tCtrl+W");
        AppendMenuW(m, MF_SEPARATOR, 0, NULL);
        AppendMenuW(m, MF_STRING, CMD_NEWFOLDER + 1002, L"关闭其他标签页");
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        int r = (int)TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                    pt.x, pt.y, 0, hwnd, NULL);
        DestroyMenu(m);
        if (r == CMD_NEWFOLDER + 1000) tab_new(cur_tab()->dir);
        else if (r == CMD_NEWFOLDER + 1001) tab_close(idx);
        else if (r == CMD_NEWFOLDER + 1002) {
            while (s_tabCount > 1) tab_close(s_tabCount - 1);
        }
        return 0;
    }

    case WM_FF_ACTIVATE:
        cmd_open();
        return 0;

    case WM_FF_CONTEXT: {
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        /* 右键命中空白处则清除选择 */
        POINT cp = pt;
        ScreenToClient(g_app.list, &cp);
        LVHITTESTINFO ht;
        ZeroMemory(&ht, sizeof(ht));
        ht.pt = cp;
        ListView_HitTest(g_app.list, &ht);
        if (ht.iItem >= 0 && !(ListView_GetItemState(g_app.list, ht.iItem, LVIS_SELECTED) & LVIS_SELECTED)) {
            ListView_SetItemState(g_app.list, -1, 0, LVIS_SELECTED);
            ff_list_focus_item(g_app.list, ht.iItem);
        } else if (ht.iItem < 0) {
            ListView_SetItemState(g_app.list, -1, 0, LVIS_SELECTED);
        }
        ff_update_ui_state();
        if (GetKeyState(VK_CONTROL) < 0)
            popup_menu(build_menu(true), pt);      /* Ctrl+右键：本程序自己那份 */
        else
            request_shell_menu();                  /* 右键：直接 Windows 那份 */
        return 0;
    }

    case WM_FF_TREE_RCLICK: {
        /* 目录树右键：节点已由 ff_tree_notify 设为选中（导航也随之发生），
         * 这里直接复用列表那套上下文菜单。 */
        POINT pt = { GET_X_LPARAM(lp), GET_Y_LPARAM(lp) };
        tree_context_menu(pt);
        return 0;
    }

    case WM_FF_TREE_DRAG:
        /* 目录树节点左键拖动（TVN_BEGINDRAG 转发，lp=节点完整路径） */
        tree_drag_out((const wchar_t *)lp);
        return 0;

    case WM_FF_SHELL_MENU: {
        /* 延后到这里才真的弹系统菜单：此刻上一份菜单已经彻底收完、
         * 键盘/鼠标队列也清了，新菜单才不会被系统立刻收掉。
         * 弹出位置用光标当前坐标 —— 点「更多选项」时鼠标就停在它上面，
         * 和 Win11 的"显示更多选项"一样从光标处展开。
         * ★s_shellPaths 要活到菜单关闭：shellmenu.c 的宿主动词回调（重命名等）
         *   要靠它知道操作对象。 */
        POINT pt;
        GetCursorPos(&pt);
        bool did = ff_shell_menu_show(g_app.main, g_app.curDir,
                                      (const wchar_t **)s_shellPaths,
                                      s_shellCount, pt);
        ff_free_paths(s_shellPaths, s_shellCount);
        s_shellPaths = NULL;
        s_shellCount = 0;
        if (did) ff_refresh(true);   /* 扩展可能压缩/删除/改名过，立刻重读 */
        return 0;
    }

    case WM_FF_TREE_MENU_END:
        /* 树右键菜单已收且命令已处理：恢复"选中集=列表选中项"。
         * 这条消息在 tree_context_menu 里投递，排在菜单命令之后。 */
        s_treeMenuSel[0] = 0;
        return 0;

    case WM_FF_TREE_CONFIRM:
        /* 拖动落手确认：DoDragDrop 已完全返回，这里弹菜单/执行是安全的
         * （在 Drop 里直接弹会因模态泵重入 OLE 循环，同一松手执行两遍）。
         * 上下文在 dtgt_Drop / tree_drag_out 兜底里存进 s_pendingDrop*。 */
        if (s_pendingDropSrc[0] && s_pendingDropDst[0]) {
            tree_drop_confirm(s_pendingDropSrc, s_pendingDropDst, s_pendingDropPt);
            s_pendingDropSrc[0] = 0;
            s_pendingDropDst[0] = 0;
        }
        return 0;

    case WM_FF_SORTED: {
        FfTab *t = cur_tab();
        t->sortCol = (int)LOWORD(lp);
        t->sortAsc = HIWORD(lp) ? TRUE : FALSE;
        build_order(t);
        refresh_list();
        update_status();
        return 0;
    }

    case WM_FF_WATCH:
        /* 目录有变化（可能是刚刚点完的删除，也可能是 WinRAR 在解压）。
         * 用定时器去抖：解压几百个文件会连发几十条通知，合并成一次刷新。 */
        DBG(L"WM_FF_WATCH 收到，去抖 350ms");
        SetTimer(g_app.main, FF_TIMER_WATCH, 350, NULL);
        return 0;

    case WM_ACTIVATE:
        /* 从别的程序切回本窗口：期间可能有解压/删除/改名已经完成，
         * 同样走一次去抖刷新（"回来就是最新状态"）。 */
        if (LOWORD(wp) != 0) SetTimer(g_app.main, FF_TIMER_WATCH, 300, NULL);
        return 0;

    case WM_TIMER:
        if (wp == FF_TIMER_RENAME) {
            /* 第一段：先夺回焦点，再等一小段让焦点/激活真正稳定下来 */
            KillTimer(g_app.main, FF_TIMER_RENAME);
            SetActiveWindow(g_app.main);
            SetFocus(g_app.list);
            SetTimer(g_app.main, FF_TIMER_RENAME2, 150, NULL);
        } else if (wp == FF_TIMER_WATCH) {
            KillTimer(g_app.main, FF_TIMER_WATCH);
            DBG(L"FF_TIMER_WATCH: 执行刷新");
            refresh_from_watch();
        } else if (wp == FF_TIMER_RENAME2) {
            /* 第二段：这时才建编辑框 —— 太早建会被菜单收尾的消息立刻取消 */
            KillTimer(g_app.main, FF_TIMER_RENAME2);
            DBG(L"timer rename: focus=%p fg=%p", (void *)GetFocus(),
                (void *)GetForegroundWindow());
            cmd_rename();
        }
        return 0;


    case WM_FF_RENAME: {
        if (wp == 0) return 0;
        wchar_t *newName = (wchar_t *)lp;
        FfTab *t = cur_tab();
        /* ★焦点行可能已被前面的对话框/菜单弄丢，退回"当前选中项" */
        int row = ListView_GetNextItem(g_app.list, -1, LVNI_FOCUSED);
        if (row < 0) {
            int rr[MAX_SEL];
            if (ff_list_selected(g_app.list, rr, MAX_SEL) > 0) row = rr[0];
        }
        const FfEntry *e = ff_list_row_entry(g_app.list, row);
        if (!e) { DBG(L"WM_FF_RENAME: 没有可改名的行 row=%d", row); return 0; }
        wchar_t oldPath[FF_PATH_MAX];
        entry_full_path(t, e, oldPath, FF_PATH_MAX);
        if (_wcsicmp(e->name, newName) == 0) return 0;

        /* 名字合法性检查 */
        static const wchar_t *bad = L"\\/:*?\"<>|";
        for (const wchar_t *p = newName; *p; ++p) {
            if (wcschr(bad, *p)) {
                ff_msg_error(g_app.main, L"名称中不能包含下列字符：\\ / : * ? \" < > |");
                return 0;
            }
        }
        DBG(L"WM_FF_RENAME: old=%ls new=%ls", oldPath, newName);
        if (!fs_rename(oldPath, newName)) {
            ff_msg_error(g_app.main, L"重命名失败，目标名称可能已存在，或文件正在被占用。");
            return 0;
        }
        /* 记下这一次重命名，供"更多选项"里的「撤消 重命名」用（只记最近一次）：
         * 把旧完整路径的最后一段换成新名字即可 */
        ff_str_copy(s_undoFrom, FF_PATH_MAX, oldPath);
        ff_str_copy(s_undoTo, FF_PATH_MAX, oldPath);
        {
            wchar_t *sl = wcsrchr(s_undoTo, L'\\');
            if (sl) ff_str_copy(sl + 1, FF_PATH_MAX - (size_t)(sl + 1 - s_undoTo), newName);
        }
        ff_refresh(true);
        ff_update_ui_state();
        return 0;
    }

    case WM_FF_ADDR:
        return 0;

    case WM_FF_BEGINDRAG:
        /* 左键从列表拖出选中的文件（拖到程序图标=打开，拖到文件夹=复制/移动） */
        drag_out_selected();
        return 0;

    case WM_DROPFILES:
        /* 文件被拖到本程序上（列表转发或拖到主窗口其它区域） */
        handle_drop_files((HDROP)wp);
        return 0;

    case WM_NOTIFY: {
        NMHDR *nh = (NMHDR *)lp;
        if (g_app.list && nh->hwndFrom == g_app.list)
            return ff_list_notify(g_app.list, nh);
        if (g_app.tree && nh->hwndFrom == g_app.tree)
            return ff_tree_notify(g_app.tree, nh);
        if (g_app.addrBar && nh->hwndFrom == g_app.addrBar)
            return 0;
        break;
    }

    case WM_SETFOCUS: {
        /* 只有焦点从窗口外（如从其它程序 Alt-Tab 切回，此时 GetFocus 可能为
         * NULL 或主窗口自身）回来时，才把键盘焦点交还给列表。
         * 若焦点已经落在某个子控件上（地址栏编辑框、树、列表等），绝不要
         * 抢走它——否则点击地址栏时焦点会被立刻夺回列表，导致无法输入路径。 */
        HWND f = GetFocus();
        if (f == NULL || f == hwnd || !IsChild(hwnd, f))
            SetFocus(g_app.list);
        return 0;
    }

    /* 系统右键菜单（shellmenu.c）显示期间，TrackPopupMenu 的模态循环会把
     * owner-draw 与弹出通知派发到本窗口，必须转给扩展的 IContextMenu2/3：
     * 不转的话扩展自绘的项是空白、它自己的二级子菜单（WinRAR 的
     * "解压到 xxx\"）展不开。
     * 没有系统菜单在显示时 ff_shell_menu_msg 恒返回 false，直接落到
     * DefWindowProc，对其它控件零影响。 */
    case WM_DRAWITEM:
    case WM_MEASUREITEM:
    case WM_MENUCHAR: {
        LRESULT r = 0;
        if (ff_shell_menu_msg(msg, wp, lp, &r)) return r;
        break;
    }

    case WM_INITMENUPOPUP: {
        {
            LRESULT r = 0;
            if (ff_shell_menu_msg(msg, wp, lp, &r)) return r;
        }
        /* 菜单栏里的勾选项每次展开都要按当前状态刷新（菜单栏是启动时建好的，
         * 视图模式/目录树可见性此后可能已经变过）。
         * 右键菜单是每次现建的，句柄不会等于这两个，无需处理。 */
        HMENU opened = (HMENU)wp;
        if (s_menuView && opened == s_menuView) {
            /* 注意：不能用 CheckMenuRadioItem —— 它按 ID 数值区间界定分组，
             * 而本工程的 CMD_VIEW_* 数值并不连续（20023/20020/20021/20022），
             * 调用会直接返回 FALSE 且什么都不改。逐个显式打勾才可靠。 */
            FfTab *t = cur_tab();
            UINT cur = view_cmd_from_mode(t->viewMode);
            static const UINT ids[] = { CMD_VIEW_DETAIL, CMD_VIEW_LARGE,
                                        CMD_VIEW_SMALL,  CMD_VIEW_LIST };
            for (int i = 0; i < 4; ++i)
                CheckMenuItem(s_menuView, ids[i],
                              MF_BYCOMMAND | (ids[i] == cur ? MF_CHECKED : MF_UNCHECKED));
            CheckMenuItem(s_menuView, CMD_TOGGLE_ADDRBAR,
                          MF_BYCOMMAND | (g_app.addrBarVisible ? MF_CHECKED : MF_UNCHECKED));
        } else if (s_menuGo && opened == s_menuGo) {
            CheckMenuItem(s_menuGo, CMD_TOGGLE_TREE,
                          MF_BYCOMMAND | (g_app.treeVisible ? MF_CHECKED : MF_UNCHECKED));
        }
        return 0;
    }

    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLORBTN:
        return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);

    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;

    case WM_DESTROY:
        fs_watch_stop();
        /* 退出前撤销 OLE 拖放目标 */
        if (g_app.tree) RevokeDragDrop(g_app.tree);
        if (g_app.list) RevokeDragDrop(g_app.list);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

/* ===================================================== 主窗口创建 */
bool ff_main_register(HINSTANCE inst)
{
    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = ff_main_proc;
    wc.hInstance = inst;
    wc.hIcon = LoadIconW(inst, (LPCWSTR)1);
    wc.hIconSm = LoadIconW(inst, (LPCWSTR)1);
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = FF_APP_CLASS;
    return RegisterClassExW(&wc) != 0;
}

void ff_main_init(void)
{
    if (!s_tabs) s_tabs = (FfTab *)calloc(MAX_TABS, sizeof(FfTab));
    s_cfDropEffect = RegisterClipboardFormatW(L"Preferred DropEffect");
    s_tabCount = 1;
    s_active = 0;
    ZeroMemory(&s_tabs[0], sizeof(FfTab));
    s_tabs[0].sortCol = COL_NAME;
    s_tabs[0].sortAsc = TRUE;
    s_tabs[0].viewMode = LVS_REPORT;
}

void ff_main_setup(void)
{
    g_app.filterPanel = filter_panel_create(g_app.main);
    if (g_app.filterPanel) {
        ShowWindow(g_app.filterPanel, SW_HIDE);
        SendMessageW(g_app.filterPanel, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
    }
    build_address_list();
    {
        HWND edit = FindWindowExW(g_app.addr, NULL, L"Edit", NULL);
        if (edit) SetWindowSubclass(edit, addr_edit_proc, 1, 0);
    }

    /* 地址栏面包屑层：盖在地址编辑框上，点路径段直达目录（详见 crumb_proc） */
    {
        WNDCLASSW wc;
        ZeroMemory(&wc, sizeof(wc));
        wc.style = CS_DBLCLKS;          /* 需要双击消息来进入编辑态 */
        wc.lpfnWndProc = crumb_proc;
        wc.hInstance = g_app.inst;
        wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
        wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);   /* 无背景时未绘制区是黑的 */
        wc.lpszClassName = L"FFCrumb";
        RegisterClassW(&wc);
        /* WS_CLIPSIBLINGS:兄弟窗口(组合框)重绘时排除面包屑区域,
         * 否则组合框每次重绘都会把面包屑盖掉(表现为"要鼠标移过才出现") */
        s_crumb = CreateWindowExW(0, L"FFCrumb", L"", WS_CHILD | WS_CLIPSIBLINGS,
                                  0, 0, 10, 10, g_app.main, NULL, g_app.inst, NULL);
        crumb_reposition();
    }

    /* 主菜单常驻窗口标题栏下方（菜单栏属于非客户区，GetClientRect 会自动排除它，
     * 所以下面工具栏/标签栏的布局不用改，整体自然下移一行）。 */
    s_menuBar = build_main_menu();
    if (s_menuBar) {
        SetMenu(g_app.main, s_menuBar);
        DrawMenuBar(g_app.main);
    }
}

void ff_show_search_results(FfEntryList *list, const wchar_t *pattern)
{
    if (!list) return;
    FfTab *t = cur_tab();
    fs_entry_list_free(&t->raw);
    t->raw = *list;
    ZeroMemory(list, sizeof(FfEntryList));
    t->dir[0] = 0;
    t->searchMode = true;
    t->sortCol = COL_NAME;
    t->sortAsc = TRUE;
    build_order(t);
    update_title();
    set_address_text(L"");
    refresh_list();
    ff_update_ui_state();
    wchar_t msg[512];
    StringCchPrintfW(msg, 512, L"查找完成：%s 共匹配 %d 项，结果已列出。",
             pattern ? pattern : L"", t->raw.count);
    ff_set_status(msg);
}
