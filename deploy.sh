#!/bin/bash

# ================= 配置区 =================
# 您的 Docker 镜像名称 (用户名/仓库名)
IMAGE_NAME="seaside111/torrent-webui"
# ==========================================

# 遇到错误立即停止
set -e

echo "========================================"
echo "   🚀 种子工厂 (Seed Factory) 一键发布脚本"
echo "========================================"

# 1. 获取输入信息
read -p "请输入本次更新的版本号 (例如 v1.2): " VERSION
if [ -z "$VERSION" ]; then
    echo "❌ 错误: 版本号不能为空！"
    exit 1
fi

read -p "请输入本次更新的内容说明 (Commit Message): " MSG
if [ -z "$MSG" ]; then
    MSG="Update to $VERSION"
fi

# 2. Git 同步流程
echo ""
echo "---------- [1/3] 同步到 GitHub ----------"
git add .
git commit -m "$MSG"
git push origin main
echo "✅ GitHub 同步完成！"

# 3. Docker 构建流程
echo ""
echo "---------- [2/3] 构建 Docker 镜像 ----------"
echo "正在构建版本: $VERSION ..."
docker build -t $IMAGE_NAME:$VERSION .

echo "正在标记 Latest ..."
docker tag $IMAGE_NAME:$VERSION $IMAGE_NAME:latest
echo "✅ 镜像构建完成！"

# 4. Docker 推送流程
echo ""
echo "---------- [3/3] 推送到 Docker Hub ----------"
echo "正在推送版本: $VERSION ..."
docker push $IMAGE_NAME:$VERSION

echo "正在推送 Latest ..."
docker push $IMAGE_NAME:latest
echo "✅ 镜像推送完成！"

echo ""
echo "========================================"
echo "🎉 恭喜！版本 $VERSION 已成功发布！"
echo "========================================"
