"""Bounded undo/redo history of complete, immutable equalizer working states.

History intentionally covers live audio edits rather than filesystem operations.
Saving/exporting a named profile does not change the undo stack; deletion of
profiles can invalidate their IDs and should clear the stack in the GUI.
"""
from __future__ import annotations

from dataclasses import dataclass

from equalizer import Settings


@dataclass(frozen=True)
class AudioState:
    settings: Settings
    custom: Settings


class EditHistory:
    def __init__(self, capacity: int = 100):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._undo: list[AudioState] = []
        self._redo: list[AudioState] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_count(self) -> int:
        return len(self._undo)

    @property
    def redo_count(self) -> int:
        return len(self._redo)

    def record(self, before: AudioState, after: AudioState) -> bool:
        """Record one user action, dropping the redo branch only if changed."""
        if before == after:
            return False
        self._undo.append(before)
        if len(self._undo) > self.capacity:
            del self._undo[:len(self._undo) - self.capacity]
        self._redo.clear()
        return True

    def undo(self, current: AudioState) -> AudioState | None:
        if not self._undo:
            return None
        self._redo.append(current)
        return self._undo.pop()

    def redo(self, current: AudioState) -> AudioState | None:
        if not self._redo:
            return None
        self._undo.append(current)
        if len(self._undo) > self.capacity:
            del self._undo[:len(self._undo) - self.capacity]
        return self._redo.pop()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
