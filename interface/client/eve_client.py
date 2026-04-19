from typing import Optional
import time

import win32con
import win32gui
import win32process

from interface.client.input_controller import InputController
from interface.eve_ui.ui_root import UIRoot
from memory.ui_tree import UITree


class EvEClient:
    @staticmethod
    def _get_pid_from_window_name(window_name: str) -> int:
        hwnd = win32gui.FindWindow(None, window_name)

        if not hwnd:
            raise RuntimeError(f"Could not find EVE window: {window_name}")

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid

    @staticmethod
    def _get_hwnd_from_process_id(process_id: int) -> Optional[int]:
        def callback(hwnd, hwnds):
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == process_id and win32gui.IsWindowVisible(hwnd):
                    hwnds.append(hwnd)
            except Exception:
                pass
            return True

        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        return hwnds[0] if hwnds else None

    @staticmethod
    def _prepare_window_for_memory_reader(hwnd: Optional[int]) -> None:
        """
        Try to avoid initializing the memory reader while EVE exposes only
        UIRoot:desktopBlurred.
        """
        if not hwnd:
            return

        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.75)
        except Exception as exc:
            print(f"[WARN] Could not foreground EVE window before memory read: {exc}")

    def __init__(self, client_name: str):
        self.client_name = client_name

        window_name = f"EVE - {client_name}"
        self.pid = self._get_pid_from_window_name(window_name)
        self.hwnd = self._get_hwnd_from_process_id(self.pid)
        self.window_title = win32gui.GetWindowText(self.hwnd) if self.hwnd else "<no hwnd>"

        print(
            f"[INFO] Initializing client {client_name!r}: "
            f"[INFO] Window mapping: wanted={window_name!r}, "
            f"hwnd={self.hwnd}, pid={self.pid}, title={self.window_title!r}"
        )

        self._prepare_window_for_memory_reader(self.hwnd)

        self.input_handler = InputController(self.hwnd)

        # Important: initialize memory reader only after preparation.
        self.ui_tree = UITree(self.pid)
        self.ui_root = UIRoot(self.ui_tree)

        # Prevent already-initialized clients from continuously reading memory while
        # the next clients are still being initialized.
        self.ui_tree.pause_reader()