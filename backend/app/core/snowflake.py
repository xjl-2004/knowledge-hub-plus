import asyncio
import logging
import threading
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

WORKER_BITS = 10
SEQUENCE_BITS = 12
MAX_WORKER_ID = (1 << WORKER_BITS) - 1
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1
WORKER_SHIFT = SEQUENCE_BITS
TIMESTAMP_SHIFT = SEQUENCE_BITS + WORKER_BITS

_lock = threading.Lock()
_last_timestamp = -1
_sequence = 0


def next_id() -> int:
    """生成 64 位趋势递增 ID（时间戳 + worker + 序列）。"""
    global _last_timestamp, _sequence
    worker_id = settings.snowflake_worker_id & MAX_WORKER_ID
    with _lock:
        now = int(time.time() * 1000) - settings.snowflake_offset
        if now < _last_timestamp:
            now = _last_timestamp
        if now == _last_timestamp:
            _sequence = (_sequence + 1) & MAX_SEQUENCE
            if _sequence == 0:
                while now <= _last_timestamp:
                    now = int(time.time() * 1000) - settings.snowflake_offset
        else:
            _sequence = 0
        _last_timestamp = now
        return (now << TIMESTAMP_SHIFT) | (worker_id << WORKER_SHIFT) | _sequence


def next_id_str() -> str:
    return str(next_id())


async def next_id_async() -> int:
    return await asyncio.to_thread(next_id)
