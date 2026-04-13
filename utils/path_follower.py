from dataclasses import dataclass
from typing import Optional

from memory.ui_tree import UITreeNode


@dataclass
class UIPathStep:
    type_: Optional[str] = None
    attrs: Optional[dict] = None
    index: Optional[int] = 0

class UIPathFollower:
    @staticmethod
    def follow_path(start_node: UITreeNode, path: list[UIPathStep]) -> Optional[UITreeNode]:
        """
        Uses a path to find a child node in a UI tree.
        """
        current = start_node
        for step in path:
            current = UIPathFollower._find_next(current, step)
            if current is None:
                return None
        return current

    @staticmethod
    def _find_next(node: UITreeNode, step: UIPathStep) -> Optional[UITreeNode]:
        i = 0
        for child in node.children:
            if UIPathFollower._matches(child, step):
                if i == step.index:
                    return child
                i += 1
        return None

    @staticmethod
    def _matches(node: UITreeNode, step: UIPathStep) -> bool:
        return (
            step.type_ is None or node.type_ == step.type_
        ) and (
            step.attrs is None or all(
            step.attrs.get(k) == node.attrs.get(k)
            for k in step.attrs.keys())
        )