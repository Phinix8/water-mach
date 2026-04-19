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

    @staticmethod
    def _manual_prepare_window(client_name: str, hwnd: Optional[int]) -> None:
        """
        Debug/manual fallback for Windows foreground restrictions.

        The memory reader appears to select a UIRoot candidate during
        initialization. If the client is blurred/backgrounded at that moment,
        it can lock onto UIRoot:desktopBlurred.

        In debug mode, we let the user explicitly bring the correct client to
        the front before initializing the memory reader.
        """
        if hwnd:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass

        print()
        print(f"[MANUAL INIT] Prepare EVE client: {client_name!r}")
        print("  1. Bring this exact EVE window to the foreground.")
        print("  2. Make sure the ship HUD is visible.")
        print("  3. Make sure the client is fully loaded and in space.")
        print("  4. Then press Enter here.")
        input(f"[MANUAL INIT] Press Enter when 'EVE - {client_name}' is ready...")

        # Give EVE/memory a small moment to settle after the window change.
        time.sleep(0.75)

    def __init__(self, client_name: str, manual_prepare: bool = False):
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

        if manual_prepare:
            self._manual_prepare_window(client_name, self.hwnd)
        else:
            self._prepare_window_for_memory_reader(self.hwnd)

        self.input_handler = InputController(self.hwnd)

        # Important: initialize memory reader only after preparation.
        self.ui_tree = UITree(self.pid)
        self.ui_root = UIRoot(self.ui_tree)

        # Prevent already-initialized clients from continuously reading memory while
        # the next clients are still being initialized.
        self.ui_tree.pause_reader()