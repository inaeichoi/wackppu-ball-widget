from __future__ import annotations

import math
import os
import random
import sys
import threading
import time

import tkinter as tk

from wakppu_widget import (
    BALL_SIZE,
    MP3_SEGMENTS,
    POLL_MS,
    WINDOW_SIZE,
    CrackSound,
    WakppuWidget,
    self_test,
    sound_scan,
    sound_test,
)


CLICK_HITS_TO_BREAK = 5
CLICK_DRAG_THRESHOLD = 6


class ClickCrackSound(CrackSound):
    def play_random(self) -> str:
        name = random.choice(("rub", "crunch", "break"))
        if self._source_ms > 900:
            segment = self._next_forced_mp3_segment(name)
            if segment is None:
                return name

            start, end = segment
            thread = threading.Thread(target=self._play_mp3_sync, args=(start, end, name), daemon=True)
            thread.start()
            return name

        self.play(name)
        return name

    def _next_forced_mp3_segment(self, name: str) -> tuple[int, int] | None:
        with self._play_lock:
            candidates = MP3_SEGMENTS.get(name, MP3_SEGMENTS["crunch"])
            index = self._segment_index.get(name, 0)
            ratio, duration_ms = candidates[index % len(candidates)]
            self._segment_index[name] = index + 1

            center = int(self._source_ms * ratio)
            start = max(0, center - duration_ms // 2)
            end = min(self._source_ms, start + duration_ms)
            start = max(0, end - duration_ms)

        return start, end


class ClickWakppuWidget(WakppuWidget):
    def __init__(self) -> None:
        self.click_hits = 0
        self.drag_start: tuple[int, int] | None = None
        self.drag_moved = False
        super().__init__()
        self.root.title("Wakppu Ball Click")
        self.sound = ClickCrackSound()

    def _schedule_poll(self) -> None:
        self.root.after(POLL_MS, self._schedule_poll)

    def _on_ball_click(self) -> None:
        if self.breaking:
            return

        self.click_hits += 1
        self.durability = max(0.0, self.max_durability - self.click_hits)
        self.crack_progress = min(1.0, self.click_hits / self.max_durability)
        self.impact = min(0.46, self.impact + 0.18)
        self.sound.play_random()

        if self.click_hits >= CLICK_HITS_TO_BREAK:
            self._start_break_without_extra_sound()

    def _start_break_without_extra_sound(self) -> None:
        if self.breaking:
            return

        self.breaking = True
        self.break_start = time.monotonic()
        self.pieces = self._make_pieces()

    def _start_drag(self, event: tk.Event) -> None:
        super()._start_drag(event)
        self.drag_start = (event.x_root, event.y_root)
        self.drag_moved = False

    def _drag(self, event: tk.Event) -> None:
        if self.drag_start is not None:
            moved = math.hypot(event.x_root - self.drag_start[0], event.y_root - self.drag_start[1])
            if moved > CLICK_DRAG_THRESHOLD:
                self.drag_moved = True

        super()._drag(event)

    def _end_drag(self, event: tk.Event) -> None:
        if self.drag_start is not None:
            moved = math.hypot(event.x_root - self.drag_start[0], event.y_root - self.drag_start[1])
            if moved > CLICK_DRAG_THRESHOLD:
                self.drag_moved = True

        should_click = not self.drag_moved and self._is_ball_click(event.x, event.y)
        super()._end_drag(event)
        self.drag_start = None
        self.drag_moved = False

        if should_click:
            self._on_ball_click()

    @staticmethod
    def _is_ball_click(x: int, y: int) -> bool:
        return math.hypot(x - WINDOW_SIZE / 2, y - WINDOW_SIZE / 2) <= BALL_SIZE * 0.58

    def _reset_ball(self, now: float | None = None) -> None:
        self.click_hits = 0
        self.max_durability = float(CLICK_HITS_TO_BREAK)
        self.durability = self.max_durability
        self.crack_progress = 0.0
        self.crack_sound_index = 0
        self.last_texture_sound_at = 0.0
        self.crack_paths = self._make_crack_paths()
        self.refill_start = time.monotonic() if now is None else now


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
        print("Wakppu Ball Click is designed for Windows.")

    app = ClickWakppuWidget()
    app.run()


if __name__ == "__main__":
    main()
