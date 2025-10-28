# ✅ 基础镜像
FROM python:3.11-slim

# ✅ 设置环境变量，强制 pip 使用国内源并关闭缓存
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# ✅ 工作目录
WORKDIR /app

# ✅ 安装系统依赖 & 修复证书
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && update-ca-certificates \
    && python -m pip install --upgrade --index-url https://mirrors.aliyun.com/pypi/simple/ pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

# ✅ 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple/

# ✅ 确保 gunicorn 存在
RUN pip install gunicorn --index-url https://mirrors.aliyun.com/pypi/simple/

# ✅ 复制应用文件
COPY . .

# ✅ 创建必要目录
RUN mkdir -p data/summaries logs

# ✅ 暴露端口
EXPOSE 8000

# ✅ 启动命令
CMD ["/bin/bash", "run_gunicorn.sh"]

