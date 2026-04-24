#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-/workspace/projects/trade_agent}"
REPO_URL="https://github.com/andi-zhx/trade_agent.git"

mkdir -p "$(dirname "$TARGET_DIR")"

if [ -d "$TARGET_DIR/.git" ]; then
  echo "[INFO] 检测到已存在 Git 仓库，跳过 clone：$TARGET_DIR"
else
  if git clone "$REPO_URL" "$TARGET_DIR"; then
    echo "[INFO] clone 完成：$TARGET_DIR"
  else
    echo "[WARN] 无法访问 GitHub，已创建本地目录用于后续手动拉取：$TARGET_DIR"
    mkdir -p "$TARGET_DIR"
  fi
fi

if [ ! -d "$TARGET_DIR/.venv" ]; then
  python3 -m venv "$TARGET_DIR/.venv"
  echo "[INFO] 已创建虚拟环境：$TARGET_DIR/.venv"
else
  echo "[INFO] 虚拟环境已存在：$TARGET_DIR/.venv"
fi

ACTIVATE_CMD="source $TARGET_DIR/.venv/bin/activate"

echo "\n下一步："
echo "1) 激活环境: $ACTIVATE_CMD"
echo "2) 进入目录: cd $TARGET_DIR"
echo "3) 安装依赖: pip install -r requirements.txt"
