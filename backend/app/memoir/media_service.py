"""回忆照片的落盘、校验与寻址（M6）。

存储选择：**应用磁盘**（`storage/memoir_media/`），数据库里只存相对路径。
刻意**不** mount `StaticFiles`——照片必须经鉴权接口读取：

- 契约2：创伤故事会被强制 `private` 且锁定。如果照片走静态目录，
  它就变成"知道 URL 就能看"的一个洞，前端过滤拦不住任何东西。
- 因此 `story_media.url` 存的是磁盘相对路径（如 `12/ab12…cd.jpg`），
  对外 URL 由 presenter 现场生成成 `/api/v1/memoir/media/{id}`，
  再由读接口做「老人本人 / 已绑定家属 且 故事当前可见」的判定。

命名用内容 SHA256 前 16 位 + 原始扩展名，同一张图重复上传不会堆文件。
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from app.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

# content-type → 落盘扩展名。与 vision 的白名单保持一致，
# 免得出现"拍照能识别、存档说格式不对"的割裂体验。
ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

# 扩展名 → content-type（读回来时用；FileResponse 需要正确的 media_type）
EXT_CONTENT_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}

HASH_LEN = 16


class MediaError(ValueError):
    """照片不合法（空 / 太大 / 不是图片 / 类型不支持）。路由层转成 400。"""


def media_root() -> Path:
    """照片根目录（绝对路径）。目录不存在时创建。"""
    settings = get_settings()
    root = Path(settings.memoir_media_dir)
    if not root.is_absolute():
        root = Path(BASE_DIR) / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def max_bytes() -> int:
    return max(1, int(get_settings().memoir_media_max_mb)) * 1024 * 1024


def sniff_image_type(data: bytes) -> Optional[str]:
    """从文件头认出真实图片类型；认不出返回 None。

    为什么不只信 `UploadFile.content_type`：那是**客户端说了算**的字符串，
    改个后缀就能把它说成 `image/jpeg`。这里认文件头，认不出就拒收——
    免得有人把一段 HTML 当照片存进来。
    """
    if len(data) < 12:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def validate_image(data: bytes, content_type: str = "") -> str:
    """校验照片并返回落盘扩展名。不合法抛 `MediaError`。

    `content_type` 只用于**日志/兜底提示**，判据以文件头为准：
    客户端声明的类型不能作为"这确实是张图片"的证据。
    """
    if not data:
        raise MediaError("照片是空的，请重新选一张")
    limit = max_bytes()
    if len(data) > limit:
        mb = limit // (1024 * 1024)
        raise MediaError(f"照片超过 {mb}MB，请换一张小一点的")
    if len(data) < 12:
        raise MediaError("这个文件不像是一张照片，请换一张试试")

    sniffed = sniff_image_type(data)
    if sniffed is None:
        logger.info("拒绝非图片文件：声明类型=%s 大小=%s", content_type or "(未声明)", len(data))
        raise MediaError("这个文件不像是一张照片，请换一张试试")

    ext = ALLOWED_IMAGE_TYPES.get(sniffed)
    if ext is None:
        raise MediaError("只支持 jpg / png / webp / gif / bmp / tiff 格式的照片")
    return ext


def _rel_path(story_id: int, data: bytes, ext: str) -> str:
    digest = hashlib.sha256(data).hexdigest()[:HASH_LEN]
    # 按 story 分目录：删故事时整目录可清，也避免单目录文件过多
    return f"{int(story_id)}/{digest}{ext}"


def save_photo(story_id: int, data: bytes, ext: str) -> str:
    """把照片写盘，返回相对路径（可以直接存进 `story_media.url`）。

    同一张图重复上传：内容哈希相同 → 覆盖同名文件，不产生副本。
    """
    rel = _rel_path(story_id, data, ext)
    target = resolve_path(rel)
    if target is not None and target.exists():
        return rel
    target = media_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再 rename，避免读到半个文件
    tmp = target.with_suffix(target.suffix + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)
    logger.info("回忆照片落盘 story=%s path=%s bytes=%s", story_id, rel, len(data))
    return rel


def resolve_path(rel_path: str) -> Optional[Path]:
    """相对路径 → 绝对路径。越界（`..` / 绝对路径）返回 None。

    这是唯一的读盘入口，所有拼路径的地方都走它，杜绝路径穿越。
    反斜杠先归一成 `/`——否则在 POSIX 上 `..\\..\\etc` 会被当成普通文件名放行，
    而在 Windows 上它真的会往上跳，同一份数据两种行为。
    """
    if not rel_path:
        return None
    rel = str(rel_path).replace("\\", "/")
    if rel.startswith("/") or ".." in rel.split("/"):
        logger.warning("拒绝越界的媒体路径: %s", rel_path)
        return None
    root = media_root()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        logger.warning("拒绝越界的媒体路径: %s", rel_path)
        return None
    return candidate


def content_type_for(rel_path: str) -> str:
    return EXT_CONTENT_TYPES.get(Path(rel_path).suffix.lower(), "application/octet-stream")


def remove_photo(rel_path: str) -> bool:
    """删盘上的文件。找不到也算成功（幂等），越界返回 False。"""
    target = resolve_path(rel_path)
    if target is None:
        return False
    try:
        target.unlink()
    except FileNotFoundError:
        return True
    except OSError as e:  # 删不掉不该让接口 500，库里记录照删
        logger.warning("删除媒体文件失败 %s: %s", rel_path, e)
        return False
    return True
