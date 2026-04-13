import random
from typing import Dict

from memory.memory import EveMemoryReader


class UITreeNode:
    __slots__ = ("address", "type_", "attrs", "x", "y", "data", "parent", "children")

    def __init__(self, **node):
        self.address: int = node["address"]
        self.type_: str = node["type"]
        self.attrs: dict = node["attrs"]
        self.x: int = node.get("x", 0)
        self.y: int = node.get("y", 0)
        self.parent: int = node.get("parent", 0)
        self.data = dict()
        self.children: list = []

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