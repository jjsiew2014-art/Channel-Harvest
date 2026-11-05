# Channel Harvest (渠道收割机)

<p align="center">
  <img src="Channel Harvest__Logo.png" alt="Channel Harvest Logo" width="120"/>
</p>

<p align="center">
  <strong>YouTube、YouTube Music、TikTok、哔哩哔哩 (Bilibili)、Facebook、Instagram 与 X (Twitter) 媒体与创作者一站式归档下载器</strong><br/>
  收割你喜爱的频道、创作者主页、空间、专页与账号。完整保存每一份媒体资产 —— 全量视频、高清图片、无损音频、多语字幕、方形封面、逐字同步歌词与平台专属元数据档案。<br/>
  基于 Python、PySide6 (Qt for Python)、yt-dlp、gallery-dl、Deno 与 FFmpeg 构建。
</p>

<p align="center">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

<p align="center">
  <img alt="版本" src="https://img.shields.io/badge/version-1.4.1-6C63FF?style=flat-square"/>
  <img alt="操作系统" src="https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue?style=flat-square"/>
  <img alt="开源许可" src="https://img.shields.io/badge/license-MIT-22C55E?style=flat-square"/>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-F59E0B?style=flat-square"/>
</p>

---

## 🌟 核心功能

### 🌐 全方位多平台支持 (YouTube, YouTube Music, TikTok, Bilibili, Facebook, Instagram & X)
通过顶部平台切换器自由切换平台，输入框自适应呈现不同平台的链接占位引导：

* **🎵 YouTube Music 专属音乐平台支持**：
  * 原生顶栏平台切换与自适应智能识别 (`music.youtube.com`)。
  * 专辑、单曲与播放列表自动默认进入 **仅音频 (Audio Only)** 极速下载模式。
  * **1:1 原生方形母带封面抽取与去重**：从 Google CDN 提取最高 1400×1400+ 原图无黑边封面，智能按专辑名归纳命名（如 `<专辑名>.jpg`），同一张专辑内的所有曲目仅下载一次封面并全局复用，杜绝冗余重复文件。
  * **LRC 逐字同步动态歌词**：高精度在线检索并下载标准化 `.lrc` 同步歌词，支持一键无损写入音频标签（MP3、M4A、FLAC、Opus）。
* **📺 YouTube 视频、Shorts 短视频、播放列表与频道完整归档**：
  * 全面支持单视频、Shorts、公共/私有播放列表及整个创作者频道 (`/channel/`, `/@handle`, `/c/`)。
  * 内置 **EJS & Deno 客户端 JS 解密求解器**（内置于 `runtime/`），无缝绕过客户端 `n-sig` 播放挑战算法，彻底消灭限速与 HTTP 403 Forbidden 报错。
  * 多语言字幕深度提取与自动转码为标准 SubRip (`.srt`)，章节标记自动导出为 `.chapters.txt`，以及完整结构化元数据保存。
* **📸 Facebook 视频、Watch、Reels 短视频与主页深度媒体归档**：
  * 完美支持 Facebook Watch (`/watch/?v=...`)、主页/创作者视频 (`/{user}/videos/...`) 与 Facebook Reels (`/reel/`, `fb.watch`)。
  * **全新 Comet GraphQL 深度游标扫描引擎**：无需 Meta Graph API 授权或 Page 管理员权限，完美支持公开主页未登录与 Cookie 登录模式，深度遍历相册图集（Photos Tab）、完整长视频库（Videos Tab）与短视频（Reels Tab），单次扫描可枚举多达数百上千项媒体。
  * **原生标题智能优化**：自动提取真实原帖 Caption，彻底清除话题标签（`#` 与 `＃`），实施语言自适应截断（中文字符 50 字、英文字符 30 词），若仅有标签则优雅降级为规范的系统标识符。
* **📷 Instagram Reels、视频帖子、轮播图集与创作者主页归档**：
  * 全面覆盖单条 Reels (`/reel/`, `/reels/`)、标准图文视频帖子 (`/p/`)、IGTV (`/tv/`) 与创作者个人主页 (`/<username>/`)。
  * **全新 Logged-Out GraphQL 游标分页引擎**：基于 Meta 官方免登录接口（`PolarisOwnerToTimelineMediaLoggedOutQuery_connection`，Doc ID: `29239200285696526`），彻底突破常规接口在未登录状态下的 1675002 / 1675004 速率限制拦截。
  * 支持单次批处理 50 项的游标连续深度下潜翻页，数十秒内即可遍历检索完多达数百个 Reels 影片与独立照片/轮播图集。
  * **跨任务零开销缓存通道**：Task 1（图集扫描）发现的全部影片与 Reels 在 Task 2 中以 0.0 秒直接复用并完成去重转换，免除二次重复请求。
* **𝕏 X (前 Twitter) 视频推文与多媒体归档**：
  * 深度支持单视频推文与循环播放动图 GIF (`x.com/<user>/status/<id>`, `twitter.com/<user>/status/<id>`)。
  * **多视频推文独立解包**：自动解包包含多条视频的合集推文为独立序号条目（`/video/1`, `/video/2`），支持单独勾选下载。
  * **智能标题净化 (`clean_x_title`)**：自动剥离冗余的 `User on X: "..."` 包装文本与尾部 `t.co` 链接，保留完整中日韩 CJK 字符与 Emoji 表情包。
  * 专属 Netscape `cookies.txt` 认证支持，轻松归档锁推账号与敏感内容限制推文。
* **🎵 TikTok 视频与创作者主页归档**：
  * 超高速批量检测与无水印视频下载，支持单视频链接 (`/video/...`, `vt.tiktok.com`) 及创作者个人主页 (`/@username`)。
  * 新增专属 Netscape `cookies.txt` 认证连接，突破年龄限制与隐私受限内容。
* **⚡ 哔哩哔哩视频、多P分P合集与创作者空间归档 (Bilibili)**：
  * 全面支持普通视频 (`BV...`/`av...`)、分P剧集、互动视频与个人空间完整归档 (`space.bilibili.com/{mid}`)，内置防爬虫 Wbi 签名密钥算法保护。

---

### 🎛️ 灵活丰富的下载与归档模式
* **视频 + 音频 (Video + Audio)**：下载最高画质视频流并自动合并音频轨道（MP4, MOV, MKV），保留最佳观影体验。
* **仅视频 (Video Only)**：下载无音频轨道的纯净超清画面。
* **仅音频 (Audio Only)**：抽取纯净独立音频文件（WAV, MP3, M4A, FLAC, AAC, OPUS），支持自定义音质码率。
* **仅图片 (Image Only)**：专为图文社交媒体打造的图片归档模式，提供格式转换（保持原格式, JPG, PNG, WEBP）与压缩质量设置（70% - 100%）。
* **仅伴生资产 (Assets Only)**：秒级极速提取字幕 (`.srt`)、高分辨率封面 (`.jpg`, `.png`)、描述文本 (`.description`)、章节标记及元数据，无需重复下载庞大的音视频数据流。
* **平台专属结构化元数据**：模块化元数据导出器 (`metadata/`)，生成严格适配各平台字段属性的 UTF-8 `.metadata.txt` 档案。

---

### 🛡️ 智能文件组织与命名系统
* **跳过已下载媒体 (Skip Downloaded Media)**：可在“设置 -> 通用”中启用。基于本地持久化 `download_archive.txt`，二次扫描同一主页或播放列表时自动跳过历史已下载项。
* **添加序号前缀 (Add Sequence No. to Filename)**：自动为下载文件添加从 1 开始的扫描顺序编号（如 `01_`、`001_`，最高支持 6 位数前缀 `000001_`），按顺序整齐排列专辑曲目与剧集。
* **文件名包含媒体 ID (Include Media ID in Filename)**：在文件名末尾附加规范的平台媒体唯一 ID（如 `[<id>]`），防止同名视频冲突。
* **创建单独媒体文件夹 (Create Individual Media Folders)**：为每一条媒体及其伴生文件（封面、字幕、歌词、元数据）创建独立命名的子文件夹。
* **创建频道子文件夹 (Create Channel Subfolder)**：自动以频道或创作者名称归纳文件夹层级。
* **创建自定义文件夹名称 (Create Custom Folder Name)**：直接将所有下载文件汇聚到用户自定义的文件夹中，自动绕开频道名称层级。

---

### 🔒 平台专属隔离认证与通用 Cookie 模式
* **🌐 全新“全部平台 (All)”通用 Cookie 模式**：
  * 在平台认证下拉菜单中选择 **All（全部平台）**，只需导入一份包含多域名登录态的通用 Netscape `cookies.txt`，即可一键应用于所有支持的平台，彻底告别逐个平台分别导入配置的繁琐操作。
* **🎵 TikTok 自定义 Cookie 认证支持**：
  * 认证配置平台菜单新增 **TikTok** 选项，支持加载用户自定义的 Cookie 文件，解锁私密视频、地区限制与登录墙限制。
* **平台隔离保护**：针对 YouTube、YouTube Music、TikTok、Facebook、Instagram、X、Bilibili 与抖音提供按需隔离配置，避免各站点凭据交叉泄漏。
* **会话有效性即时检测**：内置专用的会话连通性检测器，自动验证 YouTube 会话、Instagram (`sessionid`)、Bilibili (`SESSDATA`)、Facebook 与 TikTok 的有效登录状态。

---

### 🖥️ 现代化桌面体验与交互设计
* **粘贴自动扫描 (Auto-Scan on Paste)**：在“设置 -> 通用”中随心开启。当剪贴板复制有效平台链接并粘贴到输入框时，软件即刻自动启动解析（键盘手动键入时不会误触发）。
* **Available Media 媒体列表管理**：实时直观显示当前已发现项、总条目数计数器、动态状态徽章，扫描完成后自动选中全部条目。
* **PySide6 原生流畅交互**：提供经过精心调优的深色 (Dark) 与浅色 (Light) 主题，集成 Windows 任务栏实时动态下载进度条 (`ITaskbarList3`)，全后台无阻塞扫描与多线程并发下载。
* **解耦式进度监控与精准权重**：分离当前单文件进度与全局队列进度，后处理阶梯式权重设计确保封面、音频与歌词全部写入完毕后才判定为 100%。
* **三语界面动态即时切换**：无需重启应用程序，在设置中即可在 **English**、**简体中文** 与 **繁體中文** 之间即时无缝切换。
* **组件运行环境仪表盘**：主界面直观呈现 `yt-dlp`、`gallery-dl`、`Deno` 与 `FFmpeg` 的就绪状态与本地版本号，支持一键在线后台静默升级。
* **独立悬浮式活动日志窗口 (Activity Log)**：将以往固定于底部的日志窗格升级为独立的无模态悬浮窗口，释放主窗口 100% 的可用表格纵向空间，支持毫秒级日志流水、一键复制与日志清空。

---

## 📥 下载与安装

欢迎前往 [GitHub Releases](https://github.com/jjsiew2014-art/ChannelHarvest/releases) 页面下载适用于 **Windows 10 / 11 (64位)** 的最新正式发布版本：

| 软件包版本 | 文件名 | 描述 |
| :--- | :--- | :--- |
| **Windows 安装向导** (推荐) | `ChannelHarvest-Setup-v1.4.1.exe` | 标准向导式安装程序 (基于 Inno Setup)，自动创建桌面快捷方式并附带卸载程序 |
| **独立便携压缩包** | `ChannelHarvest-Portable-v1.4.1.zip` | 绿色免安装版 —— 解压到任意目录直接运行 `ChannelHarvest.exe` 即可使用 |

> **提示**：两个发布包均已预先完整集成所必需的外部运行时二进制组件 (`ffmpeg.exe`, `ffprobe.exe`, `deno.exe`, `yt-dlp.exe`)，开箱即用，无需额外配置环境变量。

---

## 🛡️ Windows SmartScreen 提示说明

由于 Channel Harvest 属于开源自由软件，尚未购买昂贵的商业数字代码签名证书：

1. 当首次运行时，Windows Defender SmartScreen 可能弹出提示：**“Windows 已保护你的电脑”**。
2. 点击提示界面的 **“更多信息”**。
3. 点击 **“仍要运行”** 即可正常开启。

你可以在 Windows PowerShell 中计算所下载文件的 SHA-256 哈希值，并与官方发布的 `SHA256SUMS.txt` 进行比对核实完整性：

```powershell
Get-FileHash ChannelHarvest-Setup-v1.4.1.exe -Algorithm SHA256
Get-FileHash ChannelHarvest-Portable-v1.4.1.zip -Algorithm SHA256
```

---

## 📁 项目架构与目录索引

```
Channel Harvest/
├── app.py                         # 应用程序主入口
├── build.py                       # 自动化一键构建与 Release 打包脚本
├── build_release.bat              # 便捷调起 build.py 的批处理脚本
├── ChannelHarvest.spec            # PyInstaller 打包与依赖收集规格文件
├── version_info.txt               # Windows PE 可执行文件版本资源元数据
├── ChannelHarvest.ico             # 多尺寸应用高清图标 (16x16 至 256x256)
├── Channel Harvest__Logo.png      # 品牌高清 Logo
├── requirements.txt               # 运行环境 Python 依赖清单
├── requirements-build.txt         # 打包构建环境依赖 (PyInstaller, Pillow)
├── LICENSE                        # MIT 开源许可证
├── README.md                      # 英文项目主文档
├── README_CN.md                   # 简体中文项目文档
├── RELEASE_NOTES_v1.4.1.md        # v1.4.1 版本更新与发布说明
│
├── core/                          # 核心业务逻辑、数据模型、存储与国际化
│   ├── __init__.py
│   ├── availability.py            # 平台文件可用性及跳过检测
│   ├── diagnostics.py             # 系统诊断报告生成器
│   ├── error_classifier.py        # 智能错误分类与用户引导建议
│   ├── i18n.py                    # 三语国际化字典 (English / 简体中文 / 繁體中文)
│   ├── inventory.py               # 主页媒体清单 SQLite 本地缓存管理
│   ├── media_classifier.py        # 媒体分类引擎 (Photo, Video, Reel, Carousel)
│   ├── models.py                  # 核心数据模型 (VideoItem, DownloadSettings, ScanResult)
│   ├── paths.py                   # AppData 路径规范化及 Windows 路径安全脱敏
│   ├── settings.py                # 持久化 JSON 配置管理器
│   ├── single_instance.py         # 本地 IPC 单实例防多开互斥锁
│   ├── version.py                 # 集中版本号与发布信息
│   └── platform/                  # 可扩展多平台适配器模块
│       ├── __init__.py
│       ├── auth.py                # 平台认证配置与凭证实体
│       ├── base.py                # 平台抽象基类 BasePlatformAdapter
│       ├── capabilities.py        # 平台特性开关与功能定义
│       ├── detector.py            # 链接归属平台智能探测器
│       ├── youtube.py             # YouTube 平台适配器
│       ├── youtubemusic.py        # YouTube Music 平台专属适配器
│       ├── tiktok.py              # TikTok 平台适配器
│       ├── bilibili.py            # 哔哩哔哩平台适配器
│       ├── facebook.py            # Facebook 基础适配器与入口路由
│       ├── facebook_comet.py      # Facebook Comet GraphQL 深度游标扫描客户端
│       ├── instagram.py           # Instagram 基础适配器
│       ├── instagram_web.py       # Instagram Logged-Out GraphQL 游标分页客户端
│       ├── x.py                   # X (Twitter) 平台适配器
│       └── douyin.py              # 抖音适配器
│
├── downloader/                    # 下载执行、外部引擎调度与资产后处理
│   ├── __init__.py
│   ├── auth_checker.py            # 浏览器 Cookie 提取与 Netscape 格式校验
│   ├── cover_art_manager.py       # 1:1 方形封面提取、智能去重与音频标签注入
│   ├── deno_checker.py            # Deno 运行环境健康探测
│   ├── download_manager.py        # 异步 QThread 下载队列调度管理器
│   ├── engine_router.py           # 双引擎智能下载路由调度 (yt-dlp vs gallery-dl)
│   ├── ffmpeg_checker.py          # FFmpeg / FFprobe 二进制状态巡检
│   ├── format_selector.py         # 动态画质与音质格式参数构建器
│   ├── gallerydl_engine.py        # gallery-dl 图像流下载引擎
│   ├── info_manager.py            # 视频描述、章节信息及扩展元数据处理器
│   ├── lyrics_manager.py          # LRC 同步动态歌词在线搜索、下载与标签嵌入
│   ├── profile_scan_manager.py    # 双引擎主页扫描综合调度中心
│   ├── profile_video_discovery_engine.py # Facebook 与 Instagram 视频深度探测引擎
│   ├── runtime_manager.py         # 依赖版本管理与静默在线更新器
│   ├── scan_reporter.py           # 扫描诊断与状态综合报告器
│   ├── subtitle_manager.py        # 多语言字幕提取、格式转码与语言命名标准化
│   ├── thumbnail_manager.py       # 封面与缩略图下载器
│   ├── updater.py                 # yt-dlp 独立可执行程序在线更新组件
│   └── ytdlp_engine.py            # 基于 yt-dlp 原生 Python API 的下载交互引擎
│
├── metadata/                      # 平台专属结构化元数据档案导出器
│   ├── __init__.py
│   ├── base_formatter.py          # 元数据格式化器基类
│   ├── metadata_exporter.py       # 格式化导出分发引擎
│   ├── youtube_formatter.py       # YouTube 专属 .metadata.txt 格式化器
│   ├── tiktok_formatter.py        # TikTok 专属 .metadata.txt 格式化器
│   ├── bilibili_formatter.py      # Bilibili 专属 .metadata.txt 格式化器
│   ├── facebook_formatter.py      # Facebook 专属 .metadata.txt 格式化器
│   ├── instagram_formatter.py     # Instagram 专属 .metadata.txt 格式化器
│   ├── x_formatter.py             # X (Twitter) 专属 .metadata.txt 格式化器
│   └── generic_formatter.py       # 通用后备元数据格式化器
│
├── gui/                           # 基于 PySide6 的现代化桌面用户界面
│   ├── __init__.py
│   ├── activity_log_dialog.py     # 独立悬浮式实时运行日志查看器
│   ├── auth_result_dialog.py      # 平台认证连通性检测详情对话框
│   ├── circular_progress.py       # 抗锯齿环形扫描动画指示器组件
│   ├── error_details_dialog.py    # 错误分级分析与操作指引提示框
│   ├── main_window.py             # 应用主界面窗体及平台快速切换器
│   ├── settings_dialog.py         # 全功能设置对话框 (通用/认证/运行时管理)
│   ├── styles.py                  # 深色/浅色 Windows 现代化 QSS 主题渲染引擎
│   ├── summary_dialog.py          # 队列完成综合指标汇总报告框
│   ├── taskbar_progress.py        # Windows 任务栏实时进度控制器
│   ├── toggle_switch.py           # 现代化动画平滑滑动切换开关组件
│   └── video_table.py             # 媒体资源表格与进度条实时渲染视图
│
├── installer/                     # Inno Setup Windows 安装包打包工程
│   └── ChannelHarvest.iss         # Inno Setup 6 编译构建配置文件
│
└── runtime/                       # 内置预置的外部必备执行文件
    ├── deno.exe                   # Deno JavaScript 运行时引擎
    ├── ffmpeg.exe                 # FFmpeg 音视频多媒体处理转码工具
    ├── ffprobe.exe                # FFprobe 音视频媒体流分析工具
    └── yt-dlp.exe                 # 官方发布的独立便携式 yt-dlp 核心引擎
```

---

## 🔨 从源码构建与开发

### 环境要求
* Windows 10 或 Windows 11 (64位系统)
* Python 3.10+ (推荐使用 Python 3.14 64位版本)
* [Inno Setup 6](https://jrsoftware.org/isdl.php) (可选，仅用于编译生成 `.exe` 安装程序)

### 1. 克隆代码仓库并安装依赖
```powershell
git clone https://github.com/jjsiew2014-art/ChannelHarvest.git
cd "ChannelHarvest"
pip install -r requirements-build.txt
```

### 2. 本地直接运行 (开发调试)
```powershell
python app.py
```

### 3. 一键自动化构建 Release 生产包
在项目根目录下执行打包脚本：
```powershell
python build.py
```
*(也可以直接双击运行 `build_release.bat`)*

构建脚本将全自动依次完成：
1. 校验本地必备运行时二进制组件 (`deno.exe`, `ffmpeg.exe`, `ffprobe.exe`, `yt-dlp.exe`)。
2. 自动生成多尺寸应用图标并注入 Windows PE 版本元数据。
3. 清理缓存并通过 PyInstaller 执行 onedir 冻结打包。
4. 将 `runtime/` 工具链完整复制部署至 `dist/ChannelHarvest/` 内部。
5. 生成便携免安装包 `release/ChannelHarvest-Portable-v1.4.1.zip`。
6. 调用 Inno Setup 编译器生成向导安装包 `release/ChannelHarvest-Setup-v1.4.1.exe`。
7. 计算全部发布资产的 SHA-256 校验和并写入 `release/SHA256SUMS.txt`。

---

## 📜 开源协议

本项目采用 [MIT 许可证](LICENSE) 开源发布。版权所有 (c) 2026 jjsiew2014-art。
