from interface.eve_ui.base import ParsedUIRegion
from utils.path_follower import UIPathStep, UIPathFollower


class LocationEntry(ParsedUIRegion):
    _TO_LABEL = [
        UIPathStep(type_="EveLabelMedium"),
    ]

    def _parse(self):
        self.name = self._parse_name()

    def _parse_name(self) -> str:
        label = UIPathFollower.follow_path(self.node, self._TO_LABEL)
        text = label.attrs.get("_setText", "") if label else ""
        return text.split("<t>")[0]

class Locations(ParsedUIRegion):
    _TO_ENTRIES = [
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "main"}),
        UIPathStep(type_="Scroll"),
        UIPathStep(attrs={"_name": "maincontainer"}),
        UIPathStep(attrs={"_name": "__clipper"}),
        UIPathStep(attrs={"_name": "__content"}),
    ]

    def _parse(self):
        self.entries = self._parse_entries()

    def _parse_entries(self) -> list[LocationEntry]:
        node = UIPathFollower.follow_path(self.node, self._TO_ENTRIES)
        return [LocationEntry(c) for c in node.children
                if c.type_ == "PlaceEntry"]