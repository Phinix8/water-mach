import random
import time
from typing import Any

from memory.memory import EveMemoryReader


class UITreeNode:
    """
    One parsed UI node.

    The native DLL returns raw dictionaries with fields like:
    - address
    - type
    - attrs
    - children

    We convert "type" to "type_" internally because "type" is a Python builtin.
    """

    __slots__ = (
        "address",
        "type_",
        "attrs",
        "x",
        "y",
        "data",
        "parent",
        "children",
    )

    def __init__(self, **node):
        self.address: int = node.get("address", 0)
        self.type_: str = node.get("type", "")
        self.attrs: dict = node.get("attrs", {})

        self.x: int = node.get("x", 0)
        self.y: int = node.get("y", 0)

        self.parent = node.get("parent", None)
        self.data: dict = {}
        self.children: list[UITreeNode] = []

    @property
    def display_area(self) -> tuple[int, int, int, int]:
        return (
            self.x,
            self.y,
            self.x + self.attrs.get("_width", 0),
            self.y + self.attrs.get("_height", 0),
        )

    @property
    def center(self) -> tuple[int, int]:
        return (
            self.x + self.attrs.get("_width", 0) // 2,
            self.y + self.attrs.get("_height", 0) // 2,
        )

    @property
    def clickable_location(self) -> tuple[int, int]:
        width = self.attrs.get("_displayWidth", self.attrs.get("_width", 0))
        height = self.attrs.get("_displayHeight", self.attrs.get("_height", 0))

        x = int(self.x + random.uniform(width * 0.4, width * 0.6))
        y = int(self.y + random.uniform(height * 0.4, height * 0.6))

        return x, y


def _tree_contains_type(tree: dict[str, Any], type_name: str) -> bool:
    stack = [tree]

    while stack:
        node = stack.pop()

        if node.get("type") == type_name:
            return True

        stack.extend(node.get("children", []))

    return False


def _tree_contains_child_named(tree: dict[str, Any], name: str) -> bool:
    stack = [tree]

    while stack:
        node = stack.pop()

        if node.get("attrs", {}).get("_name") == name:
            return True

        stack.extend(node.get("children", []))

    return False


def summarize_raw_root(tree: dict[str, Any] | None) -> str:
    """
    Small debug summary for a raw tree from the DLL.
    """
    if not tree:
        return "tree=None"

    return (
        f"address={tree.get('address')}, "
        f"type={tree.get('type')}, "
        f"name={tree.get('attrs', {}).get('_name')}, "
        f"children={len(tree.get('children', []))}, "
        f"has_ship_ui={_tree_contains_type(tree, 'ShipUI')}, "
        f"has_l_main={_tree_contains_child_named(tree, 'l_main')}, "
        f"has_l_viewstate={_tree_contains_child_named(tree, 'l_viewstate')}"
    )


def is_usable_eve_root(tree: dict[str, Any] | None) -> bool:
    """
    Decide whether a raw tree looks like the real in-game EVE UI root.

    UIRoot:desktopBlurred is explicitly rejected because it only contains blur
    Fill nodes and no useful gameplay UI.
    """
    if not tree:
        return False

    if tree.get("type") != "UIRoot":
        return False

    root_name = tree.get("attrs", {}).get("_name", "")

    if root_name == "desktopBlurred":
        return False

    # Best case: the in-space ship UI exists.
    if _tree_contains_type(tree, "ShipUI"):
        return True

    # Fallback: accept a root with the normal high-level EVE UI structure.
    has_l_main = _tree_contains_child_named(tree, "l_main")
    has_l_viewstate = _tree_contains_child_named(tree, "l_viewstate")

    return has_l_main and has_l_viewstate


class UITree:
    """
    Owns the native memory reader and exposes the parsed Python UITreeNode root.
    """

    def __init__(self, process_id: int):
        self.process_id = process_id
        self._reader: EveMemoryReader | None = None
        self.last_bad_root_summary = "no tree read yet"

        self.root = self._initialize_until_usable_root()

    def _initialize_until_usable_root(
            self,
            attempts: int = 2,
            per_attempt_timeout: float = 90.0,
    ) -> UITreeNode:
        """
        Start/restart the memory reader until it returns a usable root.

        This helps if the native reader hits a transient access violation or
        temporarily returns an unusable root.
        """
        last_error = "no attempt made"

        for attempt in range(1, attempts + 1):
            print(
                f"[INFO] Initializing UI tree for pid={self.process_id} "
                f"(attempt {attempt}/{attempts})"
            )

            self._reader = EveMemoryReader(self.process_id)
            self._reader.initialize()

            try:
                return self._wait_for_initial_usable_root(
                    timeout=per_attempt_timeout
                )
            except Exception as exc:
                last_error = str(exc)
                print(f"[WARN] UI tree init attempt failed: {last_error}")

                try:
                    self._reader.shutdown()
                except Exception:
                    pass

                self._reader = None
                time.sleep(1.0)

        raise RuntimeError(
            f"Could not find usable EVE UI root for pid={self.process_id} "
            f"after {attempts} attempts. Last error: {last_error}"
        )

    def _wait_for_initial_usable_root(self, timeout: float = 240.0) -> UITreeNode:
        assert self._reader is not None

        deadline = time.time() + timeout
        last_log = 0.0

        while time.time() < deadline:
            elapsed = timeout - (deadline - time.time())

            if elapsed - last_log >= 5.0:
                last_log = elapsed
                print(
                    f"[INFO] Waiting for UI tree for pid={self.process_id} "
                    f"elapsed={elapsed:.1f}s / {timeout:.1f}s"
                )

            try:
                tree = self._reader.get_ui_tree()
            except Exception as exc:
                self.last_bad_root_summary = f"reader exception: {exc}"
                raise RuntimeError(self.last_bad_root_summary) from exc

            if is_usable_eve_root(tree):
                return self._load(tree)

            self.last_bad_root_summary = summarize_raw_root(tree)
            time.sleep(0.25)

        raise RuntimeError(
            f"Could not find usable EVE UI root for pid={self.process_id}. "
            f"Last bad root: {self.last_bad_root_summary}"
        )

    def _ingest(self, tree: dict[str, Any], x: int = 0, y: int = 0, parent=None) -> UITreeNode:
        node = UITreeNode(
            **tree,
            x=x,
            y=y,
            parent=parent,
        )

        for child in tree.get("children", []):
            real_x = x + child.get("attrs", {}).get("_displayX", 0)
            real_y = y + child.get("attrs", {}).get("_displayY", 0)

            node.children.append(
                self._ingest(
                    child,
                    x=real_x,
                    y=real_y,
                    parent=node,
                )
            )

        return node

    def pause_reader(self) -> None:
        if self._reader is not None:
            self._reader.pause()

    def resume_reader(self) -> None:
        if self._reader is not None:
            self._reader.resume()

    def _load(self, tree: dict[str, Any]) -> UITreeNode:
        return self._ingest(tree)

    def refresh(self) -> None:
        if self._reader is None:
            return

        try:
            tree = self._reader.get_ui_tree()
        except Exception as exc:
            self.last_bad_root_summary = f"reader exception during refresh: {exc}"
            return

        if not tree:
            return

        if not is_usable_eve_root(tree):
            self.last_bad_root_summary = summarize_raw_root(tree)
            return

        self.root = self._load(tree)