/* dialogs.c —— 查找文件 / 批量属性 / 备用数据流 / 关于 / 帮助 / 复制进度 */
#include "ff.h"
#include <shobjidl.h>

#define CLS_FIND    L"FFFindDlg"
#define CLS_ATTR    L"FFAttrDlg"
#define CLS_TEXT    L"FFTextDlg"

#define ID_FIND_ROOT    5001
#define ID_FIND_BROWSE  5002
#define ID_FIND_PATTERN 5003
#define ID_FIND_SUB     5004
#define ID_FIND_GO      5005
#define ID_FIND_STOP    5006
#define ID_FIND_CLOSE   5007
#define ID_FIND_STATUS  5008

#define ID_ATTR_RO      5101
#define ID_ATTR_HIDDEN  5102
#define ID_ATTR_SYS     5103
#define ID_ATTR_ARCH    5104
#define ID_ATTR_SUB     5105
#define ID_ATTR_OK      5106
#define ID_ATTR_CANCEL  5107

#define ID_TEXT_EDIT    5201
#define ID_TEXT_OK      5202

/* ===================================================== 公共 */
static HWND create_dialog(const wchar_t *cls, WNDPROC proc, const wchar_t *title,
                          int w, int h, HWND owner, LPVOID param)
{
    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = proc;
    wc.hInstance = g_app.inst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = cls;
    RegisterClassExW(&wc);

    DWORD style = WS_POPUP | WS_CAPTION | WS_SYSMENU;
    RECT r = { 0, 0, ff_scale(w), ff_scale(h) };
    AdjustWindowRectEx(&r, style, FALSE, 0);
    int ww = r.right - r.left, hh = r.bottom - r.top;

    RECT orc;
    GetWindowRect(owner, &orc);
    int x = orc.left + ((orc.right - orc.left) - ww) / 2;
    int y = orc.top + ((orc.bottom - orc.top) - hh) / 2;
    if (x < 0) x = 0;
    if (y < 0) y = 0;

    return CreateWindowExW(0, cls, title, style, x, y, ww, hh, owner, NULL,
                           g_app.inst, param);
}

static void modal_loop(HWND dlg, HWND owner)
{
    EnableWindow(owner, FALSE);
    ShowWindow(dlg, SW_SHOW);
    UpdateWindow(dlg);
    MSG msg;
    while (IsWindow(dlg) && GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (!IsDialogMessageW(dlg, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    if (IsWindow(owner)) {
        EnableWindow(owner, TRUE);
        SetForegroundWindow(owner);
    }
}

static HWND mk(HWND parent, const wchar_t *cls, const wchar_t *text, DWORD style,
               int x, int y, int w, int h, int id)
{
    HWND c = CreateWindowExW(WS_EX_CLIENTEDGE, cls, text,
                             WS_CHILD | WS_VISIBLE | style,
                             ff_scale(x), ff_scale(y), ff_scale(w), ff_scale(h),
                             parent, (HMENU)(INT_PTR)id, g_app.inst, NULL);
    if (c) SendMessageW(c, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
    return c;
}

static HWND mk_plain(HWND parent, const wchar_t *cls, const wchar_t *text, DWORD style,
                     int x, int y, int w, int h, int id)
{
    HWND c = CreateWindowExW(0, cls, text, WS_CHILD | WS_VISIBLE | style,
                             ff_scale(x), ff_scale(y), ff_scale(w), ff_scale(h),
                             parent, (HMENU)(INT_PTR)id, g_app.inst, NULL);
    if (c) SendMessageW(c, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
    return c;
}

/* ===================================================== 文本类对话框 */
static LRESULT CALLBACK text_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE: {
        CREATESTRUCTW *cs = (CREATESTRUCTW *)lp;
        const wchar_t *text = (const wchar_t *)cs->lpCreateParams;
        HWND e = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", text ? text : L"",
                                 WS_CHILD | WS_VISIBLE | WS_VSCROLL | ES_MULTILINE |
                                 ES_READONLY | ES_AUTOVSCROLL,
                                 ff_scale(12), ff_scale(12),
                                 ff_scale(566), ff_scale(300),
                                 hwnd, (HMENU)(INT_PTR)ID_TEXT_EDIT,
                                 g_app.inst, NULL);
        SendMessageW(e, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
        HWND b = CreateWindowExW(0, L"BUTTON", L"确定",
                                 WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON | WS_TABSTOP,
                                 ff_scale(516), ff_scale(322), ff_scale(64), ff_scale(28),
                                 hwnd, (HMENU)(INT_PTR)ID_TEXT_OK, g_app.inst, NULL);
        SendMessageW(b, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
        return 0;
    }
    case WM_COMMAND:
        if (LOWORD(wp) == ID_TEXT_OK || LOWORD(wp) == IDCANCEL) {
            DestroyWindow(hwnd);
            return 0;
        }
        break;
    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static void show_text_dialog(HWND owner, const wchar_t *title, const wchar_t *text)
{
    HWND d = create_dialog(CLS_TEXT, text_proc, title, 590, 372, owner, (LPVOID)text);
    if (d) modal_loop(d, owner);
}

void ff_dlg_about(HWND owner)
{
    wchar_t buf[4096];
    StringCchPrintfW(buf, 4096,
        L"%s\r\n"
        L"%s\r\n"
        L"版本 %s    %s\r\n"
        L"\r\n"
        L"—— 一个不依赖任何运行时的高速文件管理器 ——\r\n"
        L"\r\n"
        L"技术特征\r\n"
        L"  · 纯 C (C17) + Win32 API 编写，无 .NET / 无脚本引擎\r\n"
        L"  · 静态链接，单文件 exe，解压即用\r\n"
        L"  · 支持 Windows 7 SP1 x64 ~ Windows 11\r\n"
        L"  · 虚拟列表（LVS_OWNERDATA）：十万级目录即时呈现\r\n"
        L"  · 类型名与图标按扩展名缓存、按需解析\r\n"
        L"  · 多标签页，每个标签独立保存目录、历史与排序\r\n"
        L"\r\n"
        L"主要功能\r\n"
        L"  · 目录树 + 六列详细信息（名称/类型/大小/属性/修改/创建）\r\n"
        L"  · 前进后退历史、地址栏直跳、常用位置\r\n"
        L"  · 复制 / 移动 / 重命名 / 回收站删除 / 永久删除\r\n"
        L"  · 与资源管理器互通剪贴板（支持 Ctrl+C / Ctrl+V 互操作）\r\n"
        L"  · 递归查找文件、按修改日期与大小筛选\r\n"
        L"  · 批量设置只读/隐藏/系统/存档属性\r\n"
        L"  · NTFS 备用数据流（ADS）查看\r\n"
        L"\r\n"
        L"快捷键\r\n"
        L"  Ctrl+Shift+N 新建文件夹    F2 重命名    F5 刷新\r\n"
        L"  Ctrl+C/X/V 复制剪切粘贴    Delete 回收站    Shift+Delete 永久删除\r\n"
        L"  Ctrl+F 查找                Ctrl+L 地址栏/筛选    Ctrl+T 新标签\r\n"
        L"  Alt+← / Alt+→ 前进后退     Backspace 上级目录    F1 帮助\r\n"
        L"\r\n"
        L"本程序为独立实现，界面与交互参考经典文件管理器习惯，\r\n"
        L"不包含任何第三方运行库或受版权保护的资源。\r\n",
        FF_APP_TITLE, FF_APP_SUBTITLE, FF_APP_VERSION, FF_APP_BUILDTAG);
    show_text_dialog(owner, L"关于 " FF_APP_TITLE, buf);
}

void ff_dlg_help(HWND owner)
{
    wchar_t buf[4096];
    StringCchPrintfW(buf, 4096,
        L"【浏览】\r\n"
        L"  左侧目录树点击即跳转；地址栏可直接输入路径后回车。\r\n"
        L"  快捷键：Alt+← 后退、Alt+→ 前进、Backspace 上级、Alt+Home 此电脑、F5 刷新。\r\n"
        L"  在文件夹上双击即进入该文件夹；文件双击则用系统默认程序打开。\r\n"
        L"\r\n"
        L"【选择与排序】\r\n"
        L"  Ctrl+A 全选、Ctrl+单击 多选、Shift+单击 连续选择；\r\n"
        L"  单击列标题按该列排序，再次单击可反向；目录始终排在最前。\r\n"
        L"\r\n"
        L"【文件操作】\r\n"
        L"  Ctrl+C 复制、Ctrl+X 剪切、Ctrl+V 粘贴（与资源管理器双向兼容）。\r\n"
        L"  Delete 移入回收站，Shift+Delete 永久删除。F2 重命名。\r\n"
        L"  粘贴时若目标存在同名对象，会自动追加序号；\r\n"
        L"  移动大批文件时，同盘操作为瞬时改名，跨盘才进行实际拷贝。\r\n"
        L"\r\n"
        L"【筛选】\r\n"
        L"  工具栏漏斗按钮打开筛选面板：可按修改日期区间、最小尺寸、\r\n"
        L"  对象类型（文件/文件夹）过滤当前目录。状态栏右侧显示开关状态。\r\n"
        L"\r\n"
        L"【查找文件】\r\n"
        L"  Ctrl+F 打开查找窗口，支持通配符 * 与 ?，多模式用分号分隔，\r\n"
        L"  例如  *.txt;*.md;报告* 。查找在后台线程执行，可随时中断，\r\n"
        L"  结果会作为一个新的视图列出（名称列显示完整路径）。\r\n"
        L"\r\n"
        L"【多标签】\r\n"
        L"  Ctrl+T 新建标签、Ctrl+W 关闭当前标签，标签栏双击空白处亦可新建；\r\n"
        L"  鼠标滚轮可在标签之间切换；每个标签独立保存目录与历史。\r\n"
        L"\r\n"
        L"【进阶】\r\n"
        L"  右键菜单中的「备用数据流」可查看 NTFS 隐藏数据流；\r\n"
        L"  「批量设置属性」可对多选对象统一设置只读/隐藏/系统/存档。\r\n",
        FF_APP_TITLE);
    show_text_dialog(owner, L"帮助 - " FF_APP_TITLE, buf);
}

void ff_dlg_streams(HWND owner)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) {
        ff_msg_error(owner, L"请先选中一个文件再查看备用数据流。");
        return;
    }
    wchar_t buf[16384];              /* 栈上即可(32KB):static 零数组会进 .data */
    buf[0] = 0;
    for (int i = 0; i < n && i < 8; ++i) {
        wchar_t hdr[1024];
        StringCchPrintfW(hdr, 1024, L"%s\r\n", paths[i]);
        ff_str_cat(buf, 16384, hdr);
        wchar_t info[16384];
        if (fs_enum_streams(paths[i], info, 16384)) ff_str_cat(buf, 16384, info);
        else ff_str_cat(buf, 16384, L"  （无附加数据流）\r\n");
        ff_str_cat(buf, 16384, L"\r\n");
    }
    ff_free_paths(paths, n);
    show_text_dialog(owner, L"备用数据流 (Alternate Data Streams)", buf);
}

/* ===================================================== 批量属性 */
typedef struct {
    wchar_t **paths;
    int       count;
    bool      ok;
} AttrCtx;

static void attr_sync_ui(HWND hwnd, AttrCtx *ctx)
{
    int cnt[4] = { 0 }, total = 0;
    DWORD masks[4] = { FILE_ATTRIBUTE_READONLY, FILE_ATTRIBUTE_HIDDEN,
                       FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_ARCHIVE };
    for (int i = 0; i < ctx->count; ++i) {
        DWORD a = GetFileAttributesW(ctx->paths[i]);
        if (a == INVALID_FILE_ATTRIBUTES) continue;
        ++total;
        for (int k = 0; k < 4; ++k) if (a & masks[k]) ++cnt[k];
    }
    int ctrls[4] = { ID_ATTR_RO, ID_ATTR_HIDDEN, ID_ATTR_SYS, ID_ATTR_ARCH };
    for (int k = 0; k < 4; ++k) {
        int st = BST_UNCHECKED;
        if (total > 0 && cnt[k] == total) st = BST_CHECKED;
        else if (cnt[k] > 0) st = BST_INDETERMINATE;
        CheckDlgButton(hwnd, ctrls[k], st);
    }
}

static LRESULT CALLBACK attr_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    AttrCtx *ctx = (AttrCtx *)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
    switch (msg) {
    case WM_CREATE: {
        CREATESTRUCTW *cs = (CREATESTRUCTW *)lp;
        ctx = (AttrCtx *)cs->lpCreateParams;
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)ctx);

        mk_plain(hwnd, L"STATIC", L"勾选要应用的属性，灰显表示当前对象状态不一致：",
                 SS_LEFT, 16, 14, 380, 20, 0);
        mk_plain(hwnd, L"BUTTON", L"只读(&R)", BS_AUTO3STATE | WS_TABSTOP, 24, 44, 160, 24, ID_ATTR_RO);
        mk_plain(hwnd, L"BUTTON", L"隐藏(&H)", BS_AUTO3STATE | WS_TABSTOP, 24, 74, 160, 24, ID_ATTR_HIDDEN);
        mk_plain(hwnd, L"BUTTON", L"系统(&S)", BS_AUTO3STATE | WS_TABSTOP, 24, 104, 160, 24, ID_ATTR_SYS);
        mk_plain(hwnd, L"BUTTON", L"存档(&A)", BS_AUTO3STATE | WS_TABSTOP, 24, 134, 160, 24, ID_ATTR_ARCH);
        mk_plain(hwnd, L"BUTTON", L"应用到所有子文件夹与文件",
                 BS_AUTOCHECKBOX | WS_TABSTOP, 24, 168, 300, 24, ID_ATTR_SUB);

        wchar_t info[128];
        StringCchPrintfW(info, 128, L"共 %d 个对象", ctx ? ctx->count : 0);
        mk_plain(hwnd, L"STATIC", info, SS_LEFT, 24, 198, 300, 20, 0);

        mk_plain(hwnd, L"BUTTON", L"确定", BS_DEFPUSHBUTTON | WS_TABSTOP, 236, 226, 80, 28, ID_ATTR_OK);
        mk_plain(hwnd, L"BUTTON", L"取消", WS_TABSTOP, 324, 226, 80, 28, ID_ATTR_CANCEL);
        if (ctx) attr_sync_ui(hwnd, ctx);
        return 0;
    }
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if (id == ID_ATTR_OK && ctx) {
            DWORD setM = 0, clrM = 0;
            int ctrls[4] = { ID_ATTR_RO, ID_ATTR_HIDDEN, ID_ATTR_SYS, ID_ATTR_ARCH };
            DWORD masks[4] = { FILE_ATTRIBUTE_READONLY, FILE_ATTRIBUTE_HIDDEN,
                               FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_ARCHIVE };
            for (int k = 0; k < 4; ++k) {
                int st = IsDlgButtonChecked(hwnd, ctrls[k]);
                if (st == BST_CHECKED) setM |= masks[k];
                else if (st == BST_UNCHECKED) clrM |= masks[k];
            }
            bool recurse = IsDlgButtonChecked(hwnd, ID_ATTR_SUB) == BST_CHECKED;
            int fail = 0;
            for (int i = 0; i < ctx->count; ++i)
                if (!fs_set_attrs(ctx->paths[i], setM, clrM, recurse)) ++fail;
            ctx->ok = (fail == 0);
            if (fail) ff_msg_error(hwnd, L"有 %d 个对象设置失败（可能被占用或无权限）。", fail);
            DestroyWindow(hwnd);
            return 0;
        }
        if (id == ID_ATTR_CANCEL || id == IDCANCEL) {
            DestroyWindow(hwnd);
            return 0;
        }
        break;
    }
    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

void ff_dlg_attr(HWND owner)
{
    wchar_t **paths = NULL;
    int n = ff_selected_paths(&paths);
    if (n <= 0) {
        ff_msg_error(owner, L"请先选中要设置属性的对象。");
        return;
    }
    AttrCtx ctx;
    ctx.paths = paths;
    ctx.count = n;
    ctx.ok = false;

    HWND d = create_dialog(CLS_ATTR, attr_proc, L"批量设置属性", 430, 300, owner, &ctx);
    if (d) modal_loop(d, owner);
    ff_free_paths(paths, n);
    if (ctx.ok) ff_refresh(true);
}

/* ===================================================== 查找 */
typedef struct {
    wchar_t      root[FF_PATH_MAX];
    wchar_t      pattern[400];
    bool         recurse;
    FfEntryList  result;
    volatile LONG cancel;
    volatile LONG done;
    HWND         notify;
    HANDLE       thread;
    bool         taken;
} FindJob;

static FindJob *s_job = NULL;

static DWORD WINAPI find_thread(LPVOID p)
{
    FindJob *j = (FindJob *)p;
    fs_find_files(NULL, j->root, j->pattern, j->recurse, &j->result, &j->cancel);
    InterlockedExchange(&j->done, 1);
    if (IsWindow(j->notify)) PostMessageW(j->notify, WM_FF_FIND_PROG, 0, 0);
    return 0;
}

static void find_refresh_status(HWND hwnd)
{
    if (!s_job) return;
    wchar_t st[256];
    if (InterlockedCompareExchange(&s_job->done, 0, 0))
        StringCchPrintfW(st, 256, L"查找完成，共匹配 %d 项。", s_job->result.count);
    else
        StringCchPrintfW(st, 256, L"正在查找… 已匹配 %d 项", s_job->result.count);
    SetDlgItemTextW(hwnd, ID_FIND_STATUS, st);
}

static LRESULT CALLBACK find_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE: {
        wchar_t initRoot[FF_PATH_MAX] = L"";
        /* 用主窗口当前目录作为默认起始 */
        GetWindowTextW(g_app.addr, initRoot, FF_PATH_MAX);
        if (initRoot[0] == 0 || wcscmp(initRoot, L"此电脑") == 0) initRoot[0] = 0;

        mk_plain(hwnd, L"STATIC", L"查找位置", SS_LEFT, 16, 18, 90, 20, 0);
        mk(hwnd, L"EDIT", initRoot, ES_AUTOHSCROLL | WS_TABSTOP, 16, 40, 400, 26, ID_FIND_ROOT);
        mk_plain(hwnd, L"BUTTON", L"浏览…", WS_TABSTOP, 424, 40, 70, 26, ID_FIND_BROWSE);

        mk_plain(hwnd, L"STATIC", L"名称模式（支持 * ?，多个用分号分隔）", SS_LEFT, 16, 78, 400, 20, 0);
        mk(hwnd, L"EDIT", L"*.*", ES_AUTOHSCROLL | WS_TABSTOP, 16, 100, 478, 26, ID_FIND_PATTERN);

        mk_plain(hwnd, L"BUTTON", L"包含子文件夹(&S)", BS_AUTOCHECKBOX | WS_TABSTOP,
                 16, 136, 200, 24, ID_FIND_SUB);
        CheckDlgButton(hwnd, ID_FIND_SUB, BST_CHECKED);

        mk_plain(hwnd, L"STATIC", L"就绪。", SS_LEFT, 16, 168, 478, 20, ID_FIND_STATUS);

        HWND b = mk_plain(hwnd, L"BUTTON", L"开始查找", BS_DEFPUSHBUTTON | WS_TABSTOP,
                          316, 198, 88, 30, ID_FIND_GO);
        (void)b;
        mk_plain(hwnd, L"BUTTON", L"关闭", WS_TABSTOP, 410, 198, 84, 30, ID_FIND_CLOSE);
        return 0;
    }
    case WM_COMMAND: {
        int id = LOWORD(wp);
        if (id == ID_FIND_CLOSE || id == IDCANCEL) {
            if (s_job && !InterlockedCompareExchange(&s_job->done, 0, 0)) {
                InterlockedExchange(&s_job->cancel, 1);
                SetDlgItemTextW(hwnd, ID_FIND_STATUS, L"正在中断…");
                return 0;
            }
            DestroyWindow(hwnd);
            return 0;
        }
        if (id == ID_FIND_BROWSE) {
            wchar_t cur[FF_PATH_MAX];
            GetDlgItemTextW(hwnd, ID_FIND_ROOT, cur, FF_PATH_MAX);
            wchar_t sel[FF_PATH_MAX];
            if (ff_dlg_find_folder(hwnd, cur, sel, FF_PATH_MAX))
                SetDlgItemTextW(hwnd, ID_FIND_ROOT, sel);
            return 0;
        }
        if (id == ID_FIND_GO) {
            if (s_job && !InterlockedCompareExchange(&s_job->done, 0, 0)) return 0;

            wchar_t root[FF_PATH_MAX] = L"", pat[400] = L"";
            GetDlgItemTextW(hwnd, ID_FIND_ROOT, root, FF_PATH_MAX);
            GetDlgItemTextW(hwnd, ID_FIND_PATTERN, pat, 400);
            ff_trim(root); ff_trim(pat);
            if (!root[0]) {
                ff_msg_error(hwnd, L"请先指定查找位置。");
                return 0;
            }
            if (!pat[0]) ff_str_copy(pat, 400, L"*.*");

            if (s_job) {
                if (s_job->thread) CloseHandle(s_job->thread);
                if (!s_job->taken) fs_entry_list_free(&s_job->result);
                free(s_job);
                s_job = NULL;
            }
            s_job = (FindJob *)calloc(1, sizeof(FindJob));
            if (!s_job) return 0;
            ff_str_copy(s_job->root, FF_PATH_MAX, root);
            ff_str_copy(s_job->pattern, 400, pat);
            s_job->recurse = IsDlgButtonChecked(hwnd, ID_FIND_SUB) == BST_CHECKED;
            s_job->notify = hwnd;

            SetDlgItemTextW(hwnd, ID_FIND_STATUS, L"正在查找…");
            EnableWindow(GetDlgItem(hwnd, ID_FIND_GO), FALSE);
            SetTimer(hwnd, 1, 200, NULL);
            s_job->thread = CreateThread(NULL, 0, find_thread, s_job, 0, NULL);
            if (!s_job->thread) {
                /* 线程创建失败：退回同步查找 */
                fs_find_files(hwnd, s_job->root, s_job->pattern, s_job->recurse,
                              &s_job->result, &s_job->cancel);
                InterlockedExchange(&s_job->done, 1);
                SendMessageW(hwnd, WM_FF_FIND_PROG, 0, 0);
            }
            return 0;
        }
        break;
    }
    case WM_TIMER:
        find_refresh_status(hwnd);
        return 0;
    case WM_FF_FIND_PROG:
        if (s_job && InterlockedCompareExchange(&s_job->done, 0, 0)) {
            KillTimer(hwnd, 1);
            EnableWindow(GetDlgItem(hwnd, ID_FIND_GO), TRUE);
            find_refresh_status(hwnd);
            if (s_job->cancel) {
                SetDlgItemTextW(hwnd, ID_FIND_STATUS, L"查找已中断。");
            } else if (s_job->result.count == 0) {
                SetDlgItemTextW(hwnd, ID_FIND_STATUS, L"未找到匹配项。");
            } else {
                FfEntryList res = s_job->result;
                ZeroMemory(&s_job->result, sizeof(s_job->result));
                s_job->taken = true;
                ff_show_search_results(&res, s_job->pattern);
                DestroyWindow(hwnd);
            }
        }
        return 0;
    case WM_CLOSE:
        SendMessageW(hwnd, WM_COMMAND, MAKEWPARAM(ID_FIND_CLOSE, 0), 0);
        return 0;
    case WM_DESTROY:
        KillTimer(hwnd, 1);
        if (s_job) {
            InterlockedExchange(&s_job->cancel, 1);
            if (s_job->thread) {
                WaitForSingleObject(s_job->thread, 5000);
                CloseHandle(s_job->thread);
            }
            if (!s_job->taken) fs_entry_list_free(&s_job->result);
            free(s_job);
            s_job = NULL;
        }
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

void ff_dlg_find(HWND owner)
{
    HWND d = create_dialog(CLS_FIND, find_proc, L"查找文件", 522, 272, owner, NULL);
    if (d) modal_loop(d, owner);
}

/* ===================================================== 选择文件夹 */
bool ff_dlg_find_folder(HWND owner, const wchar_t *init, wchar_t *out, size_t cch)
{
    out[0] = 0;
    IFileOpenDialog *dlg = NULL;
    bool ok = false;
    HRESULT hr = CoCreateInstance(&CLSID_FileOpenDialog, NULL, CLSCTX_INPROC_SERVER,
                                  &IID_IFileOpenDialog, (void **)&dlg);
    if (SUCCEEDED(hr) && dlg) {
        DWORD opt = 0;
        dlg->lpVtbl->GetOptions(dlg, &opt);
        dlg->lpVtbl->SetOptions(dlg, opt | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM |
                                     FOS_PATHMUSTEXIST);
        if (init && *init) {
            IShellItem *item = NULL;
            if (SUCCEEDED(SHCreateItemFromParsingName(init, NULL, &IID_IShellItem, (void **)&item)) && item) {
                dlg->lpVtbl->SetFolder(dlg, item);
                item->lpVtbl->Release(item);
            }
        }
        if (SUCCEEDED(dlg->lpVtbl->Show(dlg, owner))) {
            IShellItem *item = NULL;
            if (SUCCEEDED(dlg->lpVtbl->GetResult(dlg, &item)) && item) {
                PWSTR p = NULL;
                if (SUCCEEDED(item->lpVtbl->GetDisplayName(item, SIGDN_FILESYSPATH, &p)) && p) {
                    ff_str_copy(out, cch, p);
                    CoTaskMemFree(p);
                    ok = true;
                }
                item->lpVtbl->Release(item);
            }
        }
        dlg->lpVtbl->Release(dlg);
    }
    if (!ok) {
        /* 回退到经典选择框（老系统或 COM 不可用时） */
        BROWSEINFOW bi;
        ZeroMemory(&bi, sizeof(bi));
        bi.hwndOwner = owner;
        bi.lpszTitle = L"请选择文件夹";
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_USENEWUI;
        LPITEMIDLIST pidl = SHBrowseForFolderW(&bi);
        if (pidl) {
            if (SHGetPathFromIDListW(pidl, out)) ok = true;
            CoTaskMemFree(pidl);
        }
    }
    return ok;
}

/* ===================================================== 复制进度对话框 */
LRESULT CALLBACK ff_copy_dlg_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE: {
        HWND c = CreateWindowExW(WS_EX_CLIENTEDGE, L"STATIC", L"正在准备…",
                                 WS_CHILD | WS_VISIBLE | SS_LEFTNOWORDWRAP | SS_ENDELLIPSIS,
                                 ff_scale(16), ff_scale(16), ff_scale(388), ff_scale(20),
                                 hwnd, (HMENU)(INT_PTR)IDC_COPY_CURRENT, g_app.inst, NULL);
        SendMessageW(c, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);

        c = CreateWindowExW(0, PROGRESS_CLASSW, L"", WS_CHILD | WS_VISIBLE,
                            ff_scale(16), ff_scale(46), ff_scale(388), ff_scale(18),
                            hwnd, (HMENU)(INT_PTR)IDC_COPY_PROGRESS, g_app.inst, NULL);
        SendMessageW(c, PBM_SETRANGE32, 0, 100);

        c = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_LEFT,
                            ff_scale(16), ff_scale(72), ff_scale(388), ff_scale(20),
                            hwnd, (HMENU)(INT_PTR)IDC_COPY_STATS, g_app.inst, NULL);
        SendMessageW(c, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);

        c = CreateWindowExW(0, L"BUTTON", L"取消", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                            ff_scale(324), ff_scale(100), ff_scale(80), ff_scale(28),
                            hwnd, (HMENU)(INT_PTR)IDC_COPY_CANCEL, g_app.inst, NULL);
        SendMessageW(c, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
        return 0;
    }
    case WM_COMMAND:
        if (LOWORD(wp) == IDC_COPY_CANCEL || LOWORD(wp) == IDCANCEL) {
            fs_cancel_copy();
            EnableWindow(GetDlgItem(hwnd, IDC_COPY_CANCEL), FALSE);
            SetDlgItemTextW(hwnd, IDC_COPY_CURRENT, L"正在取消…");
            return 0;
        }
        break;
    case WM_CLOSE:
        SendMessageW(hwnd, WM_COMMAND, MAKEWPARAM(IDC_COPY_CANCEL, 0), 0);
        return 0;
    case WM_CTLCOLORSTATIC: {
        SetBkMode((HDC)wp, TRANSPARENT);
        return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
    }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

bool ff_copy_dlg_register(HINSTANCE inst) { (void)inst; return true; }

/* ===================================================== "打开方式"对话框
 *
 * Win10 1809 起，公开的 SHOpenWithDialog 被系统降级：不管传什么 flag，都只
 * 弹一条橙色横幅"若要更改默认应用，请转到设置>应用>默认应用"（实测 Win10
 * 22H2 / 19045.6504，flags=0/EXEC/ALLOW_REG都一样，窗口类 Shell_Dialog
 * 只有 680x118 高）。Explorer 那个带列表的对话框走的是 shell 内部未公开的
 * 路径，第三方拿不到。所以这里按 Win10 的样子自己实现一个。
 *
 * 外观对齐资源管理器：
 *   标题"你要如何打开这个文件?"
 *   列表：默认程序在第一组（无标题），其余在"其他选项"组下面
 *   单选高亮 32x32 图标 + 程序名
 *   "始终使用此应用打开 .<ext> 文件" 复选框
 *   确定 / 取消
 */
#define CLS_OW        L"FFOpenWithDlg"
#define ID_OW_LIST    5301
#define ID_OW_ALWAYS  5302
#define ID_OW_OK      5303
#define ID_OW_GROUP1  5304   /* 默认程序（静态标题，Win10 里不带文字） */
#define ID_OW_GROUP2  5305   /* "其他选项" */
#define ID_OW_BROWSE  5306   /* "浏览..."：自己挑任意 exe */

#define OW_MAX        24

typedef struct {
    const wchar_t *file;
    wchar_t       ext[32];
    FfOpenWithChoice *ch;        /* 自己 malloc 的候选数组（允许追加浏览到的程序） */
    int           n;
    int           cap;
    int           sel;
    bool          always;
    /* 只有按下"确定"才置 true。之前只看 sel 是否有效，于是点"取消"
     * 也被当成"选中了第 0 项"，照样把文件打开了 —— 取消必须什么都不做。*/
    bool          accepted;
    HWND          list;
} OwCtx;

/* ow_row_to_choice 的返回值：>=0 候选下标，下面两个是特殊行 */
#define OW_ROW_HEADER  (-1)      /* "其它选项"分组标题 */
#define OW_ROW_BROWSE  (-2)      /* 最后一行"浏览其它应用程序…" */

static OwCtx *g_ow;      /* 模态期间只有一个 */

static HFONT g_ow_font;

/* 图标缓存：这个列表是自绘的（WM_DRAWITEM），**每次重绘都会问一次图标**。
 * 原来每次都走 SHGetFileInfo 并 CopyIcon，而且 CopyIcon 之后没有 DestroyIcon ——
 * 每画一次就泄漏一个 HICON；像 WorkBuddy 那种 195MB 的 Electron exe，
 * 首次提取还要 40+ms，滚动/重绘时就会肉眼可见地卡（用户实测"卡在 WorkBuddy 的图标"）。
 * 现在改成"每个 exe 只取一次、随对话框一起释放"。 */
#define OW_ICON_MAX 24
/* ★路径用指针存、按需分配：早先用的是 wchar_t exe[FF_PATH_MAX] 的内联数组，
 *   24 项 × (1024×2+8) ≈ 48 KB，而且因为结构体里有 HICON（需要重定位），
 *   整块被链接器放进 .data —— 直接从 exe 里多占了 48 KB 文件体积。
 *   改成指针后静态部分只有 24×16 = 384 字节，路径实际长度也就一百来个字符。 */
static wchar_t *s_owIconExe[OW_ICON_MAX];
static HICON    s_owIconIc[OW_ICON_MAX];
static int      s_owIconN = 0;

static void ow_icon_clear(void)
{
    for (int i = 0; i < s_owIconN; ++i) {
        if (s_owIconIc[i]) DestroyIcon(s_owIconIc[i]);
        s_owIconIc[i] = NULL;
        free(s_owIconExe[i]);
        s_owIconExe[i] = NULL;
    }
    s_owIconN = 0;
}

/* 取 32x32 图标（列表用大图标，和资源管理器一致）。
 * ★返回值由缓存持有，调用方不要 DestroyIcon。 */
static HICON ow_big_icon(const wchar_t *exe)
{
    if (!exe || !exe[0]) return NULL;
    for (int i = 0; i < s_owIconN; ++i)
        if (s_owIconExe[i] && _wcsicmp(s_owIconExe[i], exe) == 0) return s_owIconIc[i];

    HICON ic = NULL;
    /* SHGetFileInfo 的 SHGFI_ICON|SHGFI_LARGE 走系统图标缓存，最稳 */
    SHFILEINFOW sfi;
    ZeroMemory(&sfi, sizeof(sfi));
    if (SHGetFileInfoW(exe, 0, &sfi, sizeof(sfi), SHGFI_ICON | SHGFI_LARGEICON)
            && sfi.hIcon) {
        ic = (HICON)CopyIcon(sfi.hIcon);
        DestroyIcon(sfi.hIcon);      /* ★原来漏了这一句：每绘制一次泄漏一个图标句柄 */
    }
    if (!ic) ExtractIconExW(exe, 0, &ic, NULL, 1);
    if (!ic) {
        /* 兜底：取"通用 exe 图标"，别让这一行空着。
         * 商店应用别名、路径失效、权限受限的程序都可能拿不到真实图标
         * （用户实测：Word 2016 / Qianwen / WorkBuddy 这几项图标是空的）。 */
        ZeroMemory(&sfi, sizeof(sfi));
        if (SHGetFileInfoW(L"x.exe", FILE_ATTRIBUTE_NORMAL, &sfi, sizeof(sfi),
                           SHGFI_ICON | SHGFI_LARGEICON | SHGFI_USEFILEATTRIBUTES)
                && sfi.hIcon) {
            ic = (HICON)CopyIcon(sfi.hIcon);
            DestroyIcon(sfi.hIcon);
        }
    }

    if (s_owIconN < OW_ICON_MAX) {
        wchar_t *dup = _wcsdup(exe);
        if (dup) {
            s_owIconExe[s_owIconN] = dup;
            s_owIconIc[s_owIconN] = ic;
            ++s_owIconN;
            return ic;
        }
    }
    if (ic) DestroyIcon(ic);         /* 缓存满了：不要泄漏，这一项就不显示图标 */
    return NULL;
}

/* ---- 行布局（索引全部由行号推导，列表里不存 item data）----
 *   行 0              默认程序（候选 0）
 *   行 1（n>1 时）    分隔线 + "其它选项"标题
 *   行 2 ..n          其余候选（候选 1..n-1）
 *   最后一行          "浏览其它应用程序…"，自己弹文件框挑 exe
 * 之前只有前三种，没有最后一行 —— 系统枚举不到程序时列表就是空的，
 * 用户没有任何办法自己指定程序。 */
static int ow_row_to_choice(int row);
static int ow_row_count(void);
static int ow_row_from_y(HWND list, int y);

/* 自己挑一个 exe：弹系统"打开"对话框，过滤 *.exe */
static bool ow_pick_exe(HWND owner, wchar_t *out, size_t cch);
/* 把挑到的 exe 追加进候选列表（去重），返回候选下标；满了返回 -1 */
static int  ow_append_choice(const wchar_t *exe);
static bool ow_do_browse(HWND dlg, bool allowDirectConfirm);

static int ow_row_to_choice(int row)
{
    int last = ow_row_count() - 1;
    if (row == last)                return OW_ROW_BROWSE;
    if (row == 0)                   return 0;
    if (g_ow->n > 1 && row == 1)    return OW_ROW_HEADER;
    return row - 1;
}
static int ow_row_count(void)
{
    return (g_ow->n > 1 ? g_ow->n + 1 : g_ow->n) + 1;   /* +1 = 浏览行 */
}
/* 候选下标 -> 它在列表里的行号。
 * 只有 1 个候选时没有"其它选项"标题行，候选 0 在行 0；
 * 有多个候选时行 1 被标题行占掉，候选 idx(idx>=1) 在行 idx+1。 */
static int ow_row_of_choice(int idx)
{
    if (idx <= 0) return 0;
    if (g_ow->n <= 1) return idx;
    return idx + 1;
}

/* ---- 列表自己画每一项 ----
 * 不走"父窗口收WM_DRAWITEM"那条路：自绘弹窗里那条路由不可靠（消息确实
 * 到了父窗口，但按 hwndCtl 匹配不上，结果整片空白）。改成给列表框装子类，
 * 由列表框的 WM_PAINT 里逐行画，行为与ListView 的 owner-draw 一致。 */
static LRESULT CALLBACK ow_list_sub(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                UINT_PTR id, DWORD_PTR ref)
{
    OwCtx *ctx = (OwCtx *)ref;
    if (msg == WM_PAINT && ctx) {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        RECT rc;
        GetClientRect(hwnd, &rc);
        HBRUSH bg = CreateSolidBrush(GetSysColor(COLOR_WINDOW));
        FillRect(dc, &rc, bg);
        DeleteObject(bg);

        int rows = ow_row_count();
        int cur  = (int)SendMessageW(hwnd, LB_GETCURSEL, 0, 0);
        bool focused = GetFocus() == hwnd;

        SelectObject(dc, g_ow_font);
        SetBkMode(dc, TRANSPARENT);

        for (int i = 0; i < rows; ++i) {
            /* ★每行的矩形一律问列表框要（LB_GETITEMRECT），不再自己按
             *   "滚动位置 × 行高"推算 —— 推算一旦和控件内部的行高/滚动量
             *   对不上，行就会画错位，用户看到的就是"第 5 行跑出来和框重叠"。 */
            RECT row;
            if (SendMessageW(hwnd, LB_GETITEMRECT, (WPARAM)i, (LPARAM)&row) == LB_ERR)
                continue;
            if (row.bottom <= rc.top || row.top >= rc.bottom) continue;  /* 不可见 */
            /* ★只画"整行都在可视区内"的行：底部露半截的一律不画。
             *   否则那半截会压在列表框的下边框上，看着就像"多出来一项、和框重叠"
             *   （用户实测报过）。列表照旧能滚动，滚到完整可见的行才画。 */
            if (row.bottom > rc.bottom) continue;
            int idx = ow_row_to_choice(i);
            int rowH = row.bottom - row.top;
            if (rowH <= 0) continue;

            /* 分组标题行：一条分隔线 + 灰字"其它选项" */
            if (idx == OW_ROW_HEADER) {
                HPEN pen = CreatePen(PS_SOLID, 1, RGB(224, 224, 224));
                HGDIOBJ oldPen = SelectObject(dc, pen);
                MoveToEx(dc, ff_scale(12), row.top + rowH / 2, NULL);
                LineTo(dc, rc.right - ff_scale(12), row.top + rowH / 2);
                SelectObject(dc, oldPen);
                DeleteObject(pen);
                SetTextColor(dc, RGB(110, 110, 110));
                RECT t = row;
                t.left += ff_scale(20); t.right -= ff_scale(8);
                DrawTextW(dc, L"其它选项", -1, &t,
                          DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX);
                continue;
            }

            if (i == cur) {
                /* 用系统 Highlight 跟随主题（Win10 是蓝的），别硬编码颜色 */
                HBRUSH b = CreateSolidBrush(focused ? GetSysColor(COLOR_HIGHLIGHT)
                                                    : GetSysColor(COLOR_BTNFACE));
                FillRect(dc, &row, b);
                DeleteObject(b);
                SetTextColor(dc, focused ? GetSysColor(COLOR_HIGHLIGHTTEXT)
                                        : GetSysColor(COLOR_BTNTEXT));
            } else {
                SetTextColor(dc, GetSysColor(COLOR_BTNTEXT));
            }

            int pad = ff_scale(8), isz = ff_scale(32);
            RECT t;
            t.left = row.left + pad;
            t.right = row.right - pad;
            t.top = row.top; t.bottom = row.bottom;

            if (idx == OW_ROW_BROWSE) {
                /* 最后一行：一个文件夹样式图标 + "浏览其它应用程序…" */
                HICON ic = ow_big_icon(L"%SystemRoot%\\System32\\imageres.dll");
                if (!ic) ic = LoadIconW(NULL, IDI_APPLICATION);
                if (ic) {
                    DrawIconEx(dc, pad, row.top + (rowH - isz) / 2, ic, isz, isz,
                               0, NULL, DI_NORMAL);
                    /* 图标由缓存持有，这里不销毁（IDI_APPLICATION 也是共享图标） */
                }
                t.left = row.left + pad + isz + ff_scale(10);
                DrawTextW(dc, L"浏览其它应用程序(&B)…", -1, &t,
                          DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX);
                continue;
            }

            HICON ic = ow_big_icon(ctx->ch[idx].exe);
            if (ic) {
                DrawIconEx(dc, pad, row.top + (rowH - isz) / 2, ic, isz, isz,
                           0, NULL, DI_NORMAL);
                /* 同上：缓存持有，不销毁 */
            }
            t.left = row.left + pad + isz + ff_scale(10);
            DrawTextW(dc, ctx->ch[idx].label, -1, &t,
                      DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX);
        }
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (msg == WM_KEYDOWN && wp == VK_RETURN) {
        /* 列表吃掉回车后不会产生 WM_COMMAND，这里补一次"确定" */
        SendMessageW(GetParent(hwnd), WM_COMMAND, MAKEWPARAM(ID_OW_OK, 0), 0);
        return 0;
    }
    if (msg == WM_LBUTTONDOWN) {
        /* 单击即选中那一行（Win10 同款）。只重绘不拦截，让列表框自己走
         * 原生的按下/锚点逻辑；点在"浏览"行上只选中不弹文件框（双击才直接挑）。 */
        int row = ow_row_from_y(hwnd, GET_Y_LPARAM(lp));
        if (row >= 0) SendMessageW(hwnd, LB_SETCURSEL, row, FALSE);
        InvalidateRect(hwnd, NULL, FALSE);
        /* 不 return：交给 DefSubclassProc 完成原生按下处理 */
    }
    if (msg == WM_LBUTTONDBLCLK) {
        /* 双击：选中那一行；点在"浏览"行上就直接开文件框 */
        int row = ow_row_from_y(hwnd, GET_Y_LPARAM(lp));
        if (row >= 0) SendMessageW(hwnd, LB_SETCURSEL, row, FALSE);
        SendMessageW(GetParent(hwnd), WM_COMMAND, MAKEWPARAM(ID_OW_OK, 0), 0);
        return 0;
    }
    if (msg == WM_LBUTTONDOWN || msg == WM_LBUTTONUP || msg == WM_KEYUP ||
        msg == WM_KILLFOCUS || msg == WM_MOUSEWHEEL)
        InvalidateRect(hwnd, NULL, FALSE);
    return DefSubclassProc(hwnd, msg, wp, lp);
}

/* 列表的行布局：第 0 行是默认程序，接着一行"其它选项"标题，
 * 之后依次是其余候选，最后一行是"浏览其它应用程序…"。 */

/* 屏幕 y坐标 -> 行号（考虑列表的滚动位置）；点在空白处返回 -1 */
static int ow_row_from_y(HWND list, int y)
{
    int itemH = (int)SendMessageW(list, LB_GETITEMHEIGHT, 0, 0);
    int rowH  = (itemH > ff_scale(32)) ? itemH - 2 : ff_scale(32) + ff_scale(6);
    if (rowH <= 0) return -1;
    int top = (int)SendMessageW(list, LB_GETTOPINDEX, 0, 0);
    if (top < 0) top = 0;
    int row = top + y / rowH;
    if (row < 0 || row >= ow_row_count()) return -1;
    return row;
}

static void ow_fill(HWND list, int selRow)
{
    SendMessageW(list, LB_RESETCONTENT, 0, 0);
    /* 占位文本无所谓（每项都是子类自绘），只为让 LB_GETCOUNT / 滚动条有值。 */
    int rows = ow_row_count();
    for (int i = 0; i < rows; ++i)
        SendMessageW(list, LB_ADDSTRING, 0, (LPARAM)L"");
    if (selRow >= 0 && selRow < rows) {
        SendMessageW(list, LB_SETCURSEL, selRow, FALSE);
        SendMessageW(list, LB_SETTOPINDEX, selRow, FALSE);
    }
    InvalidateRect(list, NULL, TRUE);
}

/* 用户点了列表里的"浏览其它应用程序…"或底部的"浏览..."按钮。
 * 挑到 exe 就追加进候选并选中。返回 true=可以直接进入"确定"流程；
 * 返回 false=用户取消了文件框（对话框继续留着）。 */
static bool ow_do_browse(HWND dlg, bool allowDirectConfirm)
{
    OwCtx *ctx = g_ow;
    HWND list = GetDlgItem(dlg, ID_OW_LIST);
    wchar_t exe[FF_PATH_MAX];
    if (!ow_pick_exe(dlg, exe, FF_PATH_MAX)) return false;   /* 用户取消 */
    int added = ow_append_choice(exe);
    if (added < 0) return false;
    ow_fill(list, ow_row_of_choice(added));
    SetFocus(list);
    /* 一个候选都没有时（系统枚举不出来），挑完直接确认打开，
     * 否则先让用户在列表里看到新加的这一项，再点确定。 */
    return allowDirectConfirm && ctx->n <= 1;
}

static LRESULT CALLBACK ow_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    OwCtx *ctx = g_ow;
    switch (msg) {
    case WM_COMMAND: {
        WORD id = LOWORD(wp), code = HIWORD(wp);
        if (id == ID_OW_ALWAYS && code == BN_CLICKED && ctx) {
            ctx->always = Button_GetCheck(GetDlgItem(hwnd, ID_OW_ALWAYS)) == BST_CHECKED;
            return 0;
        }
        if (id == ID_OW_BROWSE) {
            ow_do_browse(hwnd, false);      /* 从按钮进来：一律先回列表看选中了谁 */
            return 0;
        }
        if (id == ID_OW_OK) {
            HWND list = GetDlgItem(hwnd, ID_OW_LIST);
            int row = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
            if (row < 0) return 0;                   /* 没选中：不给关 */
            int idx = ow_row_to_choice(row);

            if (idx == OW_ROW_BROWSE && !ow_do_browse(hwnd, true)) return 0;

            row = (int)SendMessageW(list, LB_GETCURSEL, 0, 0);
            idx = ow_row_to_choice(row);
            if (idx >= 0 && idx < ctx->n) {
                ctx->sel = idx;
                ctx->accepted = true;               /* 只有确定才算数 */
                ctx->always = Button_GetCheck(GetDlgItem(hwnd, ID_OW_ALWAYS)) == BST_CHECKED;
                DestroyWindow(hwnd);
                return 0;
            }
            return 0;
        }
        if (id == IDCANCEL) {
            /* 取消：什么都不打开，accepted 保持 false */
            if (ctx) ctx->sel = -1;
            DestroyWindow(hwnd);
            return 0;
        }
        break;
    }
    case WM_CLOSE:
        if (ctx) ctx->sel = -1;
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        /* 只结束自己的模态循环：不能 PostQuitMessage —— 那条 WM_QUIT 会被
         * 主窗口的 GetMessage 消费掉，主窗口随之退出（表现为"关掉对话框后
         * 整个程序崩/消失"）。改成向外层 modal_loop 发一条自定义消息。 */
        PostMessageW(GetParent(hwnd), WM_FF_OWDLG_CLOSED, 0, 0);
        return 0;
    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLORBTN:
        SetBkMode((HDC)wp, TRANSPARENT);
        return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

/* 读一个字符串值；name 传 NULL = 默认值。cb 在内部按cch 复位，
     * 循环里反复读不同槽位时不会越读越短。 */
static bool reg_read(HKEY root, const wchar_t *sub, const wchar_t *name,
                     wchar_t *out, size_t cch)
{
    out[0] = 0;
    HKEY k;
    if (RegOpenKeyExW(root, sub, 0, KEY_QUERY_VALUE, &k) != ERROR_SUCCESS)
        return false;
    DWORD type = 0, cb = (DWORD)(cch * sizeof(wchar_t));
    LONG r = RegQueryValueExW(k, name, NULL, &type, (BYTE *)out, &cb);
    RegCloseKey(k);
    if (r != ERROR_SUCCESS || (type != REG_SZ && type != REG_EXPAND_SZ)) {
        out[0] = 0;
        return false;
    }
    out[cch - 1] = 0;
    return out[0] != 0;
}

/* 写一个字符串值（自动建键）。name 传 NULL = 默认值。 */
static bool reg_write(HKEY root, const wchar_t *sub, const wchar_t *name,
                      const wchar_t *val)
{
    HKEY k;
    if (RegCreateKeyExW(root, sub, 0, NULL, 0, KEY_SET_VALUE, NULL, &k, NULL)
            != ERROR_SUCCESS) return false;
    DWORD cb = (DWORD)((wcslen(val) + 1) * sizeof(wchar_t));
    LONG r = RegSetValueExW(k, name, 0, REG_SZ, (const BYTE *)val, cb);
    RegCloseKey(k);
    return r == ERROR_SUCCESS;
}

/* 勾选"始终使用此应用"后落地关联。Win10 的 UserChoice 键带 hash 保护，
 * 第三方程序写不了，所以只能走 HKCU\Software\Classes 这条路 —— 但 Explorer
 * 的"打开方式"菜单和"默认应用"设置都会照它显示。
 *
 * 关键是必须写全。一个程序要出现在"打开方式"列表里，shell 至少要看到：
 *   Applications\<exe>\shell\open\command   知道拿哪个 exe 启动
 *   Applications\<exe>\SupportedTypes\<ext>  知道支持什么扩展名
 *   <ext>\OpenWithProgids\<progid>           SHAssocEnumHandlers 只枚举这里
 * 以前只写了第 2 项，于是"勾了始终使用此应用"也照样不进列表 —— 而这
 * 恰恰是绿色版程序唯一的注册途径。 */
static void ow_apply_always(const OwCtx *ctx)
{
    if (!ctx || ctx->sel < 0 || ctx->sel >= ctx->n || !ctx->ext[0]) return;
    const FfOpenWithChoice *c = &ctx->ch[ctx->sel];
    const wchar_t *exeName = PathFindFileNameW(c->exe);
    wchar_t sub[512], cmd[FF_PATH_MAX + 16];
    StringCchPrintfW(cmd, FF_PATH_MAX + 16, L"\"%s\" \"%%1\"", c->exe);

    /* 1) Applications\<exe>：完整的程序注册 */
    StringCchPrintfW(sub, 512,
        L"Software\\Classes\\Applications\\%s\\shell\\open\\command", exeName);
    reg_write(HKEY_CURRENT_USER, sub, NULL, cmd);
    StringCchPrintfW(sub, 512,
        L"Software\\Classes\\Applications\\%s\\shell\\edit\\command", exeName);
    reg_write(HKEY_CURRENT_USER, sub, NULL, cmd);

    /* 不写图标的话菜单里只有 exe 名没有图标 */
    wchar_t icon[FF_PATH_MAX + 8];
    StringCchPrintfW(icon, FF_PATH_MAX + 8, L"\"%s\",0", c->exe);
    StringCchPrintfW(sub, 512, L"Software\\Classes\\Applications\\%s\\DefaultIcon",
                     exeName);
    reg_write(HKEY_CURRENT_USER, sub, NULL, icon);

    /* 声明支持该扩展名。按 Windows 惯例写成 SupportedTypes 键下的
     * "值"（画图/WMP 都是这个写法），而不是子键 —— 早先写成子键，
     * Explorer 和按值枚举的检查都认不出来。 */
    StringCchPrintfW(sub, 512,
        L"Software\\Classes\\Applications\\%s\\SupportedTypes", exeName);
    reg_write(HKEY_CURRENT_USER, sub, ctx->ext, L"");

    /* 2) progID：用现成的，没有就造一个稳定的（progID 里不能有空格） */
    wchar_t autoId[96];
    const wchar_t *progid = c->progid;
    if (!progid || !progid[0]) {
        wchar_t safe[64];
        StringCchCopyW(safe, 64, exeName);
        for (wchar_t *p = safe; *p; ++p)
            if (*p == L' ' || *p == L'.') *p = L'_';
        StringCchPrintfW(autoId, 96, L"FileCE.%s.%s", ctx->ext, safe);
        progid = autoId;
        StringCchPrintfW(sub, 512, L"Software\\Classes\\%s\\shell\\open\\command", progid);
        reg_write(HKEY_CURRENT_USER, sub, NULL, cmd);
        StringCchPrintfW(sub, 512, L"Software\\Classes\\%s\\DefaultIcon", progid);
        reg_write(HKEY_CURRENT_USER, sub, NULL, icon);
    }

    /* 3) 扩展名默认 ProgID（HKCU 覆盖 HKCR） */
    StringCchPrintfW(sub, 512, L"Software\\Classes\\%s", ctx->ext);
    reg_write(HKEY_CURRENT_USER, sub, NULL, progid);

    /* 3b) 删掉 Explorer 的 UserChoice。它带 hash 保护（第三方写不进去），
     *     而 shell 取"当前默认"时它优先于 HKCU\Software\Classes\<ext> ——
     *     不删的话，上面第 3 步写了也白写，双击/再打开还是老程序
     *     （用户实测："选了始终打开没有用，再次打开还是记事本"）。
     *     删掉它，shell 会退回按 Classes\<ext> 的默认 ProgID 解析，正是我们刚写的。 */
    StringCchPrintfW(sub, 512,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\"
        L"FileExts\\%s\\UserChoice", ctx->ext);
    RegDeleteKeyW(HKEY_CURRENT_USER, sub);

    /* 4) OpenWithProgids：SHAssocEnumHandlers 唯一的数据来源。
     *    不写这一项，系统枚举永远返回不了这个程序。
     *    注意 progid 是 OpenWithProgids 键下的"值"（Windows 惯例，Explorer
     *    只认值），不是子键 —— 写成子键 Explorer 枚举不出来（与 SupportedTypes
     *    同一个坑）。 */
    StringCchPrintfW(sub, 512, L"Software\\Classes\\%s\\OpenWithProgids",
                     ctx->ext);
    reg_write(HKEY_CURRENT_USER, sub, progid, L"");
    StringCchPrintfW(sub, 512,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\"
        L"FileExts\\%s\\OpenWithProgids", ctx->ext);
    reg_write(HKEY_CURRENT_USER, sub, progid, L"");

    /* 5) 加进 Explorer 的"打开方式"历史。
     *    插到最前而不是只写 MRUList="a" —— 后者会把用户原有历史全抹掉。
     *
     *    这里必须用 reg_read：RegQueryValueExW 的 cb 是 in/out 参数，
     *    循环里复用同一个 cb 会越读越短，最后只剩首字符（拿到 "N" 这种
     *    碎片），后面几个槽位就被当成无效值丢掉。丢的正是"用户以前用过、
     *    这次没选"的那几个 —— 表现为"刚勾了始终使用它在列表里，
     *    一旦改回默认程序它就消失了"。 */
    StringCchPrintfW(sub, 512,
        L"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\"
        L"FileExts\\%s\\OpenWithList", ctx->ext);
    {
        /* 8 * FF_PATH_MAX 有 16KB，别放栈上 */
        wchar_t(*old)[FF_PATH_MAX] = calloc(8, sizeof(wchar_t) * FF_PATH_MAX);
        int no = 0;
        if (old) {
            for (int i = 0; i < 8; ++i) {
                wchar_t slot[8];
                StringCchPrintfW(slot, 8, L"%c", L'a' + i);
                if (!reg_read(HKEY_CURRENT_USER, sub, slot, old[no], FF_PATH_MAX))
                    break;
                if (_wcsicmp(old[no], exeName) != 0) ++no;
            }
            for (int i = no; i > 0; --i) {
                wchar_t slot[8];
                StringCchPrintfW(slot, 8, L"%c", L'a' + i);
                reg_write(HKEY_CURRENT_USER, sub, slot, old[i - 1]);
            }
        }
        reg_write(HKEY_CURRENT_USER, sub, L"a", exeName);
        wchar_t mru[16];
        mru[0] = 0;
        for (int i = 0; i < no && i < 7; ++i) {
            wchar_t one[8];
            StringCchPrintfW(one, 8, L"%c", L'b' + i);
            StringCchCatW(mru, 16, one);
        }
        reg_write(HKEY_CURRENT_USER, sub, L"MRUList", mru);
        free(old);
    }

    /* 6) 记进本程序私有的历史（存完整路径）。这样即便系统那边注册失败、
     *    或被 UserChoice 的 hash 挡住，我们的列表里始终有它。 */
    ff_open_with_remember(ctx->ext, c->exe);

    /* 7) 通知 shell 关联变了，图标/菜单立刻刷新 */
    SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, NULL, NULL);
}

/* "浏览其它应用程序…"：弹系统文件框，让用户自己挑一个 exe。
 * 之前对话框只有系统枚举出来的候选，枚举不到（冷门扩展名、没装对应
 * 程序、UWP 应用）时列表就是空的，用户一点办法都没有。 */
static bool ow_pick_exe(HWND owner, wchar_t *out, size_t cch)
{
    out[0] = 0;
    IFileOpenDialog *dlg = NULL;
    if (SUCCEEDED(CoCreateInstance(&CLSID_FileOpenDialog, NULL, CLSCTX_INPROC_SERVER,
                                  &IID_IFileOpenDialog, (void **)&dlg)) && dlg) {
        DWORD opt = 0;
        dlg->lpVtbl->GetOptions(dlg, &opt);
        dlg->lpVtbl->SetOptions(dlg, (opt | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST |
                                      FOS_FILEMUSTEXIST) & ~FOS_PICKFOLDERS);
        COMDLG_FILTERSPEC fs[1];
        fs[0].pszName = L"应用程序 (*.exe)";
        fs[0].pszSpec = L"*.exe";
        dlg->lpVtbl->SetFileTypes(dlg, 1, fs);
        dlg->lpVtbl->SetTitle(dlg, L"选择用来打开此文件的程序");
        if (SUCCEEDED(dlg->lpVtbl->Show(dlg, owner))) {
            IShellItem *item = NULL;
            if (SUCCEEDED(dlg->lpVtbl->GetResult(dlg, &item)) && item) {
                PWSTR p = NULL;
                if (SUCCEEDED(item->lpVtbl->GetDisplayName(item, SIGDN_FILESYSPATH, &p))
                    && p) {
                    ff_str_copy(out, cch, p);
                    CoTaskMemFree(p);
                }
                item->lpVtbl->Release(item);
            }
        }
        dlg->lpVtbl->Release(dlg);
    }
    return out[0] != 0;
}

/* 挑好的 exe 追加进候选数组（同一个 exe 不重复加）。返回候选下标。 */
static int ow_append_choice(const wchar_t *exe)
{
    if (!g_ow || !exe || !exe[0]) return -1;
    for (int i = 0; i < g_ow->n; ++i)
        if (_wcsicmp(g_ow->ch[i].exe, exe) == 0) return i;   /* 已在列表里 */

    if (g_ow->n >= g_ow->cap) {
        int cap = g_ow->cap * 2;
        FfOpenWithChoice *p = (FfOpenWithChoice *)realloc(g_ow->ch,
                                        (size_t)cap * sizeof(FfOpenWithChoice));
        if (!p) return -1;
        g_ow->ch = p;
        g_ow->cap = cap;
    }
    FfOpenWithChoice *c = &g_ow->ch[g_ow->n];
    ZeroMemory(c, sizeof(*c));
    StringCchCopyW(c->exe, FF_PATH_MAX, exe);

    /* 显示名：优先问系统这个 exe 叫什么，其次用文件名（去掉 .exe） */
    DWORD need = 0;
    if (SUCCEEDED(AssocQueryStringW(ASSOCF_INIT_BYEXENAME, ASSOCSTR_FRIENDLYAPPNAME,
                                    exe, NULL, NULL, &need)) && need > 1) {
        wchar_t nm[128];
        if (need < 128 && SUCCEEDED(AssocQueryStringW(ASSOCF_INIT_BYEXENAME,
                                        ASSOCSTR_FRIENDLYAPPNAME, exe, NULL, nm, &need)))
            StringCchCopyW(c->label, 128, nm);
    }
    if (!c->label[0]) {
        StringCchCopyW(c->label, 128, PathFindFileNameW(exe));
        wchar_t *d = wcsrchr(c->label, L'.');
        if (d && d != c->label) *d = 0;
    }
    /* progID 留空：ow_apply_always 会按 exe 名自动造一个稳定的 */
    return g_ow->n++;
}

bool ff_dlg_open_with(HWND owner, const wchar_t *file,
                      FfOpenWithChoice *choices, int count, int *picked,
                      wchar_t *outExe, size_t cchExe)
{
    /* count 可以为 0（冷门扩展名一个候选都没有）：照样弹框，框里还有
     * "浏览..."让用户自己挑。只挡"有候选却没给数组"的真错误 —— 早先
     * 写成 !choices && count <= 0 就 return，靠着系统 NONE 枚举兜底
     * 候选永远非零从没暴露；砍掉 NONE 枚举后冷门扩展名一弹就哑。 */
    if (count > 0 && !choices) return false;
    if (picked) *picked = -1;
    if (outExe && cchExe) outExe[0] = 0;

    OwCtx ctx;
    ZeroMemory(&ctx, sizeof(ctx));
    ctx.file = file;
    ctx.n = count;
    ctx.cap = count > 0 ? count : 4;
    /* 拷一份到自己的数组：浏览时可能还要往里追加，调用方那块是定长的 */
    ctx.ch = (FfOpenWithChoice *)calloc((size_t)ctx.cap, sizeof(FfOpenWithChoice));
    if (!ctx.ch) return false;
    for (int i = 0; i < count; ++i) ctx.ch[i] = choices[i];
    ctx.sel = -1;
    const wchar_t *dot = file ? wcsrchr(PathFindFileNameW(file), L'.') : NULL;
    if (dot && dot[1]) StringCchCopyW(ctx.ext, 32, dot);
    g_ow = &ctx;

    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = ow_proc;
    wc.hInstance = g_app.inst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = CLS_OW;
    RegisterClassExW(&wc);

    /* 宽 420 高 470：和 Win10 那个对话框比例接近 */
    const int DW = 420, DH = 352;
    DWORD style = WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_CLIPCHILDREN;
    RECT r = { 0, 0, ff_scale(DW), ff_scale(DH) };
    AdjustWindowRectEx(&r, style, FALSE, 0);
    int ww = r.right - r.left, hh = r.bottom - r.top;
    RECT orc;
    GetWindowRect(owner, &orc);
    int x = orc.left + ((orc.right - orc.left) - ww) / 2;
    int y = orc.top+ ((orc.bottom - orc.top) - hh) / 2;
    if (x < 0) x = 0;
    if (y < 0) y = 0;

    HWND dlg = CreateWindowExW(WS_EX_DLGMODALFRAME, CLS_OW, L"你要如何打开这个文件?",
                              style, x, y, ww, hh, owner, NULL, g_app.inst, NULL);
    if (!dlg) { g_ow = NULL; return false; }

    HFONT f = ff_ui_font();
    /* 列表。注意几个坑：
     *  1) 不能加 WS_EX_LAYERED —— 分层窗口不走普通 WM_PAINT，owner-draw
     *     的每一项都画不出来（列表整片空白）；
     *  2) 每一项由 ow_list_sub 在列表框自己的 WM_PAINT 里逐行画（父窗口的
     *     WM_DRAWITEM 路由在自绘弹窗里匹配不上 hwndCtl，会整片空白）；
     *  3) 不往列表里存 item data —— LBS_NODATA 下实测 LB_GETITEMDATA 仍返回
     *     NULL，行号到候选的映射由 ow_row_to_choice() 直接算，最省事也最稳。
     *  4) 必须用 LBS_OWNERDRAWFIXED + LB_SETITEMHEIGHT 把【控件自己的行高】
     *     设成和自绘一致 —— 普通列表框行高只有一行字（约 20px），自绘却按
     *     38px 画行，于是原生的鼠标命中/键盘定位全按 20px 算：点"写字板"
     *     实际选中隔一行的那项，再点一下空区 LB_SETCURSEL 又被清掉 ——
     *     用户看到的就是"上面的选项点不中、点来点去停在记事本"。 */
    HWND list = CreateWindowExW(WS_EX_CLIENTEDGE, L"LISTBOX", L"",
                                WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_TABSTOP |
                                LBS_NOINTEGRALHEIGHT | LBS_OWNERDRAWFIXED,
                                ff_scale(12), ff_scale(12), ff_scale(DW - 24), ff_scale(228),
                                dlg, (HMENU)(INT_PTR)ID_OW_LIST, g_app.inst, NULL);
    {
        int rowH = ff_scale(32) + ff_scale(6);
        SendMessageW(list, LB_SETITEMHEIGHT, 0, MAKELPARAM(rowH, 0));
    }
    SendMessageW(list, WM_SETFONT, (WPARAM)f, TRUE);
    g_ow_font = f;
    ctx.list = list;
    SetWindowSubclass(list, ow_list_sub, 1, (DWORD_PTR)&ctx);

    /* "始终使用此应用打开 .txt 文件" */
    HWND ck = CreateWindowExW(0, L"BUTTON", L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                              BS_AUTOCHECKBOX,
                              ff_scale(12), ff_scale(252), ff_scale(300), ff_scale(24),
                              dlg, (HMENU)(INT_PTR)ID_OW_ALWAYS, g_app.inst, NULL);
    SendMessageW(ck, WM_SETFONT, (WPARAM)f, TRUE);
    wchar_t ckText[160];
    StringCchPrintfW(ckText, 160, L"始终使用此应用打开 %s 文件",
                     ctx.ext[0] ? ctx.ext : L"这些");
    SetWindowTextW(ck, ckText);

    /* 确定 / 取消 */
    HWND ok = CreateWindowExW(0, L"BUTTON", L"确定",
                              WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
                              ff_scale(DW - 196), ff_scale(292), ff_scale(84), ff_scale(28),
                              dlg, (HMENU)(INT_PTR)ID_OW_OK, g_app.inst, NULL);
    SendMessageW(ok, WM_SETFONT, (WPARAM)f, TRUE);
    HWND cancel = CreateWindowExW(0, L"BUTTON", L"取消",
                                 WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                                 ff_scale(DW - 104), ff_scale(292), ff_scale(84), ff_scale(28),
                                 dlg, (HMENU)(INT_PTR)IDCANCEL, g_app.inst, NULL);
    SendMessageW(cancel, WM_SETFONT, (WPARAM)f, TRUE);

    /* "浏览..."按钮：列表里那行可能因为候选太多被滚到看不见的地方，
     * 所以底部再给一个常驻入口，保证"自己找程序"永远有点得到。 */
    HWND brow = CreateWindowExW(0, L"BUTTON", L"浏览(&B)...",
                                WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                                ff_scale(12), ff_scale(290), ff_scale(92), ff_scale(28),
                                dlg, (HMENU)(INT_PTR)ID_OW_BROWSE, g_app.inst, NULL);
    SendMessageW(brow, WM_SETFONT, (WPARAM)f, TRUE);

    /* 一个候选都没有时，默认选中"浏览其它应用程序…"，让用户能立刻挑程序 */
    ow_fill(list, ctx.n > 0 ? 0 : ow_row_count() - 1);

    /* 模态循环。用 PeekMessage 而不是 GetMessage：GetMessage 取到 WM_QUIT
     * 会直接返回 0，而这条 WM_QUIT 若被本循环吃掉、或者它是被别的窗口
     * 塞进来的，主窗口的消息循环就会跟着终止（现象是关掉对话框后整个程序
     * 消失）。这里改成轮询，只认对话框自己销毁那条 WM_FF_OWDLG_CLOSED。 */
    EnableWindow(owner, FALSE);
    ShowWindow(dlg, SW_SHOW);
    UpdateWindow(dlg);
    SetForegroundWindow(dlg);
    SetFocus(list);
    MSG msg;
    for (;;) {
        if (!IsWindow(dlg)) break;
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_FF_OWDLG_CLOSED) continue;   /* 只是关窗通知 */
            if (msg.message == WM_QUIT) { PostQuitMessage(0); break; }
            if (!IsDialogMessageW(dlg, &msg)) {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
        }
        if (!IsWindow(dlg)) break;
        /* 让出 CPU，别把消息循环跑满 */
        MsgWaitForMultipleObjects(0, NULL, FALSE, 40, QS_ALLINPUT);
    }
    if (IsWindow(owner)) { EnableWindow(owner, TRUE); SetForegroundWindow(owner); }

    /* 只有"确定"才算选中。之前只看 ctx.sel 在不在范围内，而 sel 一进来
     * 就被初始化成第 0 项，于是点"取消"、按 ESC、点右上角 × 全都照样
     * 把文件打开了 —— 必须是 ctx.accepted 为真才返回 true。 */
    bool okk = ctx.accepted && ctx.sel >= 0 && ctx.sel < ctx.n;
    if (okk) {
        /* 勾了"始终使用此应用"：把关联写进注册表（UserChoice 有hash 保护，
         * 只能走 HKCU\Software\Classes + Applications\<exe>\SupportedTypes
         * 这条路，Explorer 和"打开方式"菜单都会认） */
        if (ctx.always) ow_apply_always(&ctx);
        /* 返回 exe 路径而不是下标：用户可能是在对话框里现挑的程序，
         * 它只存在于本函数拷贝的那份数组里，调用方手里那块看不到。 */
        if (outExe) ff_str_copy(outExe, cchExe, ctx.ch[ctx.sel].exe);
    }
    free(ctx.ch);
    g_ow = NULL;
    ow_icon_clear();        /* 图标缓存随对话框一起释放（每次打开重新取） */
    return okk;
}

/* ------------------------------------------------------------------ 重命名框 */
/* ★为什么不用列表的内联编辑：本程序的列表是 LVS_OWNERDATA 虚拟列表，
 *   ListView_EditLabel 在它上面建立不了真正的编辑会话 —— 返回了句柄，
 *   但编辑框根本不存在、打字也进不去（F2 路径实测同样如此）。
 *   所以重命名统一走这个小对话框：稳定、能显示完整原名、不依赖菜单时序/焦点。 */
static WNDPROC  s_rnEditOldProc = NULL;

/* 编辑框子类化：回车/ESC 直接转成「确定 / 取消」。
 * ★为什么要子类化而不靠 IsDialogMessageW：焦点在 EDIT 上时，VK_RETURN 先发给
 *   编辑框，单行 EDIT 既不吃这个键、也不会转成 IDOK，结果"打了字按回车没反应"。
 *   自己接住最稳。 */
static LRESULT CALLBACK rn_edit_proc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_KEYDOWN) {
        HWND dlg = GetParent(h);
        if (w == VK_RETURN) {
            if (dlg) SendMessageW(dlg, WM_COMMAND, MAKEWPARAM(IDOK, BN_CLICKED), 0);
            return 0;
        }
        if (w == VK_ESCAPE) {
            if (dlg) SendMessageW(dlg, WM_COMMAND, MAKEWPARAM(IDCANCEL, BN_CLICKED), 0);
            return 0;
        }
    }
    return CallWindowProcW(s_rnEditOldProc, h, m, w, l);
}

static HWND     s_rnEdit = NULL;
static wchar_t *s_rnOut  = NULL;
static size_t   s_rnCch  = 0;
static bool     s_rnOK   = false;

static LRESULT CALLBACK rn_proc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_CREATE:
        CreateWindowExW(0, L"STATIC", L"新名称(&N)：",
                        WS_CHILD | WS_VISIBLE, 12, 12, 300, 18, h, NULL, NULL, NULL);
        CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
                                   WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
                                   12, 34, 300, 24, h, (HMENU)10, NULL, NULL);
        CreateWindowExW(0, L"BUTTON", L"确定",
                        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
                        152, 70, 76, 26, h, (HMENU)IDOK, NULL, NULL);
        CreateWindowExW(0, L"BUTTON", L"取消",
                        WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                        236, 70, 76, 26, h, (HMENU)IDCANCEL, NULL, NULL);
        return 0;

    case WM_COMMAND:
        /* 编辑框内容一变就同步进 s_rnOut：这样"确定"时不必再依赖那一刻的读取，
         * 用户敲一个字就更新一次，行为也和肉眼看到的一致。 */
        if (HIWORD(w) == EN_CHANGE && LOWORD(w) == 10) {
            HWND e2 = GetDlgItem(h, 10);
            if (e2 && s_rnOut)
                GetWindowTextW(e2, s_rnOut, (int)s_rnCch);
            DBG(L"rn EN_CHANGE -> [%ls]", s_rnOut ? s_rnOut : L"");
            return 0;
        }
        if (LOWORD(w) == IDOK) {
            HWND ed = GetDlgItem(h, 10);       /* ★一律现问，别信全局缓存 */
            int got = 0;
            if (ed && s_rnOut)
                got = GetWindowTextW(ed, s_rnOut, (int)s_rnCch);
            DBG(L"rn IDOK: edit=%p got=%d text=[%ls]", (void *)ed, got,
                s_rnOut ? s_rnOut : L"");
            s_rnOK = (got > 0);
            DestroyWindow(h);
        } else if (LOWORD(w) == IDCANCEL) {
            DestroyWindow(h);
        }
        return 0;

    case WM_ACTIVATE:
        /* 对话框一激活就把焦点钉在编辑框上：SetForegroundWindow/SetActiveWindow
         * 是异步生效的，光在创建时 SetFocus 一次常常不生效（焦点留在主窗口），
         * 用户就会觉得"这个框打不了字"。这里每次都补一次。 */
        if (LOWORD(w) != WA_INACTIVE) {
            HWND e2 = GetDlgItem(h, 10);
            if (e2) {
                SetFocus(e2);
                SendMessageW(e2, EM_SETSEL, 0, -1);   /* 全选，直接打字就替换 */
            }
        }
        return 0;

    case WM_CLOSE:
        DestroyWindow(h);
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

/* 返回 true = 用户确认（outed 里是新名字） */
bool ff_dlg_rename(HWND owner, const wchar_t *oldName, wchar_t *outed, size_t cch)
{
    static bool reg = false;
    if (!reg) {
        WNDCLASSEXW wc;
        ZeroMemory(&wc, sizeof(wc));
        wc.cbSize = sizeof(wc);
        wc.lpfnWndProc = rn_proc;
        wc.hInstance = GetModuleHandleW(NULL);
        wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
        wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
        wc.lpszClassName = L"FFRenameDlg";
        RegisterClassExW(&wc);
        reg = true;
    }
    if (!outed || cch == 0) return false;
    outed[0] = 0;
    s_rnOut = outed;
    s_rnCch = cch;
    s_rnOK = false;
    s_rnEdit = NULL;

    HWND h = CreateWindowExW(WS_EX_DLGMODALFRAME, L"FFRenameDlg", L"重命名",
                             WS_POPUP | WS_CAPTION | WS_SYSMENU,
                             0, 0, 340, 140, owner, NULL,
                             GetModuleHandleW(NULL), NULL);
    if (!h) return false;

    HWND ed = GetDlgItem(h, 10);       /* 直接问对话框要，稳妥 */
    s_rnEdit = ed;
    DBG(L"rn_dlg: h=%p ed=%p old=[%ls]", (void *)h, (void *)ed,
        oldName ? oldName : L"(null)");
    if (ed) {
        BOOL sok = SetWindowTextW(ed, oldName ? oldName : L"");
        SendMessageW(ed, EM_SETSEL, 0, -1);            /* 全选：直接打字就替换 */
        DBG(L"rn_dlg: SetWindowText=%d", sok ? 1 : 0);
        (void)sok;                                 /* 非 DBG 编译时 DBG 展开为空 */
    }
    RECT ro, rd;
    GetWindowRect(owner, &ro);
    GetWindowRect(h, &rd);
    SetWindowPos(h, HWND_TOP,
                 ro.left + ((ro.right - ro.left) - (rd.right - rd.left)) / 2,
                 ro.top + ((ro.bottom - ro.top) - (rd.bottom - rd.top)) / 2,
                 0, 0, SWP_NOSIZE | SWP_SHOWWINDOW);
    EnableWindow(owner, FALSE);
    /* ★这三步缺一不可：只 SetFocus 而不把对话框变成活动窗口，
     *   焦点会留在主窗口上，里面打字进不去（实测"这个框不能用"就是这个）。 */
    ShowWindow(h, SW_SHOW);
    SetForegroundWindow(h);
    SetActiveWindow(h);
    if (ed && !s_rnEditOldProc)
        s_rnEditOldProc = (WNDPROC)SetWindowLongPtrW(ed, GWLP_WNDPROC,
                                                     (LONG_PTR)rn_edit_proc);
    if (ed) {
        SetFocus(ed);
        SendMessageW(ed, EM_SETSEL, 0, -1);
    }

    MSG msg;
    while (IsWindow(h) && GetMessageW(&msg, NULL, 0, 0) > 0) {
        /* ★回车/ESC 在这里直接截获：焦点在编辑框上时，这两个键先发给 EDIT，
         * 单行 EDIT 既不吃它们也不会转成 IDOK —— 用户敲完名字按回车毫无反应。
         * 在消息循环里拦一道，不管焦点在哪个子控件上都管用。 */
        if (msg.message == WM_KEYDOWN &&
            (msg.wParam == VK_RETURN || msg.wParam == VK_ESCAPE)) {
            WPARAM id = (msg.wParam == VK_RETURN) ? IDOK : IDCANCEL;
            DBG(L"rn loop: 截获 vk=%d -> id=%d", (int)msg.wParam, (int)id);
            if (IsWindow(h))
                SendMessageW(h, WM_COMMAND, MAKEWPARAM(id, BN_CLICKED), 0);
            continue;
        }
        /* ★WM_COMMAND 必须自己派发：IsDialogMessageW 会把发给对话框的
         *   WM_COMMAND 当成"对话框消息"吞掉，窗口过程根本收不到 ——
         *   于是「确定」按钮点了没反应、PostMessage(IDOK) 也无效。 */
        if (msg.message == WM_COMMAND) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
            continue;
        }
        if (!IsDialogMessageW(h, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    EnableWindow(owner, TRUE);
    SetActiveWindow(owner);
    SetFocus(owner);
    s_rnEdit = NULL;
    return s_rnOK && outed[0] != 0;
}
