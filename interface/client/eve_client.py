from typing import Optional

import win32gui
import win32process

from interface.client.input_controller import InputController
from interface.eve_ui.ui_root import UIRoot
from memory.ui_tree import UITree


class EvEClient:
    @staticmethod
    def _get_pid_from_window_name(window_name: str) -> int:
        hwnd = win32gui.FindWindow(None, window_name)
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

    def __init__(self, client_name: str):
        self.client_name = client_name
        self.pid = self._get_pid_from_window_name(f"EVE - {client_name}")
        hwnd = self._get_hwnd_from_process_id(self.pid)
        self.input_handler = InputController(hwnd)

        self.ui_tree = UITree(self.pid)
        self.ui_root = UIRoot(self.ui_tree)


