# 基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y mktorrent mediainfo ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖 (增加了 requests)
RUN pip install --no-cache-dir flask requests

# 复制当前目录代码
COPY . .

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["python", "app.py"]