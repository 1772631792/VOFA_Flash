"""模拟模式与 PID 闭环：波形生成、对象积分、参数与设定值联动。"""
from __future__ import annotations

import math
import random


from ..constants import DEMO_CHANNELS
from ..settings import save_setting


class SimulationMixin:
    def apply_sim_mode(self, index: int) -> None:
        modes = ("sine", "step", "pid")
        mode = modes[max(0, min(int(index), len(modes) - 1))]
        if mode == self.sim_mode:
            return
        self.sim_mode = mode
        save_setting("demo/mode", mode)
        self._sync_pid_group()
        if mode == "pid":
            self._pid_states = [self._new_pid_state(ch) for ch in range(DEMO_CHANNELS)]
        self._demo_last_step_ms = 0.0
        self.clear_plot()
        for target in self.pages:
            target.clear_data()
            target.refresh()
        self.statusBar().showMessage(
            {
                "sine": "模拟模式：正弦扫描",
                "step": "模拟模式：阶跃响应",
                "pid": "模拟模式：PID 响应",
            }[mode],
            2500,
        )

    def _sync_record_limit(self) -> None:
        limit = 0 if self.record_unlimited else int(self.buffer_spin.value())
        for page in self.pages:
            page.set_buffer_limit(limit)
        self.buffer_spin.setEnabled(not self.record_unlimited)

    def apply_record_mode(self, enabled: bool) -> None:
        self.record_unlimited = bool(enabled)
        if hasattr(self, "record_btn"):
            self.record_btn.blockSignals(True)
            self.record_btn.setChecked(self.record_unlimited)
            self.record_btn.blockSignals(False)
        self._sync_record_limit()
        self.statusBar().showMessage(
            "连续记录模式已开启：一直记录，关闭软件自动清除"
            if self.record_unlimited
            else "连续记录模式已关闭：恢复缓冲长度限制",
            3500,
        )

    def generate_demo_data(self) -> None:
        if self.sim_mode == "pid":
            self._sync_pid_gains()
        rate = self.demo_rate_combo.int_value()
        channels = DEMO_CHANNELS
        per_frame = rate / 30.0
        frames = int(per_frame) + (1 if self._demo_remainder_add(per_frame) else 0)
        if frames <= 0:
            return
        t0 = self.sample_index * self.dt_ms / 1000.0
        step = self.dt_ms / 1000.0
        for k in range(frames):
            t = t0 + k * step
            t_ms = (self.sample_index + k) * self.dt_ms
            if self.sim_mode != "pid" and t_ms % self._demo_step_period_ms < self.dt_ms:
                self._demo_last_step_ms = t_ms
            local_t = (t_ms - self._demo_last_step_ms) / 1000.0
            values = []
            for ch in range(channels):
                if self.sim_mode == "sine":
                    freq = 0.8 + ch * 0.5
                    phase = ch * 0.9
                    value = (
                        2.0 * math.sin(2 * math.pi * freq * t + phase)
                        + 0.18 * math.sin(2 * math.pi * 9.0 * t)
                        + ch * 0.6
                    )
                elif self.sim_mode == "pid":
                    # 真实闭环：每个采样点跑一步 PID + 对象积分
                    value = self._pid_step(step, ch)
                else:
                    value = self._demo_response(local_t, ch)
                # 微小随机噪声：模拟真实采样抖动，不依赖外部数据源
                value += random.gauss(0.0, 0.006)
                values.append(value)
            self.append_values(values, from_demo=True)

    @staticmethod
    def _new_pid_state(ch: int) -> dict:
        """二阶对象（质量-弹簧-阻尼）+ 离散 PID 的初始状态。

        二阶对象上 P 决定刚度、D 直接加阻尼，超调变化明显；
        三路对象阻尼略有差异，曲线不会重合。
        """
        return {
            "y": 0.0,
            "v": 0.0,
            "integral": 0.0,
            "d_filtered": 0.0,
            "u": 0.0,
            "c": 0.28 + ch * 0.08,  # 对象自然阻尼
            "k": 0.5,  # 对象自然刚度（无控制器时回到 0）
        }

    def _pid_step(self, dt: float, ch: int) -> float:
        """跑一步真实闭环：测量 → PID → 执行器限幅 → 二阶对象积分。"""
        state = self._pid_states[ch]
        kp, ki, kd = self._pid_gains
        error = self._pid_target - state["y"]

        # 测量值微分（对象速度），低通滤波抑制噪声放大
        alpha = dt / (dt + 0.012) if dt > 0 else 1.0
        state["d_filtered"] += alpha * (state["v"] - state["d_filtered"])

        state["integral"] += error * dt
        state["integral"] = max(-5.0, min(5.0, state["integral"]))

        u = kp * error + ki * state["integral"] - kd * state["d_filtered"]
        u_raw = u
        u = max(-8.0, min(8.0, u))
        # 反算抗饱和
        if u != u_raw and ki > 1e-6:
            state["integral"] += (u - u_raw) / ki
        state["u"] = u

        # 二阶对象：y'' = (u - c*y' - k*y) / m，半隐式欧拉积分
        accel = u - state["c"] * state["v"] - state["k"] * state["y"]
        state["v"] += accel * dt
        state["y"] += state["v"] * dt
        return state["y"]

    def _demo_response(self, t: float, ch: int) -> float:
        """阶跃 / PID 模拟：带超调与衰减振荡的二阶响应，便于直接测量性能指标。"""
        delay = 0.02 + ch * 0.01
        x = t - delay
        amp = 1.2 + ch * 0.45
        if x <= 0.0:
            return 0.0
        p_gain, i_gain, d_gain = self._pid_gains
        if self.sim_mode == "step":
            wn = 2 * math.pi * (1.6 + ch * 0.15)
            zeta = 0.42
        else:
            # 目标值即阶跃设定值；P 加快响应，D 增加阻尼，I 抑制稳态误差
            amp = self._pid_target * (1.0 + ch * 0.04)
            wn = 2 * math.pi * (1.4 + 0.9 * p_gain + ch * 0.15)
            zeta = max(0.12, min(0.95, 0.34 + 0.16 * d_gain - 0.06 * i_gain))
            amp *= 1.0 / (1.0 + 0.12 * i_gain)
        wd = wn * math.sqrt(1.0 - zeta * zeta)
        response = 1.0 - math.exp(-zeta * wn * x) * (
            math.cos(wd * x) + (zeta * wn / wd) * math.sin(wd * x)
        )
        return amp * response + 0.012 * math.sin(2 * math.pi * 12.0 * x + ch)

    def _demo_remainder_add(self, per_frame: float) -> bool:
        self._demo_acc = getattr(self, "_demo_acc", 0.0) + (per_frame - int(per_frame))
        if self._demo_acc >= 1.0:
            self._demo_acc -= 1.0
            return True
        return False

    def _sync_pid_group(self) -> None:
        """PID 滑块组只在「模拟模式 + PID 响应」时存在，其它情况自动移除。"""
        wanted = self.interface_name == "模拟模式" and self.sim_mode == "pid"
        members = [
            item
            for item in self._command_widgets()
            if item.kind == "slider" and item.group == self._pid_group
        ]
        if not wanted:
            for item in members:
                item.setParent(None)
                item.deleteLater()
            if members:
                self._update_command_hint()
                self._apply_group_styles()
                self._refresh_command_previews()
            return
        if members:
            return
        self.add_slider_group(
            count=4,
            head_text="text:S",
            tail_text="text:E",
            group=self._pid_group,
        )
        members = [
            item
            for item in self._command_widgets()
            if item.kind == "slider" and item.group == self._pid_group
        ]
        specs = (
            ("目标", self._pid_target, 0.0, 10.0),
            ("P", self._pid_gains[0], 0.0, 3.0),
            ("I", self._pid_gains[1], 0.0, 5.0),
            ("D", self._pid_gains[2], 0.0, 2.0),
        )
        for item, (title, value, vmin, vmax) in zip(members[-4:], specs):
            data = item.settings()
            data.update(
                {
                    "title": title,
                    "dtype": "float32",
                    "vmin": vmin,
                    "vmax": vmax,
                    "step": 0.01,
                    "decimals": 3,
                    "value": value,
                }
            )
            item.apply_settings(data)
        self._apply_group_styles()
        self._refresh_command_previews()

    def _sync_pid_gains(self) -> None:
        """每帧从 PID 组读取 P/I/D，让拖动滑块直接改变模拟曲线。"""
        members = [
            item
            for item in self._command_widgets()
            if item.kind == "slider" and item.group == self._pid_group
        ]
        if len(members) < 4:
            return
        values: dict[str, float] = {}
        for item in members:
            key = item.title.strip()
            if key in ("目标", "P", "I", "D"):
                values[key] = item.numeric_value()
        if len(values) < 4:
            return
        # 只更新参数与设定值，绝不重置对象状态：真实对象的位置/速度不会瞬间归零，
        # 曲线必须从当前值连续过渡到新目标。
        self._pid_gains = (values["P"], values["I"], values["D"])
        self._pid_target = values["目标"]
