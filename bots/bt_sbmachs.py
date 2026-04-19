from __future__ import annotations

import asyncio
import time

import py_trees
from py_trees.common import Access

from interface.client.eve_client import EvEClient
from behavioral_tree.bt_nodes import (
    BOT_BLACKBOARD_NAMESPACE,
    ActivateModuleAcrossClients,
    Delay,
    InitiateWarpToBookmark,
    InitiateWarpToSite,
    IsAllClientsNotWarping,
    IsAnyClientWarping,
    IsCurrentTimePast,
    IsDreadNpcPresent,
    IsDreadGuristaNpcPresent,
    AreAllShipUIsReadable,
    IsSiteClearForDuration,
    IsLocalDangerous,
    PauseUntilInput,
    PrintMessage,
    SendDiscordWebhook,
    SetBlackboardValue,
    SetCurrentTime,
    SetRandomDeadlineFromNow,
)

###########################################################
### Module / EvE Constants
###########################################################

_WARP_STAB_MODULE_IDS = [11640]
_SMARTBOMB_MODULE_IDS = [15931]


###########################################################
### Macharial Smartbomb Bot
###########################################################

class SmartbombBot:
    """
        Smartbomb Mach behavior tree.

        Responsibilities of this class:
        - own the EVE client objects
        - seed the blackboard with shared bot state
        - construct the py_trees behavior tree
        - tick the tree in a loop while refreshing the UI in parallel
        """

    def __init__(
            self,
            client_names: list[str],
            discord_url: str,
            bookmark_name: str = "Safe (1)",
            site_name: str = "haven",
            shutdown_time: int = 60 * 60 * 4,
            min_break_time: int = int(60 * 60 * 1.5),
            max_break_time: int = int(60 * 60 * 2.5),
            tick_interval: float = 0.25,
            debug_mode: bool = False,
            debug_tree_interval: float = 1.0,
    ) -> None:
        self.clients = []

        for name in client_names:
            client = EvEClient(name)
            self.clients.append(client)

        for client in self.clients:
            client.ui_tree.resume_reader()

        self.discord_url = discord_url
        self.bookmark_name = bookmark_name
        self.site_name = site_name

        self.shutdown_time = shutdown_time
        self.min_break_time = min_break_time
        self.max_break_time = max_break_time
        self.tick_interval = tick_interval

        self.debug_mode = debug_mode
        self.debug_tree_interval = debug_tree_interval
        self._next_debug_tree_print = 0.0
        self.snapshot_visitor = None

        # Single blackboard client for seeding shared runtime state.
        self.blackboard = py_trees.blackboard.Client(
            name="SmartbombBot Blackboard",
            namespace=BOT_BLACKBOARD_NAMESPACE,
        )
        self._register_blackboard_keys()
        self._seed_static_blackboard_values()

        self.behaviour_tree = py_trees.trees.BehaviourTree(self.create_tree())

        if self.debug_mode:
            self.snapshot_visitor = py_trees.visitors.SnapshotVisitor()
            self.behaviour_tree.visitors.append(self.snapshot_visitor)


###########################################################
### Blackboard setup
###########################################################

    def _register_blackboard_keys(self) -> None:
        """Register the keys this runner writes to on the shared blackboard."""
        for key in (
            "eve_clients",
            "discord_url",
            "bookmark_name",
            "running",
            "start_time",
            "last_break",
            "next_break_deadline",
            "shutdown_deadline",
            "dread_notified",
            "stuck_client",
        ):
            self.blackboard.register_key(key=key, access=Access.WRITE)

    def _seed_static_blackboard_values(self) -> None:
        """
        Seed values that are known before the tree starts ticking.

        Dynamic timing values such as start_time and deadlines are initialized
        by the startup subtree so that they begin when the operator actually
        starts the bot.
        """
        self.blackboard.set("eve_clients", self.clients, overwrite=True)
        self.blackboard.set("discord_url", self.discord_url, overwrite=True)
        self.blackboard.set("bookmark_name", self.bookmark_name, overwrite=True)
        self.blackboard.set("running", True, overwrite=True)
        self.blackboard.set("dread_notified", False, overwrite=True)
        self.blackboard.set("stuck_client", None, overwrite=True)

###########################################################
### SB-Bot Specific Nodes and Tree Building helper.
###########################################################

    @staticmethod
    def _success(name: str) -> py_trees.behaviour.Behaviour:
        """Convenience wrapper for an always-success leaf."""
        return py_trees.behaviours.Success(name=name)

    @staticmethod
    def _running(name: str) -> py_trees.behaviour.Behaviour:
        """Convenience wrapper for an always-running leaf."""
        return py_trees.behaviours.Running(name=name)

    def _wait_until_local_safe(self) -> py_trees.behaviour.Behaviour:
        """
        Return RUNNING while local is unsafe, SUCCESS once it becomes clear.

        Replacing old retry startup logic to keep it in the bt.

        #TODO Probably worth adding a randomized waiting time after local is clear.
        """
        root = py_trees.composites.Selector(name="Wait Until Local Safe", memory=False)
        root.add_children(
            [
                py_trees.decorators.Inverter(
                    name="Local Is Safe?",
                    child=IsLocalDangerous(),
                ),
                self._running("Waiting For Local To Become Safe"),
            ]
        )
        return root

    def _retry_until_success(
            self,
            child: py_trees.behaviour.Behaviour,
            timeout: float,
            name: str,
    ) -> py_trees.behaviour.Behaviour:
        """
        Keep retrying a child until it succeeds or the timeout expires.

        This is useful for UI actions, because the parsed UI can temporarily be
        unavailable for one tick.
        """
        retry_selector = py_trees.composites.Selector(
            name=f"{name} Retry Selector",
            memory=False,
        )
        retry_selector.add_children(
            [
                child,
                self._running(f"Retrying: {name}"),
            ]
        )

        return py_trees.decorators.Timeout(
            name=f"{name} Timeout ({timeout:.0f}s)",
            child=retry_selector,
            duration=timeout,
        )

    def _wait_until_ship_uis_readable(self) -> py_trees.behaviour.Behaviour:
        """
        Wait until every configured client exposes a readable ShipUI.

        This returns RUNNING while some clients are unreadable instead of failing
        the startup sequence and causing the OneShot startup to restart.
        """
        wait = py_trees.composites.Selector(
            name="Wait Until Ship UIs Readable",
            memory=False,
        )
        wait.add_children(
            [
                AreAllShipUIsReadable(),
                self._running("Waiting For Ship UIs To Become Readable"),
            ]
        )
        return wait

    def _wait_until_any_client_warping(self, timeout: float) -> py_trees.behaviour.Behaviour:
        """
        Wait until at least one client enters warp.

        A timeout is used here because hanging forever usually means the click
        or context-menu interaction failed.
        """
        wait_subtree = py_trees.composites.Selector(name="Wait For Warp Start", memory=False)
        wait_subtree.add_children(
            [
                IsAnyClientWarping(),
                self._running("Warp Not Started Yet"),
            ]
        )

        return py_trees.decorators.Timeout(
            name=f"Warp Start Timeout ({timeout:.0f}s)",
            child=wait_subtree,
            duration=timeout,
        )

    def _wait_until_all_clients_not_warping(self, timeout: float) -> py_trees.behaviour.Behaviour:
        """
        Wait until all clients are confirmed to no longer be warping.

        If detection times out, do NOT fail upward and restart the work branch.
        Instead, pause for manual confirmation. This avoids the dangerous behaviour
        where the bot lands in a site, fails to detect arrival, and then warps to
        another site.
        """
        wait_subtree = py_trees.composites.Selector(
            name="Wait For Warp Finish",
            memory=False,
        )
        wait_subtree.add_children(
            [
                IsAllClientsNotWarping(),
                self._running("Still Warping"),
            ]
        )

        automatic_wait = py_trees.decorators.Timeout(
            name=f"Warp Finish Timeout ({timeout:.0f}s)",
            child=wait_subtree,
            duration=timeout,
        )

        manual_recovery = py_trees.composites.Sequence(
            name="Manual Warp Finish Confirmation",
            memory=True,
        )
        manual_recovery.add_children(
            [
                PrintMessage(
                    "Warp finish detection timed out. "
                    "Check whether all ships have landed."
                ),
                PauseUntilInput("If all ships are out of warp, press Enter to continue..."),
            ]
        )

        root = py_trees.composites.Selector(
            name="Wait For Warp Finish Or Manual Confirm",
            memory=False,
        )
        root.add_children(
            [
                automatic_wait,
                manual_recovery,
            ]
        )

        return root

    def _wait_until_site_clear(self, timeout: float) -> py_trees.behaviour.Behaviour:
        """
        Wait until the site appears clear for a stable duration.

        This replaces the old single-check inverter logic. A missing/unreadable
        overview now means "keep waiting", not "site complete".
        """
        return py_trees.decorators.Timeout(
            name=f"Site Clear Timeout ({timeout:.0f}s)",
            child=IsSiteClearForDuration(clear_duration=5.0),
            duration=timeout,
        )


    #TODO
    def _handle_dread(self) -> py_trees.behaviour.Behaviour:
        """
        Handle spawning of a dread.

        Ensure safe warping off of all BS.

        Note: Separating previous behavior into sense / act.
        """
        dread_sequence = py_trees.composites.Sequence(name="Handle Dreadnought", memory=False)
        dread_sequence.add_children(
            [
                IsDreadNpcPresent(),
                SendDiscordWebhook("Dreadnought spawn detected!"),
                ActivateModuleAcrossClients(module_type_ids=_WARP_STAB_MODULE_IDS),
            ]
        )

        root = py_trees.composites.Selector(name="Handle Dreadnought", memory=False)
        root.add_children(
            [
                dread_sequence,
                self._success("No Dreadnought Response Needed"),
            ]
        )
        return root

    #TODO
    def _handle_guristas(self) -> py_trees.behaviour.Behaviour:
        """
        Handle spawning of a Dread gurista.
        """
        gurista_sequence = py_trees.composites.Selector(name="Handle Gurista", memory=False)
        gurista_sequence.add_children(
            [
                IsDreadGuristaNpcPresent(),
                SendDiscordWebhook("Dread Gurista spawn detected!")
                # A: Drop BM
                # B: Drop MTU + BM
                # C: Loot Wreck after Kill
            ]
        )

        root = py_trees.composites.Selector(name="Handle Gurista", memory=False)
        root.add_children(
            [
                gurista_sequence,
                self._success("No Dread Guristas Response Needed"),
            ]
        )
        return root

    ###########################################################
    ### SB-Bot Specific Subtrees
    ###########################################################

    def _create_startup_subtree(self) -> py_trees.behaviour.Behaviour:
        """
        Startup should happen exactly once.

        Wrapped in a OneShot decorator so it does not run again every time the
        root later returns SUCCESS after completing a site or a break.
        """
        startup = py_trees.composites.Sequence(name="Startup Sequence", memory=True)
        startup.add_children(
            [
                PrintMessage("Smartbomb bot ready."),
                PauseUntilInput("Press Enter to start the bot..."),

                PrintMessage("Ensuring no hostiles are present before starting..."),
                self._wait_until_local_safe(),

                PrintMessage("Checking ship UI readability..."),
                self._wait_until_ship_uis_readable(),

                SetCurrentTime("start_time"),
                SetCurrentTime("last_break"),
                SetBlackboardValue(
                    "shutdown_deadline",
                    lambda: time.time() + self.shutdown_time,
                ),
                SetRandomDeadlineFromNow(
                    key="next_break_deadline",
                    min_delay=self.min_break_time,
                    max_delay=self.max_break_time,
                ),
                PrintMessage("Startup complete."),
            ]
        )

        return py_trees.decorators.OneShot(
            name="Startup Once",
            child=startup,
            policy=py_trees.common.OneShotPolicy.ON_SUCCESSFUL_COMPLETION,
        )

    def _create_escape_subtree(self) -> py_trees.behaviour.Behaviour:
        """Abort the current activity and warp the fleet to the safe bookmark."""
        escape = py_trees.composites.Sequence(name="Escape Sequence", memory=True)
        escape.add_children(
            [
                self._handle_dread(),
                InitiateWarpToBookmark(bookmark_name=self.bookmark_name),
                self._wait_until_any_client_warping(timeout=3),
                self._wait_until_all_clients_not_warping(timeout=90),
            ]
        )
        return escape

    def _create_warp_to_site_subtree(self) -> py_trees.behaviour.Behaviour:
        """Warp to the target ratting site and wait for the fleet to arrive."""
        warp = py_trees.composites.Sequence(name="Warp To Site", memory=True)
        warp.add_children(
            [
                self._handle_dread(),
                InitiateWarpToSite(site_name=self.site_name),
                self._wait_until_any_client_warping(timeout=10),
                self._wait_until_all_clients_not_warping(timeout=90),
            ]
        )
        return warp

    def _create_complete_site_subtree(self) -> py_trees.behaviour.Behaviour:
        """
        Complete the active site.

        This preserves the broad old behavior:
        - small delay after landing
        - activate smartbombs on non-warping-anchor clients
        - do not check for completion immediately
        - then wait until the overview no longer shows known enemies
        """
        complete = py_trees.composites.Sequence(name="Complete Site", memory=True)
        complete.add_children(
            [
                Delay(5, name="Short Landing Delay"),
                self._retry_until_success(
                    child=ActivateModuleAcrossClients(
                        module_type_ids=_SMARTBOMB_MODULE_IDS,
                        start_client_index=1,
                        name="Activate Smartbombs",
                    ),
                    timeout=10,
                    name="Activate Smartbombs",
                ),
                Delay(60, name="Do Not Check Completion Too Early"),
                self._wait_until_site_clear(timeout=300),
            ]
        )
        return complete

    def _create_shutdown_branch(self) -> py_trees.behaviour.Behaviour:
        """
        Once the shutdown deadline is reached, the bot escapes and then stops the
        external tick loop by writing running=False.
        """
        shutdown = py_trees.composites.Sequence(name="Shutdown Branch", memory=False)
        shutdown.add_children(
            [
                IsCurrentTimePast("shutdown_deadline"),
                PrintMessage("Shutdown deadline reached."),
                self._create_escape_subtree(),
                SetBlackboardValue("running", False),
                PrintMessage("Smartbomb bot shutting down."),
            ]
        )
        return shutdown

    def _create_break_branch(self) -> py_trees.behaviour.Behaviour:
        """
        Break branch.

        (Importantly resets break time afterwards)
        """
        break_branch = py_trees.composites.Sequence(name="Break Branch", memory=False)
        break_branch.add_children(
            [
                IsCurrentTimePast("next_break_deadline"),
                PrintMessage("Break time reached."),
                self._create_escape_subtree(),
                PauseUntilInput("Take a break, then press Enter to continue..."),
                SetCurrentTime("last_break"),
                SetRandomDeadlineFromNow(
                    key="next_break_deadline",
                    min_delay=self.min_break_time,
                    max_delay=self.max_break_time,
                ),
                PrintMessage("Break complete."),
            ]
        )
        return break_branch

    def _create_local_danger_branch(self) -> py_trees.behaviour.Behaviour:
        """
        Safety branch for hostiles in local.

        This is intentionally above breaks and work so it preempts those branches.
        """
        danger = py_trees.composites.Sequence(name="Local Danger Branch", memory=False)
        danger.add_children(
            [
                IsLocalDangerous(),
                PrintMessage("Hostiles detected in local. Escaping."),
                self._create_escape_subtree(),
                PrintMessage("Verify safety, then press Enter to continue."),
                PauseUntilInput(),
            ]
        )
        return danger



    def _create_work_branch(self) -> py_trees.behaviour.Behaviour:
        """
        Main work branch.

        Because this is a sequence with memory=True, it can stay inside the
        current multi-step task instead of restarting from the top every tick.
        """
        work = py_trees.composites.Sequence(name="Work Branch", memory=True)
        work.add_children(
            [
                self._create_warp_to_site_subtree(),
                self._create_complete_site_subtree(),
            ]
        )
        return work

    ###########################################################
    ### Root creation
    ###########################################################

    def create_tree(self) -> py_trees.behaviour.Behaviour:
        """
        Build the full smartbomb bot tree.

        Root structure:
        - startup once
        - then repeatedly evaluate a global priority selector

        Selector order matters:
        1. shutdown
        2. local danger
        3. break
        4. work
        """
        priority_selector = py_trees.composites.Selector(
            name="Priority Selector",
            memory=False,
        )
        priority_selector.add_children(
            [
                self._create_shutdown_branch(),
                self._create_local_danger_branch(),
                self._create_break_branch(),
                self._create_work_branch(),
            ]
        )

        root = py_trees.composites.Sequence(name="Smartbomb Mach Root", memory=True)
        root.add_children(
            [
                self._create_startup_subtree(),
                priority_selector,
            ]
        )
        return root


    ###########################################################
    ### Runtime Loop
    ###########################################################

    def _debug_print_tree(self) -> None:
        """
        Print the currently visited part of the behavior tree.

        This is intentionally rate-limited, otherwise the console becomes useless
        because the bot ticks several times per second.
        """
        if not self.debug_mode or self.snapshot_visitor is None:
            return

        now = time.monotonic()
        if now < self._next_debug_tree_print:
            return

        self._next_debug_tree_print = now + self.debug_tree_interval

        print()
        print("[DEBUG] Current behavior tree state:")
        print(
            py_trees.display.unicode_tree(
                root=self.behaviour_tree.root,
                show_only_visited=True,
                show_status=True,
                visited=self.snapshot_visitor.visited,
                previously_visited=self.snapshot_visitor.previously_visited,
            )
        )

    #TODO: refreshing the ui_tree should be done in threads rather then subsequential

    async def refresh_ui_tree_loop(self) -> None:
        """Continuously refresh the parsed UI trees for all clients."""
        while self.blackboard.running:
            for client in self.clients:
                try:
                    client.ui_tree.refresh()
                except Exception as exc:
                    if self.debug_mode:
                        print(
                            f"[DEBUG] UI refresh failed for "
                            f"{client.client_name}: {exc}"
                        )

            await asyncio.sleep(0.1)

    def logic_loop(self) -> None:
        """
        Tick the behavior tree until the blackboard says the bot should stop.

        Important:
        `behaviour_tree.setup()` must not happen here because this function runs
        in a worker thread via asyncio.to_thread(), and py_trees.setup() uses
        Python signal handling.
        """
        while self.blackboard.running:
            self.behaviour_tree.tick()
            self._debug_print_tree()
            time.sleep(self.tick_interval)

    async def run(self) -> None:
        """
        Run both the UI refresh loop and the behavior-tree logic loop.

        The behavior tree must be set up from the main thread before the logic loop
        is moved into a worker thread.
        """
        self.behaviour_tree.setup(timeout=15)

        refresh_task = asyncio.create_task(self.refresh_ui_tree_loop())
        logic_task = asyncio.create_task(asyncio.to_thread(self.logic_loop))

        await asyncio.gather(refresh_task, logic_task)