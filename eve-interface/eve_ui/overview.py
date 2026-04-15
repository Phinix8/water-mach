from typing import List, Dict

from eve_ui.base import ParsedUIRegion
from memory.ui_tree import UITreeNode
from utils.path_follower import UIPathFollower, UIPathStep


class OverviewWindowHeader(ParsedUIRegion):
    _TO_EVE_LABEL_SMALL = [UIPathStep(type_="EveLabelSmall")]

    def _parse(self):
        self.text = self._parse_text()

    def _parse_text(self) -> str:
        # Icon and some other headers have name in the _hint attribute
        if _hint := self.node.attrs.get("_hint"):
            return _hint

        # Whilst others have a nested EveLabelSmall
        eve_label_small = UIPathFollower.follow_path(self.node, self._TO_EVE_LABEL_SMALL)
        return eve_label_small.attrs.get("_setText", "") if eve_label_small else ""


class OverviewEntry(ParsedUIRegion):
    def __init__(self, node: UITreeNode, headers: List[OverviewWindowHeader]):
        self._headers = headers
        super().__init__(node)

    def _parse(self):
        self.fields: Dict[str, str] = self._parse_fields()

    def _parse_fields(self) -> Dict[str, str]:
        fields = {}
        label_nodes = [child for child in self.node.children
                       if child.type_ in ("OverviewLabel", "SpaceObjectIcon")]

        for i, label_node in enumerate(reversed(label_nodes)):
            if label_node == "SpaceObjectIcon":
                continue

            text = label_node.attrs.get("_text", "")
            fields[self._headers[i].text] = text
        return fields

class OverviewWindow(ParsedUIRegion):
    _TO_HEADERS_CONTAINER = [
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "main"}),
        UIPathStep(attrs={"_name": "overviewscroll2"}),
        UIPathStep(attrs={"_name": "maincontainer"}),
        UIPathStep(type_="SortHeaders"),
        UIPathStep(type_="Container")
    ]

    _TO_ENTRIES_CONTAINER = [
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "main"}),
        UIPathStep(attrs={"_name": "overviewscroll2"}),
        UIPathStep(attrs={"_name": "maincontainer"}),
        UIPathStep(attrs={"_name": "__clipper"}),
        UIPathStep(attrs={"_name": "__content"}),
    ]

    def _parse(self):
        self.headers = self._parse_headers()
        self.entries = self._parse_entries()

    def _parse_headers(self) -> List[OverviewWindowHeader]:
        headers_container = UIPathFollower.follow_path(self.node, self._TO_HEADERS_CONTAINER)
        if not headers_container:
            return []

        return [OverviewWindowHeader(child) for child in headers_container.children
                if child.type_ == "Header"]

    def _parse_entries(self) -> List[OverviewEntry]:
        assert self.headers, "Headers must be parsed before entries"

        entries_container = UIPathFollower.follow_path(self.node, self._TO_ENTRIES_CONTAINER)
        if not entries_container:
            return []

        return [OverviewEntry(child, self.headers) for child in entries_container.children
                if child.type_ == "OverviewScrollEntry"]