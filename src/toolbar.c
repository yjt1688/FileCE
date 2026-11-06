/* toolbar.c —— 自绘矢量图标工具栏
 *
 * 图标风格：Win7 资源管理器那样的彩色拟物（绿色水晶圆底 + 白箭头、
 * 黄色文件夹 + 绿色上箭头 …），全部用 GDI 现画，不依赖任何位图资源。
 *
 * 抗锯齿：整条按 TB_SS 倍超采样绘制，最后 HALFTONE 缩回 —— 对 4 倍缩小
 * 而言 HALFTONE 就是 4×4 箱式滤波，正好等于一次高质量降采样，
 * 圆边、斜线、渐变都不会有锯齿，也不用额外引入 msimg32 / AlphaBlend。
 */
#include "ff.h"
#include <math.h>

#define TB_HEIGHT   36
#define TB_BTN      30
#define TB_ICON     18
#define TB_PAD      6
#define TB_SS        4   /* 超采样倍率 */

#define CLR_BG        RGB(250, 250, 250)
#define CLR_LINE      RGB(223, 223, 223)
#define CLR_WHITE     RGB(255, 255, 255)
#define CLR_HOT       RGB(229, 241, 251)
#define CLR_HOT_LINE  RGB(204, 232, 255)
#define CLR_DOWN      RGB(204, 232, 255)
#define CLR_DOWN_LINE RGB(152, 209, 255)
#define CLR_CHK       RGB(219, 233, 247)
#define CLR_CHK_LINE  RGB(146, 200, 245)
#define CLR_ACCENT    RGB(  0, 120, 212)

static const int s_cmd[FF_TB_COUNT] = {
    CMD_BACK, CMD_FORWARD, CMD_UP, CMD_REFRESH, CMD_HOME,
    CMD_FIND, CMD_TOGGLE_FILTER, CMD_VIEWMENU
};

static const wchar_t *s_tip[FF_TB_COUNT] = {
    L"后退  (Alt+←)", L"前进  (Alt+→)", L"上级目录  (Backspace)",
    L"刷新  (F5)", L"此电脑  (Alt+Home)",
    L"查找文件  (Ctrl+F)", L"筛选面板  (Ctrl+L)", L"查看方式"
};

typedef struct {
    int  hot;
    int  pressed;
    bool enabled[FF_TB_COUNT];
    bool checked[FF_TB_COUNT];
} TbState;

/* 按钮的启用/勾选/热跟踪状态按【全局命令索引】存一份即可 */
static TbState s_tb;

/* 一条工具栏实例：只负责 [first, first + count) 这段按钮 */
typedef struct {
    int        first;
    int        count;
    HWND       tip;
    TOOLINFOW *ti;
    wchar_t  (*tipText)[96];
} TbInst;

/* ===================================================== 配色主题
 * 一套「彩色」+ 一套「灰阶（禁用态）」。图标函数只认这个结构，
 * 所以禁用时不用另画一套形状，换主题即可 —— 灰圆 + 白箭头正是
 * Win7 里"没有历史记录"时的样子。 */
typedef struct {
    /* 圆形按钮（后退/前进）：斜分割的亮块与暗块各刷一段垂直渐变
     * disc_hi→disc_a 是左上亮块，disc_b→disc_lo 是右下暗块 */
    COLORREF disc_hi, disc_a, disc_b, disc_lo, disc_edge;
    /* 文件夹 */
    COLORREF fold_hi, fold_mid, fold_lo, fold_edge;
    /* 绿色箭头（上级 / 刷新） */
    COLORREF arr_hi, arr_lo, arr_edge;
    /* 蓝色屏幕与银色外壳 */
    COLORREF scr_hi, scr_mid, scr_lo, scr_edge, silver_lo;
    /* 放大镜玻璃 */
    COLORREF glass_hi, glass_lo, glass_edge;
    /* 漏斗 */
    COLORREF fun_hi, fun_mid, fun_lo, fun_edge;
} Theme;

static const Theme TH_COLOR = {
    RGB(178,216, 82), RGB(134,194, 58), RGB(120,182, 54), RGB( 84,154, 34), RGB( 62,124, 24),
    RGB(255,246,203), RGB(255,215,100), RGB(233,166, 46), RGB(190,132, 25),
    RGB(166,229,102), RGB( 66,164, 30), RGB( 42,110, 18),
    RGB(255,255,255), RGB(111,168,220), RGB( 44,107,176), RGB(138,138,138), RGB(208,208,208),
    RGB(242,250,255), RGB(143,196,236), RGB( 70,104,140),
    RGB(255,231,168), RGB(255,215,100), RGB(224,138, 32), RGB(184,113, 26)
};

static const Theme TH_DIS = {
    RGB(240,240,240), RGB(216,216,216), RGB(202,202,202), RGB(178,178,178), RGB(164,164,164),
    RGB(247,247,244), RGB(234,234,228), RGB(220,220,212), RGB(180,180,172),
    RGB(224,224,224), RGB(198,198,198), RGB(168,168,168),
    RGB(251,251,251), RGB(236,236,236), RGB(214,214,214), RGB(168,168,168), RGB(224,224,224),
    RGB(250,250,250), RGB(224,224,224), RGB(168,168,168),
    RGB(243,243,243), RGB(230,230,230), RGB(214,214,214), RGB(168,168,168)
};

/* ===================================================== 绘制基础
 * 所有图标按 18×18 虚拟网格作图，随 DPI（以及超采样倍率）线性缩放。
 * 线宽也用网格单位：2.4u ≈ 2.4px @100% DPI。 */
static double u_of(const RECT *r) { return (r->right - r->left) / 18.0; }
static int px(const RECT *r, double v) { return r->left + (int)(v * u_of(r) + 0.5); }
static int py(const RECT *r, double v) { return r->top  + (int)(v * u_of(r) + 0.5); }

/* 圆头圆角的粗画笔 */
static HPEN rpen(const RECT *r, double uw, COLORREF c)
{
    LOGBRUSH lb;
    int w = (int)(uw * u_of(r) + 0.5);
    if (w < 1) w = 1;
    lb.lbStyle = BS_SOLID; lb.lbColor = c; lb.lbHatch = 0;
    return ExtCreatePen(PS_GEOMETRIC | PS_SOLID | PS_JOIN_ROUND | PS_ENDCAP_ROUND,
                        w, &lb, 0, 0);
}
static HBRUSH sb(COLORREF c) { return CreateSolidBrush(c); }

/* 垂直渐变一段（gdi32 自带，Win7 SP1 起可用，不新增 DLL 依赖） */
static void vgrad(HDC dc, int x0, int y0, int x1, int y1, COLORREF c0, COLORREF c1)
{
    TRIVERTEX tv[2];
    GRADIENT_RECT gr;
    if (x1 <= x0 || y1 <= y0) return;
    tv[0].x = x0; tv[0].y = y0;
    tv[0].Red   = (COLOR16)(GetRValue(c0) << 8);
    tv[0].Green = (COLOR16)(GetGValue(c0) << 8);
    tv[0].Blue  = (COLOR16)(GetBValue(c0) << 8);
    tv[0].Alpha = 0;
    tv[1].x = x1; tv[1].y = y1;
    tv[1].Red   = (COLOR16)(GetRValue(c1) << 8);
    tv[1].Green = (COLOR16)(GetGValue(c1) << 8);
    tv[1].Blue  = (COLOR16)(GetBValue(c1) << 8);
    tv[1].Alpha = 0;
    gr.UpperLeft = 0; gr.LowerRight = 1;
    GdiGradientFill(dc, tv, 2, &gr, 1, GRADIENT_FILL_RECT_V);
}

/* 在给定裁剪区内刷四段垂直渐变（造球面/柱面感）。
 * f1 / f2 是两处分界在 [y_start, y_end] 上的比例。 */
static void shade4(HDC dc, const RECT *r, HRGN rgn,
                   double y_start, double y_end, double f1, double f2,
                   COLORREF c0, COLORREF c1, COLORREF c2, COLORREF c3)
{
    int x0 = r->left, x1 = r->right;
    int Y0 = py(r, y_start), Y1 = py(r, y_end);
    int ya = py(r, y_start + (y_end - y_start) * f1);
    int yb = py(r, y_start + (y_end - y_start) * f2);
    SelectClipRgn(dc, rgn);
    vgrad(dc, x0, Y0, x1, ya, c0, c1);
    vgrad(dc, x0, ya, x1, yb, c1, c2);
    vgrad(dc, x0, yb, x1, Y1, c2, c3);
    SelectClipRgn(dc, NULL);
}

/* 实心多边形（填充 + 同色细描边，视觉更饱满） */
static void poly(HDC dc, const RECT *r, const double pts[][2], int n, double uw, COLORREF c)
{
    POINT p[20];
    if (n > 20) n = 20;
    for (int i = 0; i < n; ++i) {
        p[i].x = px(r, pts[i][0]);
        p[i].y = py(r, pts[i][1]);
    }
    HPEN pen = rpen(r, uw, c);
    HBRUSH br = sb(c);
    HGDIOBJ op = SelectObject(dc, pen), ob = SelectObject(dc, br);
    Polygon(dc, p, n);
    SelectObject(dc, op); SelectObject(dc, ob);
    DeleteObject(pen); DeleteObject(br);
}

/* 实心多边形，填充色与描边色可不同 */
static void poly2(HDC dc, const RECT *r, const double pts[][2], int n,
                  double uw, COLORREF fill, COLORREF stroke)
{
    POINT p[20];
    if (n > 20) n = 20;
    for (int i = 0; i < n; ++i) {
        p[i].x = px(r, pts[i][0]);
        p[i].y = py(r, pts[i][1]);
    }
    HPEN pen = rpen(r, uw, stroke);
    HBRUSH br = sb(fill);
    HGDIOBJ op = SelectObject(dc, pen), ob = SelectObject(dc, br);
    Polygon(dc, p, n);
    SelectObject(dc, op); SelectObject(dc, ob);
    DeleteObject(pen); DeleteObject(br);
}

/* 把点列按网格单位算成像素，供 CreateXxxRgn / Polyline 用 */
static void to_px(const RECT *r, const double pts[][2], int n, POINT *out)
{
    for (int i = 0; i < n; ++i) {
        out[i].x = px(r, pts[i][0]);
        out[i].y = py(r, pts[i][1]);
    }
}

/* ===================================================== 八个图标 */

/* 圆形按钮（照参考图）：绿色渐变圆 + 一条斜向明暗分割。
 * 左上亮黄绿、右下深绿，一条斜线把圆切成亮/暗两块 —— 参考图里那颗
 * 「绿色圆 + 白箭头」的质感就来自这道分割线（两块的渐变方向相同、
 * 但色阶差一档，接缝处就成了那条看得见的斜边）。
 * 禁用态换 TH_DIS 主题：白箭头压在浅灰圆上，正是参考图第二颗灰圆的样子。 */
static void disc(HDC dc, const RECT *r, const Theme *t)
{
    int x0 = px(r, 0.6), y0 = py(r, 0.6);
    int x1 = px(r, 17.4), y1 = py(r, 17.4);
    HRGN cr = CreateEllipticRgn(x0, y0, x1 + 1, y1 + 1);
    if (!cr) return;

    /* 分割线：左边缘 y=15.0 → 右边缘 y=10.2，线右下侧压暗 */
    static const double sp[][2] = {
        { -0.8, 15.0 }, { 18.8, 10.2 }, { 18.8, 18.8 }, { -0.8, 18.8 }
    };
    POINT p[4];
    to_px(r, sp, 4, p);
    HRGN sr  = CreatePolygonRgn(p, 4, ALTERNATE);
    HRGN lit = CreateRectRgn(0, 0, 0, 0);
    HRGN dk  = CreateRectRgn(0, 0, 0, 0);
    CombineRgn(lit, cr, sr, RGN_DIFF);   /* 圆 − 暗三角 */
    CombineRgn(dk,  cr, sr, RGN_AND);    /* 圆 ∩ 暗三角 */

    SelectClipRgn(dc, lit);
    vgrad(dc, x0, y0, x1, y1, t->disc_hi, t->disc_a);
    SelectClipRgn(dc, dk);
    vgrad(dc, x0, y0, x1, y1, t->disc_b, t->disc_lo);
    SelectClipRgn(dc, NULL);
    DeleteObject(lit); DeleteObject(dk); DeleteObject(sr);

    /* 极细一圈深色轮廓，免得绿圆在近白的条带上"发飘" */
    HPEN pen = rpen(r, 0.45, t->disc_edge);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Ellipse(dc, x0, y0, x1, y1);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(pen);
    DeleteObject(cr);
}

/* 圆里的白色箭头（照参考图）：粗横杆 + 一个「＞」形箭头头。
 * 左右共用同一份坐标、靠 mx() 镜像，两套手写坐标最容易走形。
 * 纯白、不描边 —— 参考图就是纯白的，亮块已经压到中绿，对比足够。 */
static double mx(bool left, double v) { return left ? 18.0 - v : v; }

static void nav_arrow(HDC dc, const RECT *r, bool left)
{
    /* 箭头头：折线画 V，圆头圆角，拐角自然。
     * 尺寸照参考图量：V 尖落在圆半径 65% 处，两臂张开约 42°，
     * 与横杆合起来横跨整圆的 62%。 */
    double v[3][2] = {
        { mx(left,  8.80),  4.05 },
        { mx(left, 14.35),  9.00 },
        { mx(left,  8.80), 13.95 }
    };
    POINT p[3];
    to_px(r, v, 3, p);
    HPEN pen = rpen(r, 1.85, CLR_WHITE);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Polyline(dc, p, 3);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(pen);

    /* 横杆：右端插进 V 的内凹口（凹口被圆头磨圆后实际在 12.2 附近），
     * 视觉上与箭头头连成一体 */
    double b[4][2] = {
        { mx(left,  4.05), 8.15 }, { mx(left, 12.55), 8.15 },
        { mx(left, 12.55), 9.85 }, { mx(left,  4.05), 9.85 }
    };
    poly(dc, r, b, 4, 0.0, CLR_WHITE);
}

static void icon_back(HDC dc, const RECT *r, const Theme *t)
{
    disc(dc, r, t);
    nav_arrow(dc, r, true);
}

static void icon_forward(HDC dc, const RECT *r, const Theme *t)
{
    disc(dc, r, t);
    nav_arrow(dc, r, false);
}

/* 上级：黄色文件夹 + 绿色向上大箭头（照参考图第三个） */
static void icon_up(HDC dc, const RECT *r, const Theme *t)
{
    static const double fp[][2] = {
        {1.4,7.5}, {6.4,7.5}, {8.3,9.4}, {18.4,9.4}, {18.4,17.5}, {1.4,17.5}
    };
    static const double bend[][2] = { {10.6,17.2}, {10.9,12.6}, {11.4,9.8} };
    static const double head[][2] = { {11.4,3.2}, {7.5,9.2}, {15.3,9.2} };
    POINT p[8], b[3];
    to_px(r, fp, 6, p);
    to_px(r, bend, 3, b);

    /* 文件夹（渐变填充 + 深金描边） */
    HRGN rgn = CreatePolygonRgn(p, 6, ALTERNATE);
    shade4(dc, r, rgn, 7.5, 17.5, 0.5, 0.5,
           t->fold_hi, t->fold_mid, t->fold_mid, t->fold_lo);
    DeleteObject(rgn);
    p[6] = p[0];
    HPEN pen = rpen(r, 0.7, t->fold_edge);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Polyline(dc, p, 7);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(pen);

    /* 弯箭头压在文件夹上层：短杆 + 一枚朝上的大三角 */
    pen = rpen(r, 3.2, t->arr_lo);
    op = SelectObject(dc, pen);
    Polyline(dc, b, 3);
    SelectObject(dc, op);
    DeleteObject(pen);
    poly2(dc, r, head, 3, 0.45, t->arr_lo, t->arr_edge);
}

/* 刷新：绿色粗圆弧 + 切向箭头（顺时针） */
static void icon_refresh(HDC dc, const RECT *r, const Theme *t)
{
    /* 箭头头：顶点 = 弧端 + 3.0u·顺时针切线，底边 = 弧端 ± 2.4u·法线 */
    static const double hdr[][2] = { {16.07,9.42}, {16.98,5.69}, {12.62,7.71} };
    double cx = 9.0, cy = 9.4, rad = 6.4;
    POINT a[32];
    int n = 0;
    for (double deg = -25.0; deg <= 250.0 + 0.001; deg += 12.5) {
        double v = deg * 3.14159265358979 / 180.0;
        a[n].x = px(r, cx + rad * cos(v));
        a[n].y = py(r, cy + rad * sin(v));
        if (++n >= 32) break;
    }
    HPEN pen = rpen(r, 2.9, t->arr_lo);
    HGDIOBJ op = SelectObject(dc, pen);
    Polyline(dc, a, n);
    SelectObject(dc, op);
    DeleteObject(pen);
    poly2(dc, r, hdr, 3, 0.45, t->arr_lo, t->arr_edge);
}

/* 此电脑：银色外壳 + 蓝色屏幕 + 支架底座 */
static void icon_home(HDC dc, const RECT *r, const Theme *t)
{
    int fx0 = px(r, 1.3), fy0 = py(r, 2.4), fx1 = px(r, 17.7), fy1 = py(r, 14.4);
    int rr = (int)(1.3 * u_of(r) + 0.5) * 2;
    int sx0 = px(r, 2.9), sy0 = py(r, 4.0), sx1 = px(r, 16.1), sy1 = py(r, 13.0);

    /* 外壳 */
    HRGN fr = CreateRoundRectRgn(fx0, fy0, fx1 + 1, fy1 + 1, rr, rr);
    shade4(dc, r, fr, 2.4, 14.4, 0.45, 0.45,
           t->scr_hi, t->silver_lo, t->silver_lo, t->scr_edge);
    DeleteObject(fr);
    /* 屏幕 */
    HRGN sr = CreateRectRgn(sx0, sy0, sx1 + 1, sy1 + 1);
    shade4(dc, r, sr, 4.0, 13.0, 0.45, 0.45,
           t->scr_hi, t->scr_mid, t->scr_mid, t->scr_lo);
    DeleteObject(sr);

    /* 支架 + 底座 */
    static const double neck[][2] = { {7.6,14.4}, {12.4,14.4}, {12.4,16.2}, {7.6,16.2} };
    static const double foot[][2] = { {5.0,16.2}, {15.0,16.2}, {15.0,17.9}, {5.0,17.9} };
    poly2(dc, r, neck, 4, 0.5, t->silver_lo, t->scr_edge);
    poly2(dc, r, foot, 4, 0.5, t->silver_lo, t->scr_edge);
    /* 外框描边（压在屏幕边线上） */
    HPEN pen = rpen(r, 0.7, t->scr_edge);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    RoundRect(dc, fx0, fy0, fx1, fy1, rr, rr);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(pen);
}

/* 查找：蓝色玻璃放大镜 + 金属手柄 */
static void icon_find(HDC dc, const RECT *r, const Theme *t)
{
    int cx = px(r, 8.3), cy = py(r, 8.3), rad = (int)(6.2 * u_of(r) + 0.5);
    HRGN gr = CreateEllipticRgn(cx - rad, cy - rad, cx + rad + 1, cy + rad + 1);
    shade4(dc, r, gr, 2.1, 14.5, 0.45, 0.45,
           t->glass_hi, t->glass_lo, t->glass_lo, t->glass_lo);
    DeleteObject(gr);

    HPEN pen = rpen(r, 1.1, t->glass_edge);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Ellipse(dc, cx - rad, cy - rad, cx + rad, cy + rad);
    /* 左上一道高光 */
    POINT hi[5];
    for (int i = 0; i < 5; ++i) {
        double v = (200.0 + i * 22.0) * 3.14159265358979 / 180.0;
        hi[i].x = cx + (int)(rad * 0.74 * cos(v) + 0.5);
        hi[i].y = cy + (int)(rad * 0.74 * sin(v) + 0.5);
    }
    SelectObject(dc, ob);
    DeleteObject(pen);
    pen = rpen(r, 1.1, CLR_WHITE);
    op = SelectObject(dc, pen);
    Polyline(dc, hi, 5);
    SelectObject(dc, op);
    DeleteObject(pen);

    /* 手柄：深灰外芯 + 浅灰内芯 */
    pen = rpen(r, 3.3, t->glass_edge);
    op = SelectObject(dc, pen);
    MoveToEx(dc, px(r, 13.3), py(r, 13.3), NULL);
    LineTo(dc, px(r, 17.8), py(r, 17.8));
    SelectObject(dc, op);
    DeleteObject(pen);
    pen = rpen(r, 1.5, t->silver_lo);
    op = SelectObject(dc, pen);
    MoveToEx(dc, px(r, 13.5), py(r, 13.5), NULL);
    LineTo(dc, px(r, 17.6), py(r, 17.6));
    SelectObject(dc, op);
    DeleteObject(pen);
}

/* 筛选：橙黄渐变漏斗 */
static void icon_filter(HDC dc, const RECT *r, const Theme *t)
{
    static const double fn[][2] = {
        {1.9,3.0}, {17.1,3.0}, {11.6,9.4}, {11.6,17.3}, {7.4,17.3}, {7.4,9.4}
    };
    POINT p[8];
    to_px(r, fn, 6, p);
    HRGN rgn = CreatePolygonRgn(p, 6, ALTERNATE);
    shade4(dc, r, rgn, 3.0, 17.3, 0.42, 0.42,
           t->fun_hi, t->fun_mid, t->fun_mid, t->fun_lo);
    DeleteObject(rgn);
    p[6] = p[0];
    HPEN pen = rpen(r, 0.8, t->fun_edge);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Polyline(dc, p, 7);
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(pen);
}

/* 查看方式：蓝色大格 + 两格白底 + 右下橙色下拉三角 */
static void icon_view(HDC dc, const RECT *r, const Theme *t)
{
    /* 左上大格：蓝渐变 */
    HRGN g1 = CreateRectRgn(px(r, 1.4), py(r, 1.7), px(r, 10.9) + 1, py(r, 10.3) + 1);
    shade4(dc, r, g1, 1.7, 10.3, 0.45, 0.45,
           t->scr_hi, t->scr_mid, t->scr_mid, t->scr_lo);
    DeleteObject(g1);
    /* 右上 / 左下：白底 */
    HRGN g2 = CreateRectRgn(px(r, 12.0), py(r, 1.7), px(r, 18.5) + 1, py(r, 10.3) + 1);
    HRGN g3 = CreateRectRgn(px(r, 1.4), py(r, 11.4), px(r, 10.9) + 1, py(r, 17.9) + 1);
    HBRUSH wb = sb(t->glass_lo);
    FillRgn(dc, g2, wb);
    FillRgn(dc, g3, wb);
    DeleteObject(wb);
    DeleteObject(g2);
    DeleteObject(g3);
    /* 三格描边 */
    HPEN pen = rpen(r, 0.6, t->scr_edge);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Rectangle(dc, px(r, 1.4), py(r, 1.7), px(r, 10.9), py(r, 10.3));
    Rectangle(dc, px(r, 12.0), py(r, 1.7), px(r, 18.5), py(r, 10.3));
    Rectangle(dc, px(r, 1.4), py(r, 11.4), px(r, 10.9), py(r, 17.9));
    SelectObject(dc, ob); SelectObject(dc, op);
    DeleteObject(pen);
    /* 右下：橙色三角（下拉） */
    static const double tri[][2] = { {11.8,11.6}, {18.6,11.6}, {15.2,17.4} };
    poly2(dc, r, tri, 3, 0.6, t->fun_mid, t->fun_edge);
}

static void draw_icon(HDC dc, int idx, const RECT *rc, const Theme *t)
{
    switch (idx) {
    case FF_TB_BACK:      icon_back(dc, rc, t); break;
    case FF_TB_FORWARD:   icon_forward(dc, rc, t); break;
    case FF_TB_UP:        icon_up(dc, rc, t); break;
    case FF_TB_REFRESH:   icon_refresh(dc, rc, t); break;
    case FF_TB_HOME:      icon_home(dc, rc, t); break;
    case FF_TB_FIND:      icon_find(dc, rc, t); break;
    case FF_TB_FILTER:    icon_filter(dc, rc, t); break;
    case FF_TB_VIEW:      icon_view(dc, rc, t); break;
    default: break;
    }
}

/* ===================================================== 布局 */
static void update_tip_rects(HWND hwnd);   /* 定义在下面，这里先声明 */

static int btn_size(void)  { return ff_scale(TB_BTN); }
static int icon_size(void) { return ff_scale(TB_ICON); }

static TbInst *tb_inst(HWND hwnd)
{
    return (TbInst *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
}

/* 按钮一律从左往右排：导航五个按钮后接地址输入框 */
static void button_rect(HWND hwnd, int idx, RECT *out)
{
    RECT cr;
    GetClientRect(hwnd, &cr);
    TbInst *it = tb_inst(hwnd);
    int bs = btn_size();
    int n = (it && it->first >= 0) ? (idx - it->first) : idx;
    int x = ff_scale(2) + n * bs;
    (void)cr;
    out->left   = x;
    out->top    = (cr.bottom - bs) / 2;
    out->right  = out->left + bs;
    out->bottom = out->top + bs;
}

/* 本条工具栏占用的宽度（地址栏条用它决定输入框的起始 x） */
int ff_toolbar_width(HWND tb)
{
    TbInst *it = tb_inst(tb);
    int n = it ? it->count : FF_TB_COUNT;
    return ff_scale(2) + n * btn_size() + ff_scale(4);
}

bool ff_toolbar_button_rect(HWND tb, int index, RECT *out)
{
    TbInst *it = tb_inst(tb);
    if (!tb || !out) return false;
    if (it && (index < it->first || index >= it->first + it->count)) return false;
    if (index < 0 || index >= FF_TB_COUNT) return false;
    button_rect(tb, index, out);
    return true;
}

/* ===================================================== 绘制 */
static void paint(HWND hwnd)
{
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(hwnd, &ps);
    RECT cr;
    GetClientRect(hwnd, &cr);
    int W = cr.right, H = cr.bottom;
    if (W <= 0 || H <= 0) { EndPaint(hwnd, &ps); return; }

    /* 超采样后备位图做缓存：4 倍面积下一次分配就是 2 MB 出头，
     * 不该每个 WM_PAINT 都重建。尺寸变了才重建。 */
    static HDC     s_mem = NULL;
    static HBITMAP s_bmp = NULL, s_old = NULL;
    static int     s_bw = 0, s_bh = 0;
    if (!s_mem) s_mem = CreateCompatibleDC(dc);
    if (s_bmp && (s_bw != W * TB_SS || s_bh != H * TB_SS)) {
        SelectObject(s_mem, s_old);
        DeleteObject(s_bmp);
        s_bmp = NULL;
    }
    if (!s_bmp) {
        s_bw = W * TB_SS; s_bh = H * TB_SS;
        s_bmp = CreateCompatibleBitmap(dc, s_bw, s_bh);
        if (!s_bmp) { EndPaint(hwnd, &ps); return; }
        s_old = SelectObject(s_mem, s_bmp);
    }
    HDC mem = s_mem;

    RECT full = { 0, 0, s_bw, s_bh };
    HBRUSH bg = CreateSolidBrush(CLR_BG);
    FillRect(mem, &full, bg);
    DeleteObject(bg);

    TbInst *it = tb_inst(hwnd);
    int first = it ? it->first : 0;
    int count = it ? it->count : FF_TB_COUNT;
    int rad = ff_scale(8) * TB_SS;

    for (int i = first; i < first + count; ++i) {
        RECT r, rs;
        button_rect(hwnd, i, &r);
        rs.left   = r.left   * TB_SS;
        rs.top    = r.top    * TB_SS;
        rs.right  = r.right  * TB_SS;
        rs.bottom = r.bottom * TB_SS;
        bool on = s_tb.enabled[i];
        bool hot = (s_tb.hot == i) && on;
        bool down = (s_tb.pressed == i) && on;

        if (down || hot || s_tb.checked[i]) {
            COLORREF fill = down ? CLR_DOWN : (s_tb.checked[i] && !hot ? CLR_CHK : CLR_HOT);
            COLORREF line = down ? CLR_DOWN_LINE : (s_tb.checked[i] && !hot ? CLR_CHK_LINE : CLR_HOT_LINE);
            HBRUSH fb = CreateSolidBrush(fill);
            HPEN   fp = CreatePen(PS_SOLID, TB_SS, line);
            HGDIOBJ o1 = SelectObject(mem, fb), o2 = SelectObject(mem, fp);
            RoundRect(mem, rs.left + TB_SS, rs.top + TB_SS,
                      rs.right - TB_SS, rs.bottom - TB_SS, rad, rad);
            SelectObject(mem, o1); SelectObject(mem, o2);
            DeleteObject(fb); DeleteObject(fp);
        }

        int isz = icon_size() * TB_SS;
        RECT ir;
        ir.left   = rs.left + (rs.right - rs.left - isz) / 2;
        ir.top    = rs.top + (rs.bottom - rs.top - isz) / 2;
        ir.right  = ir.left + isz;
        ir.bottom = ir.top + isz;

        draw_icon(mem, i, &ir, on ? &TH_COLOR : &TH_DIS);
    }

    /* 底部细线：画 TB_SS 像素高，缩回后正好 1 物理像素 */
    RECT lr = { 0, s_bh - TB_SS, s_bw, s_bh };
    HBRUSH lb = CreateSolidBrush(CLR_LINE);
    FillRect(mem, &lr, lb);
    DeleteObject(lb);

    /* 4 倍缩小用 HALFTONE = 4×4 箱式滤波，等效一次高质量抗锯齿降采样 */
    SetStretchBltMode(dc, HALFTONE);
    SetBrushOrgEx(dc, 0, 0, NULL);
    StretchBlt(dc, 0, 0, W, H, mem, 0, 0, s_bw, s_bh, SRCCOPY);

    EndPaint(hwnd, &ps);
}

/* ===================================================== 窗口过程 */
static void update_tip_rects(HWND hwnd)
{
    TbInst *it = tb_inst(hwnd);
    if (!it || !it->tip) return;
    for (int k = 0; k < it->count; ++k) {
        int i = it->first + k;
        RECT r;
        button_rect(hwnd, i, &r);
        it->ti[k].rect = r;
        SendMessageW(it->tip, TTM_NEWTOOLRECTW, 0, (LPARAM)&it->ti[k]);
    }
}

static void notify_parent(HWND hwnd, int cmd)
{
    HWND p = GetParent(hwnd);
    SendMessageW(p, WM_COMMAND, MAKEWPARAM(cmd, 0), (LPARAM)hwnd);
}

static LRESULT CALLBACK tb_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE: {
        CREATESTRUCTW *cs = (CREATESTRUCTW *)lp;
        TbInst *it = (TbInst *)calloc(1, sizeof(TbInst));
        if (!it) return -1;
        /* lpParam 传的是按钮段：[first, first + count) */
        if (cs->lpCreateParams) {
            int *cfg = (int *)cs->lpCreateParams;
            it->first = cfg[0];
            it->count = cfg[1];
        } else {
            it->first = 0; it->count = FF_TB_COUNT;
        }
        if (it->first < 0) it->first = 0;
        if (it->count <= 0 || it->first + it->count > FF_TB_COUNT)
            it->count = FF_TB_COUNT - it->first;
        it->ti = (TOOLINFOW *)calloc((size_t)it->count, sizeof(TOOLINFOW));
        it->tipText = (wchar_t (*)[96])calloc((size_t)it->count, sizeof(*it->tipText));
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)it);

        s_tb.hot = -1; s_tb.pressed = -1;
        for (int i = 0; i < FF_TB_COUNT; ++i) s_tb.enabled[i] = true;

        it->tip = CreateWindowExW(WS_EX_TOPMOST, TOOLTIPS_CLASSW, NULL,
                                  WS_POPUP | TTS_NOPREFIX | TTS_ALWAYSTIP,
                                  0, 0, 0, 0, hwnd, NULL, g_app.inst, NULL);
        if (it->tip && it->ti && it->tipText) {
            SendMessageW(it->tip, TTM_SETMAXTIPWIDTH, 0, 400);
            for (int k = 0; k < it->count; ++k) {
                int i = it->first + k;
                ff_str_copy(it->tipText[k], 96, s_tip[i]);
                ZeroMemory(&it->ti[k], sizeof(TOOLINFOW));
                it->ti[k].cbSize = sizeof(TOOLINFOW);
                it->ti[k].uFlags = TTF_SUBCLASS;
                it->ti[k].hwnd = hwnd;
                it->ti[k].uId = (UINT_PTR)(i + 1);
                it->ti[k].lpszText = it->tipText[k];
                SendMessageW(it->tip, TTM_ADDTOOLW, 0, (LPARAM)&it->ti[k]);
            }
        }
        update_tip_rects(hwnd);
        return 0;
    }
    case WM_SIZE:
        update_tip_rects(hwnd);
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT:
        paint(hwnd);
        return 0;
    case WM_MOUSEMOVE: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        int hit = -1;
        TbInst *it = tb_inst(hwnd);
        int first = it ? it->first : 0, count = it ? it->count : FF_TB_COUNT;
        for (int i = first; i < first + count; ++i) {
            RECT r; button_rect(hwnd, i, &r);
            if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) { hit = i; break; }
        }
        if (hit != s_tb.hot) { s_tb.hot = hit; InvalidateRect(hwnd, NULL, FALSE); }
        TRACKMOUSEEVENT tme = { sizeof(tme), TME_LEAVE, hwnd, 0 };
        TrackMouseEvent(&tme);
        return 0;
    }
    case WM_MOUSELEAVE:
        s_tb.hot = -1;
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    case WM_LBUTTONDOWN: {
        int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
        TbInst *it = tb_inst(hwnd);
        int first = it ? it->first : 0, count = it ? it->count : FF_TB_COUNT;
        for (int i = first; i < first + count; ++i) {
            RECT r; button_rect(hwnd, i, &r);
            if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) {
                if (!s_tb.enabled[i]) return 0;
                s_tb.pressed = i;
                SetCapture(hwnd);
                InvalidateRect(hwnd, NULL, FALSE);
                if (it && it->tip) SendMessageW(it->tip, TTM_POP, 0, 0);
                break;
            }
        }
        return 0;
    }
    case WM_LBUTTONUP: {
        int i = s_tb.pressed;
        s_tb.pressed = -1;
        ReleaseCapture();
        if (i >= 0) {
            int x = GET_X_LPARAM(lp), y = GET_Y_LPARAM(lp);
            RECT r; button_rect(hwnd, i, &r);
            if (x >= r.left && x < r.right && y >= r.top && y < r.bottom)
                notify_parent(hwnd, s_cmd[i]);
        }
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    }
    case WM_KEYDOWN:
        if (wp == VK_ESCAPE) { s_tb.pressed = -1; ReleaseCapture(); InvalidateRect(hwnd, NULL, FALSE); }
        return 0;
    case WM_DESTROY: {
        TbInst *it = tb_inst(hwnd);
        if (it) {
            if (it->tip) DestroyWindow(it->tip);
            free(it->ti);
            free(it->tipText);
            free(it);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
        }
        return 0;
    }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

bool ff_toolbar_register(HINSTANCE inst)
{
    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = tb_proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = NULL;
    wc.lpszClassName = FF_TOOLBAR_CLASS;
    return RegisterClassExW(&wc) != 0;
}

/* first / count：本条带负责 s_cmd 里的哪一段按钮。
 * 现在只有一条带，创建时传 (0, FF_TB_COUNT) 即可。 */
HWND ff_toolbar_create(HWND parent, HINSTANCE inst, int first, int count)
{
    /* WS_CLIPSIBLINGS 必须要有：工具栏条横跨整条，地址栏是嵌在地址栏条上方的
     * 兄弟窗口。没有该样式时，工具栏每次重绘（例如鼠标热跟踪高亮某个按钮）都会
     * 把自己整条客户区（含地址栏所在矩形）不透明地涂满，把地址栏涂成空白——
     * 表现为"鼠标移到地址栏上就变白"。加上后绘制会裁掉地址栏矩形，不再覆盖。 */
    int cfg[2] = { first, count };
    HWND h = CreateWindowExW(0, FF_TOOLBAR_CLASS, L"",
                             WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                             0, 0, 100, 100, parent, (HMENU)(INT_PTR)IDC_TOOLBAR, inst, cfg);
    return h;
}

void ff_toolbar_set_enabled(HWND tb, int index, bool on)
{
    if (!tb || index < 0 || index >= FF_TB_COUNT) return;
    if (s_tb.enabled[index] != on) {
        s_tb.enabled[index] = on;
        InvalidateRect(tb, NULL, FALSE);
    }
}

/* 条带被隐藏时清掉热跟踪状态。
 * 否则鼠标正停在某个按钮上（按钮处于高亮态）时隐藏条带，s_tb.hot 会一直留着，
 * 条带再显示或重绘时仍按高亮画 —— 表现为"下面多出一排按钮"的残影。 */
void ff_toolbar_clear_hot(HWND tb)
{
    (void)tb;
    if (s_tb.hot != -1 || s_tb.pressed != -1) {
        s_tb.hot = -1;
        s_tb.pressed = -1;
        if (g_app.addrBar) InvalidateRect(g_app.addrBar, NULL, TRUE);
    }
}

void ff_toolbar_set_checked(HWND tb, int index, bool on)
{
    if (!tb || index < 0 || index >= FF_TB_COUNT) return;
    if (s_tb.checked[index] != on) {
        s_tb.checked[index] = on;
        InvalidateRect(tb, NULL, FALSE);
    }
}

void ff_toolbar_set_height(HWND tb, int h) { (void)tb; (void)h; }
