.PHONY: dev test lint format migrate clean

dev:
	cd backend && uvicorn app.main:app --reload

test:
	cd backend && pytest tests/ -q

lint:
	ruff check backend/app/

format:
	ruff format backend/app/

# 应用启动时（lifespan）会按 ORM 定义自动建表。
# 如需把本地 SQLite 数据迁移到 PostgreSQL，使用下面的脚本：
migrate:
	cd backend && python scripts/migrate_sqlite_to_pg.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
