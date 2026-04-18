import random
from typing import Dict

from memory.memory import EveMemoryReader



import time
import random
from typing import Dict, Any


def _tree_contains_type(tree: dict, type_name: str) -> bool:
    stack = [tree]

    while stack:
        node = stack.pop()

        if node.get("type") == type_name:
            return True

        stack.extend(node.get("children", []))

    return False


def _tree_contains_child_named(tree: dict, name: str) -> bool:
    stack = [tree]

    while stack:
        node = stack.pop()

        if node.get("attrs", {}).get("_name") == name:
            return True

        stack.extend(node.get("children", []))

    return False


def is_usable_eve_root(tree: dict) -> bool:
    """
    Decide whether a raw tree looks like the real in-game EVE UI root.

    We explicitly reject UIRoot:desktopBlurred because it contains only blur Fill
    nodes and no useful game UI.
    """
    if not tree:
        return False

    if tree.get("type") != "UIRoot":
        return False

    root_name = tree.get("attrs", {}).get("_name", "")

    if root_name == "desktopBlurred":
        return False

    # Best case: the ship UI exists.
    if _tree_contains_type(tree, "ShipUI"):
        return True

    # Accept a root that at least has the normal high-level EVE UI structure.
    has_l_main = _tree_contains_child_named(tree, "l_main")
    has_l_viewstate = _tree_contains_child_named(tree, "l_viewstate")

    return has_l_main and has_l_viewstate


class UITreeNode:
    __slots__ = ("address", "type_", "attrs", "x", "y", "data", "parent", "children")

    def __init__(self, process_id: int):
        self._reader = EveMemoryReader(process_id)

        self._reader.initialize()

        deadline = time.time() + 20.0
        last_bad_summary = "no tree received"

        while time.time() < deadline:
            tree = self._reader.get_ui_tree()

            if not tree:
                continue

            if is_usable_eve_root(tree):
                self.root = self._load(tree)
                return

            last_bad_summary = (
                f"type={tree.get('type')}, "
                f"name={tree.get('attrs', {}).get('_name')}, "
                f"children={len(tree.get('children', []))}"
            )

            time.sleep(0.25)

        raise RuntimeError(
            f"Could not find usable EVE UI root for pid={process_id}. "
            f"Last bad root: {last_bad_summary}"
        )

    @property
    def display_area(self) -> tuple[int, int, int, int]:
        return (self.x, self.y,
                self.x + self.attrs.get("_width", 0), self.y + self.attrs.get("_height", 0))

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.attrs.get("_width", 0) // 2, self.y + self.attrs.get("_height", 0) // 2

    @property
    def clickable_location(self) -> tuple[int, int]:
        width = self.attrs.get("_displayWidth", 0)
        height = self.attrs.get("_displayHeight", 0)

        x = int(self.x + random.uniform(width * 0.4, width * 0.6))
        y = int(self.y + random.uniform(height * 0.4, height * 0.6))
        return x, y

class UITree:
    def __init__(self, process_id: int):
        self._reader = EveMemoryReader(process_id)

        # Wait for initialization
        self._reader.initialize()
        while not (tree := self._reader.get_ui_tree()):
            pass
        self.root = self._load(tree)

    def _ingest(self, tree, x=0, y=0, parent=None) -> UITreeNode:
        node = UITreeNode(**{**tree, **dict(x=x, y=y, parent=parent)})

        for child in tree.get("children", []):
            real_x = x + child.get("attrs", dict()).get("_displayX", 0)
            real_y = y + child.get("attrs", dict()).get("_displayY", 0)
            node.children.append(self._ingest(child, x=real_x, y=real_y, parent=node))

        return node

    def _load(self, tree) -> UITreeNode:
        return self._ingest(tree)

    def refresh(self):
        tree = self._reader.get_ui_tree()
        if not tree:
            return # Already up to date
        self.root = self._load(tree)