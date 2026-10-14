"""
指令闸门 —— 把"每一帧的原始判定"变成"值得发给机器狗的指令"。

这一步比识别本身更影响体验，原因有两个：

1. 逐帧判定必然抖动。必须要求姿势连续保持 N 帧才算数，否则一条指令会连发几十次。
2. 机器狗的动作是阻塞式的（walk 默认 4 步、每步约 1 秒）。指令必须"边沿触发"：
   做一次动作、回中立位、再做一次，才会再发一条。否则全堆在设备队列里，看着像死机。
"""

import time
from typing import Optional, Tuple

from action_rules import Action


class CommandGate:
    def __init__(
        self,
        hold_frames: int = 8,
        release_frames: int = 6,
        cooldown_s: float = 2.0,
    ):
        self.hold_frames = hold_frames
        self.release_frames = release_frames
        self.cooldown_s = cooldown_s

        self._current: Optional[str] = None
        self._streak = 0
        self._release_streak = 0
        self._awaiting_release = False
        self._last_emit_ts = 0.0

    # -- 只读状态，供 HUD 显示 --
    @property
    def current_key(self) -> Optional[str]:
        return self._current

    @property
    def awaiting_release(self) -> bool:
        return self._awaiting_release

    def cooldown_left(self) -> float:
        left = self.cooldown_s - (time.monotonic() - self._last_emit_ts)
        return max(0.0, left)

    def reset(self) -> None:
        self._current = None
        self._streak = 0
        self._release_streak = 0
        self._awaiting_release = False
        self._last_emit_ts = 0.0

    def update(self, action: Optional[Action]) -> Tuple[Optional[Action], float]:
        """喂入一帧的判定结果。

        返回 (确认的指令 or None, 稳定进度 0~1)。
        """
        now = time.monotonic()

        # ---- 中立位：清空当前姿势，并在累计足够帧数后解锁 ----
        if action is None:
            self._current = None
            self._streak = 0
            if self._awaiting_release:
                self._release_streak += 1
                if self._release_streak >= self.release_frames:
                    self._awaiting_release = False
                    self._release_streak = 0
            else:
                self._release_streak = 0
            return None, 0.0

        self._release_streak = 0

        if self._current == action.key:
            self._streak += 1
        else:
            self._current = action.key
            self._streak = 1

        progress = min(1.0, self._streak / self.hold_frames)
        if self._streak < self.hold_frames:
            return None, progress

        # 姿势已经稳定，但还要过两道关
        if self._awaiting_release:
            # 手还没放下，不重复触发
            return None, 1.0
        if now - self._last_emit_ts < self.cooldown_s:
            return None, 1.0

        self._last_emit_ts = now
        self._awaiting_release = True
        return action, 1.0
