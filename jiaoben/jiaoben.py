import asyncio
import random
import time
from typing import List

from client.eve_client import EveClient
from client.input_controller import InputController
from eve_ui.chat_window import CharacterStandings
from jiaoben.behavior_tree import Blackboard, Sequence, Node, NodeStatus, RepeatUntilSuccess, Inverter, Sleep, \
    RepeatUntilNSuccess, Repeat, PrioritySelector, ConditionalSequence, SetBlackboardValue

_WARP_STAB_MODULE_IDS = [11640]
_SMARTBOMB_MODULE_IDS = [15931]

class Utils:
    @staticmethod
    def wait_for_context_menu_entry(client: EveClient, entry_text: str, timeout: float = 3.0, poll_interval: float = 0.05):
        """
        Waits for a specific context menu entry to appear.

        Polls the client's UI for up to `timeout` seconds. Returns the
        ContextMenuEntry whose text matches entry_text (case-insensitive,
        trimmed) or None if not found within the timeout.

        Args:
            client: the client to poll.
            entry_text: the text of the menu entry to wait for.
            timeout: maximum time to wait in seconds (default 3.0).
            poll_interval: how long to sleep between polls in seconds.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                context_menus = client.ui_root.context_menus or []
            except Exception:
                context_menus = []

            for menu in context_menus:
                if menu.node.x < 20 or menu.node.y < 0:
                    continue  # it spawns offscreen for a split second, ignore it

                entries = getattr(menu, "entries", []) or []
                for entry in entries:
                    text = getattr(entry, "text", "") or ""
                    if entry_text.lower() in text.strip().lower():
                        print(f"Found menu entry: {entry_text} at location ({entry.node.center})")
                        return entry
            time.sleep(poll_interval)
        return None

class Print(Node):
    def __init__(self, blackboard: Blackboard, text: str):
        super().__init__(blackboard)
        self.text = text

    def tick(self) -> NodeStatus:
        print(self.text)
        return NodeStatus.SUCCESS


class PauseUntilInput(Node):
    """
    Pauses the behavior tree until the user presses the enter key.
    """
    def tick(self) -> NodeStatus:
        input()
        return NodeStatus.SUCCESS


class IsAllClientsWarping(Node):
    """
    Returns Success if all clients are warping, as indicated by the
    text on the speed-meter.
    """
    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        if all(client.ui_root.ship_ui.is_warping for client in clients):
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


class IsAllClientsNotWarping(Node):
    """
    Returns Success if all clients are not warping, as indicated by the
    text on the speed-meter.
    """
    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        if all(client.ui_root.ship_ui.is_warping is False for client in clients):
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


class IsAnyClientWarping(Node):
    """
    Returns Success if any client is warping, as indicated by the
    text on the speed-meter.
    """
    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        if any(client.ui_root.ship_ui.is_warping for client in clients):
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

class InitiateWarpToSite(Node):
    def __init__(self, blackboard: Blackboard, site_name: str):
        super().__init__(blackboard)
        self.site_name = site_name

    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        client0 = clients[0]
        probe_window = client0.ui_root.probe_window

        if not probe_window:
            print("[ALERT] Probe window not found.")
            return NodeStatus.FAILURE

        entries = [entry for entry in probe_window.entries
                   if self.site_name.lower() in entry.name.lower()
                   and entry.distance > 0.1]

        if not entries:
            print("[ALERT] No sites found.")
            return NodeStatus.FAILURE

        entries.sort(key=lambda entry: entry.distance)
        nearest = entries[0]
        client0.input_handler.mouse_click(*nearest.node.clickable_location, button=InputController.MouseButton.RIGHT)

        if not (warp_button := Utils.wait_for_context_menu_entry(client0, "warp fleet (relative)")):
            print("[ALERT] Warp button not found.")
            return NodeStatus.FAILURE

        # todo: Verify that the site we clicked is actually a haven, to prevent
        # todo: awkward scenario where a new site spawns while we're clicking.

        time.sleep(0.1)

        client0.input_handler.mouse_click(*warp_button.node.clickable_location)
        return NodeStatus.SUCCESS


class InitiateWarpToBookmark(Node):
    def __init__(self, blackboard: Blackboard, bookmark_name: str):
        super().__init__(blackboard)
        self.bookmark_name = bookmark_name

    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        client0 = clients[0]
        locations_window = client0.ui_root.locations

        if not locations_window:
            print("[ALERT] Locations window not found.")
            return NodeStatus.FAILURE

        location = next((l for l in locations_window.entries if l.name == self.bookmark_name), None)
        if not location:
            print(f"[ALERT] Bookmark not found. Ensure that the bookmark name is correct: {self.bookmark_name}")
            return NodeStatus.FAILURE

        client0.input_handler.mouse_click(*location.node.clickable_location, button=InputController.MouseButton.RIGHT)

        if not (warp_button := Utils.wait_for_context_menu_entry(client0, "warp fleet (relative) to location")):
            print("[ALERT] Warp button not found.")
            return NodeStatus.FAILURE

        time.sleep(0.25)

        client0.input_handler.mouse_click(*warp_button.node.clickable_location)
        return NodeStatus.SUCCESS


class ActivateModuleAcrossClients(Node):
    def __init__(self, blackboard: Blackboard, module_ids: List[int],
                 start_client_index: int = 0,
                 end_client_index: int = None):
        super().__init__(blackboard)
        self.module_ids = module_ids
        self.start_client_index = start_client_index
        self.end_client_index = end_client_index

    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        print("[INFO] Activating modules across clients")

        for client in clients[self.start_client_index:self.end_client_index]:
            ship_ui = client.ui_root.ship_ui
            if not ship_ui:
                print("[ALERT] Ship UI not found.")
                return NodeStatus.FAILURE

            modules = [module for module in ship_ui.module_buttons
                       if module.module_type_id in self.module_ids]

            for module in modules:
                if module.is_active: continue
                client.input_handler.mouse_click(*module.button_node.clickable_location)

        return NodeStatus.SUCCESS


class IsEnemiesPresent(Node):
    """
    Checks if enemies are present in the overview window. Returns Success if
    a known Guristas Haven enemy is present.
    """
    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        client0 = clients[0]

        if len(client0.ui_root.overviews) > 1:
            print("[ALERT] Multiple overview windows found. Cannot check for enemies.")
            return NodeStatus.FAILURE

        overview = client0.ui_root.overviews[0]
        for entry in overview.entries:
            if ("Pith" in entry.fields.get("Name", "")
                or "Dread Guristas" in entry.fields.get("Name", "")):
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


class IsDreadNPCPresent(Node):
    """
    Checks if a Dreadnought is present in the main client's overview window.
    """
    def __init__(self, blackboard: Blackboard, discord_url: str):
        super().__init__(blackboard)
        self.discord_url = discord_url

    def send_discord_notif(self, message: str):
        """Sends a Discord notification. todo: move"""
        import requests
        requests.post(self.discord_url, json={"content": message})

    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        client0 = clients[0]

        if len(client0.ui_root.overviews) > 1:
            print("[ALERT] Multiple overview windows found. Cannot check for enemies.")
            return NodeStatus.FAILURE

        overview = client0.ui_root.overviews[0]
        for entry in overview.entries:
            if "Dreadnought" in entry.fields.get("Name", ""):
                self.send_discord_notif("Dread spawn detected!")
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


class IsAnyClientStuckWithDread(Node):
    """
    Checks if any client still has a dreadnought in the overview window.
    Places the client index in the blackboard under the key "stuck_client".
    """
    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")

        for i, client in enumerate(clients):
            if len(client.ui_root.overviews) > 1:
                print("[ALERT] Multiple overviews detected, cannot reliably check for dreadnought status.")
                return NodeStatus.FAILURE
            overview = client.ui_root.overviews[0]
            for entry in overview.entries:
                if "Dreadnought" in entry.fields.get("Name", ""):
                    print("[INFO] Client stuck with dreadnought detected.")
                    self.blackboard.set("stuck_client", i)
                    return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


class IsLocalDangerous(Node):
    """Checks if hostiles are in the local system."""
    def tick(self) -> NodeStatus:
        clients: List[EveClient] = self.blackboard.get("clients")
        client0 = clients[0]
        chat_channels = client0.ui_root.chat_windows or []

        if not (channel := next((c for c in chat_channels if "Local" in getattr(c, "channel_name", "")), None)):
            print("[ALERT] Local chat window not found.")
            return NodeStatus.SUCCESS  # No local channel found, assume dangerous

        if any((member for member in channel.members
                if member.standings in (CharacterStandings.RED, CharacterStandings.NEUTRAL))):
            print("[ALERT] Local chat window contains hostile characters.")
            return NodeStatus.SUCCESS

        return NodeStatus.FAILURE


class SetStartTime(Node):
    """Sets the start time of the behavior tree."""
    def tick(self) -> NodeStatus:
        self.blackboard.set("start_time", time.time())
        return NodeStatus.SUCCESS


class IsTimeForBreak(Node):
    """Checks if it's time to take a break."""
    def __init__(self, blackboard: Blackboard,
                 min_break_time: int = 60*60*1.5, max_break_time: int = 60*60*2.5):
        super().__init__(blackboard)
        self.min_break_time = min_break_time
        self.max_break_time = max_break_time
        self.break_time = None

    def tick(self) -> NodeStatus:
        if self.break_time is None:
            self.break_time = random.uniform(self.min_break_time, self.max_break_time)

        last_break = self.blackboard.get("last_break")
        if last_break is None:
            last_break = self.blackboard.get("start_time")
            self.blackboard.set("last_break", last_break)

        if time.time() - last_break > self.break_time:
            self.reset()
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE

    def reset(self):
        self.break_time = None


class IsTimeForShutdown(Node):
    """Checks if it's time to shutdown the system."""
    def __init__(self, blackboard: Blackboard, shutdown_time: int = 60*60*4):
        super().__init__(blackboard)
        self.shutdown_time = shutdown_time

    def tick(self) -> NodeStatus:
        if time.time() - self.blackboard.get("start_time") > self.shutdown_time:
            return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


### Sequence Nodes ###
class WaitForSiteCompletion(Sequence):
    """
    Waits until the site is complete. Does so by checking the overview for
    no known enemies present. Returns Success when no known enemies are
    present for five seconds in a row.

    Has a timeout, after which it will return Failure. This is useful to
    check if for whatever reason the site is taking too long to complete,
    and as such the script should be considered stuck/broken.
    """
    def __init__(self, blackboard: Blackboard, timeout: float = 120):
        super().__init__(
            blackboard=blackboard,
            children=[
                RepeatUntilSuccess(
                    blackboard=blackboard,
                    timeout=timeout,
                    child=RepeatUntilNSuccess(
                        blackboard=blackboard,
                        n=5,
                        child=Sequence(
                            blackboard=blackboard,
                            children=[
                                Inverter(blackboard, IsEnemiesPresent(blackboard)),
                                Sleep(blackboard, 1),
                            ]
                        )
                    )
                )
            ]
        )


class WarpToSiteSequence(Sequence):
    """
    Warps to a specific site by name. Returns success when the warp is complete.
    """
    def __init__(self, blackboard: Blackboard, site_name: str, discord_url: str):
        self.site_name = site_name
        super().__init__(
            blackboard=blackboard,
            children=[
                ConditionalSequence(
                    blackboard,
                    condition=IsDreadNPCPresent(blackboard, discord_url),
                    children=[ActivateModuleAcrossClients(blackboard, module_ids=_WARP_STAB_MODULE_IDS)]
                ),
                InitiateWarpToSite(blackboard, "haven"),
                RepeatUntilSuccess(blackboard, IsAnyClientWarping(blackboard), timeout=10),
                RepeatUntilSuccess(blackboard, IsAllClientsNotWarping(blackboard), timeout=90),
            ]
        )


class CompleteSiteSequence(Sequence):
    """
    Logic to complete the site, returns Success when the site is complete.
    """
    def __init__(self, blackboard: Blackboard):
        super().__init__(
            blackboard=blackboard,
            children=[
                Sleep(blackboard, 5),  # short delay to make sure no lag
                # Activate smartbomb modules...
                ActivateModuleAcrossClients(blackboard, module_ids=_SMARTBOMB_MODULE_IDS, start_client_index=1),
                # Enemies don't spawn for a while, only begin checking for site completion
                # after 60 seconds...
                Sleep(blackboard, duration=60),
                WaitForSiteCompletion(blackboard, timeout=300) # 5 minutes
            ]
        )


class EscapeSequence(Sequence):
    """
    Logic to abort the current site and escape to the safe location.
    """
    def __init__(self, blackboard: Blackboard, bookmark_name: str, discord_url: str):
        super().__init__(
            blackboard=blackboard,
            children=[
                ConditionalSequence(
                    blackboard=blackboard,
                    condition=IsDreadNPCPresent(blackboard, discord_url),
                    children=[ActivateModuleAcrossClients(blackboard, module_ids=_WARP_STAB_MODULE_IDS)]
                ),
                InitiateWarpToBookmark(blackboard, bookmark_name),
                RepeatUntilSuccess(blackboard, IsAnyClientWarping(blackboard), timeout=3),
                RepeatUntilSuccess(blackboard, Inverter(blackboard, IsAllClientsWarping(blackboard)), timeout=90)
            ]
        )


class LocalWatchdogSequence(Sequence):
    """
    Logic to monitor the local system for hostiles and escape if present.
    """
    def __init__(self, blackboard: Blackboard, bookmark_name: str, discord_url: str):
        super().__init__(
            blackboard=blackboard,
            children=[
                IsLocalDangerous(blackboard),
                EscapeSequence(blackboard, bookmark_name, discord_url),
                Print(blackboard, "Verify safety and press enter to continue."),
                PauseUntilInput(blackboard)
            ]
        )


class BreakSequence(ConditionalSequence):
    def __init__(self, blackboard: Blackboard):
        super().__init__(
            blackboard=blackboard,
            condition=IsTimeForBreak(blackboard),
            children=[
                Print(blackboard, "Time for a break!"),
                PauseUntilInput(blackboard)
            ]
        )


class SmartbombRoot(Sequence):
    def __init__(self, blackboard: Blackboard, discord_url: str, bookmark_name: str = "Safe (1)",
                 shutdown_time: int = 60*60*4, min_break_time: int = 60*60*1.5,
                 max_break_time: int = 60*60*2.5):
        super().__init__(
            blackboard=blackboard,
            children=[
                Sequence(
                    blackboard=blackboard,
                    children=[
                        Print(blackboard, "Jiaoben ready, press enter to start."),
                        PauseUntilInput(blackboard),

                        Print(blackboard, "Ensuring no hostiles are present..."),
                        RepeatUntilSuccess(blackboard, Inverter(blackboard, IsLocalDangerous(blackboard))),

                        SetStartTime(blackboard),

                        Repeat(blackboard, child=Sequence(blackboard, children=[
                            # Flag shutdown
                            ConditionalSequence(
                                blackboard=blackboard,
                                condition=IsTimeForShutdown(blackboard, shutdown_time),
                                children=[
                                    EscapeSequence(blackboard, bookmark_name, discord_url),
                                    SetBlackboardValue(blackboard, "running", False)
                                ]
                            ),

                            # Take a break if necessary
                            ConditionalSequence(
                                blackboard=blackboard,
                                condition=IsTimeForBreak(blackboard, min_break_time, max_break_time),
                                children=[
                                    EscapeSequence(blackboard, bookmark_name, discord_url),
                                    Print(blackboard, "Time to take a break..."),
                                    PauseUntilInput(blackboard)
                                ]
                            ),

                            # Execute main logic
                            WarpToSiteSequence(blackboard, "guristas haven", discord_url),
                            PrioritySelector(blackboard, children=[
                                LocalWatchdogSequence(blackboard, bookmark_name, discord_url),
                                CompleteSiteSequence(blackboard)
                            ])
                        ]))
                    ]
                )
            ]
        )


class SmartbombJiaoben:
    def __init__(self, client_names: list[str], discord_url: str, bookmark_name: str = "Safe (1)"):
        """
        :param client_names: List of client names, first is the fleet warper.
        :param bookmark_name: Name of the escape bookmark.
        """
        self.bookmark_name = bookmark_name
        self.clients = [EveClient(name) for name in client_names]
        self.discord_url = discord_url

    async def refresh_ui_tree_loop(self):
        """Continuously refreshes the UI tree of all clients."""
        while True:
            for client in self.clients:
                client.ui_tree.refresh()
            await asyncio.sleep(0.1)

    def logic_loop(self):
        """Controls the logic of the jiaoben."""
        bb = Blackboard()
        bb.set("clients", self.clients)
        bb.set("bookmark_name", self.bookmark_name)
        bt = SmartbombRoot(bb, bookmark_name=self.bookmark_name, discord_url=self.discord_url)

        bb.set("running", True)
        while bb.get("running"):
            bt.tick()
            # try:
            #     bt.tick()
            # except Exception as e:
            #     print(f"[ERROR] {e}")
            time.sleep(0.25)
        print("Jiaoben shutting down.")

    async def run(self):
        """Runs the jiaoben."""
        # schedule both coroutines without awaiting the tasks immediately
        refresh_task = asyncio.create_task(self.refresh_ui_tree_loop())
        logic_task = asyncio.create_task(asyncio.to_thread(self.logic_loop))

        # keep the run method alive while tasks run
        await asyncio.gather(refresh_task, logic_task)