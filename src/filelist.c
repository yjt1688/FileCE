/* filelist.c —— 虚拟列表文件视图（LVS_OWNERDATA）
 *
 * 速度设计：
 *   1. 列表控件只请求"当前可见行"的数据，十万级目录也是瞬间呈现；
 *   2. 类型名 / 图标索引一律延迟到首次绘制时解析，并按扩展名缓存；
 *   3. 排序与筛选由主窗口在整型索引数组上完成，不移动记录本身。
 */
#include "ff.h"

#define CLR_DRIVE_TYPE  RGB(128, 120,  0)     /* 驱动器类型：橄榄色（与原版一致） */
#define CLR_SIZE        RGB( 22, 132,  22)    /* 大小：绿色 */
#define CLR_DIM         RGB(140, 140, 140)    /* 隐藏/系统对象 */
#define CLR_FOLDER      RGB( 20,  20,  20)

static FfEntry *s_raw = NULL;      /* 由主窗口提供的记录数组 */
static int      s_rawCount = 0;
static int     *s_order = NULL;    /* 记录下标，已按当前规则排序并筛选 */
static int      s_orderCount = 0;
static int      s_sortCol = COL_NAME;
static BOOL     s_sortAsc = TRUE;
static int      s_lastHit = -1;
static bool     s_selPosted = false;

static const struct {
    const wchar_t *title;
    int            width;
    int            fmt;
} s_cols[COL_COUNT] = {
    { L"名称",     260, LVCFMT_LEFT  },
    { L"类型",     128, LVCFMT_LEFT  },
    { L"大小",     104, LVCFMT_RIGHT },
    { L"属性",      70, LVCFMT_LEFT  },
    { L"修改时间", 132, LVCFMT_LEFT  },
    { L"创建时间", 132, LVCFMT_LEFT  },
};

/* ===================================================== 懒解析 */
static void ensure_meta(FfEntry *e)
{
    if (!e) return;
    if (!e->type[0]) fs_get_file_type(e->name, e->attrs, e->type, 128);
    /* 图标：普通类型按扩展名（零 I/O）；.exe/.dll/.ico/.lnk 这类"图标长在文件里"
     * 的必须拿真实路径问 Shell，否则全是通用应用程序图标（详见 fs_icon_for_entry） */
    if (e->iconIndex < 0) e->iconIndex = fs_icon_for_entry(g_app.curDir, e->name, e->attrs);
}

const FfEntry *ff_list_row_entry(HWND list, int row)
{
    (void)list;
    if (row < 0 || row >= s_orderCount) return NULL;
    int i = s_order[row];
    if (i < 0 || i >= s_rawCount) return NULL;      /* 组头行(负数)也是 NULL */
    return &s_raw[i];
}

int ff_list_row_of_entry(HWND list, const FfEntry *e)
{
    (void)list;
    if (!e || !s_raw) return -1;
    ptrdiff_t idx = e - s_raw;
    if (idx < 0 || idx >= s_rawCount) return -1;
    for (int r = 0; r < s_orderCount; ++r) if (s_order[r] == (int)idx) return r;
    return -1;
}

/* ===================================================== 数据绑定 */
static void update_sort_header(HWND list, int col, BOOL asc)
{
    HWND hd = ListView_GetHeader(list);
    if (!hd) return;
    int n = Header_GetItemCount(hd);
    for (int i = 0; i < n; ++i) {
        HDITEMW hi;
        ZeroMemory(&hi, sizeof(hi));
        hi.mask = HDI_FORMAT;
        Header_GetItem(hd, i, &hi);
        hi.fmt &= ~(HDF_SORTUP | HDF_SORTDOWN);
        if (i == col) hi.fmt |= (asc ? HDF_SORTUP : HDF_SORTDOWN);
        Header_SetItem(hd, i, &hi);
    }
}

void ff_list_set_data(HWND list, FfEntry *raw, int rawCount,
                      int *order, int orderCount, int sortCol, BOOL sortAsc)
{
    s_raw = raw;
    s_rawCount = rawCount;
    s_order = order;
    s_orderCount = orderCount;
    s_sortCol = sortCol;
    s_sortAsc = sortAsc;
    s_lastHit = -1;
    if (!list) return;

    int top = ListView_GetTopIndex(list);
    /* 虚拟列表收缩的致命坑：若先 LVM_SETITEMCOUNT 缩小数量，comctl 不会
     * 重排滚动原点——上一目录滚动到很下方(top=84)再进入只有几项的目录时，
     * 原点悬停在内容之外(GetTopIndex 返回 -84)，报告视口全白，切视图强制
     * 重排版才恢复；此时再 LVM_SCROLL 也救不回来(滚动条已在顶部)。
     * 所以必须在旧数据仍有效时先把原点钳制回顶部，再改数量。 */
    SendMessageW(list, LVM_SCROLL, 0, -1000000);
    /* 不能带 LVSICF_NOINVALIDATEALL：它让控件认为旧行"内容没变"而不作废，
     * 目录切换后旧可见行全部保留旧画面/空白，只有鼠标逐行悬停才重绘。
     * 虚拟列表数据是整体更换的，必须全量作废重绘。 */
    SendMessageW(list, LVM_SETITEMCOUNT, (WPARAM)orderCount, 0);
    update_sort_header(list, sortCol, sortAsc);
    InvalidateRect(list, NULL, TRUE);
    if (top > 0 && top < orderCount) ListView_EnsureVisible(list, top, FALSE);
}

int ff_list_count(HWND list) { (void)list; return s_orderCount; }
int ff_list_raw_count(HWND list) { (void)list; return s_rawCount; }

/* ===================================================== 列 */
void ff_list_init_columns(HWND list)
{
    LVCOLUMNW c;
    for (int i = 0; i < COL_COUNT; ++i) {
        ZeroMemory(&c, sizeof(c));
        c.mask = LVCF_TEXT | LVCF_WIDTH | LVCF_FMT | LVCF_SUBITEM;
        c.pszText = (LPWSTR)s_cols[i].title;
        c.cx = ff_scale(s_cols[i].width);
        c.fmt = s_cols[i].fmt;
        c.iSubItem = i;
        ListView_InsertColumn(list, i, &c);
    }
}

static void autofit_columns(HWND list)
{
    LONG_PTR style = GetWindowLongPtrW(list, GWL_STYLE);
    if ((style & LVS_TYPEMASK) != LVS_REPORT) return;
    RECT rc;
    GetClientRect(list, &rc);
    int total = 0;
    for (int i = 1; i < COL_COUNT; ++i) {
        LVCOLUMNW c;
        ZeroMemory(&c, sizeof(c));
        c.mask = LVCF_WIDTH;
        ListView_GetColumn(list, i, &c);
        total += c.cx;
    }
    int extra = (rc.right - rc.left) - total - ff_scale(26);
    int minw = ff_scale(160);
    if (extra < minw) extra = minw;
    ListView_SetColumnWidth(list, COL_NAME, extra);
}

/* ===================================================== 选中 */
int ff_list_selected(HWND list, int *rows, int max)
{
    int n = 0, idx = -1;
    while ((idx = ListView_GetNextItem(list, idx, LVNI_SELECTED)) >= 0) {
        if (n >= max) break;
        rows[n++] = idx;
    }
    return n;
}

void ff_list_focus_item(HWND list, int row)
{
    if (row < 0 || row >= s_orderCount) return;
    ListView_SetItemState(list, -1, 0, LVIS_SELECTED);
    ListView_SetItemState(list, row, LVIS_SELECTED | LVIS_FOCUSED,
                          LVIS_SELECTED | LVIS_FOCUSED);
    ListView_EnsureVisible(list, row, FALSE);
}

void ff_list_apply_view(HWND list, int viewMode)
{
    LONG_PTR style = GetWindowLongPtrW(list, GWL_STYLE);
    style &= ~LVS_TYPEMASK;
    style |= (viewMode & LVS_TYPEMASK);
    SetWindowLongPtrW(list, GWL_STYLE, style);
    InvalidateRect(list, NULL, TRUE);
}

int ff_list_view_mode(HWND list)
{
    return (int)(GetWindowLongPtrW(list, GWL_STYLE) & LVS_TYPEMASK);
}

/* ===================================================== 分组头（此电脑视图）
 * comctl32 v6 不允许在 LVS_OWNERDATA 虚拟列表上启用原生组视图
 * （LVM_ENABLEGROUPVIEW 恒返回 -1，实测 Win10）。所以组头改为
 * "特殊数据行"：order 数组里的负数下标（FF_ORDER_HDR_*），
 * custom_draw 里整行自绘成 Win10 风格的组标题。 */
static int  s_grpDrv = 0;                   /* 组内条数，用于组头标题 */
static wchar_t s_hdrDrv[80] = L"";

void ff_list_set_group_counts(int drvCount)
{
    s_grpDrv = drvCount;
    StringCchPrintfW(s_hdrDrv, 80, L"设备和驱动器 (%d)", drvCount);
}

/* 当前行是不是组头行；是的话把标题文本填进 out */
static bool row_is_header(int row, const wchar_t **text)
{
    if (row < 0 || row >= s_orderCount) return false;
    int i = s_order[row];
    if (i == FF_ORDER_HDR_DRIVE) { *text = s_hdrDrv; return true; }
    return false;
}

/* ===================================================== 自定义绘制 */
static HFONT hdr_bold_font(void)
{
    static HFONT s_bold = NULL;
    if (!s_bold) {
        HFONT base = ff_ui_font();
        LOGFONTW lf;
        ZeroMemory(&lf, sizeof(lf));
        if (base && GetObjectW(base, sizeof(lf), &lf)) {
            lf.lfWeight = FW_BOLD;
        } else {
            lf.lfHeight = -12;
            lf.lfWeight = FW_BOLD;
            wcscpy_s(lf.lfFaceName, 32, L"Segoe UI");
        }
        s_bold = CreateFontIndirectW(&lf);
    }
    return s_bold;
}

/* 组头行整行自绘：浅色背景 + 灰色粗体标题 + 底部浅分隔线（Win10 组头风格） */
static void draw_header_row(HDC hdc, const RECT *rc, const wchar_t *text)
{
    FillRect(hdc, rc, (HBRUSH)(COLOR_WINDOW + 1));
    SetBkMode(hdc, TRANSPARENT);
    HFONT old = (HFONT)SelectObject(hdc, hdr_bold_font());
    SetTextColor(hdc, RGB(0x60, 0x60, 0x60));
    RECT tr = *rc;
    tr.left += ff_scale(10);
    DrawTextW(hdc, text, -1, &tr, DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS);
    SelectObject(hdc, old);
    RECT line = { rc->left, rc->bottom - ff_scale(1), rc->right, rc->bottom };
    FillRect(hdc, &line, (HBRUSH)GetStockObject(LTGRAY_BRUSH));
}

static LRESULT custom_draw(HWND list, NMLVCUSTOMDRAW *cd)
{
    switch (cd->nmcd.dwDrawStage) {
    case CDDS_PREPAINT:
        return CDRF_NOTIFYITEMDRAW;
    case CDDS_ITEMPREPAINT: {
        int row = (int)cd->nmcd.dwItemSpec;
        const wchar_t *hdr = NULL;
        if (row_is_header(row, &hdr)) {
            draw_header_row(cd->nmcd.hdc, &cd->nmcd.rc, hdr);
            return CDRF_SKIPDEFAULT;        /* 整行已自绘，控件不再画 */
        }
        return CDRF_NOTIFYSUBITEMDRAW;
    }
    case CDDS_ITEMPREPAINT | CDDS_SUBITEM: {
        int row = (int)cd->nmcd.dwItemSpec;
        const FfEntry *e = ff_list_row_entry(list, row);
        if (!e) return CDRF_DODEFAULT;
        if (cd->nmcd.uItemState & (CDIS_SELECTED | CDIS_HOT)) return CDRF_DODEFAULT;
        COLORREF clr = CLR_FOLDER;
        if (e->attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)) clr = CLR_DIM;
        else if (cd->iSubItem == COL_TYPE && e->isDrive) clr = CLR_DRIVE_TYPE;
        else if (cd->iSubItem == COL_SIZE && !e->isDir) clr = CLR_SIZE;
        cd->clrText = clr;
        cd->clrTextBk = (COLORREF)-1;
        return CDRF_NEWFONT;
    }
    default:
        break;
    }
    return CDRF_DODEFAULT;
}

/* ===================================================== 通知处理
 * 注意：控件通知统一由父窗口（主窗口）转发进来，
 *       因为 comctl32 的 LVN_* 是发给父窗口而非控件自身。 */
LRESULT ff_list_notify(HWND list, NMHDR *nh)
{
    switch (nh->code) {
    case NM_CUSTOMDRAW:
        return custom_draw(list, (NMLVCUSTOMDRAW *)nh);

    case LVN_GETDISPINFOW: {
        NMLVDISPINFOW *di = (NMLVDISPINFOW *)nh;
        int row = di->item.iItem;
        if (row < 0 || row >= s_orderCount) return 0;
        int i = s_order[row];

        /* 组头行（负数下标）：显示由 custom_draw 整行接管，这里只提供
         * 名称列文本（键盘查找/探针/无障碍用），无图标 */
        if (i < 0) {
            const wchar_t *hdr = NULL;
            row_is_header(row, &hdr);
            if ((di->item.mask & LVIF_TEXT) &&
                di->item.pszText && di->item.cchTextMax > 0) {
                int cch = di->item.cchTextMax - 1;
                int len = 0;
                while (hdr && hdr[len] && len < cch) { di->item.pszText[len] = hdr[len]; ++len; }
                di->item.pszText[len] = 0;
            }
            if (di->item.mask & LVIF_IMAGE) di->item.iImage = -1;
            return 0;
        }

        if (i >= s_rawCount) return 0;
        FfEntry *e = &s_raw[i];
        ensure_meta(e);

        if (di->item.mask & LVIF_TEXT) {
            wchar_t buf[64];
            const wchar_t *src = buf;
            switch (di->item.iSubItem) {
            case COL_NAME:
                src = e->name;
                break;
            case COL_TYPE:
                src = e->type;
                break;
            case COL_SIZE:
                if (e->isDir && !e->isDrive) buf[0] = 0;
                else ff_format_size(e->size, buf, 64);
                break;
            case COL_ATTR:
                ff_format_attr(e->attrs, buf, 64);
                break;
            case COL_MTIME:
                ff_format_dt(&e->mtime, buf, 64);
                break;
            case COL_CTIME:
                ff_format_dt(&e->ctime, buf, 64);
                break;
            default:
                buf[0] = 0;
                break;
            }
            /* v6 listview 要求写回调用方缓冲区，不能替换 pszText 指针 */
            if (di->item.pszText && di->item.cchTextMax > 0) {
                int cch = di->item.cchTextMax - 1;
                int len = 0;
                while (src[len] && len < cch) { di->item.pszText[len] = src[len]; ++len; }
                di->item.pszText[len] = 0;
            }
        }
        if (di->item.mask & LVIF_IMAGE) {
            /* 虚拟列表的数据会整体更换，不要 LVIF_DI_SETITEM 让控件缓存；
             * iconIndex 夹紧到合法范围，-1 会让 v6 绘制异常 */
            di->item.iImage = e->iconIndex >= 0 ? e->iconIndex : 0;
        }
        return 0;
    }

    case LVN_ODFINDITEMW: {
        NMLVFINDITEMW *fi = (NMLVFINDITEMW *)nh;
        if (!fi->lvfi.psz || !s_orderCount) return -1;
        const wchar_t *pat = fi->lvfi.psz;
        size_t plen = wcslen(pat);
        int start = fi->iStart;
        for (int k = 0; k < s_orderCount; ++k) {
            int row = start + k;
            if (row >= s_orderCount) row -= s_orderCount;
            const FfEntry *e = ff_list_row_entry(list, row);
            if (e && _wcsnicmp(e->name, pat, plen) == 0) {
                s_lastHit = row;
                return row;
            }
        }
        return -1;
    }

    case NM_DBLCLK:
        SendMessageW(GetParent(list), WM_FF_ACTIVATE, 0, 0);
        return 0;
    case NM_RETURN:
        SendMessageW(GetParent(list), WM_FF_ACTIVATE, 1, 0);
        return 0;
    case LVN_BEGINDRAG:
        /* 左键在列表里按下并拖动：交给主窗口发起 OLE 拖出
         * （拖到桌面程序图标=用该程序打开，拖到文件夹=复制/移动） */
        DBG(L"BEGINDRAG notify");
        SendMessageW(GetParent(list), WM_FF_BEGINDRAG, 0, 0);
        return 0;
    case NM_RCLICK: {
        POINT pt;
        GetCursorPos(&pt);
        SendMessageW(GetParent(list), WM_FF_CONTEXT, 0, MAKELPARAM(pt.x, pt.y));
        return 0;
    }
    case LVN_KEYDOWN: {
        NMLVKEYDOWN *k = (NMLVKEYDOWN *)nh;
        if (k->wVKey == VK_RETURN) {
            SendMessageW(GetParent(list), WM_FF_ACTIVATE, 1, 0);
            return 0;
        }
        break;
    }
    case LVN_ENDLABELEDITW: {
        NMLVDISPINFOW *di = (NMLVDISPINFOW *)nh;
        wchar_t *txt = di->item.pszText;
        SendMessageW(GetParent(list), WM_FF_RENAME,
                     (WPARAM)(txt && txt[0] ? 1 : 0), (LPARAM)txt);
        return 0;
    }
    case LVN_COLUMNCLICK: {
        NMLISTVIEW *lv = (NMLISTVIEW *)nh;
        if (lv->iSubItem == s_sortCol) s_sortAsc = !s_sortAsc;
        else { s_sortCol = lv->iSubItem; s_sortAsc = TRUE; }
        SendMessageW(GetParent(list), WM_FF_SORTED, 2,
                     MAKEWPARAM((WORD)s_sortCol, (WORD)(s_sortAsc ? 1 : 0)));
        return 0;
    }
    case LVN_ITEMCHANGED: {
        NMLISTVIEW *lv = (NMLISTVIEW *)nh;
        if ((lv->uChanged & LVIF_STATE) &&
            ((lv->uNewState ^ lv->uOldState) & LVIS_SELECTED)) {
            if (!s_selPosted) {
                s_selPosted = true;
                PostMessageW(GetParent(list), WM_FF_SELCHANGED, 0, 0);
            }
        }
        return 0;
    }
    case LVN_DELETEALLITEMS:
        return 0;
    }
    return 0;
}

bool ff_list_take_sel_flag(void)
{
    bool v = s_selPosted;
    s_selPosted = false;
    return v;
}

/* ===================================================== 滚动原点看门狗
 * 虚拟列表(LVS_OWNERDATA)跑久了，comctl 内部的滚动原点会自己跑成负数：
 *   ListView_GetTopIndex() 返回 -8 / -84 这种值
 * → 所有内容被画到客户区**上方**，视口只剩一片白（用户看到"右边白了、文件和
 *   目录都往下跑了"），只有鼠标逐行悬停才把那一行画回来。
 *
 * 复位手法是实测出来的（在真机上把 top 弄成 -8 后逐个试）：
 *   ✗ InvalidateRect + UpdateWindow      —— 无效
 *   ✗ LVM_SCROLL(0, -1000000)            —— 无效（滚动条已经在顶部）
 *   ✗ LVM_SETITEMCOUNT(当前数量)          —— 无效
 *   ✗ MoveWindow 尺寸抖动                 —— 无效
 *   ✓ LVM_SETVIEW 往返（LIST → 原视图）   —— 立刻回到 top=0
 * 所以这里只用 SETVIEW 往返，并先记下当前视图、切完再切回去。
 * 正常情况 top>=0 直接返回，开销可忽略。 */
static int lv_view_of_style(int lvsStyle)
{
    switch (lvsStyle & LVS_TYPEMASK) {
    case LVS_ICON:      return LV_VIEW_ICON;
    case LVS_SMALLICON: return LV_VIEW_SMALLICON;
    case LVS_LIST:      return LV_VIEW_LIST;
    default:            return LV_VIEW_DETAILS;
    }
}

static void list_fix_scroll(HWND list)
{
    static int s_fixing = 0;              /* 防重入：切视图会重排、再触发消息 */
    if (s_fixing) return;
    int top = ListView_GetTopIndex(list);
    if (top >= 0) return;

    s_fixing = 1;
    int vm = ff_list_view_mode(list);
    DBG(L"list_fix_scroll: top=%d view=%d -> SETVIEW 往返复位", top, vm);
    SendMessageW(list, LVM_SETVIEW, LV_VIEW_LIST, 0);
    SendMessageW(list, LVM_SETVIEW, lv_view_of_style(vm), 0);
    InvalidateRect(list, NULL, TRUE);
    s_fixing = 0;
}

/* ===================================================== 窗口过程 */
static LRESULT CALLBACK list_subclass(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                      UINT_PTR id, DWORD_PTR ref)
{
    (void)id; (void)ref;
    switch (msg) {
    case WM_DROPFILES:
        /* 从资源管理器/桌面把文件拖进来：列表登记了 DragAcceptFiles，
         * WM_DROPFILES 先落到列表，原样转给主窗口统一处理（复制到当前目录） */
        SendMessageW(GetParent(hwnd), WM_DROPFILES, wp, lp);
        return 0;
    case WM_SIZE:
        autofit_columns(hwnd);
        break;
    case WM_SETFOCUS:
        InvalidateRect(hwnd, NULL, FALSE);
        break;
    case WM_KEYDOWN:
        if (wp == VK_BACK) {
            SendMessageW(GetParent(hwnd), WM_COMMAND, MAKEWPARAM(CMD_UP, 0), 0);
            return 0;
        }
        break;
    case WM_PAINT: {
        /* 每帧画完检查一次滚动原点；异常时下一帧就恢复正常 */
        LRESULT r = DefSubclassProc(hwnd, msg, wp, lp);
        list_fix_scroll(hwnd);
        return r;
    }
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN:
    case WM_MOUSEWHEEL:
    case WM_VSCROLL: {
        LRESULT r = DefSubclassProc(hwnd, msg, wp, lp);
        list_fix_scroll(hwnd);
        return r;
    }
    }
    return DefSubclassProc(hwnd, msg, wp, lp);
}

bool ff_list_register(HINSTANCE inst) { (void)inst; return true; }

HWND ff_list_create(HWND parent, HINSTANCE inst)
{
    HWND l = CreateWindowExW(WS_EX_CLIENTEDGE, WC_LISTVIEWW, L"",
                             WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                             LVS_REPORT | LVS_OWNERDATA | LVS_SHOWSELALWAYS |
                             LVS_EDITLABELS | WS_HSCROLL,
                             0, 0, 100, 100, parent, (HMENU)(INT_PTR)IDC_LIST,
                             inst, NULL);
    if (!l) return NULL;
    ListView_SetExtendedListViewStyle(l,
        LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_LABELTIP |
        LVS_EX_HEADERDRAGDROP);
    if (g_app.sysSmall) ListView_SetImageList(l, g_app.sysSmall, LVSIL_SMALL);
    if (g_app.sysLarge) ListView_SetImageList(l, g_app.sysLarge, LVSIL_NORMAL);
    DragAcceptFiles(l, TRUE);        /* 接收从别的程序拖进来的文件 */
    ff_list_init_columns(l);
    SendMessageW(l, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
    SetWindowSubclass(l, list_subclass, 1, 0);
    return l;
}
