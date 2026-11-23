"""VOFA+ 协议解析：JustFloat 二进制帧与 RawData 原始文本。"""

from __future__ import annotations

import math
import struct

JUSTFLOAT_TAIL = b"\x00\x00\x80\x7f"
MAX_BUFFER = 1024 * 1024
_TAIL_LEN = len(JUSTFLOAT_TAIL)


class JustFloatParser:
    """JustFloat：小端 float32 数组 + 0x0000807f 帧尾。

    采用「扫描 + 一次性裁剪」，避免逐帧删除缓冲区头部导致的 O(n²)。
    """

    def __init__(self) -> None:
        self.buffer = bytearray()

    def reset(self) -> None:
        self.buffer.clear()

    def feed(self, chunk: bytes) -> list[list[float]]:
        buf = self.buffer
        buf.extend(chunk)
        frames: list[list[float]] = []
        pos = 0
        unpack = struct.unpack
        while True:
            end = buf.find(JUSTFLOAT_TAIL, pos)
            if end < 0:
                break
            payload = bytes(buf[pos:end])
            pos = end + _TAIL_LEN
            if not payload or len(payload) % 4 != 0:
                continue
            count = len(payload) // 4
            values = list(unpack("<" + "f" * count, payload))
            if not all(math.isfinite(v) for v in values):
                continue
            frames.append(values)

        if pos:
            del buf[:pos]
        if len(buf) > MAX_BUFFER:
            buf.clear()
        return frames


def decode_raw(chunk: bytes, encoding: str = "utf-8") -> str:
    return chunk.decode(encoding, errors="replace")
