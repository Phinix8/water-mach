from typing import List

from eve_ui.base import ParsedUIRegion
from utils.path_follower import UIPathStep, UIPathFollower


class ContextMenuEntry(ParsedUIRegion):
    _TO_TEXT_BODY = [
        UIPathStep(type_="TextBody")
    ]

    def _parse(self):
        self.text = self._parse_text()

    def _parse_text(self) -> str:
        text_body = UIPathFollower.follow_path(self.node, self._TO_TEXT_BODY)
        return text_body.attrs.get("_setText", "") if text_body else ""

class ContextMenu(ParsedUIRegion):
    _TO_ENTRIES = [
        UIPathStep(type_="ContainerAutoSize")
    ]

    def _parse(self):
        self.entries = self._parse_entries()

    def _parse_entries(self) -> List[ContextMenuEntry]:
        entry_parent = UIPathFollower.follow_path(self.node, self._TO_ENTRIES)
        return [
            ContextMenuEntry(child) for child in entry_parent.children
            if "MenuEntryView" in child.type_
        ]