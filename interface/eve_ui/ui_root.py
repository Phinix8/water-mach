from typing import List, Optional

from interface.eve_ui.chat_window import ChatWindowStack
from interface.eve_ui.context_menu import ContextMenu
from interface.eve_ui.locations import Locations
from interface.eve_ui.overview import OverviewWindow
from interface.eve_ui.probe_window import ProbeWindow
from interface.eve_ui.ship_ui import ShipUI
from memory.ui_tree import UITree, UITreeNode
from utils.path_follower import UIPathStep, UIPathFollower


class UIRoot:
    """Parsed representation of the full UI tree"""
    _TO_L_MENU = [UIPathStep(attrs={"_name": "l_menu"})]
    _TO_L_MAIN = [UIPathStep(attrs={"_name": "l_main"})]
    _TO_SUN_ICON = [  # maybe just use search?
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

        return [ContextMenu(child) for child in l_menu.children
                if child.type_ in ("ContextMenu", "ContextSubMenu")]

    @property
    def overviews(self) -> List[OverviewWindow]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        if not l_main:
            return []

        return [OverviewWindow(child) for child in l_main.children
                if child.type_ == "OverviewWindow"]

    @property
    def sun_icon(self) -> Optional[UITreeNode]:
        return UIPathFollower.follow_path(self._ui_tree.root, self._TO_SUN_ICON)

    @property
    def chat_windows(self) -> List[ChatWindowStack]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)

        return [
            ChatWindowStack(child)
                for child in l_main.children
                if child.type_ == "ChatWindowStack"
        ]

    @property
    def probe_window(self) -> Optional[ProbeWindow]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        node = next((child for child in l_main.children if child.type_ == "ProbeScannerWindow"), None)
        return ProbeWindow(node) if node else None

    @property
    def ship_ui(self) -> Optional[ShipUI]:
        node = UIPathFollower.follow_path(self._ui_tree.root, self._TO_SHIP_UI)
        return ShipUI(node) if node else None

    @property
    def locations(self) -> Optional[Locations]:
        l_main = UIPathFollower.follow_path(self._ui_tree.root, self._TO_L_MAIN)
        node = next((child for child in l_main.children if child.type_ == "StandaloneBookmarkWnd"), None)
        return Locations(node) if node else None
