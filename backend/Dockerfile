FROM python:3.11-slim

WORKDIR /app

# 先安装依赖以利用构建缓存；editable 安装需要 app/ 源码先就位
COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install --no-cache-dir -e .

# 运行时资源（内容推荐依赖 data/*.json，必须一并打包）
COPY data/ ./data/
COPY scripts/ ./scripts/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
