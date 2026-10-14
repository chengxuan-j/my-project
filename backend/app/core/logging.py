"""结构化日志：structlog 配置。

输出 JSON 行（生产）或彩色控制台（开发）。所有日志自动带 timestamp/level/logger。
路由层用 structlog.contextvars.bind_contextvars 注入 request_id / user_id。
"""
import logging
import sys

import structlog

from app.config import get_settings


def configure_logging() -> None:
    s = get_settings()
    level = getattr(logging, s.log_level.upper(), logging.INFO)

    # 标准 logging → structlog 桥接
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if s.is_production:
        # 生产：JSON 行，方便收集
        processors.append(structlog.processors.JSONRenderer())
    else:
        # 开发：彩色可读输出
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
