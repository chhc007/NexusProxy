#!/bin/bash

# 1. 确保目标挂载目录存在
mkdir -p /app/modules

# 2. 检查是否开启了强制覆盖模式 (用于镜像更新后强制同步最新代码)
if [ "$FORCE_UPDATE_MODULES" = "true" ] || [ "$FORCE_UPDATE_MODULES" = "1" ]; then
    echo "🔄 检测到 FORCE_UPDATE_MODULES=true，正在强制覆盖并同步所有模块文件..."
    # 强制覆盖：使用 -f (force) 和 -r (recursive)
    cp -r -f /app/default_modules/. /app/modules/
    echo "✅ 强制同步完成！所有文件已更新为镜像最新版本。"
else
    # 3. 默认行为：增量同步，不覆盖已存在的文件（保护用户自定义修改）
    if [ ! -f "/app/modules/base.py" ]; then
        echo "🚀 首次运行：正在初始化 modules 目录，释放基础模块..."
    else
        echo "⚡ 检测到 modules 目录已有基础文件，正在检查并补充缺失/新增的模块..."
    fi
    
    # 【核心修复】：使用 /. 而不是 /* 
    # /. 表示复制目录内部的所有内容并深度合并，确保子目录中缺失的文件也能被补充进去
    # -n (no-clobber) 确保不覆盖用户已经修改过的文件
    cp -r -n /app/default_modules/. /app/modules/
    
    echo "✅ 模块同步完成！(已保留您的自定义修改，并补充了新增/缺失的文件)"
fi

set -e

MODULE_DIR="/app/modules"

echo "[Plugin] 扫描插件依赖..."

REQ_FILES=$(find "$MODULE_DIR" -maxdepth 1 -name "requirements.*.txt")

if [ -n "$REQ_FILES" ]; then

    TMP_REQ="/tmp/plugin_requirements.txt"

    rm -f "$TMP_REQ"

    for file in $REQ_FILES
    do
        echo "[Plugin] 发现依赖: $file"
        cat "$file" >> "$TMP_REQ"
        printf "\n" >> "$TMP_REQ"
    done

    # 去重空行
    sed -i '/^$/d' "$TMP_REQ"

    if [ -s "$TMP_REQ" ]; then
        echo "[Plugin] 开始安装插件依赖..."

        pip install \
            --no-cache-dir \
            -r "$TMP_REQ"

        echo "[Plugin] 插件依赖安装完成"
    fi

else
    echo "[Plugin] 未发现额外插件依赖"
fi


# 4. 启动 FastAPI 主程序
echo "🚀 NexusProxy 启动，监听端口 9118"
# 使用 exec 确保 uvicorn 成为 PID 1，能够正确接收 Docker 的停止信号 (SIGTERM)
exec uvicorn main:app --host 0.0.0.0 --port 9118
