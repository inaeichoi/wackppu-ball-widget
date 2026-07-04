from __future__ import annotations

import ctypes
import io
import json
import math
import os
import random
import struct
import sys
import threading
import time
import wave
from collections import deque
from pathlib import Path
from tkinter import Menu, TclError
import tkinter as tk

try:
    from PIL import Image, ImageTk
except Exception:  # pragma: no cover - optional runtime fallback
    Image = None
    ImageTk = None

if sys.platform == "win32":
    import winsound
else:  # pragma: no cover - the widget is intended for Windows
    winsound = None


APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
RUNTIME_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_DIR
ASSET_PATH = APP_DIR / "assets" / "wakppu-ball.png"
SOUND_SOURCE_PATHS = (
    RUNTIME_DIR / "assets" / "sounds" / "wakppu-asmr-source.mp3",
    APP_DIR / "assets" / "sounds" / "wakppu-asmr-source.mp3",
)
STATE_PATH = Path(os.environ.get("APPDATA", str(RUNTIME_DIR))) / "WackppuBallWidget" / "widget-state.json"

TRANSPARENT_COLOR = "#07111f"
WINDOW_SIZE = 178
BALL_SIZE = 128
POLL_MS = 22
FRAME_MS = 16
CRACK_SOUND_STEPS = (0.25, 0.55, 0.82)
MIN_KEYS_TO_BREAK = 19.0
MAX_KEYS_TO_BREAK = 21.0
MP3_VOLUME = 360
MP3_SEGMENTS = {
    "rub": ((0.18, 1050), (0.42, 1050), (0.66, 1050)),
    "crunch": ((0.24, 1180), (0.48, 1180), (0.72, 1180)),
    "break": ((0.34, 1420), (0.56, 1420), (0.78, 1420)),
}


class GlobalTypingMonitor:
    """Counts key-down transitions only; it never reads typed characters."""

    COUNTED_KEYS = (
        [0x08, 0x09, 0x0D, 0x20]
        + list(range(0x30, 0x5B))
        + list(range(0x60, 0x70))
        + list(range(0xBA, 0xE0))
    )

    def __init__(self) -> None:
        self.available = sys.platform == "win32"
        self._pressed: set[int] = set()
        self._user32 = ctypes.windll.user32 if self.available else None

    def poll(self) -> int:
        if not self.available:
            return 0

        hits = 0
        for vk in self.COUNTED_KEYS:
            is_down = bool(self._user32.GetAsyncKeyState(vk) & 0x8000)
            was_down = vk in self._pressed

            if is_down and not was_down:
                self._pressed.add(vk)
                hits += 1
            elif not is_down and was_down:
                self._pressed.remove(vk)

        return hits


class CrackSound:
    def __init__(self) -> None:
        self._source_path = self._find_source_path()
        self._source_ms = self._probe_mp3_length_ms() if self._can_play_mp3() else 0
        self._segment_index = {"rub": 0, "crunch": 0, "break": 0}
        self._play_lock = threading.Lock()
        self._active_until = 0.0
        self._sounds = {
            "rub": self._build_wav("rub"),
            "crunch": self._build_wav("crunch"),
            "break": self._build_wav("break"),
        }

    def play(self, name: str = "break") -> None:
        if self._source_ms > 900:
            segment = self._next_mp3_segment(name)
            if segment is None:
                return

            start, end = segment
            thread = threading.Thread(target=self._play_mp3_sync, args=(start, end, name), daemon=True)
            thread.start()
            return

        data = self._sounds.get(name, self._sounds["break"])
        thread = threading.Thread(target=self._play_sync, args=(data,), daemon=True)
        thread.start()

    def _can_play_mp3(self) -> bool:
        return sys.platform == "win32" and self._source_path.exists()

    @staticmethod
    def _find_source_path() -> Path:
        for path in SOUND_SOURCE_PATHS:
            if path.exists():
                return path
        return SOUND_SOURCE_PATHS[0]

    def _probe_mp3_length_ms(self) -> int:
        alias = f"probe_{random.randrange(1_000_000_000)}"
        buffer = ctypes.create_unicode_buffer(256)
        if self._mci(f'open "{self._source_path}" type mpegvideo alias {alias}') != 0:
            return 0

        try:
            self._mci(f"set {alias} time format milliseconds")
            if self._mci(f"status {alias} length", buffer) != 0:
                return 0
            return max(0, int(float(buffer.value)))
        except ValueError:
            return 0
        finally:
            self._mci(f"close {alias}")

    def _next_mp3_segment(self, name: str) -> tuple[int, int] | None:
        now = time.monotonic()
        with self._play_lock:
            if name != "break" and now < self._active_until:
                return None

            candidates = MP3_SEGMENTS.get(name, MP3_SEGMENTS["crunch"])
            index = self._segment_index.get(name, 0)
            ratio, duration_ms = candidates[index % len(candidates)]
            self._segment_index[name] = index + 1

            center = int(self._source_ms * ratio)
            start = max(0, center - duration_ms // 2)
            end = min(self._source_ms, start + duration_ms)
            start = max(0, end - duration_ms)

            self._active_until = now + max(0.05, (end - start) / 1000.0)

        return start, end

    def _play_mp3_sync(self, start_ms: int, end_ms: int, name: str) -> None:
        alias = f"wakppu_{name}_{random.randrange(1_000_000_000)}"
        if self._mci(f'open "{self._source_path}" type mpegvideo alias {alias}') != 0:
            self._play_sync(self._sounds.get(name, self._sounds["break"]))
            return

        try:
            self._mci(f"set {alias} time format milliseconds")
            self._mci(f"setaudio {alias} volume to {MP3_VOLUME}")
            self._mci(f"seek {alias} to {start_ms}")
            self._mci(f"play {alias} from {start_ms} to {end_ms} wait")
        finally:
            self._mci(f"close {alias}")
            with self._play_lock:
                self._active_until = min(self._active_until, time.monotonic() + 0.02)

    @staticmethod
    def _mci(command: str, buffer: ctypes.Array[ctypes.c_wchar] | None = None) -> int:
        if winsound is None:
            return 1

        return ctypes.windll.winmm.mciSendStringW(command, buffer, 0 if buffer is None else len(buffer), None)

    def _play_sync(self, data: bytes) -> None:
        if winsound is None:
            return

        try:
            winsound.PlaySound(data, winsound.SND_MEMORY)
        except RuntimeError:
            try:
                winsound.Beep(480, 24)
                winsound.Beep(360, 28)
            except RuntimeError:
                pass

    @staticmethod
    def _build_wav(name: str) -> bytes:
        sample_rate = 44100
        if name == "rub":
            duration = 0.075
            volume = 1200
            chunks = ((0.006, 0.50, 260.0, 72.0), (0.034, 0.32, 410.0, 84.0))
        elif name == "crunch":
            duration = 0.13
            volume = 2500
            chunks = (
                (0.006, 0.76, 220.0, 64.0),
                (0.030, 0.68, 360.0, 72.0),
                (0.060, 0.52, 510.0, 78.0),
                (0.092, 0.36, 300.0, 88.0),
            )
        else:
            duration = 0.21
            volume = 3200
            chunks = (
                (0.004, 0.82, 190.0, 52.0),
                (0.028, 0.88, 280.0, 58.0),
                (0.057, 0.74, 430.0, 68.0),
                (0.096, 0.56, 330.0, 72.0),
                (0.138, 0.42, 240.0, 84.0),
            )

        rng = random.Random(9173 + sum(ord(char) for char in name))
        frames = bytearray()
        low = 0.0
        band = 0.0

        for index in range(int(sample_rate * duration)):
            t = index / sample_rate
            noise = rng.uniform(-1.0, 1.0)
            low = low * 0.94 + noise * 0.06
            band = band * 0.50 + (noise - low) * 0.50
            value = 0.0

            for center, amp, pitch, decay in chunks:
                if t < center:
                    pre = math.exp(-((center - t) * 180.0) ** 2) * 0.10
                    value += band * amp * pre
                    continue

                dt = t - center
                env = math.exp(-dt * decay)
                body = (
                    math.sin(2 * math.pi * pitch * dt)
                    + 0.42 * math.sin(2 * math.pi * pitch * 1.7 * dt + 0.8)
                    + 0.24 * math.sin(2 * math.pi * pitch * 2.35 * dt + 1.7)
                )
                snap = math.tanh(body * 1.35 + band * 1.05)
                value += amp * env * (snap * 0.72 + low * 0.18)

            attack = min(1.0, t / 0.012)
            release = min(1.0, max(0.0, (duration - t) / 0.045))
            envelope = attack * release
            value *= envelope
            value = max(-1.0, min(1.0, value))
            frames.extend(struct.pack("<h", int(value * volume)))

        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(frames))
        return output.getvalue()


class WakppuWidget:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Wakppu Ball")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)

        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
        except TclError:
            pass

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_SIZE,
            height=WINDOW_SIZE,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.monitor = GlobalTypingMonitor()
        self.sound = CrackSound()
        self.key_times: deque[float] = deque()
        self.max_durability = 1.0
        self.durability = 1.0
        self.crack_progress = 0.0
        self.crack_sound_index = 0
        self.last_texture_sound_at = 0.0
        self.crack_paths: list[dict[str, object]] = []
        self.impact = 0.0
        self.breaking = False
        self.break_start = 0.0
        self.refill_start = time.monotonic()
        self.pieces: list[dict[str, float | str]] = []
        self.drag_origin: tuple[int, int] | None = None
        self.photo_cache: dict[int, tk.PhotoImage] = {}
        self.current_photo: tk.PhotoImage | None = None
        self.base_photo: tk.PhotoImage | None = None
        self.base_image = self._load_ball_image()
        self._reset_ball(self.refill_start)

        self._place_window()
        self._install_drag()
        self._install_menu()
        self._apply_toolwindow_hint()
        self._schedule_poll()
        self._draw_loop()

    def run(self) -> None:
        self.root.mainloop()

    def _load_ball_image(self):
        if not ASSET_PATH.exists():
            raise FileNotFoundError(f"Missing asset: {ASSET_PATH}")

        if Image is not None and ImageTk is not None:
            image = Image.open(ASSET_PATH).convert("RGBA")
            bbox = image.getbbox()
            if bbox:
                image = image.crop(bbox)
            return self._hard_alpha_for_keyed_window(image)

        source = tk.PhotoImage(file=str(ASSET_PATH))
        factor = max(1, round(max(source.width(), source.height()) / BALL_SIZE))
        self.base_photo = source.subsample(factor, factor)
        return None

    def _place_window(self) -> None:
        saved = self._load_position()
        if saved:
            x, y = saved
        else:
            self.root.update_idletasks()
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            x = max(16, screen_w - WINDOW_SIZE - 96)
            y = max(16, int(screen_h * 0.35))

        self.root.geometry(f"{WINDOW_SIZE}x{WINDOW_SIZE}+{x}+{y}")

    def _install_drag(self) -> None:
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._end_drag)

    def _install_menu(self) -> None:
        menu = Menu(self.root, tearoff=False)
        menu.add_command(label="Quit", command=self._quit)
        self.canvas.bind("<Button-3>", lambda event: menu.tk_popup(event.x_root, event.y_root))
        self.root.bind("<Control-Shift-Q>", lambda _event: self._quit())

    def _apply_toolwindow_hint(self) -> None:
        if sys.platform != "win32":
            return

        try:
            hwnd = self.root.winfo_id()
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_toolwindow = 0x00000080
            ws_ex_appwindow = 0x00040000

            get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_window_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = get_window_long(hwnd, gwl_exstyle)
            style = (style | ws_ex_toolwindow) & ~ws_ex_appwindow
            set_window_long(hwnd, gwl_exstyle, style)
        except Exception:
            pass

    def _schedule_poll(self) -> None:
        hits = self.monitor.poll()
        if hits and not self.breaking:
            now = time.monotonic()
            for _ in range(hits):
                self._on_key_hit(now)

        self.root.after(POLL_MS, self._schedule_poll)

    def _on_key_hit(self, now: float) -> None:
        self.key_times.append(now)
        while self.key_times and now - self.key_times[0] > 1.45:
            self.key_times.popleft()

        keys_per_second = len(self.key_times) / 1.45
        damage = 1.0 + min(0.18, keys_per_second * 0.02)
        self.durability -= damage
        previous_progress = self.crack_progress
        self.crack_progress = min(1.0, 1.0 - self.durability / self.max_durability)
        self.impact = min(0.34, self.impact + 0.052 + keys_per_second * 0.005)
        self._maybe_play_texture_sound(now, previous_progress)

        if self.durability <= 0:
            self._break_ball()

    def _maybe_play_texture_sound(self, now: float, previous_progress: float) -> None:
        milestone_hit = False
        while self.crack_sound_index < len(CRACK_SOUND_STEPS):
            if self.crack_progress < CRACK_SOUND_STEPS[self.crack_sound_index]:
                break
            self.crack_sound_index += 1
            milestone_hit = True

        min_gap = 1.05
        if milestone_hit and now - self.last_texture_sound_at > 0.62:
            self.sound.play("crunch")
            self.last_texture_sound_at = now
            return

        if previous_progress > self.crack_progress:
            return

        if now - self.last_texture_sound_at >= min_gap:
            self.sound.play("rub" if self.crack_progress < 0.58 else "crunch")
            self.last_texture_sound_at = now

    def _break_ball(self) -> None:
        if self.breaking:
            return

        self.breaking = True
        self.break_start = time.monotonic()
        self.pieces = self._make_pieces()
        self.sound.play("break")

    def _make_pieces(self) -> list[dict[str, float | str]]:
        rng = random.Random(time.monotonic_ns())
        palette = ["#ff7568", "#ffd98d", "#f4f1c3", "#b8e1be", "#d7b4e8", "#f99aa8"]
        pieces: list[dict[str, float | str]] = []

        for _ in range(22):
            angle = rng.uniform(0, math.tau)
            radius = rng.uniform(4, BALL_SIZE * 0.34)
            speed = rng.uniform(110, 270)
            size = rng.uniform(7, 17)
            pieces.append(
                {
                    "x": WINDOW_SIZE / 2 + math.cos(angle) * radius,
                    "y": WINDOW_SIZE / 2 + math.sin(angle) * radius,
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed - rng.uniform(20, 90),
                    "size": size,
                    "spin": rng.uniform(-7.0, 7.0),
                    "color": rng.choice(palette),
                }
            )

        return pieces

    def _draw_loop(self) -> None:
        self.canvas.delete("all")
        now = time.monotonic()

        if self.breaking:
            self._draw_break(now)
        else:
            self._draw_ball(now)

        self.root.after(FRAME_MS, self._draw_loop)

    def _draw_ball(self, now: float) -> None:
        elapsed = max(0.0, now - self.refill_start)
        spawn_scale = min(1.0, elapsed / 0.18)
        pop = math.sin(spawn_scale * math.pi) * 0.08 if spawn_scale < 1.0 else 0.0
        float_y = math.sin(now * 2.0) * 2.2

        self.impact *= 0.78
        shake_x = math.sin(now * 68.0) * self.impact * 1.55
        shake_y = math.cos(now * 61.0) * self.impact * 1.05
        scale = max(0.08, spawn_scale) * (1.0 + pop + self.impact * 0.012)
        size = max(4, int(BALL_SIZE * scale))

        photo = self._photo_for_size(size)
        self.current_photo = photo
        self.canvas.create_image(
            WINDOW_SIZE / 2 + shake_x,
            WINDOW_SIZE / 2 + float_y + shake_y,
            image=photo,
            anchor="center",
        )
        if spawn_scale > 0.92:
            self._draw_cracks(
                WINDOW_SIZE / 2 + shake_x,
                WINDOW_SIZE / 2 + float_y + shake_y,
                size,
                self.crack_progress,
            )

    def _draw_cracks(self, cx: float, cy: float, size: int, progress: float) -> None:
        if progress < 0.04:
            return

        radius = size * 0.47
        for path in self.crack_paths:
            threshold = float(path["threshold"])
            if progress < threshold:
                continue

            reveal = min(1.0, (progress - threshold) / 0.18)
            points = path["points"]
            scaled = [(cx + x * radius, cy + y * radius) for x, y in points]  # type: ignore[misc]
            partial = self._partial_polyline(scaled, reveal)
            if len(partial) < 2:
                continue

            flat = [coord for point in partial for coord in point]
            width = max(1, int(float(path["width"]) * max(0.7, size / BALL_SIZE)))
            self.canvas.create_line(
                flat,
                fill="#ffe8c6",
                width=width + 1,
                smooth=True,
                capstyle="round",
                joinstyle="round",
            )
            self.canvas.create_line(
                flat,
                fill="#9e6a66",
                width=width,
                smooth=True,
                capstyle="round",
                joinstyle="round",
            )

    @staticmethod
    def _partial_polyline(points: list[tuple[float, float]], reveal: float) -> list[tuple[float, float]]:
        if reveal >= 1.0:
            return points

        lengths = [
            math.dist(points[index - 1], points[index])
            for index in range(1, len(points))
        ]
        target = sum(lengths) * reveal
        walked = 0.0
        partial = [points[0]]

        for index, segment_length in enumerate(lengths, start=1):
            if walked + segment_length <= target:
                partial.append(points[index])
                walked += segment_length
                continue

            if segment_length <= 0:
                break
            ratio = (target - walked) / segment_length
            x0, y0 = points[index - 1]
            x1, y1 = points[index]
            partial.append((x0 + (x1 - x0) * ratio, y0 + (y1 - y0) * ratio))
            break

        return partial

    def _draw_break(self, now: float) -> None:
        t = now - self.break_start
        progress = min(1.0, t / 0.46)

        for piece in self.pieces:
            x = float(piece["x"]) + float(piece["vx"]) * t
            y = float(piece["y"]) + float(piece["vy"]) * t + 380 * t * t
            size = float(piece["size"]) * (1.0 - progress * 0.38)
            color = str(piece["color"])
            angle = float(piece["spin"]) * t
            self._draw_piece(x, y, size, angle, color)

        if progress >= 1.0:
            self.breaking = False
            self.key_times.clear()
            self.impact = 0.0
            self._reset_ball(now)

    def _draw_piece(self, x: float, y: float, size: float, angle: float, color: str) -> None:
        points = []
        for offset in (0, 2.25, 4.25):
            px = x + math.cos(angle + offset) * size
            py = y + math.sin(angle + offset) * size
            points.extend([px, py])
        self.canvas.create_polygon(points, fill=color, outline="")

    def _photo_for_size(self, size: int) -> tk.PhotoImage:
        size = max(4, min(WINDOW_SIZE, size))
        if size in self.photo_cache:
            return self.photo_cache[size]

        if self.base_image is not None and Image is not None and ImageTk is not None:
            resized = self.base_image.resize((size, size), Image.Resampling.LANCZOS)
            resized = self._hard_alpha_for_keyed_window(resized)
            photo = ImageTk.PhotoImage(resized)
        else:
            photo = self.base_photo

        self.photo_cache[size] = photo
        if len(self.photo_cache) > 36:
            oldest = next(iter(self.photo_cache))
            self.photo_cache.pop(oldest, None)
        return photo

    @staticmethod
    def _hard_alpha_for_keyed_window(image):
        red, green, blue, alpha = image.split()
        alpha = alpha.point(lambda value: 255 if value >= 118 else 0)
        return Image.merge("RGBA", (red, green, blue, alpha))

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if not self.drag_origin:
            return

        dx, dy = self.drag_origin
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _end_drag(self, _event: tk.Event) -> None:
        self.drag_origin = None
        self._save_position()

    def _save_position(self) -> None:
        data = {"x": self.root.winfo_x(), "y": self.root.winfo_y()}
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _load_position(self) -> tuple[int, int] | None:
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            x = int(data["x"])
            y = int(data["y"])
            return x, y
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _quit(self) -> None:
        self._save_position()
        self.root.destroy()

    @staticmethod
    def _new_durability() -> float:
        return random.uniform(MIN_KEYS_TO_BREAK, MAX_KEYS_TO_BREAK)

    def _reset_ball(self, now: float | None = None) -> None:
        self.max_durability = self._new_durability()
        self.durability = self.max_durability
        self.crack_progress = 0.0
        self.crack_sound_index = 0
        self.last_texture_sound_at = 0.0
        self.crack_paths = self._make_crack_paths()
        self.refill_start = time.monotonic() if now is None else now

    def _make_crack_paths(self) -> list[dict[str, object]]:
        rng = random.Random(time.monotonic_ns())
        paths: list[dict[str, object]] = []

        for index in range(13):
            threshold = 0.07 + index * 0.065 + rng.uniform(0.0, 0.035)
            origin_angle = rng.uniform(0, math.tau)
            origin_radius = rng.uniform(0.05, 0.30)
            direction = origin_angle + rng.uniform(-0.65, 0.65)
            points: list[tuple[float, float]] = [
                (math.cos(origin_angle) * origin_radius, math.sin(origin_angle) * origin_radius)
            ]

            for step in range(rng.randint(3, 6)):
                last_x, last_y = points[-1]
                direction += rng.uniform(-0.55, 0.55)
                segment = rng.uniform(0.06, 0.105) * (1.0 - step * 0.045)
                next_x = last_x + math.cos(direction) * segment
                next_y = last_y + math.sin(direction) * segment

                distance = math.hypot(next_x, next_y)
                if distance > 0.43:
                    scale = 0.43 / distance
                    next_x *= scale
                    next_y *= scale
                    points.append((next_x, next_y))
                    break

                points.append((next_x, next_y))

            paths.append(
                {
                    "threshold": min(0.95, threshold),
                    "points": points,
                    "width": rng.uniform(1.15, 2.25),
                }
            )

        return paths


def self_test() -> None:
    if not ASSET_PATH.exists():
        raise SystemExit(f"Missing asset: {ASSET_PATH}")

    sound = CrackSound()
    if sound._source_path.exists() and sys.platform == "win32" and sound._source_ms <= 900:
        raise SystemExit("MP3 sound source exists but could not be read by Windows MCI")

    if any(len(data) < 1000 for data in sound._sounds.values()):
        raise SystemExit("Crack sound failed to build")

    monitor = GlobalTypingMonitor()
    if sys.platform == "win32" and not monitor.available:
        raise SystemExit("Global key monitor unavailable on Windows")

    print("self-test ok")


def sound_test() -> None:
    sound = CrackSound()
    if sound._source_ms <= 900:
        print("MP3 source was not available; playing fallback generated sounds.")
    else:
        print(f"Playing fixed MP3 segments from {sound._source_path.name}.")

    for name in ("crunch", "crunch", "break"):
        print(f"play {name}")
        sound.play(name)
        time.sleep(1.55)


def sound_scan() -> None:
    sound = CrackSound()
    if sound._source_ms <= 900:
        print("MP3 source was not available.")
        return

    ratios = (0.08, 0.16, 0.24, 0.32, 0.40, 0.48, 0.56, 0.64, 0.72, 0.80, 0.88)
    duration_ms = 640
    print(f"Scanning {sound._source_path.name}. Tell Codex the best candidate number.")
    for index, ratio in enumerate(ratios, start=1):
        center = int(sound._source_ms * ratio)
        start = max(0, center - duration_ms // 2)
        end = min(sound._source_ms, start + duration_ms)
        print(f"candidate {index}: {start / 1000:.2f}s - {end / 1000:.2f}s")
        sound._play_mp3_sync(start, end, f"scan{index}")
        time.sleep(0.35)


def main() -> None:
    if "--self-test" in sys.argv:
        self_test()
        return

    if "--sound-test" in sys.argv:
        sound_test()
        return

    if "--sound-scan" in sys.argv:
        sound_scan()
        return

    if os.name != "nt":
        print("Wakppu Ball is designed for Windows global typing detection.")

    app = WakppuWidget()
    app.run()


if __name__ == "__main__":
    main()
