# Docker Torrent WebUI

这是一个基于 Docker 的轻量级 PT 种子制作工具。它集成了 mktorrent、MediaInfo 和 FFmpeg，提供了一个现代化的 Web 界面，可以一键生成种子文件、媒体信息（MediaInfo）以及视频缩略图预览。

## ✨ 主要功能

* **可视化操作**：通过 Web 界面填写路径和 Tracker，无需敲命令行。
* **自动生成种子**：基于 `mktorrent`，支持设置分块大小、PT 私有标记。
* **MediaInfo 集成**：自动扫描目录下最大的视频文件，生成详细的参数报告。
* **视频缩略图**：使用 `FFmpeg` 极速生成 4x4 视频预览拼图。
* **任务队列**：异步后台处理，支持大文件操作，界面不卡顿。
* **自动归档**：所有生成的文件自动整理到源目录下的 `/torrent` 文件夹中。
* **安全保护**：内置登录验证界面。

## 🛠️ 安装指南 (Docker)

### 方法一：使用 Docker CLI

你可以直接构建并运行容器：

1. **克隆代码**
   ```bash
   git clone [https://github.com/seaside111/docker-torrent-webui.git](https://github.com/seaside111/docker-torrent-webui.git)
   cd docker-torrent-webui