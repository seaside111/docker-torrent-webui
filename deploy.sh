#!/bin/bash

# ================= 配置区 =================
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

# 关键修改：检查是否有文件变更
if [ -n "$(git status --porcelain)" ]; then
    echo "📝 检测到代码变更，正在提交..."
    git add .
    git commit -m "$MSG"
    git push origin main
    echo "✅ GitHub 同步完成！"
else
    echo "⚠️  工作区干净（无代码变更），跳过 Git 提交步骤..."
    echo "ℹ️  当前 Git 状态：已是最新"
fi

# 3. Docker 构建流程
echo ""
echo "---------- [2/3] 构建 Docker 镜像 ----------"
echo "正在构建版本: $VERSION ..."
# 建议：添加 --pull 确保基础镜像是最新的
docker build --pull -t $IMAGE_NAME:$VERSION .

echo "正在标记 Latest ..."
docker tag $IMAGE_NAME:$VERSION $IMAGE_NAME:latest
echo "✅ 镜像构建完成！"

# 4. Docker 推送流程
echo ""
echo "---------- [3/3] 推送到 Docker Hub ----------"
# 检查是否已登录 Docker Hub
if ! docker info | grep -q "Username"; then
    echo "⚠️  检测到未登录 Docker Hub，请先登录："
    docker login
fi

echo "正在推送版本: $VERSION ..."
docker push $IMAGE_NAME:$VERSION

echo "正在推送 Latest ..."
docker push $IMAGE_NAME:latest
echo "✅ 镜像推送完成！"

echo ""
echo "========================================"
echo "🎉 恭喜！版本 $VERSION (及 Latest) 已成功发布！"
echo "========================================"