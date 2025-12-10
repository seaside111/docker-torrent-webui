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

本镜像已发布至 Docker Hub，无需构建，直接拉取即可使用。

### 1. 拉取镜像

    ```bash
      docker pull seaside111/torrent-webui:latest

### 2. 启动容器
方法一：使用 Docker CLI (推荐)

复制以下命令并根据你的实际情况修改挂载路径：

    ```bash
       docker run -d \
         --name torrent-webui \
         --restart unless-stopped \
         -p 5000:5000 \
         -v /path/to/your/downloads:/data \
         -e ADMIN_USER=admin \
         -e ADMIN_PASS=password123 \
         -e SECRET_KEY=your_secret_key \
         seaside111/torrent-webui:latest

方法二：使用 Docker Compose (NAS/高级用户推荐)

创建一个 docker-compose.yml 文件：

    ```bash
       version: '3.8'
       services:
         torrent-webui:
           image: seaside111/torrent-webui:latest
           container_name: torrent-webui
           restart: unless-stopped
           ports:
             - "5000:5000"
           volumes:
             - /path/to/your/downloads:/data  # <--- 请将冒号左侧改为你服务器的真实路径
           environment:
             - ADMIN_USER=admin               # 自定义用户名
             - ADMIN_PASS=password123         # 自定义密码
             - SECRET_KEY=random_string       # Session 加密密钥 (建议修改)

    ```bash
参数 (Flag)	  描述 (Description)	    备注
-p 5000:5000	端口映射。	冒号左侧可自定义，右侧 5000 不可变。
-v /path:/data	目录挂载 (核心)。将宿主机的资源目录挂载到容器内。程序将在此目录读取视频并输出种子。	冒号左侧填真实路径，右侧 /data 严禁修改。
-e ADMIN_USER	WebUI 登录用户名。	
-e ADMIN_PASS	WebUI 登录密码。	
-e SECRET_KEY	Flask Session 密钥。	建议设置一个随机字符串以增强安全性。


🚀 访问与使用

    容器启动后，浏览器访问：http://你的服务器IP:5000

    输入你设置的账号密码登录。

    在路径栏输入相对于 /data 的路径（例如：若挂载了 /home/download 到 /data，且你要处理 /home/download/Movie，则只需填写 Movie）。
