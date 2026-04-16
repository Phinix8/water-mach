from abc import ABC, abstractmethod

from memory.ui_tree import UITree, UITreeNode


class ParsedUIRegion(ABC):
    """Base class for parsed UI regions."""
    def __init__(self, node: UITreeNode):
        self.node = node
        self.address = node.address
        self._parse()

    @abstractmethod
    def _parse(self):
        ...