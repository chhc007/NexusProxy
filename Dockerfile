FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制主程序代码
COPY main.py utils.py ./

# 【关键修改】将默认模块复制到 /app/default_modules 作为备份，而不是 /app/modules
COPY modules/ ./default_modules/

# 复制并赋予启动脚本执行权限
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 确保映射目标目录存在
RUN mkdir -p /app/modules

EXPOSE 9118

# 使用自定义启动脚本
ENTRYPOINT ["/entrypoint.sh"]
