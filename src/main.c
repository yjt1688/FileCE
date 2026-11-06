/* main.c —— 程序入口：DPI 感知、通用控件初始化、窗口装配、消息循环
 *
 * 启动路径刻意保持极短：不做磁盘扫描、不加载脚本引擎、不读配置文件，
 * 从进程创建到主窗口呈现通常在一帧之内完成。
 */
#include "ff.h"

static HACCEL s_accel = NULL;

static HACCEL build_accelerators(void)
{
    ACCEL a[] = {
        { FVIRTKEY,                     VK_F5,     CMD_REFRESH     },
        { FVIRTKEY,                     VK_F2,     CMD_RENAME      },
        { FVIRTKEY,                     VK_F1,     CMD_HELP        },
        { FVIRTKEY,                     VK_F6,     CMD_MAINMENU    },
        { FVIRTKEY,                     VK_DELETE, CMD_DELETE      },
        { FVIRTKEY | FSHIFT,            VK_DELETE, CMD_DELETE_HARD },
        { FVIRTKEY,                     VK_BACK,   CMD_UP          },
        { FVIRTKEY,                     VK_BROWSER_BACK,  CMD_BACK    },
        { FVIRTKEY,                     VK_BROWSER_FORWARD, CMD_FORWARD },
        { FVIRTKEY | FALT,              VK_LEFT,   CMD_BACK        },
        { FVIRTKEY | FALT,              VK_RIGHT,  CMD_FORWARD     },
        { FVIRTKEY | FALT,              VK_HOME,   CMD_HOME        },
        { FVIRTKEY | FALT,              VK_RETURN, CMD_PROPERTIES  },
        { FVIRTKEY | FALT,              VK_UP,     CMD_UP          },
        { FVIRTKEY | FCONTROL,          'A',       CMD_SELECT_ALL  },
        { FVIRTKEY | FCONTROL,          'I',       CMD_INVERT_SEL  },
        { FVIRTKEY | FCONTROL,          'C',       CMD_COPY        },
        { FVIRTKEY | FCONTROL,          'X',       CMD_CUT         },
        { FVIRTKEY | FCONTROL,          'V',       CMD_PASTE       },
        { FVIRTKEY | FCONTROL,          'F',       CMD_FIND        },
        { FVIRTKEY | FCONTROL,          'L',       CMD_FOCUS_ADDR  },
        { FVIRTKEY | FCONTROL,          'T',       CMD_TAB_NEW     },
        { FVIRTKEY | FCONTROL,          'W',       CMD_TAB_CLOSE   },
        { FVIRTKEY | FCONTROL,          VK_TAB,    CMD_TAB_NEXT    },
        { FVIRTKEY | FCONTROL | FSHIFT, VK_TAB,    CMD_TAB_PREV    },
        { FVIRTKEY | FCONTROL | FSHIFT, 'N',       CMD_NEWFOLDER   },
        { FVIRTKEY | FCONTROL | FSHIFT, 'T',       CMD_TOGGLE_TREE },
        { FVIRTKEY | FALT,              VK_F4,     CMD_EXIT        },
    };
    return CreateAcceleratorTableW(a, (int)(sizeof(a) / sizeof(a[0])));
}

static HWND create_child_windows(HWND hwnd, HINSTANCE inst)
{
    /* 只有一条带：导航 5 个 + 查找/筛选/查看 3 个，后接地址输入框。
     * 原来的第二条"工具栏"（新建文件夹/复制/剪切/粘贴/删除）已整条取消，
     * 这些操作走右键菜单、主菜单「文件」和快捷键。 */
    g_app.addrBar = ff_toolbar_create(hwnd, inst, 0, FF_TB_COUNT);
    g_app.tabs = ff_tabs_create(hwnd, inst);

    g_app.addr = CreateWindowExW(0, L"COMBOBOX", L"",
                                 WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_CLIPSIBLINGS |
                                 CBS_DROPDOWN | CBS_AUTOHSCROLL | WS_VSCROLL,
                                 0, 0, 100, ff_scale(260), hwnd,
                                 (HMENU)(INT_PTR)IDC_ADDR, inst, NULL);
    if (g_app.addr) {
        SendMessageW(g_app.addr, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);
        SendMessageW(g_app.addr, CB_LIMITTEXT, FF_PATH_MAX - 1, 0);
    }

    g_app.tree = ff_tree_create(hwnd, inst);
    g_app.list = ff_list_create(hwnd, inst);

    /* 树/列表挂 OLE 拖放目标：树内拖动悬停显示 复制/移动 光标，松手弹确认菜单 */
    ff_register_droptarget();

    g_app.status = CreateWindowExW(0, STATUSCLASSNAMEW, L"",
                                   WS_CHILD | WS_VISIBLE | SBARS_SIZEGRIP,
                                   0, 0, 100, 24, hwnd,
                                   (HMENU)(INT_PTR)IDC_STATUS, inst, NULL);
    if (g_app.status)
        SendMessageW(g_app.status, WM_SETFONT, (WPARAM)ff_ui_font(), TRUE);

    /* z 序修正：地址栏条窗口横跨整条区域，会盖住嵌在其中的地址栏输入框。
     * 必须把输入框提到最前，否则点击地址栏时鼠标消息全部被条带吃掉：
     * 地址栏拿不到焦点 -> 无法输入路径；悬停时还被条带的高亮盖住而"变白"。 */
    if (g_app.addr)
        SetWindowPos(g_app.addr, HWND_TOP, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    return hwnd;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    (void)prev;
    SetProcessDPIAware();
    /* OLE 初始化：拖放（DoDragDrop）要的不只是 COM 单元初始化，
     * 只调 CoInitializeEx 时拖出会返回 CO_E_NOTINITIALIZED（实测），
     * 必须走 OleInitialize（内含 STA COM + OLE 剪贴板/拖放服务）。 */
    OleInitialize(NULL);

    INITCOMMONCONTROLSEX icc;
    icc.dwSize = sizeof(icc);
    icc.dwICC = ICC_WIN95_CLASSES | ICC_LISTVIEW_CLASSES | ICC_TREEVIEW_CLASSES |
                ICC_PROGRESS_CLASS | ICC_DATE_CLASSES | ICC_BAR_CLASSES |
                ICC_STANDARD_CLASSES | ICC_TAB_CLASSES | ICC_USEREX_CLASSES;
    InitCommonControlsEx(&icc);

    fs_init();

    ZeroMemory(&g_app, sizeof(g_app));
    g_app.inst = inst;
    g_app.treeVisible = true;
    g_app.treeWidth = -1;          /* 稍后按 DPI 计算 */
    g_app.addrBarVisible = true;
    g_app.filterVisible = false;
    g_app.viewMode = LVS_REPORT;

    {
        HDC dc = GetDC(NULL);
        if (dc) {
            g_app.dpi = GetDeviceCaps(dc, LOGPIXELSX);
            ReleaseDC(NULL, dc);
        }
        if (g_app.dpi < 96) g_app.dpi = 96;
    }
    if (g_app.treeWidth < 0) g_app.treeWidth = ff_scale(210);

    /* 系统图像列表：小图标用于列表，大图标用于大图标视图 */
    {
        SHFILEINFOW sfi;
        ZeroMemory(&sfi, sizeof(sfi));
        g_app.sysSmall = (HIMAGELIST)SHGetFileInfoW(L"C:\\", FILE_ATTRIBUTE_DIRECTORY,
                            &sfi, sizeof(sfi),
                            SHGFI_SYSICONINDEX | SHGFI_SMALLICON);
        g_app.sysLarge = (HIMAGELIST)SHGetFileInfoW(L"C:\\", FILE_ATTRIBUTE_DIRECTORY,
                            &sfi, sizeof(sfi),
                            SHGFI_SYSICONINDEX | SHGFI_LARGEICON);
    }

    ff_ui_font();
    ff_main_init();

    if (!ff_toolbar_register(inst) || !ff_tabs_register(inst) || !ff_main_register(inst)) {
        MessageBoxW(NULL, L"窗口类注册失败，程序无法启动。", FF_APP_TITLE, MB_ICONERROR);
        return 1;
    }

    /* 自检模式：--list-open-with=<ext> 把候选程序写到 %TEMP%\ffce_owlist.txt
     * 然后退出。用来验证"绿色版程序（压根没注册）能不能出现在打开方式列表
     * 里" —— 这类问题在 GUI 上看不出来，只能靠枚举结果断言。写文件而不是
     * printf：-mwindows 下 stdout 未必有控制台可用。 */
    if (cmdline && wcsstr(cmdline, L"--list-open-with")) {
        const wchar_t *eq = wcschr(cmdline, L'=');
        if (eq) {
            wchar_t ext[32];
            StringCchCopyW(ext, 32, eq + 1);
            for (wchar_t *q = ext; *q; ++q)
                if (*q == L' ' || *q == L'"') { *q = 0; break; }
            FfOpenWithChoice *ch = NULL;
            int cnt = ff_open_with_choices(ext, &ch);

            wchar_t path[MAX_PATH * 2], tmp[MAX_PATH * 2];
            GetTempPathW(MAX_PATH * 2, tmp);
            StringCchPrintfW(path, MAX_PATH * 2, L"%sffce_owlist.txt", tmp);
            HANDLE hf = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                                     CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
            if (hf != INVALID_HANDLE_VALUE) {
                /* 直接写 UTF-16：_snprintf 的 %S 在 MinGW 下处理不了
                 * 非 ASCII，中文程序名会被整段吞掉（实测列表里只剩
                 * 几个纯英文项，看着像"枚举漏了"，其实是编码问题）。 */
                wchar_t buf[4400];
                DWORD wr;
                StringCchPrintfW(buf, 4400, L"choices=%d\n", cnt);
                WriteFile(hf, buf, (DWORD)((wcslen(buf) + 1) * sizeof(wchar_t)),
                          &wr, NULL);
                for (int i = 0; i < cnt; ++i) {
                    StringCchPrintfW(buf, 4400, L"[%d] %s | exe=%s | progid=%s\n",
                                     i, ch[i].label, ch[i].exe,
                                     ch[i].progid[0] ? ch[i].progid : L"(none)");
                    WriteFile(hf, buf, (DWORD)((wcslen(buf) + 1) * sizeof(wchar_t)),
                              &wr, NULL);
                }
                CloseHandle(hf);
            }
            free(ch);
            OleUninitialize();
            return 0;
        }
    }

    /* 自检模式 2：--dump-shell-menu=<路径> 把 Windows 系统右键菜单的项
     * （序号 / 命令 ID / 相对序号 / 文本）写到 %TEMP%\ffce_shellmenu.txt 后退出。
     * 用来断言两件 GUI 上看不出来的事：① 系统菜单里到底有没有"发送到"
     * 这类只有 shell 扩展才有的项；② 命令 ID 基准有没有错位一格。 */
    if (cmdline && wcsstr(cmdline, L"--dump-shell-menu")) {
        const wchar_t *eq2 = wcschr(cmdline, L'=');
        if (eq2 && eq2[1]) {
            wchar_t path[MAX_PATH * 2];
            StringCchCopyW(path, MAX_PATH * 2, eq2 + 1);
            size_t l = wcslen(path);
            while (l && (path[l - 1] == L' ' || path[l - 1] == L'"')) path[--l] = 0;
            const wchar_t *p = path;
            while (*p == L'"') ++p;
            ff_shell_menu_dump(p);
            OleUninitialize();
            return 0;
        }
    }

    /* 与 update_title() 保持同一格式，避免窗口创建到首次导航之间标题样式跳变 */
    wchar_t cap[256];
    StringCchPrintfW(cap, 256, L"此电脑 - %s [%s]", FF_APP_TITLE, FF_APP_SUBTITLE);

    HWND hwnd = CreateWindowExW(0, FF_APP_CLASS, cap,
                                WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
                                CW_USEDEFAULT, CW_USEDEFAULT,
                                ff_scale(1060), ff_scale(680),
                                NULL, NULL, inst, NULL);
    if (!hwnd) {
        MessageBoxW(NULL, L"主窗口创建失败。", FF_APP_TITLE, MB_ICONERROR);
        return 1;
    }
    g_app.main = hwnd;

    create_child_windows(hwnd, inst);
    ff_main_setup();

    ff_tree_populate(g_app.tree);
    ShowWindow(hwnd, show ? show : SW_SHOWNORMAL);
    UpdateWindow(hwnd);

    /* 首个标签进入"此电脑"视图 */
    ff_navigate(L"", true);
    SetFocus(g_app.list);

    s_accel = build_accelerators();

    /* 支持在命令行/拖放到 exe 上时直接打开指定目录 */
    if (cmdline && *cmdline) {
        wchar_t path[FF_PATH_MAX];
        ff_str_copy(path, FF_PATH_MAX, cmdline);
        ff_trim(path);
        if (path[0] == L'"') {
            memmove(path, path + 1, wcslen(path) * sizeof(wchar_t));
            wchar_t *q = wcschr(path, L'"');
            if (q) *q = 0;
        }
        if (fs_is_dir(path)) ff_navigate(path, true);
    }

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        bool inEdit = false;
        HWND focus = GetFocus();
        if (focus) {
            wchar_t cls[64] = L"";
            GetClassNameW(focus, cls, 64);
            if (_wcsicmp(cls, L"Edit") == 0) inEdit = true;
        }
        if (!inEdit && s_accel && TranslateAcceleratorW(hwnd, s_accel, &msg))
            continue;

        /* IsDialogMessageW 会把回车 / ESC 翻译成 WM_COMMAND(IDOK / IDCANCEL)
         * 发给主窗口，编辑框和列表根本收不到 WM_KEYDOWN —— 后果是：地址栏敲完
         * 路径按回车不跳转、列表里回车打不开选中项、ESC 不还原地址栏。
         * 这里只对这两个键跳过它，让按键原样进入窗口过程；其余键（Tab 焦点切换
         * 等）仍走原来的对话框式处理。 */
        bool passThrough = false;
        if (msg.message == WM_KEYDOWN || msg.message == WM_SYSKEYDOWN) {
            if (msg.wParam == VK_RETURN || msg.wParam == VK_ESCAPE)
                passThrough = true;
        }

        if (!passThrough && IsDialogMessageW(hwnd, &msg))
            continue;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (s_accel) DestroyAcceleratorTable(s_accel);
    OleUninitialize();
    return (int)msg.wParam;
}
