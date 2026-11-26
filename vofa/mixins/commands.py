"""命令面板：固定命令、滑块组、自建组、拼帧与预览。"""
from __future__ import annotations

import re

from PySide6.QtWidgets import QDialog
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QPoint
from PySide6.QtCore import QTimer

from ..command_panel import CRC_MODES
from ..command_panel import CommandDialog
from ..command_panel import CommandItem
from ..command_panel import CustomGroupDialog
from ..theme import GROUP_COLORS
from ..command_panel import crc_bytes
from ..command_panel import dtype_limits
from ..command_panel import parse_frame_bytes


class CommandsMixin:
    def _command_widgets(self) -> list[CommandItem]:
        widgets: list[CommandItem] = []
        for i in range(self.cmd_layout.count()):
            widget = self.cmd_layout.itemAt(i).widget()
            if isinstance(widget, CommandItem):
                widgets.append(widget)
        return widgets

    def _command_groups(self) -> list[str]:
        groups: list[str] = []
        for item in self._command_widgets():
            if item.kind == "slider" and item.group and item.group not in groups:
                groups.append(item.group)
        return groups

    def _group_color(self, name: str) -> str:
        """组配色：优先用手动选择的颜色，否则按调色板自动分配一个没用过的。"""
        if name not in self._group_colors:
            used = set(self._group_colors.values())
            color = GROUP_COLORS[len(self._group_colors) % len(GROUP_COLORS)]
            for candidate in GROUP_COLORS:
                if candidate not in used:
                    color = candidate
                    break
            self._group_colors[name] = color
        return self._group_colors[name]

    def _apply_group_styles(self) -> None:
        """同组滑块使用统一配色的卡片与滑轨，便于区分不同组。"""
        for item in self._command_widgets():
            grouped = item.kind == "slider" and bool(item.group)
            item.set_group_color(self._group_color(item.group) if grouped else None)

    def _group_members(self, item: CommandItem) -> list[CommandItem]:
        """同一组的滑动条，按界面添加顺序打包。"""
        if item.kind != "slider" or not item.group:
            return [item]
        members = [
            w
            for w in self._command_widgets()
            if w.kind == "slider" and w.group == item.group
        ]
        return members or [item]

    def _build_add_menu(self, parent=None) -> QMenu:
        menu = QMenu(parent or self)
        menu.addAction("新增固定命令", lambda: self.add_command("fixed"))
        menu.addAction("新增滑动条", lambda: self.add_command("slider"))
        menu.addSeparator()
        menu.addAction("自建滑动组…", self.add_custom_group)
        for count in (2, 3, 4):
            menu.addAction(
                f"新增滑块组（{count} 个）",
                lambda _=False, n=count: self.add_slider_group(count=n),
            )
        return menu

    def show_add_command_menu(self, pos=None) -> None:
        """命令区空白处右键：在鼠标位置弹出新增菜单。"""
        menu = self._build_add_menu(self)
        if not isinstance(pos, QPoint):
            pos = self.cmd_inner.mapToGlobal(QPoint(0, 0))
        menu.exec(pos)
        menu.deleteLater()

    def _update_command_hint(self) -> None:
        self.cmd_empty.setVisible(not self._command_widgets())

    def _next_auto_number(self, prefix: str, names: list[str] | None = None) -> int:
        """自动编号：优先补上被删掉留下的最小空号，避免「删了再加数字一直涨」。"""
        used: set[int] = set()
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        source = names if names is not None else [
            item.title for item in self._command_widgets()
        ]
        for name in source:
            match = pattern.match((name or "").strip())
            if match:
                used.add(int(match.group(1)))
        index = 1
        while index in used:
            index += 1
        return index

    def add_command(
        self,
        kind: str = "fixed",
        content: str = "",
        title: str | None = None,
    ) -> CommandItem:
        """新增一条命令；名称留空时自动编号（补空号，不复用已占用的编号）。"""
        if kind == "slider":
            item = CommandItem("slider", title or f"滑块{self._next_auto_number('滑块')}", "")
        else:
            item = CommandItem("fixed", title or f"命令{self._next_auto_number('命令')}", content)
        item.send_requested.connect(self._on_command_send)
        item.remove_requested.connect(self._remove_command)
        item.edit_requested.connect(self._edit_command)
        item.groupRenameRequested.connect(self._rename_command_group)
        item.groupColorRequested.connect(self._set_command_group_color)
        self.cmd_layout.insertWidget(self.cmd_layout.indexOf(self.cmd_empty), item)
        self._update_command_hint()
        self._apply_group_styles()
        self._refresh_command_previews()
        return item

    def add_slider_group(
        self,
        count: int = 3,
        head_text: str = "",
        tail_text: str = "",
        group: str | None = None,
    ) -> None:
        """一次创建 N 个绑定到同一组的滑动条。"""
        if not group:
            existing = [
                item.group
                for item in self._command_widgets()
                if item.kind == "slider" and item.group
            ]
            group = f"组{self._next_auto_number('组', existing)}"
        for _ in range(count):
            item = self.add_command("slider")
            data = item.settings()
            data.update(
                {
                    "group": group,
                    "head_enabled": bool(head_text),
                    "head_text": head_text,
                    "tail_enabled": bool(tail_text),
                    "tail_text": tail_text,
                }
            )
            item.apply_settings(data)
        self._apply_group_styles()
        self._refresh_command_previews()
        self.statusBar().showMessage(f"已新增滑块组 {group}（{count} 个滑块）", 3000)

    def add_custom_group(self) -> None:
        """从 + 菜单自建滑动组：统一配置协议、CRC 与每个通道的数据类型。"""
        dialog = CustomGroupDialog(self._command_groups(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        cfg = dialog.values()
        group = cfg["group"] or f"组{self._next_auto_number('组', self._command_groups())}"
        for index, channel in enumerate(cfg["channels"]):
            item = self.add_command("slider")
            data = item.settings()
            data.update(
                {
                    "title": channel["title"],
                    "group": group,
                    "dtype": channel["dtype"],
                    "big_endian": cfg["big_endian"],
                    "vmin": channel["vmin"],
                    "vmax": channel["vmax"],
                    "step": max((channel["vmax"] - channel["vmin"]) / 100, 0.001),
                    "value": channel["vmin"],
                    "head_enabled": cfg["head_enabled"],
                    "head_text": cfg["head_text"],
                    "tail_enabled": cfg["tail_enabled"],
                    "tail_text": cfg["tail_text"],
                    "crc": cfg["crc"],
                }
            )
            # 整数类型的范围要在类型可表示范围内，避免 spin 被截断
            lo, hi = dtype_limits(channel["dtype"])
            data["vmin"] = max(data["vmin"], lo)
            data["vmax"] = min(data["vmax"], hi)
            if data["vmax"] <= data["vmin"]:
                data["vmin"], data["vmax"] = lo, hi
            item.apply_settings(data)
        self._apply_group_styles()
        self._refresh_command_previews()
        crc_label = CRC_MODES[cfg["crc"]][0] if cfg["crc"] in CRC_MODES else "无"
        self.statusBar().showMessage(
            f"已自建滑动组 {group}（{len(cfg['channels'])} 个滑块，CRC: {crc_label}）", 4000
        )

    def _edit_command(self, item: CommandItem) -> None:
        dialog = CommandDialog(
            item.settings(), self._command_groups(), self.hex_mode, self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        item.apply_settings(dialog.values())
        if item.kind == "slider" and item.group:
            for member in self._group_members(item):
                if member is item:
                    continue
                data = member.settings()
                data.update(
                    {
                        "head_enabled": item.head_enabled,
                        "head_text": item.head_text,
                        "tail_enabled": item.tail_enabled,
                        "tail_text": item.tail_text,
                        "crc": item.crc,
                    }
                )
                member.apply_settings(data)
        self._apply_group_styles()
        self._refresh_command_previews()

    def _rename_command_group(self, item: CommandItem, name: str) -> None:
        """双击组徽标改名：同组所有滑块一起换成新组名。"""
        old = item.group
        name = name.strip()
        if not name or name == old:
            return
        for member in self._group_members(item):
            member.group = name
            member.refresh()
        self._apply_group_styles()
        self._refresh_command_previews()
        self.statusBar().showMessage(f"滑块组 {old} 已重命名为 {name}", 2500)

    def _set_command_group_color(self, item: CommandItem, color: str) -> None:
        """右键组徽标换色：整组滑块统一换色，空字符串表示恢复自动配色。"""
        name = item.group
        if not name:
            return
        if color:
            self._group_colors[name] = color
        else:
            self._group_colors.pop(name, None)
        self._apply_group_styles()
        self.statusBar().showMessage(
            f"滑块组 {name} " + ("已恢复自动配色" if not color else "配色已更新"), 2000
        )

    def _remove_command(self, item: CommandItem) -> None:
        """删除命令；属于滑块组时整组一起删除。"""
        targets = (
            self._group_members(item)
            if item.kind == "slider" and item.group
            else [item]
        )
        for member in targets:
            member.setParent(None)
            member.deleteLater()
        self._update_command_hint()
        QTimer.singleShot(0, self._after_command_change)
        if len(targets) > 1:
            self.statusBar().showMessage(
                f"已删除滑块组 {item.group}（{len(targets)} 个滑块）", 2500
            )

    def _after_command_change(self) -> None:
        self._apply_group_styles()
        self._refresh_command_previews()

    def _on_command_send(self, item: CommandItem) -> None:
        payload = self._command_frame(item)
        if not payload:
            return
        self.send_payload(payload)
        self._refresh_command_previews()

    def _command_frame(self, item: CommandItem, silent: bool = False) -> bytes:
        """按“头帧 + 数据 + 尾帧”拼出一帧；滑动条按组一起打包。"""
        try:
            if item.kind == "fixed":
                body = self._encode_command_content(item.content, silent)
                if body is None:
                    return b""
                return (
                    item.head_bytes(self.encoding)
                    + body
                    + item.tail_bytes(self.encoding)
                )
            members = self._group_members(item)
            head = members[0].head_bytes(self.encoding)
            tail = members[0].tail_bytes(self.encoding)
            body = b"".join(member.pack_payload() for member in members)
            crc = crc_bytes(members[0].crc, head + body) if members[0].crc != "none" else b""
            return head + body + crc + tail
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "帧格式错误",
                    "头帧 / 尾帧或命令内容无法解析：请检查 hex: 写法的十六进制位数是否为偶数。",
                )
            return b""

    def _encode_command_content(self, text: str, silent: bool = False) -> bytes | None:
        if not text.strip():
            return b""
        stripped = text.strip()
        forced_hex = stripped.lower().startswith(("hex:", "x:"))
        try:
            if self.hex_mode or forced_hex:
                # Hex 模式也支持直接写文本：出现非十六进制字符时按文本编码发送
                return parse_frame_bytes(stripped, self.encoding)
            return text.encode(self.encoding, errors="replace")
        except ValueError:
            if not silent:
                QMessageBox.warning(
                    self,
                    "命令格式错误",
                    "hex: 前缀的十六进制位数需为偶数；普通内容可直接写 Hex（AA 55）或文本。",
                )
            return None

    def _refresh_command_previews(self) -> None:
        for item in self._command_widgets():
            item.set_preview(self._command_frame(item, silent=True).hex(" ").upper())
