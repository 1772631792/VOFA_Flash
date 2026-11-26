"""发送格式串解析：把 `S%fE,1.31` 这样的文本打包成二进制帧。

语法：模板 + 逗号 + 参数列表
  模板中的 `%f %d %u %h %H %b %B` 是数值占位符，按顺序取逗号后的参数；
  其它字面文本 / Hex 片段用 parse_frame_bytes 解析（与帧头帧尾一致）。

示例（默认小端）：
  S%fE,1.31        → 53 + float32(1.31) + 45
  AA55%f%d,1.5,10  → AA 55 + float32(1.5) + int32(10)
  text:SET %h\r\n,200 → "SET " + int16(200) + "\\r\\n"

大小端由调用方传入（默认小端，最常用）。
"""
from __future__ import annotations

import re
import struct

from .command_panel import parse_frame_bytes

# 占位符 -> struct 格式符
_FORMAT_TYPES: dict[str, tuple[str, int]] = {
    "f": ("f", 4),  # float32
    "d": ("i", 4),  # int32
    "u": ("I", 4),  # uint32
    "h": ("h", 2),  # int16
    "H": ("H", 2),  # uint16
    "b": ("b", 1),  # int8
    "B": ("B", 1),  # uint8
    "q": ("q", 8),  # int64
    "Q": ("Q", 8),  # uint64
    "l": ("d", 8),  # float64
}

_TOKEN = re.compile(r"%([fduhHbBqQl])")


def is_format_command(text: str) -> bool:
    """是否为格式串（含占位符且带逗号参数）。"""
    stripped = (text or "").strip()
    return bool(_TOKEN.search(stripped)) and "," in stripped


def parse_format_command(
    text: str, encoding: str = "utf-8", big_endian: bool = False
) -> bytes:
    """解析格式串并打包；不是格式串或参数不匹配时抛 ValueError。"""
    stripped = (text or "").strip()
    # 用第一个位于占位符之后的逗号切分模板 / 参数
    match = _TOKEN.search(stripped)
    if match is None:
        raise ValueError("格式串缺少 % 占位符")
    split_at = stripped.find(",", match.end())
    if split_at < 0:
        raise ValueError("格式串缺少逗号参数（如 S%fE,1.31）")
    template = stripped[:split_at]
    args_text = stripped[split_at + 1 :]

    args = [part.strip() for part in args_text.split(",") if part.strip()]
    tokens = list(_TOKEN.finditer(template))
    if len(args) < len(tokens):
        raise ValueError(f"参数不足：需要 {len(tokens)} 个，实际 {len(args)} 个")

    endian = ">" if big_endian else "<"
    out = bytearray()
    cursor = 0
    for index, token in enumerate(tokens):
        literal = template[cursor : token.start()]
        if literal:
            out += parse_frame_bytes(literal, encoding)
        fmt, _ = _FORMAT_TYPES[token.group(1)]
        value = _to_number(args[index], fmt)
        out += struct.pack(endian + fmt, value)
        cursor = token.end()
    out += parse_frame_bytes(template[cursor:], encoding)
    return bytes(out)


def _to_number(text: str, fmt: str) -> float | int:
    value = float(text) if fmt == "f" else int(text, 0)
    return value


def format_command_help() -> str:
    return (
        "格式串：%f float32 / %d int32 / %u uint32 / %h int16 / %H uint16 / "
        "%b int8 / %B uint8 / %q int64 / %Q uint64 / %l float64；"
        "例：S%fE,1.31。双击发送框切换大端/小端。"
    )
