/*
 * FileCE —— 纯 C (C17) / Win32 API 文件管理器
 * ---------------------------------------------------------------
 * 目标平台 : Windows 7 SP1 x64 ~ Windows 11 (x64)
 * 依赖     : 仅系统自带 DLL，静态链接，单一 exe，无 .NET 运行时
 * 编译     : x86_64-w64-mingw32-gcc -std=c17 -municode -mwindows -static
 */
#ifndef FF_H
#define FF_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601          /* Windows 7 SP1 */
#endif
#ifndef _WIN32_IE
#define _WIN32_IE 0x0700
#endif

#include <windows.h>
#include <windowsx.h>
#include <commctrl.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <shlobj.h>
#include <uxtheme.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <stdio.h>

/* MinGW / msvcrt 的宽字符 printf 把 %s 当作 char*（历史行为），
 * 这里统一改用 Windows 原生 StringCch* 系列：语义明确，%s 即 wchar_t*，
 * 且自动保证终止符，拼接长度也不会越界。 */
#ifndef STRSAFE_NO_DEPRECATE
#define STRSAFE_NO_DEPRECATE
#endif
#include <strsafe.h>

#ifndef MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#endif
#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

/* ============================ 应用信息 ============================ */
#define FF_APP_TITLE      L"FileCE"
#define FF_APP_SUBTITLE   L"开院文件管理 · 内测版"
#define FF_APP_BUILDTAG   L"纯 C / Win32 重写版"
#define FF_APP_VERSION    L"1.0.0"
#define FF_APP_CLASS      L"FFMainWnd"
#define FF_TOOLBAR_CLASS  L"FFToolBar"
#define FF_COPYDLG_CLASS  L"FFCopyDlg"

#define FF_PATH_MAX       1024
#define FF_UNDO_STACK     32
#define FF_ICON_SMALL     16

/* ============================ 控件 ID ============================ */
#define IDC_LIST          1001
#define IDC_TREE          1002
#define IDC_ADDR          1003
#define IDC_TOOLBAR       1004
#define IDC_STATUS        1005
#define IDC_FILTER_CHK    1006
#define IDC_FILTER_FROM   1007
#define IDC_FILTER_TO     1008
#define IDC_FILTER_DIR    1009
#define IDC_FILTER_SIZE   1010
#define IDC_FILTER_SIZEU  1011
#define IDC_FILTER_CLEAR  1012
#define IDC_COPY_PROGRESS 1020
#define IDC_COPY_CURRENT  1021
#define IDC_COPY_STATS    1022
#define IDC_COPY_CANCEL   1023

/* ============================ 命令 ID ============================ */
#define CMD_BACK          20001
#define CMD_FORWARD       20002
#define CMD_UP            20003
#define CMD_REFRESH       20004
#define CMD_HOME          20005
#define CMD_NEWFOLDER     20006
#define CMD_COPY          20007
#define CMD_CUT           20008
#define CMD_PASTE         20009
#define CMD_DELETE        20010
#define CMD_DELETE_HARD   20011
#define CMD_RENAME        20012
#define CMD_PROPERTIES    20013
#define CMD_OPEN          20014
#define CMD_OPEN_WITH     20015
#define CMD_SELECT_ALL    20016
#define CMD_FIND          20017
#define CMD_ATTR          20018
#define CMD_STREAMS       20019
#define CMD_VIEW_LARGE    20020
#define CMD_VIEW_SMALL    20021
#define CMD_VIEW_LIST     20022
#define CMD_VIEW_DETAIL   20023
#define CMD_SORT_NAME     20024
#define CMD_SORT_TYPE     20025
#define CMD_SORT_SIZE     20026
#define CMD_SORT_MTIME    20027
#define CMD_TOGGLE_FILTER 20028
#define CMD_ABOUT         20029
#define CMD_HELP          20030
#define CMD_EXIT          20031
#define CMD_MAINMENU      20032
#define CMD_OPEN_TERM     20033
#define CMD_EDIT_ADDR     20034
#define CMD_TOGGLE_TREE   20035
#define CMD_FOCUS_ADDR    20036
#define CMD_INVERT_SEL    20037
#define CMD_COPY_PATH     20038
#define CMD_FIND_NEXT     20039
#define CMD_TAB_NEW       20040
#define CMD_TAB_CLOSE     20041
#define CMD_TAB_NEXT      20042
#define CMD_TAB_PREV      20043
#define CMD_COLUMNS       20044
#define CMD_VIEWMENU      20045
/* CMD_TOGGLE_TOOLBAR(20046) 已随工具栏整条取消而移除 */
#define CMD_TOGGLE_ADDRBAR 20047
/* "打开方式"子菜单：CMD_OPEN_WITH 是最后那项"选择其他应用…"，
 * CMD_OPEN_WITH_STORE 是"搜索 Microsoft Store"，
 * CMD_OPEN_WITH_APP + i 是动态列出的第 i 个已关联程序（和 Win10 一致）。 */
#define CMD_OPEN_WITH_STORE 20048
#define CMD_OPEN_WITH_APP   20049
#define OPEN_WITH_MAX       16

/* 右键菜单底部「更多选项…」：弹出 Windows 自己的那份菜单（shell 扩展全集）。
 * 见 shellmenu.c —— 本程序自己做不出来的东西（解压、Git、发送到、
 * 固定到快速访问、还原以前的版本……）只能向系统要。
 * ★ID 必须避开 CMD_OPEN_WITH_APP(20049) 起的 OPEN_WITH_MAX(16) 个连续号
 *   （20049~20064）——那一段被 do_command 开头的区间判断整段拦截，
 *   放进去会被当成"打开方式里第 N 个程序"静默吃掉（实测踩过）。 */
#define CMD_MORE_OPTIONS    20080

/* 目录树专属命令（树右键菜单；与列表菜单共用打开/复制等通用命令） */
#define CMD_TREE_PASTE      20070   /* 粘贴到该目录 */
#define CMD_TREE_NEWFOLDER  20071   /* 在该目录下新建文件夹 */

/* 菜单资源 */
#define IDM_MAIN          300
#define IDM_CONTEXT       301
#define IDM_COLUMN        302

/* 列表 → 主窗口 的自定义通知 */
#define WM_FF_ACTIVATE    (WM_APP + 11)   /* 双击 / 回车 */
#define WM_FF_CONTEXT     (WM_APP + 12)   /* 右键 */
#define WM_FF_SORTED      (WM_APP + 13)   /* 列头点击已排序 */
#define WM_FF_DROP        (WM_APP + 14)   /* 拖放目标 */
#define WM_FF_ADDR         (WM_APP + 15)   /* 地址栏事件 */
#define WM_FF_FILTER      (WM_APP + 16)   /* 筛选面板事件 */
#define WM_FF_FIND_PROG   (WM_APP + 17)   /* 查找进度 */
#define WM_FF_COPY_CANCEL (WM_APP + 18)
#define WM_FF_RENAME      (WM_APP + 19)   /* 列表内重命名完成 */
#define WM_FF_SELCHANGED  (WM_APP + 25)   /* 列表选中变化（已去重） */
#define WM_FF_BEGINDRAG   (WM_APP + 26)   /* 列表左键拖出（LVN_BEGINDRAG 转发） */
#define WM_FF_OW_CLEANUP  (WM_APP + 27)   /* 菜单关完，释放"打开方式"枚举出来的对象 */
#define WM_FF_OWDLG_CLOSED (WM_APP + 28)  /* "打开方式"对话框已关闭（结束它自己的模态循环） */
#define WM_FF_TREE_RCLICK (WM_APP + 29)   /* 树右键（NM_RCLICK 转发；lp=屏幕坐标） */
#define WM_FF_TREE_DRAG   (WM_APP + 30)   /* 树左键拖动（TVN_BEGINDRAG；lp=完整路径 wchar_t*，调用方管理生命周期） */
#define WM_FF_TREE_MENU_END (WM_APP + 31)  /* 树右键菜单已收：清除 s_treeMenuSel（排在 WM_COMMAND 之后） */
#define WM_FF_TREE_CONFIRM (WM_APP + 32)  /* 拖动落手确认：wp/lp 无参，用 s_pendingDrop 上下文 */
#define WM_FF_SHELL_MENU   (WM_APP + 33)  /* 延后弹 Windows 系统右键菜单（见 CMD_MORE_OPTIONS） */
#define WM_FF_RENAME_NOW   (WM_APP + 34)  /* 菜单关完之后再开重命名编辑框 */
#define WM_FF_RENAME_GO    (WM_APP + 35)
#define WM_FF_WATCH        (WM_APP + 36)  /* 当前目录有变化（外部程序改了文件/解压/删除） */  /* 第二拍：焦点已落到列表，正式开编辑框 */
#define FF_TIMER_RENAME    ((UINT_PTR)1) /* 菜单收尾后延迟开重命名编辑框 */
#define FF_TIMER_RENAME2   ((UINT_PTR)2)
#define FF_TIMER_WATCH     ((UINT_PTR)3)  /* 目录变化的去抖定时器 */ /* 第二段：焦点稳定后才真正开编辑框 */

/* ============================ 列表列 ============================ */
enum {
    COL_NAME = 0, COL_TYPE, COL_SIZE, COL_ATTR, COL_MTIME, COL_CTIME,
    COL_COUNT
};

/* ============================ 数据结构 ============================ */

/* 一条文件/文件夹记录 */
typedef struct {
    wchar_t   name[512];
    wchar_t   type[128];
    ULONGLONG size;
    DWORD     attrs;
    FILETIME  mtime, ctime, atime;
    int       isDir;
    int       isDrive;
    int       driveKind;      /* 见 DRIVE_* 常量 */
    int       iconIndex;
    int       groupId;        /* "此电脑"视图分组：PCGRP_*，普通目录恒为 0 */
} FfEntry;

/* 目录枚举结果 */
typedef struct {
    FfEntry  *items;
    int       count;
    int       cap;
} FfEntryList;

/* 筛选条件 */
typedef struct {
    bool      enabled;
    FILETIME  mtimeFrom, mtimeTo;
    bool      hasMtime;
    ULONGLONG sizeMin;        /* 单位: 字节, 0 表示不限 */
    ULONGLONG sizeMax;
    bool      hasSize;
    int       kind;           /* 0=全部 1=仅文件 2=仅文件夹 */
    int       driveKind;      /* 0=全部, 或 DRIVE_* */
} FfFilter;

/* 地址栏历史（栈按需在堆上分配，避免多标签时占用大量数据段） */
typedef struct {
    wchar_t (*stack)[FF_PATH_MAX];
    int       top;            /* 当前位于的位置 */
    int       count;
    int       cap;
} FfHistory;

/* 全局窗口集合 */
typedef struct {
    HINSTANCE     inst;
    HWND          main;
    HWND          addrBar;      /* 唯一的一条带：导航5 + 查找/筛选/查看 + 地址输入框 */
    HWND          tabs;
    HWND          addr;
    HWND          tree;
    HWND          list;
    HWND          status;
    HWND          filterPanel;
    HIMAGELIST    sysSmall;
    HIMAGELIST    sysLarge;
    HFONT         fontUI;
    HFONT         fontBold;
    int           dpi;
    int           treeWidth;
    bool          treeVisible;
    bool          addrBarVisible;
    bool          filterVisible;
    wchar_t       curDir[FF_PATH_MAX];
    FfHistory     hist;
    FfFilter      filter;
    int           sortCol;
    BOOL          sortAsc;
    HICON         appIconSm, appIconLg;
    wchar_t       clipboardDir[FF_PATH_MAX];
    bool          clipboardCut;
    bool          clipboardHas;
    int           viewMode;   /* LVS_* */
} FfApp;

extern FfApp g_app;

/* 剪贴板文件列表(全局共享) */
extern wchar_t *g_clipFiles;
extern int      g_clipCount;

/* ============================ util.c ============================ */
void   ff_str_copy(wchar_t *dst, size_t cch, const wchar_t *src);
void   ff_str_cat(wchar_t *dst, size_t cch, const wchar_t *src);
void   ff_path_join(wchar_t *out, size_t cch, const wchar_t *dir, const wchar_t *name);
void   ff_path_normalize(wchar_t *path);           /* 去掉末尾多余反斜杠 */
void   ff_path_parent(wchar_t *path);              /* 改为上级目录（UNC 按网络层级逐级上溯） */
const wchar_t *ff_path_name(const wchar_t *path);  /* 取末段 */
bool   ff_path_is_unc(const wchar_t *path);        /* 以 \\ 开头 */
int    ff_path_unc_segs(const wchar_t *path);      /* \\ 之后的段数，非 UNC 返回 -1 */
void   ff_path_ext(const wchar_t *name, wchar_t *out, size_t cch);
void   ff_format_size(ULONGLONG bytes, wchar_t *out, size_t cch);
void   ff_format_dt(const FILETIME *ft, wchar_t *out, size_t cch);
void   ff_format_attr(DWORD attrs, wchar_t *out, size_t cch);
void   ff_format_count(int n, wchar_t *out, size_t cch);
bool   ff_same_path(const wchar_t *a, const wchar_t *b);
int    fs_icon_unc(const wchar_t *unc);        /* \\SERVER 或 \\SERVER\SHARE 的图标 */
int    fs_icon_network_root(void);             /* "网络" 节点图标 */
void   ff_trim(wchar_t *s);
void   ff_msg_error(HWND owner, const wchar_t *fmt, ...);

#ifdef FFDBG
void   ff_dbg(const wchar_t *fmt, ...);
#define DBG(...) ff_dbg(__VA_ARGS__)
#else
#define DBG(...) ((void)0)
#endif
bool   ff_confirm(HWND owner, const wchar_t *fmt, ...);
HFONT  ff_ui_font(void);
int    ff_dpi_scale(int v);
int    ff_scale(int v);
void   ff_set_clip_files(const wchar_t **files, int count);
void   ff_clear_clip_files(void);
void   ff_hist_push(FfHistory *h, const wchar_t *dir);
void   ff_hist_free(FfHistory *h);
DWORD  ff_flags_from_check(int state);
int    ff_msgbox(HWND owner, const wchar_t *text, const wchar_t *caption, UINT type);
HBITMAP ff_make_icon_bmp(HICON icon, int size);

/* ============================ fs.c ============================ */
#define DRIVE_UNKNOWN_K   0
#define DRIVE_NOROOT_K    1
#define DRIVE_REMOVABLE_K 2
#define DRIVE_FIXED_K     3
#define DRIVE_REMOTE_K    4
#define DRIVE_CDROM_K     5
#define DRIVE_RAMDISK_K   6
#define DRIVE_SPECIAL_K   7   /* 库/用户目录等虚拟节点 */
#define DRIVE_DESKTOP_K   9   /* 桌面（虚拟节点，双击进真实桌面目录） */
#define DRIVE_DOCS_K     10   /* 文档（同上） */
#define DRIVE_VIDEO_K    12   /* 视频（此电脑页常用位置） */
#define DRIVE_PICS_K     13   /* 图片 */
#define DRIVE_MUSIC_K    14   /* 音乐 */
#define DRIVE_DL_K       15   /* 下载（Vista+ 已知文件夹，走 SHGetKnownFolderPath） */

/* "此电脑"视图里条目所属的分组。
 * 注意：comctl32 v6 不允许在 LVS_OWNERDATA 虚拟列表上用原生 LVGROUP
 * （LVM_ENABLEGROUPVIEW 返回 -1），所以分组头改为"特殊数据行"实现：
 * order 数组里的负数下标 = 组头行，custom_draw 整行自绘成组标题。 */
#define PCGRP_NONE   0        /* 顶部常用文件夹 */
#define PCGRP_DRIVE  1        /* "设备和驱动器 (n)" */

/* order 数组里的组头行标记（filelist 据此自绘组头） */
#define FF_ORDER_HDR_DRIVE  (-1)

bool   fs_list_dir(const wchar_t *dir, FfEntryList *out);
void   fs_entry_list_free(FfEntryList *l);
bool   fs_is_dir(const wchar_t *path);
bool   fs_path_exists(const wchar_t *path);
bool   fs_make_dir(const wchar_t *path);
bool   fs_rename(const wchar_t *oldPath, const wchar_t *newName);
bool   fs_delete_to_recycle(HWND owner, const wchar_t **paths, int count, wchar_t *err, size_t cch);
bool   fs_delete_permanent(HWND owner, const wchar_t **paths, int count, wchar_t *err, size_t cch);
bool   fs_set_attrs(const wchar_t *path, DWORD setMask, DWORD clearMask, bool recurse);
void   fs_describe_drive(const wchar_t *root, wchar_t *label, size_t cchLabel,
                         wchar_t *fsname, size_t cchFs);
int    fs_drive_kind(const wchar_t *root);
const  wchar_t *fs_drive_kind_name(int kind);
void   fs_enum_drives(FfEntryList *out);
void   fs_enum_this_pc(FfEntryList *out);    /* 此电脑页：6 常用位置 + 驱动器（带分组） */
bool   fs_special_path(int kind, wchar_t *out, size_t cch);  /* 桌面/文档等虚拟节点 → 真实路径 */
int    fs_icon_special_folder(int kind, const wchar_t *path);/* 桌面/文档真实图标 */
int    fs_icon_this_pc(void);                                /* 此电脑图标 */
int    fs_icon_quick_access(void);                            /* 快速访问图标 */
bool   fs_get_file_type(const wchar_t *name, DWORD attrs, wchar_t *out, size_t cch);
int    fs_get_icon_index(const wchar_t *path, DWORD attrs);
int    fs_icon_for_entry(const wchar_t *dir, const wchar_t *name, DWORD attrs);
bool   fs_copy_move(HWND owner, const wchar_t **src, int count, const wchar_t *dstDir,
                    bool move, wchar_t *err, size_t cch);
bool   fs_enum_streams(const wchar_t *path, wchar_t *out, size_t cch);
bool   fs_find_files(HWND owner, const wchar_t *root, const wchar_t *pattern,
                     bool recurse, FfEntryList *out, volatile LONG *cancel);
ULONGLONG fs_dir_size(const wchar_t *dir);
bool   fs_open_path(HWND owner, const wchar_t *path);
bool   fs_show_properties(HWND owner, const wchar_t *path);
bool   fs_show_properties_multi(HWND owner, const wchar_t **paths, int count);
bool   fs_recycle_empty(HWND owner);
void   fs_cancel_copy(void);
void   fs_reset_copy_cancel(void);
void   fs_init(void);

/* ============================ toolbar.c ============================ */
/* 只有一条带（地址栏条），8 个按钮全在这条上，地址输入框紧跟其后：
 *   后退 / 前进 / 上级 / 刷新 / 此电脑 | 查找 / 筛选 / 查看 | [地址输入框]
 * 索引必须与 toolbar.c 的 s_cmd 顺序一致。
 * （原先的第二条"工具栏"已整条取消：新建文件夹/复制/剪切/粘贴/删除改用
 *   右键菜单、主菜单「文件」和快捷键，不再占一条带。） */
#define FF_TB_BACK      0
#define FF_TB_FORWARD   1
#define FF_TB_UP        2
#define FF_TB_REFRESH   3
#define FF_TB_HOME      4
#define FF_TB_FIND      5
#define FF_TB_FILTER    6
#define FF_TB_VIEW      7
#define FF_TB_COUNT     8

bool ff_toolbar_register(HINSTANCE inst);
HWND ff_toolbar_create(HWND parent, HINSTANCE inst, int first, int count);
void ff_toolbar_set_enabled(HWND tb, int index, bool on);
void ff_toolbar_set_checked(HWND tb, int index, bool on);
void ff_toolbar_clear_hot(HWND tb);
void ff_toolbar_set_height(HWND tb, int h);
int  ff_toolbar_width(HWND tb);
bool ff_toolbar_button_rect(HWND tb, int index, RECT *out);

/* ============================ tree.c ============================ */
/* 树节点 lParam 指向的结构（tree.c 私有实现按这个布局分配）。
 * kind: 1=驱动器 2=文件夹 5=此电脑根（path 为空） */
typedef struct {
    int     kind;
    wchar_t path[FF_PATH_MAX];
} FfTreeData;

bool ff_tree_register(HINSTANCE inst);
HWND ff_tree_create(HWND parent, HINSTANCE inst);
void ff_tree_populate(HWND tree);
void ff_tree_select_path(HWND tree, const wchar_t *path);
void ff_tree_refresh_current(HWND tree);
LRESULT ff_tree_notify(HWND tree, NMHDR *nh);
void   ff_tree_reveal(HWND tree, const wchar_t *path);  /* 展开到 path(不改选中) */
void   ff_register_droptarget(void);            /* 树/列表挂 OLE 拖放目标（复制/移动光标+确认菜单） */
/* 命中测试：屏幕坐标处是树节点时填出节点路径（此电脑根返回 kind=5）。
 * 返回 true=命中节点。 */
bool ff_tree_hit_path(HWND tree, POINT ptScreen, FfTreeData *out);

/* ============================ filelist.c ============================ */
/* zipw.c —— 往压缩包里加/替换文件（同名直接替换、不弹框）
 * .zip 自己写；.rar/.7z 借系统已装的 WinRAR / 7-Zip */
bool ff_zip_add_or_replace(const wchar_t *zipPath, const wchar_t **files, int count,
                           wchar_t *err, size_t cchErr);
bool ff_archive_insert(const wchar_t *archivePath, const wchar_t **files, int count,
                       wchar_t *err, size_t cchErr);

bool ff_list_register(HINSTANCE inst);
HWND ff_list_create(HWND parent, HINSTANCE inst);
void ff_list_init_columns(HWND list);
void ff_list_set_data(HWND list, FfEntry *raw, int rawCount,
                      int *order, int orderCount, int sortCol, BOOL sortAsc);
const FfEntry *ff_list_row_entry(HWND list, int row);
int  ff_list_row_of_entry(HWND list, const FfEntry *e);
int  ff_list_count(HWND list);
int  ff_list_raw_count(HWND list);
int  ff_list_selected(HWND list, int *rows, int max);
void ff_list_focus_item(HWND list, int row);
void ff_list_apply_view(HWND list, int viewMode);
int  ff_list_view_mode(HWND list);
void ff_list_set_group_counts(int drvCount);
LRESULT ff_list_notify(HWND list, NMHDR *nh);
bool ff_list_take_sel_flag(void);

/* ============================ tabs.c ============================ */
#define WM_FF_TAB_SEL    (WM_APP + 21)
#define WM_FF_TAB_CLOSE  (WM_APP + 22)
#define WM_FF_TAB_NEW    (WM_APP + 23)
#define WM_FF_TAB_RCLICK (WM_APP + 24)

bool ff_tabs_register(HINSTANCE inst);
HWND ff_tabs_create(HWND parent, HINSTANCE inst);
void ff_tabs_update(HWND tabs, int count, int active);
void ff_tabs_set_title(HWND tabs, int index, const wchar_t *title);
void ff_tabs_set_icon(HWND tabs, int index, HICON icon);
void   ff_tabs_set_icon_index(HWND tabs, int index, int iconIndex);
void   ff_tabs_set_hicon(HWND tabs, int index, HICON icon);
void ff_tabs_set_loading(HWND tabs, int index, bool loading);
int  ff_tabs_height(HWND tabs);

/* ============================ dialogs.c ============================ */
void ff_dlg_find(HWND owner);
void ff_dlg_attr(HWND owner);
void ff_dlg_streams(HWND owner);
void ff_dlg_about(HWND owner);
void ff_dlg_help(HWND owner);
bool ff_dlg_find_folder(HWND owner, const wchar_t *init, wchar_t *out, size_t cch);
bool   ff_dlg_rename(HWND owner, const wchar_t *oldName, wchar_t *outed, size_t cch);
bool ff_copy_dlg_register(HINSTANCE inst);
LRESULT CALLBACK ff_copy_dlg_proc(HWND h, UINT m, WPARAM w, LPARAM l);

/* ---------------------------------------------------------
 * Win10 风格"你要如何打开这个文件？"对话框
 * ---------------------------------------------------------
 * 为什么自己画：Win10 1809 起SHOpenWithDialog 被系统降级成"若要更改默认
 * 应用，请转到设置>默认应用"的橙色横幅（与 flag 无关，flags=0 也一样），
 * 根本列不出程序 —— Explorer 用的是 shell 内部未公开的另一条路径。
 * 这里自己实现同等功能：列出 SHAssocEnumHandlers 给出的全部候选程序
 * （默认程序排最前）+ 单选 + "始终使用此应用" 勾选 + 确定后真正打开，
 * 勾选时还会把关联写进注册表。 */
typedef struct FfOpenWithChoice {
    wchar_t exe  [FF_PATH_MAX];   /* 实际要启动的程序 */
    wchar_t label[128];           /* 显示名（本地化） */
    wchar_t progid[64];           /* 关联用的 progID */
} FfOpenWithChoice;

/* 枚举该扩展名的全部候选程序（系统顺序：默认程序排最前）。返回条数；
 * 条数 > 0 时 *out 指向 malloc 出来的数组，调用方用 free() 释放。
 * 每项的 exe/label/progid 都填好。
 * 除了 SHAssocEnumHandlers，还会补上它看不到的三处：本程序私有的使用
 * 历史、Explorer 的FileExts\<ext>\OpenWithList、OpenWithProgids ——
 * 便携程序（只解压没安装）常常一个都没登记，却仍然该出现在列表里。 */
int  ff_open_with_choices(const wchar_t *ext, FfOpenWithChoice **out);

/* 记下"这个扩展名刚用过 prog"，写进本程序私有的打开方式列表
 * （HKCU\Software\FileCE\OpenWith\<ext>，存的是完整路径）。
 * 下次 ff_open_with_choices 就能列出它 —— Explorer 那个OpenWithList
 * 只存文件名，光有名字还原不出路径，列出来也点不开。 */
void ff_open_with_remember(const wchar_t *ext, const wchar_t *exe);

/* 弹出"你要如何打开这个文件？"对话框。file=要打开的文件（决定标题里的
 * 扩展名）；choices/count 来自 ff_open_with_choices（count 可以是 0，此时
 * 列表里只有"浏览其它应用程序…"一行）；*picked 返回选中项下标。
 * outExe/cchExe 返回真正要启动的 exe 路径 —— 用户可能是在对话框里现挑的
 * 程序，它不在 choices 数组里，所以只能拿路径回去。
 * 返回 true=用户点了确定；false=取消（此时绝不能打开文件）。 */
bool ff_dlg_open_with(HWND owner, const wchar_t *file,
                FfOpenWithChoice *choices, int count, int *picked,
                wchar_t *outExe, size_t cchExe);

/* ============================ shellmenu.c ============================ */
/* 系统右键菜单里"本程序自己插进去的项"的命令 ID。
 * 必须与 shell 自己分配的 0x7000~0x7FFF 错开，也不能落在 CMD_OPEN_WITH_APP
 * 那段连续号里 —— 这里用 0x5000 起。 */
#define SM_CMD_BASE        0x5000
#define SM_CMD_OPEN        (SM_CMD_BASE + 0)   /* 打开（shell 默认菜单不给，宿主得自己加） */
#define SM_CMD_PRINT       (SM_CMD_BASE + 1)
#define SM_CMD_EDIT        (SM_CMD_BASE + 2)
#define SM_CMD_REFRESH     (SM_CMD_BASE + 3)   /* 空白处：刷新 */
#define SM_CMD_CUSTOMIZE   (SM_CMD_BASE + 4)   /* 空白处：自定义文件夹 */
#define SM_CMD_UNDORENAME  (SM_CMD_BASE + 5)   /* 空白处：撤消重命名 */
#define SM_CMD_DELETE_HARD (SM_CMD_BASE + 6)
#define SM_CMD_COPY_PATH   (SM_CMD_BASE + 7)
#define SM_CMD_ADS         (SM_CMD_BASE + 8)
#define SM_CMD_ATTR        (SM_CMD_BASE + 9)
#define SM_CMD_PASTE       (SM_CMD_BASE + 10)  /* 空白处：粘贴 */
#define SM_CMD_PASTELINK   (SM_CMD_BASE + 11)  /* 空白处：粘贴快捷方式 */

/* fs.c：在 dir 里给剪贴板中的每个文件建 .lnk（"粘贴快捷方式"） */
bool fs_paste_shortcut(HWND owner, const wchar_t *dir, wchar_t *err, size_t cchErr);

/* fs.c：监听某个目录的变化（解压/删除/复制等在别的进程里完成时也能察觉）。
 * 有变化时给 notify 投 WM_FF_WATCH；dir 与当前监听的一致时不会重建线程。 */
bool fs_watch_set(HWND notify, const wchar_t *dir);
void fs_watch_stop(void);

/* mainwin.c：造「打开方式」子菜单（含未注册的绿色版程序），用完调 ff_ow_release() */
HMENU ff_ow_make_menu(const wchar_t *file);
void  ff_ow_release(void);
/* mainwin.c：给系统菜单追加本程序的 查看/排序/全选/反选（空白处菜单用） */
void  ff_menu_append_extras(HMENU m, bool background);

/* 弹出 Windows 系统右键菜单（资源管理器那份，含全部 shell 扩展）。
 *   paths/count : 选中项；count==0 时按"目录空白处"出菜单（dir 必须是真实目录）
 * 返回 true = 用户确实执行了某个 shell 命令（调用方据此刷新列表）。 */
bool ff_shell_menu_show(HWND owner, const wchar_t *dir,
                        const wchar_t **paths, int count, POINT ptScreen);

/* 菜单显示期间，把 WM_INITMENUPOPUP / WM_DRAWITEM / WM_MEASUREITEM /
 * WM_MENUCHAR 转给 shell 扩展（IContextMenu2/3）。返回 true 表示已处理，
 * 主窗口的窗口过程应当直接 return *out。没有系统菜单在显示时恒返回 false。 */
bool ff_shell_menu_msg(UINT msg, WPARAM wp, LPARAM lp, LRESULT *out);

/* 自检模式（--dump-shell-menu=<path>）：把菜单项枚举结果写到
 * %TEMP%\ffce_shellmenu.txt 后退出；path 是目录则出空白处菜单。 */
void ff_shell_menu_dump(const wchar_t *path);

/* mainwin.c 实现：执行系统菜单里"本程序自己的项"（SM_CMD_*）和
 * 需要宿主配合的标准动词（DFM_CMD_RENAME 等）。返回 false = 不认识，
 * 调用方应当把命令交回 shell。 */
bool ff_shell_menu_invoke(UINT id);
bool ff_shell_menu_can_undo_rename(void);
bool ff_shell_menu_clipboard_has_files(void);

/* ============================ mainwin.c ============================ */
void ff_navigate(const wchar_t *dir, bool addHistory);
void ff_refresh(bool keepSelection);
void ff_go_up(void);
void ff_go_back(void);
void ff_go_forward(void);
HWND ff_get_list(void);
void ff_set_status(const wchar_t *text);
void ff_update_ui_state(void);
void ff_apply_filter(void);
int  ff_selected_paths(wchar_t ***outPaths);
void ff_free_paths(wchar_t **paths, int count);
bool ff_main_register(HINSTANCE inst);
void ff_main_init(void);
void ff_main_setup(void);
void ff_show_search_results(FfEntryList *list, const wchar_t *pattern);
LRESULT CALLBACK ff_main_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp);

#endif /* FF_H */
