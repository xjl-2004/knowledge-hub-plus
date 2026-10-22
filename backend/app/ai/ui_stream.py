"""AI SDK UI Message Stream 协议编码。"""

import json
from typing import Any


def encode(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def done_frame() -> str:
    return "data: [DONE]\n\n"


class UIStreamWriter:
    """收集事件帧，由外层生成器按序发出。"""

    def __init__(self) -> None:
        self._buffer: list[str] = []

    def write(self, payload: dict[str, Any]) -> None:
        self._buffer.append(encode(payload))

    def drain(self) -> list[str]:
        frames, self._buffer = self._buffer, []
        return frames
