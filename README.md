# Docker Torrent WebUI

这是一个基于 Docker 的轻量级 PT 种子制作工具。它集成了 mktorrent、MediaInfo 和 FFmpeg，提供了一个现代化的 Web 界面，可以一键生成种子文件、媒体信息（MediaInfo）以及视频缩略图预览。

## ✨ 主要功能

🤖 AI 智能字幕翻译：集成 DeepSeek 大模型 API，支持保留时间轴与序号的沉浸式翻译。智能识别电影语境，自动将外语 SRT 转换为高质量中文字幕，无需人工校对时间轴。

🎬 多轨字幕提取：一键从视频容器（MKV/MP4）中无损提取所有内封字幕流（SRT/ASS/PGS 等），并自动规范命名。

🖥️ 可视化文件管理：支持 Web 端目录浏览、批量移动/删除、文件重命名，以及在线编辑/新建文本文件（如 NFO、TXT），彻底告别命令行。

📋 实时任务监控：内置实时日志控制台，可直观追踪后台任务（AI 翻译进度、做种详情）的每一步执行状态。

⚡ 自动生成种子：基于 mktorrent，支持自定义分块大小、一键开启 PT 私有标记 (Private Flag)。

📊 MediaInfo 集成：自动扫描并分析视频文件，生成专业的媒体参数报告。

🖼️ 视频缩略图：使用 FFmpeg 极速生成 4x4 视频预览拼图，并支持自动上传图床（Pixhost）生成 BBCode。

📦 自动归档：所有生成的文件（种子、截图、字幕、NFO）自动整理归档至源目录下的 /torrent 文件夹，井井有条。

🛡️ 安全保护：内置登录验证系统，保护您的数据安全。

## 🛠️ 安装指南 (Docker)

### 方法一：使用 Docker CLI

你可以直接构建并运行容器：

1. **克隆代码**
   ```bash
   git clone [https://github.com/seaside111/docker-torrent-webui.git](https://github.com/seaside111/docker-torrent-webui.git)
   cd docker-torrent-webui
