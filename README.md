# FileCE —— 纯 C / Win32 文件管理器（内测版）

[![最新版本](https://img.shields.io/github/v/release/yjt1688/FileCE?label=release)](https://github.com/yjt1688/FileCE/releases)
[![下载总数](https://img.shields.io/github/downloads/yjt1688/FileCE/total?label=downloads)](https://github.com/yjt1688/FileCE/releases)
[![Star 数](https://img.shields.io/github/stars/yjt1688/FileCE?label=stars)](https://github.com/yjt1688/FileCE/stargazers)
[![Fork 数](https://img.shields.io/github/forks/yjt1688/FileCE?label=forks)](https://github.com/yjt1688/FileCE/network/members)
[![开源协议](https://img.shields.io/github/license/yjt1688/FileCE?label=license)](LICENSE)

基于纯 C（C17）+ Win32 API 自研的轻量 Windows 文件管理器，静态链接、单个 exe、零运行时依赖。

## 构建

需要 MinGW-w64（`x86_64-w64-mingw32-gcc`，自带 `windres`）。在项目根目录执行：

    make

产物为 `build/FileCE.exe`（单文件、绿色便携，适用 Windows 7 SP1 x64 ~ Windows 11）。

## 许可

[MIT](LICENSE)
