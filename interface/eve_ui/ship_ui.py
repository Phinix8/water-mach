from typing import List

from interface.eve_ui.base import ParsedUIRegion
from memory.ui_tree import UITreeNode
from utils.path_follower import UIPathStep, UIPathFollower


class ShipUIModuleButton(ParsedUIRegion):
    _TO_BUTTON_NODE = [
        UIPathStep(type_="ModuleButton"),
    ]

    _TO_L_RAMP = [
        UIPathStep(type_="ShipModuleButtonRamps"),
        UIPathStep(attrs={"_name": "leftRampCont"}),
        UIPathStep(attrs={"_name": "leftRamp"}),
    ]

    _TO_R_RAMP = [
        UIPathStep(type_="ShipModuleButtonRamps"),
        UIPathStep(attrs={"_name": "rightRampCont"}),
        UIPathStep(attrs={"_name": "rightRamp"}),
    ]

    _TO_BUSY_SPRITE = [
        UIPathStep(attrs={"_name": "busy"}),
    ]

    def _parse(self):
        self.button_node = self._parse_button_node()
        self.module_type_id = self._parse_module_type_id()
        self.is_active = self._parse_is_active()

    def _parse_button_node(self) -> UITreeNode:
        return UIPathFollower.follow_path(self.node, self._TO_BUTTON_NODE)

    def _parse_module_type_id(self) -> int:
        assert self.button_node, "Button node must be parsed before module type id"
        text = self.button_node.attrs.get("_name", "")
        return int(text.replace("ModuleButton_", ""))

    def _parse_is_active(self) -> bool:
        assert self.button_node, "Button node must be parsed before ramp active"
        return self.button_node.attrs.get("ramp_active", False)

    def _parse_is_busy(self) -> bool:
        return UIPathFollower.follow_path(self.node, self._TO_BUSY_SPRITE) is not None


class ShipUI(ParsedUIRegion):
    _TO_SPEED_GAUGE = [
        UIPathStep(type_="HudContainer"),
        UIPathStep(type_="CenterHudContainer"),
        UIPathStep(type_="SpeedGauge"),
        UIPathStep(attrs={"_name": "speedCircularPickParent"}),
        UIPathStep(attrs={"_name": "speedGaugeParent"}),
        UIPathStep(attrs={"_name": "speedLabel"}),
    ]

    _TO_MODULE_BUTTONS = [
        UIPathStep(type_="HudContainer"),
        UIPathStep(type_="SlotsContainer")
    ]

    def _parse(self):
        self.speed_text = self._parse_speed_text()
        self.is_warping = self._parse_is_warping()
        self.module_buttons = self._parse_module_buttons()

    def _parse_speed_text(self) -> str:
        """
        Read the raw speed label text from the ship UI.

        This is useful for debugging because the behaviour tree should not only know
        whether we think the ship is warping, but also what UI text that decision
        came from.
        """
        speed_label = UIPathFollower.follow_path(self.node, self._TO_SPEED_GAUGE)

        if not speed_label:
            return ""

        return speed_label.attrs.get("_setText", "") or ""

    def _parse_is_warping(self) -> bool:
        return "warping" in self.speed_text.lower()

    def _parse_module_buttons(self) -> List[ShipUIModuleButton]:
        buttons_container = UIPathFollower.follow_path(self.node, self._TO_MODULE_BUTTONS)
        return [ShipUIModuleButton(child) for child in buttons_container.children
                if child.type_ == "ShipSlot"]