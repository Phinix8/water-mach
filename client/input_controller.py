import random
import time
from enum import auto, Enum
import pyautogui # sends dpi aware im lazy lol

import win32api
import win32con
import win32gui

class InputController:
    """
    Used to send inputs to the game client, uses win32api sendmessage
    to allow for background input.

    Seems to work, cannot vouch for safety.

    TODO - THIS IS SOME OLD VERSION I NEED TO FIND THE NEWER ONE
    """
    class MouseButton(Enum):
        LEFT = auto()
        RIGHT = auto()

    def __init__(self, hwnd: int):
        self._hwnd = hwnd

    def key_down(self, key_code: int):
        win32gui.SendMessage(self._hwnd, win32con.WM_KEYDOWN, key_code, None)

    def key_up(self, key_code: int):
        win32gui.SendMessage(self._hwnd, win32con.WM_KEYUP, key_code, None)

    def key_down_pyautogui(self, key_name: str):
        pyautogui.keyDown(key_name)

    def key_up_pyautogui(self, key_name: str):
        pyautogui.keyUp(key_name)

    def press_key(self, key_code: int):
        self.key_down(key_code)
        time.sleep(random.uniform(0.06, 0.08)) # for my keyboard, keypresses were 60-100 ms
        self.key_up(key_code)

    def move_mouse(self, x: int, y: int):
        lparam = win32api.MAKELONG(x, y)
        win32gui.SendMessage(self._hwnd, win32con.WM_MOUSEMOVE, None, lparam)

    def mouse_down(self, button: MouseButton = MouseButton.LEFT):
        match button:
            case self.MouseButton.RIGHT:
                win32gui.SendMessage(self._hwnd, win32con.WM_RBUTTONDOWN, win32con.MK_RBUTTON, None)
            case self.MouseButton.LEFT:
                win32gui.SendMessage(self._hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, None)

    def mouse_up(self, button: MouseButton = MouseButton.LEFT):
        match button:
            case self.MouseButton.RIGHT:
                win32gui.SendMessage(self._hwnd, win32con.WM_RBUTTONUP, win32con.MK_RBUTTON, None)
            case self.MouseButton.LEFT:
                win32gui.SendMessage(self._hwnd, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, None)

    def mouse_click(self, x: int, y: int, button: MouseButton = MouseButton.LEFT):
        self.move_mouse(x, y)
        time.sleep(random.uniform(0.06, 0.08))
        self.mouse_down(button=button)
        time.sleep(random.uniform(0.06, 0.08))
        self.mouse_up(button=button)
