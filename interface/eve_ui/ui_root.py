from typing import List, Optional

from interface.eve_ui.chat_window import ChatWindowStack
from interface.eve_ui.context_menu import ContextMenu
from interface.eve_ui.locations import Locations
from interface.eve_ui.overview import OverviewWindow
from interface.eve_ui.probe_window import ProbeWindow
from interface.eve_ui.ship_ui import ShipUI
from memory.ui_tree import UITree, UITreeNode
from utils.path_follower import UIPathStep, UIPathFollower


def find_first_node_by_type(root: UITreeNode, type_name: str) -> Optional[UITreeNode]:
    """
    Recursively search the UI tree for the first node with the given type.

    This is slower than following an exact path, but useful as a fallback when
    different clients expose slightly different UI tree structures.
    """
    stack = [root]

    while stack:
        node = stack.pop()

        if node.type_ == type_name:
            return node

        stack.extend(reversed(node.children))

    return None


def count_nodes_by_type(root: UITreeNode, type_name: str) -> int:
    """Count nodes of a given type anywhere below root."""
    count = 0
    stack = [root]

    while stack:
        node = stack.pop()

        if node.type_ == type_name:
            count += 1

        stack.extend(node.children)

    return count


def summarize_children(node: Optional[UITreeNode], limit: int = 20) -> str:
    """
    Compactly summarize a node's direct children.

    Used only for debug output.
    """
    if node is None:
        return "None"

    parts = []

    for child in node.children[:limit]:
        name = child.attrs.get("_name", "")
        parts.append(f"{child.type_}:{name}")

    if len(node.children) > limit:
        parts.append(f"... +{len(node.children) - limit} more")

    return "[" + ", ".join(parts) + "]"


class UIRoot:
    """Parsed representation of the full UI tree."""

    _TO_L_MENU = [UIPathStep(attrs={"_name": "l_menu"})]
    _TO_L_MAIN = [UIPathStep(attrs={"_name": "l_main"})]

    _TO_SUN_ICON = [
        UIPathStep(attrs={"_name": "l_viewstate"}),
        UIPathStep(attrs={"_name": "l_view_overlays"}),
        UIPathStep(attrs={"_name": "l_sidePanels"}),
        UIPathStep(attrs={"_name": "sidePanel"}),
        UIPathStep(type_="InfoPanelContainer"),
        UIPathStep(attrs={"_name": "mainCont"}),
        UIPathStep(type_="InfoPanelLocationInfo"),
        UIPathStep(attrs={"_name": "topCont"}),
        UIPathStep(attrs={"_name": "headerBtnCont"}),
        UIPathStep(type_="ListSurroundingsBtn"),
    ]

    _TO_SHIP_UI = [
        UIPathStep(attrs={"_name": "l_viewstate"}),
        UIPathStep(attrs={"_name": "l_view_overlays"}),
        UIPathStep(type_="ShipUI"),
    ]

    def __init__(self, ui_tree: UITree) -> None:
        self._ui_tree = ui_tree

    @property
    def context_menus(self) -> List[ContextMenu]:
        l_menu = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MENU)
        if not l_menu:
            return []

        return [
            ContextMenu(child)
            for child in l_menu.children
            if child.type_ in ("ContextMenu", "ContextSubMenu")
        ]

    @property
    def overviews(self) -> List[OverviewWindow]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        if not l_main:
            return []

        return [
            OverviewWindow(child)
            for child in l_main.children
            if child.type_ == "OverviewWindow"
        ]

    @property
    def sun_icon(self) -> Optional[UITreeNode]:
        return UIPathFollower.follow_path(self._ui_tree.root, self._TO_SUN_ICON)

    @property
    def chat_windows(self) -> List[ChatWindowStack]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        if not l_main:
            return []

        return [
            ChatWindowStack(child)
            for child in l_main.children
            if child.type_ == "ChatWindowStack"
        ]

    @property
    def probe_window(self) -> Optional[ProbeWindow]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        if not l_main:
            return None

        node = next(
            (child for child in l_main.children if child.type_ == "ProbeScannerWindow"),
            None,
        )
        return ProbeWindow(node) if node else None

    @property
    def ship_ui(self) -> Optional[ShipUI]:
        # Fast expected path.
        node = UIPathFollower.follow_path(self._ui_tree.root, self._TO_SHIP_UI)

        # Fallback: find ShipUI anywhere in the selected UI root.
        if not node:
            node = find_first_node_by_type(self._ui_tree.root, "ShipUI")

        return ShipUI(node) if node else None

    @property
    def locations(self) -> Optional[Locations]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        if not l_main:
            return None

        node = next(
            (child for child in l_main.children if child.type_ == "StandaloneBookmarkWnd"),
            None,
        )
        return Locations(node) if node else None

    @property
    def ship_ui_debug_summary(self) -> str:
        exact_node = UIPathFollower.follow_path(self._ui_tree.root, self._TO_SHIP_UI)
        recursive_count = count_nodes_by_type(self._ui_tree.root, "ShipUI")

        return (
            f"exact_path_found={exact_node is not None}, "
            f"recursive_ship_ui_count={recursive_count}"
        )

    @property
    def root_debug_summary(self) -> str:
        """
        Debug summary for diagnosing wrong/partial UIRoot selection.

        If ShipUI count is zero, this tells us whether the selected root still
        contains other normal in-game UI regions such as overview/chat, or
        whether the selected root is completely wrong.
        """
        root = self._ui_tree.root

        l_main = UIPathFollower.follow_path(root, self._TO_L_MAIN)

        l_viewstate = UIPathFollower.follow_path(
            root,
            [UIPathStep(attrs={"_name": "l_viewstate"})],
        )

        l_view_overlays = UIPathFollower.follow_path(
            root,
            [
                UIPathStep(attrs={"_name": "l_viewstate"}),
                UIPathStep(attrs={"_name": "l_view_overlays"}),
            ],
        )

        return (
            f"root={root.type_}:{root.attrs.get('_name', '')}, "
            f"root_children={summarize_children(root)}, "
            f"l_main_children={summarize_children(l_main)}, "
            f"l_viewstate_children={summarize_children(l_viewstate)}, "
            f"l_view_overlays_children={summarize_children(l_view_overlays)}, "
            f"counts="
            f"ShipUI:{count_nodes_by_type(root, 'ShipUI')}, "
            f"HudContainer:{count_nodes_by_type(root, 'HudContainer')}, "
            f"CenterHudContainer:{count_nodes_by_type(root, 'CenterHudContainer')}, "
            f"SpeedGauge:{count_nodes_by_type(root, 'SpeedGauge')}, "
            f"SlotsContainer:{count_nodes_by_type(root, 'SlotsContainer')}, "
            f"OverviewWindow:{count_nodes_by_type(root, 'OverviewWindow')}, "
            f"ChatWindowStack:{count_nodes_by_type(root, 'ChatWindowStack')}, "
            f"ProbeScannerWindow:{count_nodes_by_type(root, 'ProbeScannerWindow')}, "
            f"StandaloneBookmarkWnd:{count_nodes_by_type(root, 'StandaloneBookmarkWnd')}"
        )