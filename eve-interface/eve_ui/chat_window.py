from enum import Enum, auto
from typing import List

from eve_ui.base import ParsedUIRegion
from utils.path_follower import UIPathStep, UIPathFollower


# name: l_main -> type: ChatWindowStack

class CharacterStandings(Enum):
    SELF = auto()
    ALLIANCE = auto()
    CORPORATION = auto()
    BLUE = auto()
    NEUTRAL = auto()
    RED = auto()
    FLEET = auto()


class ChatWindowMember(ParsedUIRegion):
    _TO_STANDING_ICON = [
        UIPathStep(attrs={"_name": "iconCont"}),
        UIPathStep(type_="FlagIconWithState"),
    ]

    def _parse(self):
        self.name = self._parse_name()
        self.standings = self._parse_standings()

    def _parse_name(self) -> str:
        return self.node.attrs.get("_name", "")

    def _parse_standings(self) -> CharacterStandings:
        icon_node = UIPathFollower.follow_path(self.node, self._TO_STANDING_ICON)
        if not icon_node:
            return CharacterStandings.SELF

        _hint = icon_node.attrs.get("_hint", "")

        match _hint:
            case "Pilot is in your alliance":
                return CharacterStandings.ALLIANCE
            case "Pilot is in your Capsuleer corporation":
                return CharacterStandings.CORPORATION
            case "Pilot has Excellent Standing." | "Pilot has Good Standing.":
                return CharacterStandings.BLUE
            case "Pilot has No Standing.":
                return CharacterStandings.NEUTRAL
            case "Pilot is in your fleet":
                return CharacterStandings.FLEET
            case _:  # todo: more explicit red cases
                return CharacterStandings.RED


class ChatWindowTab(ParsedUIRegion):
    def _parse(self):
        self.name: str
        self.is_selected: str


class ChatWindowStack(ParsedUIRegion):
    _TO_MEMBERS = [
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "__content"}),
        UIPathStep(type_="XmppChatWindow"),
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "main"}),
        UIPathStep(type_="Container"),
        UIPathStep(type_="BasicDynamicScroll", attrs={"_name": "userlist"}),
        UIPathStep(attrs={"_name": "maincontainer"}),
        UIPathStep(attrs={"_name": "__clipper"}),
        UIPathStep(attrs={"_name": "__content"}),
    ]

    _TO_CHANNEL_TABS = [
        UIPathStep(attrs={"_name": "content"}),
        UIPathStep(attrs={"_name": "headerParent"}),
        UIPathStep(type_="WindowStackHeader"),
        UIPathStep(type_="TabGroup"),
        UIPathStep(type_="ContainerAutoSize", index=1),
        UIPathStep(attrs={"_name": "tabsCont"}),
    ]

    _TO_CHANNEL_LABEL = [
        UIPathStep(attrs={"_name": "labelClipper"}),
        UIPathStep(type_="EveLabelMedium"),
    ]

    def _parse(self):
        self.channel_name = self._parse_channel_name()
        self.members = self._parse_members()

    def _parse_channel_name(self) -> str:
        tabs_cont = UIPathFollower.follow_path(self.node, self._TO_CHANNEL_TABS)

        for child in tabs_cont.children:
            if child.type_ == "WindowStackTab":
                label = UIPathFollower.follow_path(child, self._TO_CHANNEL_LABEL)
                if label.attrs.get("_color", {}).get("aPercent") >= 89:
                    return label.attrs.get("_setText", "")
        return ""

    def _parse_members(self) -> List[ChatWindowMember]:
        members_container = UIPathFollower.follow_path(self.node, self._TO_MEMBERS)
        return [ChatWindowMember(child) for child in members_container.children]
