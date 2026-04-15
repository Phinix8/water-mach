from typing import List

from eve_ui.base import ParsedUIRegion
from utils.path_follower import UIPathStep, UIPathFollower


class ProbeWindowEntry(ParsedUIRegion):
    _TO_DISTANCE_NODE = [
        UIPathStep(type_="Container"),
        UIPathStep(type_="Container", index=1),
        UIPathStep(type_="Container", index=1),
        UIPathStep(type_="EveLabelMedium"),
    ]

    _TO_ID_NODE = [
        UIPathStep(type_="Container"),
        UIPathStep(type_="Container", index=1),
        UIPathStep(type_="Container", index=2),
        UIPathStep(type_="EveLabelMedium"),
    ]

    _TO_NAME_NODE = [
        UIPathStep(type_="Container"),
        UIPathStep(type_="Container", index=1),
        UIPathStep(type_="Container", index=3),
        UIPathStep(type_="EveLabelMedium"),
    ]

    def _parse(self):
        self.distance = self._parse_distance()
        self.id = self._parse_id()
        self.name = self._parse_name()

    def _parse_distance(self) -> float:
        node = UIPathFollower.follow_path(self.node, self._TO_DISTANCE_NODE)
        if not node:
            return float("inf")  # seems to happen if probe refreshes

        text = node.attrs.get("_setText", "")

        if "km" in text:
            return float(text.replace(" km", "").replace(",", "")) / 149_597_870
        if "AU" in text:
            return float(text.replace(" AU", "").replace(",", ""))
        return 0.0  # ??? shouldn't happen, but just in case

    def _parse_id(self) -> str:
        node = UIPathFollower.follow_path(self.node, self._TO_ID_NODE)
        return node.attrs.get("_setText", "") if node else ""

    def _parse_name(self) -> str:
        node = UIPathFollower.follow_path(self.node, self._TO_NAME_NODE)
        return node.attrs.get("_setText", "") if node else ""



class ProbeWindow(ParsedUIRegion):
    _TO_ENTRIES = [
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "main"}),
        UIPathStep(type_="ProbeScannerPalette"),
        UIPathStep(attrs={"_name": "ScanResultsContainer"}),
        UIPathStep(type_="ScanResults"),
        UIPathStep(attrs={"_name": "maincontainer"}),
        UIPathStep(attrs={"_name": "__clipper"}),
        UIPathStep(attrs={"_name": "__content"}),
    ]

    def _parse(self):
        self.entries = self._parse_entries()

    def _parse_entries(self) -> List[ProbeWindowEntry]:
        node = UIPathFollower.follow_path(self.node, self._TO_ENTRIES)
        return [ProbeWindowEntry(child) for child in node.children
                if child.type_ == "ScanResultNew"]