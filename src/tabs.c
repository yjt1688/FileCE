/* tabs.c —— 浏览器风格多标签栏（自绘，无外部依赖）
 *
 * 浏览器风格的多标签栏：一个进程内多个标签页，
 * 每个标签各自维护目录、历史、排序与滚动位置。
 */
#include "ff.h"

#define MAX_TABS   32
#define TAB_H      30

#define CLR_TB_BG      RGB(238, 238, 238)
#define CLR_TB_LINE    RGB(208, 208, 208)
#define CLR_TAB_ON     RGB(255, 255, 255)
#define CLR_TAB_HOT    RGB(228, 228, 228)
#define CLR_TAB_TXT    RGB( 32,  32,  32)
/* 非活动标签文字色。原来是 RGB(96,96,96)，在 238 的灰底上小字号渲染出来
 * 几乎和背景融在一起 —— 用户看到的"标签一片空白"其实是字太淡（活动标签
 * 用 32 的深色 + 白底所以清楚）。对比度 96→238 只有 142，改到 64→238 后
 * 是 174，肉眼才能稳定分辨。 */
#define CLR_TAB_TXT_OFF RGB( 64,  64,  64)
/* 非活动标签之间的竖直分隔线：一排同名标签（都是"此电脑"）光靠留白
 * 分不清边界，加一条短竖线才有 Chrome / Edge 那种"一格一格"的分家感 */
#define CLR_TAB_SEP    RGB(198, 198, 198)
#define TAB_GAP        7    /* 标签之间的水平间距（逻辑像素） */
/* 窄窗压缩的分档阈值（逻辑像素）。标签宽低于 TAB_MIN_TEXT 时不再画文字 ——
 * 否则文字区会算成负数（内边距 9 + 图标 20 + 右侧 14 > 标签宽），
 * DrawTextW 画不出东西，而 × 会压到图标上。 */
#define TAB_MIN_ICON   48   /* 标签最窄宽：图标 + × 刚好放得下 */
/* 低于此宽只画图标、不画文字。
 * ★必须严格小于 measure_tab 里的最小宽 mn(=88)：非活动标签的常态宽度就是 88，
 *   门槛一旦 ≥88，所有非活动标签的文字都会被吃掉（实测过一个 96 的版本，
 *   除了活动标签全空白）。68 这个值算下来文字区还有 68-9-20-14 = 25px，
 *   够显示一两个字 + 省略号。 */
#define TAB_MIN_TEXT   68
/* 关闭按钮： Explorer / Edge 风格 —— 悬停淡灰圆底 + 深灰 ×，按下略深。
 * 之前用的红色实心圆太扎眼，与整体灰色调不协调。 */
#define CLR_CLOSE_BG   RGB(213, 213, 213)
#define CLR_CLOSE_BGDN RGB(196, 196, 196)
#define CLR_CLOSE_X    RGB( 70,  70,  70)
#define CLR_ACCENT     RGB(  0, 120, 212)

typedef struct {
    /* 80 字符足够：标签宽度有限，绘制时超长本来就要省略。
     * 原来 160 字符 × 32 个标签 = 10 KB，全进了 .data（本工具链 .bss 几乎为空）。 */
    wchar_t title[80];
    bool    loading;
    HICON   hIcon;          /* 目录图标(SHGFI_ICON 取,不共享,需 DestroyIcon) */
} TabItem;

typedef struct {
    int     count;
    int     active;
    int     hot;
    int     hotClose;
    bool    hotNew;
    int     pressed;
    int     newX;
    TabItem tabs[MAX_TABS];
} TabState;

static TabState s_ts;

int ff_tabs_height(HWND tabs) { (void)tabs; return ff_scale(TAB_H); }

void ff_tabs_update(HWND tabs, int count, int active)
{
    if (count < 0) count = 0;
    if (count > MAX_TABS) count = MAX_TABS;
    /* 新标签继承默认标题 */
    for (int i = s_ts.count; i < count; ++i)
        ff_str_copy(s_ts.tabs[i].title, 80, L"新标签");
    /* 标签数变少时，被关掉那些标签的图标要还回去，否则每关一个漏一个 HICON */
    for (int i = count; i < s_ts.count; ++i) {
        if (s_ts.tabs[i].hIcon) {
            DestroyIcon(s_ts.tabs[i].hIcon);
            s_ts.tabs[i].hIcon = NULL;
        }
    }
    s_ts.count = count;
    s_ts.active = (active >= 0 && active < count) ? active : 0;
    if (tabs) InvalidateRect(tabs, NULL, FALSE);
}

void ff_tabs_set_title(HWND tabs, int index, const wchar_t *title)
{
    if (index < 0 || index >= MAX_TABS) return;
    ff_str_copy(s_ts.tabs[index].title, 80, title);
    if (tabs) InvalidateRect(tabs, NULL, FALSE);
}

void ff_tabs_set_loading(HWND tabs, int index, bool loading)
{
    if (index < 0 || index >= MAX_TABS) return;
    s_ts.tabs[index].loading = loading;
    if (tabs) InvalidateRect(tabs, NULL, FALSE);
}

void ff_tabs_set_icon(HWND tabs, int index, HICON icon)
{
    (void)tabs; (void)icon;                 /* 图标走系统小图标列表按索引取 */
    /* 兼容旧签名:索引由 ff_tabs_set_icon_index 设置 */
}
void ff_tabs_set_icon_index(HWND tabs, int index, int iconIndex)
{
    (void)tabs; (void)iconIndex;    /* 旧接口保留(空实现):标签图标走 set_hicon */
}
void ff_tabs_set_hicon(HWND tabs, int index, HICON icon)
{
    (void)tabs;
    if (index < 0 || index >= MAX_TABS) return;
    TabItem *t = &s_ts.tabs[index];
    if (t->hIcon) { DestroyIcon(t->hIcon); t->hIcon = NULL; }
    t->hIcon = icon ? CopyIcon(icon) : NULL;
    InvalidateRect(tabs, NULL, FALSE);
}

/* ===================================================== 布局 */
static int measure_tab(HDC dc, const TabItem *t, bool active)
{
    SIZE sz;
    ZeroMemory(&sz, sizeof(sz));
    HFONT old = (HFONT)SelectObject(dc, ff_ui_font());
    GetTextExtentPoint32W(dc, t->title, (int)wcslen(t->title), &sz);
    SelectObject(dc, old);
    /* 图标 20 + 内边距 24;活动标签另加 × 按钮位 24(非活动不显示 ×)。
     * 之前对所有标签预留 × 位,非活动标签右侧一大段空白(用户实测)。 */
    int w = sz.cx + ff_scale(36) + (active ? ff_scale(14) : 0);
    /* mx/mn 的上限下限。mn 与上面 TAB_MIN_TEXT 联动：TAB_MIN_TEXT 必须 < mn */
    int mx = ff_scale(250), mn = ff_scale(88);
    if (w > mx) w = mx;
    if (w < mn) w = mn;
    return w;
}

static void layout(HWND h, int *xs, int *ws)
{
    HDC dc = GetDC(h);
    RECT cr;
    GetClientRect(h, &cr);
    /* 先把整张表清成"无效"：paint 只画 w>0 的项。
     * 之前两者共用一个栈数组，一旦某帧 count 变小、或中途出错留下半截数据，
     * paint 就会拿着上一次的旧坐标把标签画到别处（甚至画到栏外），
     * 表现为"前面几个标签整片空白、只有一个位置有内容"。 */
    for (int i = 0; i < MAX_TABS; ++i) { xs[i] = 0; ws[i] = 0; }
    int x = ff_scale(6);
    int total = 0;
    int avail = cr.right - ff_scale(8) - ff_scale(30);
    for (int i = 0; i < s_ts.count; ++i) {
        int w = measure_tab(dc, &s_ts.tabs[i], i == s_ts.active);
        xs[i] = x;
        ws[i] = w;
        x += w + ff_scale(TAB_GAP);
        total = x;
    }
    /* 窗口变窄时整体按比例压缩(减去"+"按钮的预留位),最小宽不保 */
    if (s_ts.count > 0 && total > avail && total > 0) {
        double k = (double)avail / (double)total;
        if (k < 0.4) k = 0.4;
        /* 间距跟着一起缩：标签只剩 40 多像素时，7px 间隙会占掉可见宽度的一成多，
         * 竖线也会贴到标签圆角上 */
        int gap = (int)(ff_scale(TAB_GAP) * k);
        int gapMin = ff_scale(2);
        if (gap < gapMin) gap = gapMin;
        int minW = ff_scale(TAB_MIN_ICON);   /* 关键：不让标签被压到放不下图标+× */
        int px = ff_scale(6);
        for (int i = 0; i < s_ts.count; ++i) {
            int nw = (int)(ws[i] * k);
            if (nw < minW) nw = minW;
            xs[i] = px;
            ws[i] = nw;
            px += nw + gap;
        }
        s_ts.newX = px + ff_scale(8);
    } else {
        s_ts.newX = x + ff_scale(8);
    }
    ReleaseDC(h, dc);
}

/* ===================================================== 绘制 */
/* 关闭按钮：hot=悬停(淡灰圆底)，down=按下(深一档) */
static void draw_close(HDC dc, int cx, int cy, int sz, bool hot, bool down)
{
    if (hot || down) {
        HBRUSH b = CreateSolidBrush(down ? CLR_CLOSE_BGDN : CLR_CLOSE_BG);
        HGDIOBJ o = SelectObject(dc, b);
        HGDIOBJ p = SelectObject(dc, GetStockObject(NULL_PEN));
        Ellipse(dc, cx - sz / 2, cy - sz / 2, cx + sz / 2, cy + sz / 2);
        SelectObject(dc, o); SelectObject(dc, p);
        DeleteObject(b);
    }
    HPEN pen = CreatePen(PS_SOLID, MAX(1, ff_scale(1)), CLR_CLOSE_X);
    HGDIOBJ op = SelectObject(dc, pen);
    int a = sz / 2 - ff_scale(4);
    MoveToEx(dc, cx - a, cy - a, NULL); LineTo(dc, cx + a + 1, cy + a + 1);
    MoveToEx(dc, cx + a, cy - a, NULL); LineTo(dc, cx - a - 1, cy + a + 1);
    SelectObject(dc, op);
    DeleteObject(pen);
}

static void paint(HWND h)
{
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(h, &ps);
    RECT cr;
    GetClientRect(h, &cr);
    if (cr.right <= 0 || cr.bottom <= 0) { EndPaint(h, &ps); return; }

    HDC mem = CreateCompatibleDC(dc);
    HBITMAP bmp = CreateCompatibleBitmap(dc, cr.right, cr.bottom);
    HGDIOBJ ob = SelectObject(mem, bmp);
    SetBkMode(mem, TRANSPARENT);

    HBRUSH bg = CreateSolidBrush(CLR_TB_BG);
    FillRect(mem, &cr, bg);
    DeleteObject(bg);

    /* 底边线 */
    HPEN line = CreatePen(PS_SOLID, 1, CLR_TB_LINE);
    HGDIOBJ ol = SelectObject(mem, line);
    MoveToEx(mem, 0, cr.bottom - 1, NULL);
    LineTo(mem, cr.right, cr.bottom - 1);
    SelectObject(mem, ol);
    DeleteObject(line);

    int xs[MAX_TABS], ws[MAX_TABS];
    layout(h, xs, ws);

    /* 只画本帧真正排过版的标签；w<=0 说明该索引无效，跳过，
     * 免得用脏坐标在别的位置画出半个标签。 */
    int drawCount = 0;
    for (int i = 0; i < s_ts.count && i < MAX_TABS; ++i)
        if (ws[i] > 0) drawCount = i + 1;
    if (drawCount > s_ts.count) drawCount = s_ts.count;

    int top = ff_scale(4);

    /* 标签之间的竖直分隔线。相邻两侧只要有一侧是活动标签或有悬停底色就跳过 ——
     * 那些标签自带浅底，线贴上去会显脏。 */
    if (drawCount > 1) {
        HPEN sep = CreatePen(PS_SOLID, ff_scale(1), CLR_TAB_SEP);
        HGDIOBJ os = SelectObject(mem, sep);
        int y0 = top + ff_scale(6);
        int y1 = cr.bottom - ff_scale(6);
        for (int i = 0; i + 1 < drawCount; ++i) {
            if (i == s_ts.active || i + 1 == s_ts.active) continue;
            if (s_ts.hot == i || s_ts.hot == i + 1) continue;
            int x = xs[i] + ws[i] + ff_scale(TAB_GAP) / 2;
            MoveToEx(mem, x, y0, NULL);
            LineTo(mem, x, y1);
        }
        SelectObject(mem, os);
        DeleteObject(sep);
    }

    for (int pass = 0; pass < 2; ++pass) {
        for (int i = 0; i < drawCount; ++i) {
            if (ws[i] <= 0) continue;
            bool active = (i == s_ts.active);
            if ((pass == 0) == active) continue;   /* 第一遍画非活动，第二遍画活动 */

            RECT r;
            r.left = xs[i];
            r.right = xs[i] + ws[i];
            r.top = top;
            r.bottom = active ? cr.bottom : cr.bottom - ff_scale(2);

            HBRUSH fb;
            COLORREF lineclr;
            if (active) { fb = CreateSolidBrush(CLR_TAB_ON); lineclr = CLR_TB_LINE; }
            else if (s_ts.hot == i) { fb = CreateSolidBrush(CLR_TAB_HOT); lineclr = CLR_TB_LINE; }
            else { fb = NULL; lineclr = CLR_TB_LINE; }

            if (fb) {
                HPEN fp = CreatePen(PS_SOLID, 1, lineclr);
                HGDIOBJ o1 = SelectObject(mem, fb), o2 = SelectObject(mem, fp);
                RoundRect(mem, r.left, r.top, r.right, r.bottom + ff_scale(6),
                          ff_scale(8), ff_scale(8));
                SelectObject(mem, o1); SelectObject(mem, o2);
                DeleteObject(fp);
                DeleteObject(fb);
                if (active) {
                    /* 抹掉活动标签底部的分隔线，与内容区连成一体 */
                    RECT cover = { r.left + 1, cr.bottom - 1, r.right - 1, cr.bottom };
                    HBRUSH wb = CreateSolidBrush(CLR_TAB_ON);
                    FillRect(mem, &cover, wb);
                    DeleteObject(wb);
                }
            }

            /* 图标(16px) + 标题。宽度不够时按优先级舍弃：先不画文字，再考虑不画图标，
             * 保证任何宽度下都不会出现"文字区算成负数"或"× 压在图标上"。 */
            bool roomIcon = (ws[i] >= ff_scale(TAB_MIN_ICON));
            bool roomText = (ws[i] >= ff_scale(TAB_MIN_TEXT));
            RECT tr = r;
            tr.left += ff_scale(9);
            tr.right -= ff_scale(14);
            if (s_ts.tabs[i].hIcon && roomIcon) {
                int cy = (r.top + r.bottom) / 2;
                DrawIconEx(mem, r.left + ff_scale(8), cy - ff_scale(8),
                           s_ts.tabs[i].hIcon, ff_scale(16), ff_scale(16),
                           0, NULL, DI_NORMAL);
                tr.left += ff_scale(20);
            }
            if (roomText) {
                SetTextColor(mem, active ? CLR_TAB_TXT : CLR_TAB_TXT_OFF);
                HFONT of = (HFONT)SelectObject(mem, ff_ui_font());
                DrawTextW(mem, s_ts.tabs[i].title, -1, &tr,
                          DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX);
                SelectObject(mem, of);
            }

            /* 关闭按钮：活动标签常显，非活动标签悬停时才出现，
             * 避免一排 × 与右侧"+"按钮挤在一起显得杂乱 */
            bool showClose = active || s_ts.hot == i;
            if (showClose) {
                int cx = r.right - ff_scale(9);
                int cy = (r.top + r.bottom) / 2;
                draw_close(mem, cx, cy, ff_scale(15), s_ts.hotClose == i, false);
            }
        }
    }

    /* 新建标签按钮 */
    {
        int bx = s_ts.newX;
        int by = cr.bottom / 2;          /* 相对客户区垂直居中；用 (top+bottom)/2 会把 top 算进去，整体偏下 2px */
        int sz = ff_scale(11);          /* 悬停背景圆半径，别太大压到标签 */
        if (s_ts.hotNew) {
            HBRUSH b = CreateSolidBrush(CLR_TAB_HOT);
            HGDIOBJ o = SelectObject(mem, b);
            HGDIOBJ p = SelectObject(mem, GetStockObject(NULL_PEN));
            Ellipse(mem, bx - sz, by - sz, bx + sz, by + sz);
            SelectObject(mem, o); SelectObject(mem, p);
            DeleteObject(b);
        }
        /* 加号：两个 FillRect（竖条 + 横条）。
         * 关键在**长度和笔画取同一奇偶**：竖条宽 = 笔画 t（偶），
         * 横条长 = 总长 L 也取偶，两者的中心才会落在同一个半像素上。
         * 之前长度用奇数 9、笔画用偶数 2，两个中心天然差 0.5px，
         * 视觉上就是"左边和上边各差一点"（竖条偏左、横条偏上）。 */
        {
            int t = MAX(2, ff_scale(2));           /* 笔画粗细（偶数） */
            int L = 2 * ff_scale(4) + 2;           /* 成品总长 10（偶数，与 t 同奇偶 => 横竖严格同心） */
            int h = L / 2;
            RECT vr = { bx - t / 2, by - h,     bx - t / 2 + t, by - h + L };  /* 竖条 */
            RECT hr = { bx - h,     by - t / 2, bx - h + L,     by - t / 2 + t };  /* 横条 */
            HBRUSH pb = CreateSolidBrush(RGB(70, 70, 70));
            FillRect(mem, &vr, pb);
            FillRect(mem, &hr, pb);
            DeleteObject(pb);
        }
    }

    BitBlt(dc, 0, 0, cr.right, cr.bottom, mem, 0, 0, SRCCOPY);
    SelectObject(mem, ob);
    DeleteObject(bmp);
    DeleteDC(mem);
    EndPaint(h, &ps);
}

/* ===================================================== 命中测试 */
static int hit_tab(HWND h, int x, int y, bool *onClose)
{
    if (onClose) *onClose = false;
    RECT cr;
    GetClientRect(h, &cr);
    if (y > cr.bottom - ff_scale(3)) return -1;
    int xs[MAX_TABS], ws[MAX_TABS];
    layout(h, xs, ws);
    for (int i = 0; i < s_ts.count; ++i) {
        if (x >= xs[i] && x < xs[i] + ws[i]) {
            if (onClose && x >= xs[i] + ws[i] - ff_scale(14)) *onClose = true;
            return i;
        }
    }
    return -1;
}

static bool hit_new(HWND h, int x, int y)
{
    (void)y;
    int r = ff_scale(12);
    return x >= s_ts.newX - r && x <= s_ts.newX + r;
}

/* ===================================================== 窗口过程 */
static LRESULT CALLBACK tabs_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE:
        ZeroMemory(&s_ts, sizeof(s_ts));
        s_ts.hot = s_ts.hotClose = -1;
        s_ts.pressed = -1;
        return 0;
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT:
        paint(hwnd);
        return 0;
    case WM_SIZE:
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    case WM_MOUSEMOVE: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        bool onClose = false;
        int t = hit_tab(hwnd, x, y, &onClose);
        int hc = (t >= 0 && onClose) ? t : -1;
        bool hn = hit_new(hwnd, x, y);
        if (t != s_ts.hot || hc != s_ts.hotClose || hn != s_ts.hotNew) {
            s_ts.hot = t; s_ts.hotClose = hc; s_ts.hotNew = hn;
            InvalidateRect(hwnd, NULL, FALSE);
            TRACKMOUSEEVENT tme = { sizeof(tme), TME_LEAVE, hwnd, 0 };
            TrackMouseEvent(&tme);
        }
        return 0;
    }
    case WM_MOUSELEAVE:
        s_ts.hot = s_ts.hotClose = -1;
        s_ts.hotNew = false;
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    case WM_LBUTTONDOWN: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        if (hit_new(hwnd, x, y)) {
            SendMessageW(GetParent(hwnd), WM_FF_TAB_NEW, 0, 0);
            return 0;
        }
        bool onClose = false;
        int t = hit_tab(hwnd, x, y, &onClose);
        if (t >= 0) {
            if (onClose) SendMessageW(GetParent(hwnd), WM_FF_TAB_CLOSE, (WPARAM)t, 0);
            else SendMessageW(GetParent(hwnd), WM_FF_TAB_SEL, (WPARAM)t, 0);
        }
        return 0;
    }
    case WM_MBUTTONDOWN: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        bool onClose = false;
        int t = hit_tab(hwnd, x, y, &onClose);
        if (t >= 0) SendMessageW(GetParent(hwnd), WM_FF_TAB_CLOSE, (WPARAM)t, 0);
        return 0;
    }
    case WM_RBUTTONUP: {
        POINT pt;
        GetCursorPos(&pt);
        int t = hit_tab(hwnd, pt.x - 0, pt.y - 0, NULL);
        (void)t;
        SendMessageW(GetParent(hwnd), WM_FF_TAB_RCLICK, 0, MAKELPARAM(pt.x, pt.y));
        return 0;
    }
    case WM_MOUSEWHEEL: {
        int delta = GET_WHEEL_DELTA_WPARAM(wp);
        int idx = s_ts.active + (delta < 0 ? 1 : -1);
        if (idx >= 0 && idx < s_ts.count)
            SendMessageW(GetParent(hwnd), WM_FF_TAB_SEL, (WPARAM)idx, 0);
        return 0;
    }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

bool ff_tabs_register(HINSTANCE inst)
{
    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = tabs_proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.lpszClassName = L"FFTabBar";
    return RegisterClassExW(&wc) != 0;
}

HWND ff_tabs_create(HWND parent, HINSTANCE inst)
{
    return CreateWindowExW(0, L"FFTabBar", L"",
                           WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN,
                           0, 0, 100, ff_scale(TAB_H), parent,
                           (HMENU)(INT_PTR)1010, inst, NULL);
}
