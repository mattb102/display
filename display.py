#!/usr/bin/env python3
import atexit
import copy
import os
import re
import subprocess
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path

CANVAS_W = 700
CANVAS_H = 380
PAD = 30
SNAP = 120  # real-pixel threshold for edge snapping
COLORS = ["#5b9bd5", "#ed7d31", "#a9d18e", "#ffc000", "#9b59b6"]
LOCK_FILE = Path("/tmp/display-gui.lock")


@dataclass
class Monitor:
    name: str
    width: int
    height: int
    x: int
    y: int
    canvas_x: float = 0.0
    canvas_y: float = 0.0
    rect_id: int = 0
    text_id: int = 0


def parse_xrandr() -> list[Monitor]:
    result = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, check=True)
    monitors = []
    pattern = re.compile(
        r"^(\S+)\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(-?\d+)\+(-?\d+)"
    )
    for line in result.stdout.splitlines():
        m = pattern.match(line)
        if m:
            monitors.append(Monitor(
                name=m.group(1),
                width=int(m.group(2)),
                height=int(m.group(3)),
                x=int(m.group(4)),
                y=int(m.group(5)),
            ))
    return monitors


def build_xrandr_cmd(monitors: list[Monitor]) -> list[str]:
    cmd = ["xrandr"]
    for m in monitors:
        cmd += ["--output", m.name, "--mode", f"{m.width}x{m.height}", "--pos", f"{m.x}x{m.y}"]
    return cmd


def normalize(monitors: list[Monitor]):
    if not monitors:
        return
    min_x = min(m.x for m in monitors)
    min_y = min(m.y for m in monitors)
    for m in monitors:
        m.x -= min_x
        m.y -= min_y


def snap_edges(dragged: Monitor, others: list[Monitor]):
    """Snap dragged monitor's edges to nearby edges of other monitors."""
    for other in others:
        # --- Horizontal (x) snapping: find closest vertical edge pair ---
        best_dx, best_dist = 0, SNAP
        for d_edge, o_edge in [
            (dragged.x, other.x + other.width),                    # left  → right
            (dragged.x + dragged.width, other.x),                  # right → left
            (dragged.x, other.x),                                  # left  → left
            (dragged.x + dragged.width, other.x + other.width),    # right → right
            (dragged.x + dragged.width // 2, other.x + other.width // 2),  # center → center
        ]:
            dist = abs(d_edge - o_edge)
            if dist < best_dist:
                best_dist = dist
                best_dx = o_edge - d_edge
        dragged.x += best_dx

        # --- Vertical (y) snapping: find closest horizontal edge pair ---
        best_dy, best_dist = 0, SNAP
        for d_edge, o_edge in [
            (dragged.y, other.y + other.height),                    # top    → bottom
            (dragged.y + dragged.height, other.y),                  # bottom → top
            (dragged.y, other.y),                                   # top    → top
            (dragged.y + dragged.height, other.y + other.height),   # bottom → bottom
            (dragged.y + dragged.height // 2, other.y + other.height // 2),  # center → center
        ]:
            dist = abs(d_edge - o_edge)
            if dist < best_dist:
                best_dist = dist
                best_dy = o_edge - d_edge
        dragged.y += best_dy

    # Push dragged out of any overlap with other monitors
    for other in others:
        resolve_overlap(dragged, other)


def resolve_overlap(a: Monitor, b: Monitor):
    """If a and b overlap, push a out by the shortest escape distance."""
    # How far a penetrates into b on each axis
    overlap_x = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
    overlap_y = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
    if overlap_x <= 0 or overlap_y <= 0:
        return  # no overlap

    # Push out along the axis with the smaller overlap (shortest escape)
    if overlap_x <= overlap_y:
        # Push left or right
        if a.x + a.width // 2 < b.x + b.width // 2:
            a.x = b.x - a.width   # push left
        else:
            a.x = b.x + b.width   # push right
    else:
        # Push up or down
        if a.y + a.height // 2 < b.y + b.height // 2:
            a.y = b.y - a.height  # push up
        else:
            a.y = b.y + b.height  # push down


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Display Positions")
        self.resizable(False, False)

        LOCK_FILE.write_text(str(os.getpid()))
        atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))

        self.monitors: list[Monitor] = []
        self.scale = 1.0
        self._origin_x = 0
        self._origin_y = 0
        self._drag_monitor: Monitor | None = None
        self._drag_start_x = 0
        self._drag_start_y = 0

        self.canvas = tk.Canvas(self, width=CANVAS_W, height=CANVAS_H, bg="#2b2b2b")
        self.canvas.pack()

        preview_frame = tk.Frame(self, bg="#1e1e1e", pady=4)
        preview_frame.pack(fill=tk.X)
        self.preview_var = tk.StringVar(value="")
        tk.Label(
            preview_frame, textvariable=self.preview_var,
            font=("Monospace", 9), fg="#aaaaaa", bg="#1e1e1e",
            anchor="w", justify="left", wraplength=CANVAS_W - 10, padx=6
        ).pack(fill=tk.X)

        btn_frame = tk.Frame(self, bg="#1e1e1e", pady=6)
        btn_frame.pack(fill=tk.X)
        tk.Button(btn_frame, text="Refresh", command=self.refresh, width=10).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Close", command=self.destroy, width=10).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Apply", command=self.apply, width=10).pack(side=tk.RIGHT, padx=10)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        self.load()

    def destroy(self):
        LOCK_FILE.unlink(missing_ok=True)
        super().destroy()

    def load(self):
        self.monitors = parse_xrandr()
        if not self.monitors:
            self.preview_var.set("No active monitors detected.")
            return
        self._compute_scale()
        self.draw()
        self.update_preview()

    def _compute_scale(self):
        if not self.monitors:
            self.scale = 1.0
            return
        vw = max(m.x + m.width for m in self.monitors) - min(m.x for m in self.monitors)
        vh = max(m.y + m.height for m in self.monitors) - min(m.y for m in self.monitors)
        vw = max(vw, 1)
        vh = max(vh, 1)
        self.scale = min(
            (CANVAS_W - 2 * PAD) / vw,
            (CANVAS_H - 2 * PAD) / vh,
            0.4,
        )
        self._origin_x = min(m.x for m in self.monitors)
        self._origin_y = min(m.y for m in self.monitors)
        for m in self.monitors:
            m.canvas_x = PAD + (m.x - self._origin_x) * self.scale
            m.canvas_y = PAD + (m.y - self._origin_y) * self.scale

    def draw(self):
        self.canvas.delete("all")
        for i, m in enumerate(self.monitors):
            color = COLORS[i % len(COLORS)]
            cw = m.width * self.scale
            ch = m.height * self.scale
            x1, y1 = m.canvas_x, m.canvas_y
            x2, y2 = x1 + cw, y1 + ch
            m.rect_id = self.canvas.create_rectangle(
                x1, y1, x2, y2,
                fill=color, outline="white", width=2,
                tags=(m.name, "monitor")
            )
            m.text_id = self.canvas.create_text(
                (x1 + x2) / 2, (y1 + y2) / 2,
                text=f"{m.name}\n{m.width}x{m.height}",
                fill="white", font=("Sans", 9, "bold"),
                tags=(m.name, "monitor")
            )

    def update_preview(self):
        if not self.monitors:
            return
        preview_monitors = copy.deepcopy(self.monitors)
        normalize(preview_monitors)
        cmd = build_xrandr_cmd(preview_monitors)
        parts = []
        i = 0
        while i < len(cmd):
            if cmd[i] == "--output":
                parts.append(f"\n  --output {cmd[i+1]}")
                i += 2
            elif cmd[i] == "--mode":
                parts[-1] += f" --mode {cmd[i+1]}"
                i += 2
            elif cmd[i] == "--pos":
                parts[-1] += f" --pos {cmd[i+1]}"
                i += 2
            else:
                parts.append(cmd[i])
                i += 1
        self.preview_var.set("xrandr" + "".join(parts))

    def on_press(self, event):
        monitor_names = {m.name for m in self.monitors}
        items = self.canvas.find_overlapping(event.x - 1, event.y - 1, event.x + 1, event.y + 1)
        for item in reversed(items):
            tags = set(self.canvas.gettags(item))
            name = next((t for t in tags if t in monitor_names), None)
            if name:
                self._drag_monitor = next(m for m in self.monitors if m.name == name)
                self._drag_start_x = event.x
                self._drag_start_y = event.y
                return

    def on_drag(self, event):
        if self._drag_monitor is None:
            return
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        self.canvas.move(self._drag_monitor.name, dx, dy)
        self._drag_monitor.canvas_x += dx
        self._drag_monitor.canvas_y += dy
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def on_release(self, event):
        if self._drag_monitor is None:
            return
        dragged = self._drag_monitor
        self._drag_monitor = None

        # Convert canvas position back to real coords using the correct origin
        dragged.x = round((dragged.canvas_x - PAD) / self.scale + self._origin_x)
        dragged.y = round((dragged.canvas_y - PAD) / self.scale + self._origin_y)

        # Snap to nearby edges of other monitors
        others = [m for m in self.monitors if m is not dragged]
        snap_edges(dragged, others)

        # Redraw from real coords
        self._compute_scale()
        self.draw()
        self.update_preview()

    def refresh(self):
        self.load()

    def apply(self):
        if not self.monitors:
            return
        apply_monitors = copy.deepcopy(self.monitors)
        normalize(apply_monitors)
        cmd = build_xrandr_cmd(apply_monitors)
        try:
            subprocess.run(cmd, check=True)
            # Re-apply wallpaper if a hook script exists
            hook = os.path.expanduser("~/.config/display/post-apply")
            if os.path.isfile(hook) and os.access(hook, os.X_OK):
                subprocess.run([hook])
        except subprocess.CalledProcessError as e:
            self.preview_var.set(f"Error: {e}")
            return
        self.load()


if __name__ == "__main__":
    App().mainloop()
