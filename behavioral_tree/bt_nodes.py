# Sensing/Action/Utility Node-Leafs extending/wrapping py_trees.

from __future__ import annotations

import random
import time
from typing import Any,  Callable, Iterable

import py_trees
from py_trees.common import Access, Status

from interface.client.eve_client import EvEClient
from interface.client.input_controller import InputController
from interface.eve_ui.chat_window import CharacterStandings
from interface.eve_ui.context_menu import ContextMenuEntry


BOT_BLACKBOARD_NAMESPACE = "bot"

##############################################
#### Utility Functions
##############################################

def wait_for_context_menu_entry(
        client: EvEClient,
        entry_text: str,
        timeout: float = 3.0,
        poll_interval: float = 0.05,
) -> ContextMenuEntry | None:
    """
    Kept from jiaboen. Helper Function rather than Node as a click actions

    Poll the parsed UI until a context-menu entry countaining 'entry_text' appears.
    Return: Matching ContextMenue or None if no match was found within Timeout.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            context_menus = client.ui_root.context_menus or []
        except Exception:
            context_menus = []

        for menu in context_menus:
            # Avoid Temporary offscreen menu
            if menu.node.x < 20 or menu.node.y < 0:
                continue

            for entry in getattr(menu, "entries", []) or []:
                text = (getattr(entry, "text", "") or "").strip().lower()
                if entry_text.lower() in text:
                    return entry #Always returns first found.

        time.sleep(poll_interval)

    return None

class EveBehaviour(py_trees.behaviour.Behaviour):
    """
    small base class for EVE-Specific leaf behaviors.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.blackboard = self.attach_blackboard_client(name=f"{name} Blackboard", namespace=BOT_BLACKBOARD_NAMESPACE)

    def register_reads(self, *keys: str) -> None:
        for key in keys:
            self.blackboard.register_key(key=key, access=Access.READ)

    def register_writes(self, *keys: str) -> None:
        for key in keys:
            self.blackboard.register_key(key=key, access=Access.WRITE)

    def get_clients(self) -> list[EvEClient]:
        return list(self.blackboard.eve_clients)

    def get_main_client(self) -> EvEClient:
        clients = self.get_clients()
        if not clients:
            raise RuntimeError("No EVE Clients are available on the blackboard.")
        return clients[0]   # Potentially let user choose main client later on.


##############################################
### Generic utility Behaviour
##############################################

class PrintMessage(EveBehaviour):
    """ Simple debug/info Node that prints once and succeeds"""
    def __init__(self, message: str, name: str | None = None) -> None:
        super().__init__(name=name or f"Print: {message}")
        self.message = message

    def update(self) -> Status:
        print(self.message)
        self.feedback_message = self.message
        return Status.SUCCESS

class PauseUntilInput(EveBehaviour):
    """
    Manual gate for operator-controlled pause.

    Blocks until enter is pressed. Replaces old blocking pause, might be redundant later on.
    """

    def __init__(self, prompt: str = "Press enter to continue..:", name: str = "Pause Until Input") -> None:
        super().__init__(name=name)
        self.prompt = prompt

    def update(self) -> Status:
        input(self.prompt)
        self.feedback_message = "Operator resumed execution"
        return Status.SUCCESS

class SetBlackboardValue(EveBehaviour):
    """Write a static or return value of callable to Blackboard.
        Customized for better readability.
    """
    def __init__(self,  key: str, value: Any | Callable[[], Any], name: str | None = None) -> None:
        super().__init__(name=name or f"Set {key}")
        self.key = key
        self.value = value
        self. register_writes(key)

    def update(self) -> Status:
        value = self.value() if  callable(self.value) else self.value
        self.blackboard.set(self.key, value, overwrite=True)
        self.feedback_message = f"{self.key} = {value!r}"
        return Status.SUCCESS

class SetCurrentTime(EveBehaviour):
    """Write the current unix timestamp to a blackboard key."""

    def __init__(self, key: str, name: str | None = None) -> None:
        super().__init__(name=name or f"Set Time: {key}")
        self.key = key
        self.register_writes(key)

    def update(self) -> Status:
        now = time.time()
        self.blackboard.set(self.key, now, overwrite=True)
        self.feedback_message = f"{self.key}={now:.2f}"
        return Status.SUCCESS

class SetRandomDeadlineFromNow(EveBehaviour):
    """
    Store `now + random.uniform(min_delay, max_delay)` in a blackboard key.

    Includes Break Time now into the tree rather than hidden state.
    """

    def __init__(
        self,
        key: str,
        min_delay: float,
        max_delay: float,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"Set Deadline: {key}")
        if min_delay > max_delay:
            raise ValueError("min_delay must be <= max_delay")

        self.key = key
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.register_writes(key)

    def update(self) -> Status:
        deadline = time.time() + random.uniform(self.min_delay, self.max_delay)
        self.blackboard.set(self.key, deadline, overwrite=True)
        self.feedback_message = f"{self.key}={deadline:.2f}"
        return Status.SUCCESS


class IsCurrentTimePast(EveBehaviour):
    """Return SUCCESS once the current time is past the stored deadline."""

    def __init__(self, key: str, name: str | None = None) -> None:
        super().__init__(name=name or f"Time Past? {key}")
        self.key = key
        self.register_reads(key)

    def update(self) -> Status:
        try:
            deadline = getattr(self.blackboard, self.key)
        except Exception:
            self.feedback_message = f"Missing key: {self.key}"
            return Status.FAILURE

        now = time.time()
        if now >= deadline:
            self.feedback_message = f"{now:.2f} >= {deadline:.2f}"
            return Status.SUCCESS

        self.feedback_message = f"{now:.2f} < {deadline:.2f}"
        return Status.FAILURE

class Delay(EveBehaviour):
    """
    Non-blocking delay node.

    Returns RUNNING until the duration has elapsed, then SUCCESS.
    """

    def __init__(self, duration: float, name: str | None = None) -> None:
        if duration <= 0:
            raise ValueError("duration must be > 0")

        super().__init__(name=name or f"Delay {duration:.1f}s")
        self.duration = duration
        self.deadline: float | None = None

    def initialise(self) -> None:
        self.deadline = time.time() + self.duration

    def update(self) -> Status:
        assert self.deadline is not None, "Delay.initialise() should set the deadline"

        remaining = self.deadline - time.time()
        if remaining <= 0:
            self.feedback_message = "Delay finished"
            return Status.SUCCESS

        self.feedback_message = f"{remaining:.2f}s remaining"
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        self.deadline = None

class SendDiscordWebhook(EveBehaviour):
    """
    Small action node for sending a Discord webhook message.

    Kept separate from sensor nodes so detection logic remains pure and easier
    to reason about.
    """

    def __init__(
        self,
        message: str | Callable[[], str],
        url_key: str = "discord_url",
        name: str = "Send Discord Webhook",
    ) -> None:
        super().__init__(name=name)
        self.message = message
        self.url_key = url_key
        self.register_reads(url_key)

    def update(self) -> Status:
        try:
            webhook_url = getattr(self.blackboard, self.url_key)
        except Exception:
            self.feedback_message = f"Missing key: {self.url_key}"
            return Status.FAILURE

        payload = self.message() if callable(self.message) else self.message

        try:
            import requests

            response = requests.post(
                webhook_url,
                json={"content": payload},
                timeout=5,
            )
            response.raise_for_status()
        except Exception as exc:
            self.feedback_message = f"Webhook failed: {exc}"
            return Status.FAILURE

        self.feedback_message = "Webhook sent"
        return Status.SUCCESS

##############################################
### Warp state checks
##############################################

class IsAnyClientWarping(EveBehaviour):
    """SUCCESS if at least one client is currently warping."""

    def __init__(self, name: str = "Any Client Warping?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            clients = self.get_clients()
            result = any(
                client.ui_root.ship_ui is not None and client.ui_root.ship_ui.is_warping
                for client in clients
            )
        except Exception as exc:
            self.feedback_message = f"Error reading ship UI: {exc}"
            return Status.FAILURE

        self.feedback_message = str(result)
        return Status.SUCCESS if result else Status.FAILURE

class IsAllClientsWarping(EveBehaviour):
    """SUCCESS if all clients are currently warping."""

    def __init__(self, name: str = "All Clients Warping?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            clients = self.get_clients()
            if not clients:
                self.feedback_message = "No clients"
                return Status.FAILURE

            result = all(
                client.ui_root.ship_ui is not None and client.ui_root.ship_ui.is_warping
                for client in clients
            )
        except Exception as exc:
            self.feedback_message = f"Error reading ship UI: {exc}"
            return Status.FAILURE

        self.feedback_message = str(result)
        return Status.SUCCESS if result else Status.FAILURE


class IsAllClientsNotWarping(EveBehaviour):
    """SUCCESS if all clients are confirmed to not be warping."""

    def __init__(self, name: str = "All Clients Not Warping?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            clients = self.get_clients()
            if not clients:
                self.feedback_message = "No clients"
                return Status.FAILURE

            result = all(
                client.ui_root.ship_ui is not None and client.ui_root.ship_ui.is_warping is False
                for client in clients
            )
        except Exception as exc:
            self.feedback_message = f"Error reading ship UI: {exc}"
            return Status.FAILURE

        self.feedback_message = str(result)
        return Status.SUCCESS if result else Status.FAILURE

# ============================================================================
# Overview / local state checks
# ============================================================================

class IsLocalDangerous(EveBehaviour):
    """
    SUCCESS if local contains neutral or hostile characters.

    Missing local chat is treated as dangerous to avoid false Negatives.
    """

    def __init__(self, name: str = "Local Dangerous?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            client0 = self.get_main_client()
            chat_channels = client0.ui_root.chat_windows or []
        except Exception as exc:
            self.feedback_message = f"Error reading chat windows: {exc}"
            return Status.SUCCESS

        local_channel = next(
            (channel for channel in chat_channels if "Local" in getattr(channel, "channel_name", "")),
            None,
        )

        if local_channel is None:
            self.feedback_message = "Local chat not found -> unsafe"
            return Status.SUCCESS

        hostile_present = any(
            member.standings in (CharacterStandings.RED, CharacterStandings.NEUTRAL)
            for member in local_channel.members
        )

        self.feedback_message = f"hostile_present={hostile_present}"
        return Status.SUCCESS if hostile_present else Status.FAILURE

class IsEnemiesPresent(EveBehaviour):
    """
    SUCCESS if a known site NPC is present in the main client's overview.
    """

    def __init__(self, name: str = "Enemies Present?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            client0 = self.get_main_client()
            if len(client0.ui_root.overviews) != 1:
                self.feedback_message = "Expected exactly one overview window"
                return Status.FAILURE

            overview = client0.ui_root.overviews[0]
        except Exception as exc:
            self.feedback_message = f"Error reading overview: {exc}"
            return Status.FAILURE

        for entry in overview.entries:
            entry_name = entry.fields.get("Name", "")
            if "Pith" in entry_name or "Dread Guristas" in entry_name:
                self.feedback_message = f"Found enemy: {entry_name}"
                return Status.SUCCESS

        self.feedback_message = "No known site enemies visible"
        return Status.FAILURE

class IsDreadNpcPresent(EveBehaviour):
    """
    SUCCESS if a dreadnought is visible in the main client's overview.

    This node is intentionally pure: it only senses. Notification is handled by
    a separate action node.
    """

    def __init__(self, name: str = "Dread NPC Present?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            client0 = self.get_main_client()
            if len(client0.ui_root.overviews) != 1:
                self.feedback_message = "Expected exactly one overview window"
                return Status.FAILURE

            overview = client0.ui_root.overviews[0]
        except Exception as exc:
            self.feedback_message = f"Error reading overview: {exc}"
            return Status.FAILURE

        for entry in overview.entries:
            entry_name = entry.fields.get("Name", "")
            if "Dreadnought" in entry_name:
                self.feedback_message = f"Found dread: {entry_name}"
                return Status.SUCCESS

        self.feedback_message = "No dread visible"
        return Status.FAILURE

class IsDreadGuristaNpcPresent(EveBehaviour):
    """
    SUCCESS if a known site NPC is present in the main client's overview.
    """

    def __init__(self, name: str = "Enemies Present?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            client0 = self.get_main_client()
            if len(client0.ui_root.overviews) != 1:
                self.feedback_message = "Expected exactly one overview window"
                return Status.FAILURE

            overview = client0.ui_root.overviews[0]
        except Exception as exc:
            self.feedback_message = f"Error reading overview: {exc}"
            return Status.FAILURE

        for entry in overview.entries:
            entry_name = entry.fields.get("Name", "")
            if "Dread Guristas" in entry_name:
                self.feedback_message = f"Found enemy: {entry_name}"
                return Status.SUCCESS

        self.feedback_message = "No Dread Guristas visible"
        return Status.FAILURE

class IsAnyClientStuckWithDread(EveBehaviour):
    """
    SUCCESS if any client still has a dreadnought in overview.

    When a stuck client is found, its index is written to:
        bot.stuck_client
    """

    def __init__(self, name: str = "Any Client Stuck With Dread?") -> None:
        super().__init__(name=name)
        self.register_reads("eve_clients")
        self.register_writes("stuck_client")

    def update(self) -> Status:
        try:
            clients = self.get_clients()
        except Exception as exc:
            self.feedback_message = f"Error reading clients: {exc}"
            return Status.FAILURE

        for index, client in enumerate(clients):
            if len(client.ui_root.overviews) != 1:
                self.feedback_message = "Expected exactly one overview per client"
                return Status.FAILURE

            overview = client.ui_root.overviews[0]
            for entry in overview.entries:
                entry_name = entry.fields.get("Name", "")
                if "Dreadnought" in entry_name:
                    self.blackboard.set("stuck_client", index, overwrite=True)
                    self.feedback_message = f"stuck_client={index}"
                    return Status.SUCCESS

        self.feedback_message = "No stuck client"
        return Status.FAILURE

# ============================================================================
# Module Activation Behavior
# ============================================================================

class ActivateModuleAcrossClients(EveBehaviour):
    """
    Activate one or more module types across a selected client slice.
    """

    def __init__(
        self,
        module_type_ids: Iterable[int],
        start_client_index: int = 0,
        end_client_index: int | None = None,
        name: str = "Activate Modules Across Clients",
    ) -> None:
        super().__init__(name=name)
        self.module_type_ids = set(module_type_ids)
        self.start_client_index = start_client_index
        self.end_client_index = end_client_index
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            clients = self.get_clients()[self.start_client_index:self.end_client_index]
        except Exception as exc:
            self.feedback_message = f"Error reading clients: {exc}"
            return Status.FAILURE

        activated_count = 0

        for client in clients:
            ship_ui = client.ui_root.ship_ui
            if ship_ui is None:
                self.feedback_message = "Ship UI not found"
                return Status.FAILURE

            matching_modules = [
                module
                for module in ship_ui.module_buttons
                if module.module_type_id in self.module_type_ids
            ]

            for module in matching_modules:
                if module.is_active:
                    continue

                client.input_handler.mouse_click(*module.button_node.clickable_location)
                activated_count += 1

        self.feedback_message = f"activated={activated_count}"
        return Status.SUCCESS

class InitiateWarpToSite(EveBehaviour):
    """
    Right-click the nearest matching probe result and choose the fleet warp entry.
    """

    def __init__(
        self,
        site_name: str,
        menu_entry_text: str = "warp fleet (relative)",
        min_distance_au: float = 0.1,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"Warp To Site: {site_name}")
        self.site_name = site_name
        self.menu_entry_text = menu_entry_text
        self.min_distance_au = min_distance_au
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            client0 = self.get_main_client()
            probe_window = client0.ui_root.probe_window
        except Exception as exc:
            self.feedback_message = f"Error reading probe window: {exc}"
            return Status.FAILURE

        if probe_window is None:
            self.feedback_message = "Probe window not found"
            return Status.FAILURE

        entries = [
            entry
            for entry in probe_window.entries
            if self.site_name.lower() in entry.name.lower() and entry.distance > self.min_distance_au
        ]

        if not entries:
            self.feedback_message = f"No matching site found: {self.site_name}"
            return Status.FAILURE

        nearest = min(entries, key=lambda entry: entry.distance)

        client0.input_handler.mouse_click(
            *nearest.node.clickable_location,
            button=InputController.MouseButton.RIGHT,
        )

        warp_entry = wait_for_context_menu_entry(
            client=client0,
            entry_text=self.menu_entry_text,
        )
        if warp_entry is None:
            self.feedback_message = f"Context menu entry not found: {self.menu_entry_text}"
            return Status.FAILURE

        time.sleep(0.1)
        client0.input_handler.mouse_click(*warp_entry.node.clickable_location)

        self.feedback_message = f"Warp initiated to {nearest.name}"
        return Status.SUCCESS

class InitiateWarpToBookmark(EveBehaviour):
    """
    Right-click a bookmark in the locations window and choose the fleet warp entry.
    """

    def __init__(
        self,
        bookmark_name: str,
        menu_entry_text: str = "warp fleet (relative) to location",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"Warp To Bookmark: {bookmark_name}")
        self.bookmark_name = bookmark_name
        self.menu_entry_text = menu_entry_text
        self.register_reads("eve_clients")

    def update(self) -> Status:
        try:
            client0 = self.get_main_client()
            locations_window = client0.ui_root.locations
        except Exception as exc:
            self.feedback_message = f"Error reading locations window: {exc}"
            return Status.FAILURE

        if locations_window is None:
            self.feedback_message = "Locations window not found"
            return Status.FAILURE

        location = next(
            (entry for entry in locations_window.entries if entry.name == self.bookmark_name),
            None,
        )
        if location is None:
            self.feedback_message = f"Bookmark not found: {self.bookmark_name}"
            return Status.FAILURE

        client0.input_handler.mouse_click(
            *location.node.clickable_location,
            button=InputController.MouseButton.RIGHT,
        )

        warp_entry = wait_for_context_menu_entry(
            client=client0,
            entry_text=self.menu_entry_text,
        )
        if warp_entry is None:
            self.feedback_message = f"Context menu entry not found: {self.menu_entry_text}"
            return Status.FAILURE

        time.sleep(0.25)
        client0.input_handler.mouse_click(*warp_entry.node.clickable_location)

        self.feedback_message = f"Warp initiated to bookmark {self.bookmark_name}"
        return Status.SUCCESS