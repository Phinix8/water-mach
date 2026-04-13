import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, List, Callable, Optional


class Blackboard:
    """Shared data between nodes"""
    def __init__(self):
        self.data = {}

    def get(self, k: str, default=None) -> Any:
        return self.data.get(k, default)

    def set(self, k: str, v):
        self.data[k] = v

    def has(self, k: str) -> bool:
        return k in self.data

    def clear(self, k: str):
        self.data.pop(k, None)

    def reset(self):
        self.data.clear()

    def keys(self) -> List[str]:
        return list(self.data.keys())


class NodeStatus(Enum):
    """Return status for behavior tree nodes"""
    SUCCESS = 0
    FAILURE = 1
    RUNNING = 2


class Node(ABC):
    """Base class for behavior tree nodes"""
    def __init__(self, blackboard: Blackboard):
        self.blackboard = blackboard

    @abstractmethod
    def tick(self) -> NodeStatus:
        """Called each bot logic tick to execute the node's behavior"""

    def reset(self):
        """Optional override for node cleanup"""


# =================================================================
# Composite Nodes
# =================================================================
class Sequence(Node):
    """Executes children in order until one returns failure, or all succeed"""
    def __init__(self, blackboard: Blackboard, children: List[Node]):
        super().__init__(blackboard)
        self.children = children
        self.current_child = 0

    def tick(self) -> NodeStatus:
        while self.current_child < len(self.children):
            status = self.children[self.current_child].tick()

            match status:
                case NodeStatus.SUCCESS:
                    self.current_child += 1
                case NodeStatus.FAILURE:
                    self.reset()
                    return NodeStatus.FAILURE
                case NodeStatus.RUNNING:
                    return NodeStatus.RUNNING

        self.reset()
        return NodeStatus.SUCCESS

    def reset(self):
        for child in self.children:
            child.reset()
        self.current_child = 0


class Selector(Node):
    """Executes children in order until one returns success, or all fail"""
    def __init__(self, blackboard: Blackboard, children: List[Node]):
        super().__init__(blackboard)
        self.children = children
        self.current_child = 0

    def tick(self) -> NodeStatus:
        while self.current_child < len(self.children):
            status = self.children[self.current_child].tick()

            match status:
                case NodeStatus.SUCCESS:
                    self.reset()
                    return NodeStatus.SUCCESS
                case NodeStatus.FAILURE:
                    self.current_child += 1
                case NodeStatus.RUNNING:
                    return NodeStatus.RUNNING

        self.reset()
        return NodeStatus.FAILURE

    def reset(self):
        for child in self.children:
            child.reset()
        self.current_child = 0


class ParallelPolicy(Enum):
    """Policy for parallel nodes"""
    SUCCESS_ON_ANY = 0
    SUCCESS_ON_ALL = 1


class Parallel(Node):
    """Executes children in parallel, returning based on the parallel policy"""
    def __init__(self, blackboard: Blackboard, children: List[Node], policy: ParallelPolicy):
        super().__init__(blackboard)
        self.children = children
        self.policy = policy

    def tick(self) -> NodeStatus:
        # Run child ticks concurrently
        results = [child.tick() for child in self.children]

        match self.policy:
            case ParallelPolicy.SUCCESS_ON_ALL:
                if all(r == NodeStatus.SUCCESS for r in results):
                    return NodeStatus.SUCCESS
                if any(r == NodeStatus.FAILURE for r in results):
                    return NodeStatus.FAILURE
                return NodeStatus.RUNNING

            case ParallelPolicy.SUCCESS_ON_ANY:
                if any(r == NodeStatus.SUCCESS for r in results):
                    return NodeStatus.SUCCESS
                if all(r == NodeStatus.FAILURE for r in results):
                    return NodeStatus.FAILURE
                return NodeStatus.RUNNING

            case _:
                raise ValueError(f"Invalid ParallelPolicy: {self.policy}")

    def reset(self):
        for child in self.children:
            child.reset()


# =================================================================
# Decorator Nodes
# =================================================================
class Inverter(Node):
    """Inverts the result of the child node"""
    def __init__(self, blackboard: Blackboard, child: Node):
        super().__init__(blackboard)
        self.child = child

    def tick(self) -> NodeStatus:
        status = self.child.tick()

        match status:
            case NodeStatus.SUCCESS:
                return NodeStatus.FAILURE
            case NodeStatus.FAILURE:
                return NodeStatus.SUCCESS
            case NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            case _:
                raise ValueError(f"Invalid NodeStatus: {status}")

    def reset(self):
        self.child.reset()


class RepeatUntilSuccess(Node):
    """Repeats the child node until it succeeds"""
    def __init__(self, blackboard: Blackboard, child: Node, timeout: float = None):
        super().__init__(blackboard)
        self.child = child
        self.timeout = timeout
        self.start_time = None

    def tick(self) -> NodeStatus:
        if self.start_time is None:
            self.start_time = time.time()

        if self.timeout is not None and time.time() - self.start_time > self.timeout:
            self.reset()
            return NodeStatus.FAILURE

        status = self.child.tick()

        if status == NodeStatus.SUCCESS:
            self.reset()
            return NodeStatus.SUCCESS

        if status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING

        # on FAILURE, keep retrying until timeout
        return NodeStatus.RUNNING

    def reset(self):
        self.child.reset()
        self.start_time = None


class RepeatUntilNSuccess(Node):
    """Repeats the child node until it succeeds N times in a row."""
    def __init__(self, blackboard: Blackboard, child: Node, n: int, timeout: float = None):
        super().__init__(blackboard)
        if n <= 0:
            raise ValueError("n must be >= 1")
        self.child = child
        self.n = n
        self.timeout = timeout
        self.count = 0
        self.start_time = None

    def tick(self) -> NodeStatus:
        if self.start_time is None:
            self.start_time = time.time()

        if self.timeout is not None and (time.time() - self.start_time) > self.timeout:
            self.reset()
            return NodeStatus.FAILURE

        status = self.child.tick()

        if status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING

        if status == NodeStatus.SUCCESS:
            self.count += 1
            if self.count >= self.n:
                self.reset()
                return NodeStatus.SUCCESS
            return NodeStatus.RUNNING

        # FAILURE: break the consecutive success streak
        self.count = 0
        return NodeStatus.RUNNING

    def reset(self):
        self.child.reset()
        self.count = 0
        self.start_time = None


class Repeat(Node):
    """Repeats the child node a given number of times, discarding the result"""
    def __init__(self, blackboard: Blackboard, child: Node, times: Optional[int] = None):
        super().__init__(blackboard)
        self.child = child
        self.times = times
        self.current = 0

    def tick(self) -> NodeStatus:
        if self.times is not None and self.current >= self.times:
            self.reset()
            return NodeStatus.SUCCESS

        status = self.child.tick()

        # If child is still running, propagate running
        if status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING

        # On completion (success or failure), count one iteration
        self.current += 1

        if self.times is not None and self.current >= self.times:
            self.reset()
            return NodeStatus.SUCCESS

        return NodeStatus.RUNNING

    def reset(self):
        self.child.reset()
        self.current = 0


class PrioritySelector(Node):
    """Priority/interrupting selector: re-evaluates children each tick and
    preempts a running lower-priority child when a higher-priority child
    becomes RUNNING or SUCCESS.
    """
    def __init__(self, blackboard: Blackboard, children: List[Node]):
        super().__init__(blackboard)
        self.children = children
        self.current_child: Optional[int] = None

    def tick(self) -> NodeStatus:
        for i, child in enumerate(self.children):
            status = child.tick()

            match status:
                case NodeStatus.SUCCESS:
                    # Higher-priority child succeeded -> stop everything and return success
                    self.reset()
                    return NodeStatus.SUCCESS

                case NodeStatus.RUNNING:
                    # If a different child is running, preempt it
                    if self.current_child is None or self.current_child != i:
                        if self.current_child is not None and 0 <= self.current_child < len(self.children):
                            self.children[self.current_child].reset()
                        self.current_child = i
                    return NodeStatus.RUNNING

                case NodeStatus.FAILURE:
                    # try next child
                    continue

        # no child succeeded or is running
        self.reset()
        return NodeStatus.FAILURE

    def reset(self):
        for child in self.children:
            child.reset()
        self.current_child = None

# =================================================================
# Utility Nodes
# =================================================================
class Sleep(Node):
    """Sleeps for a given duration"""
    def __init__(self, blackboard: Blackboard, duration: float):
        assert duration > 0, "Duration must be greater than 0"

        super().__init__(blackboard)
        self.duration = duration
        self.start_time = None

    def tick(self) -> NodeStatus:
        if self.start_time is None:
            self.start_time = time.time()

        if time.time() - self.start_time >= self.duration:
            self.reset()
            return NodeStatus.SUCCESS

        return NodeStatus.RUNNING

    def reset(self):
        self.start_time = None


class Conditional(Node):
    """Returns success if the condition is true, failure if false"""
    def __init__(self, blackboard: Blackboard, condition: Callable[..., Any]):
        super().__init__(blackboard)
        self.condition = condition

    def tick(self) -> NodeStatus:
        result = self.condition()
        return NodeStatus.SUCCESS if result else NodeStatus.FAILURE


class SetBlackboardValue(Node):
    """Sets a value in the blackboard"""
    def __init__(self, blackboard: Blackboard, key: str, value: Any):
        super().__init__(blackboard)
        self.key = key
        self.value = value

    def tick(self) -> NodeStatus:
        self.blackboard.set(self.key, self.value)
        return NodeStatus.SUCCESS


class ConditionalSequence(Node):
    """Conditional sequence node.

    Behavior:
    - Evaluate `condition` (a Node).
    - If the condition returns FAILURE (i.e. condition is false) -> return SUCCESS immediately.
    - If the condition returns RUNNING -> return RUNNING.
    - If the condition returns SUCCESS -> execute `children` in sequence (like `Sequence`).
      * If any child returns FAILURE -> reset and return FAILURE.
      * If children are still running -> return RUNNING.
      * If all children succeed -> reset and return SUCCESS.

    This matches: "Return success if condition is false OR condition is true and children succeed. Return failure only if children fail."""

    def __init__(self, blackboard: Blackboard, condition: Node, children: List[Node]):
        super().__init__(blackboard)
        self.condition = condition
        self.children = children
        self.current_child = 0

    def tick(self) -> NodeStatus:
        # First evaluate condition
        cond_status = self.condition.tick()

        if cond_status == NodeStatus.RUNNING:
            return NodeStatus.RUNNING

        if cond_status == NodeStatus.FAILURE:
            # Condition is false -> treat as success without running children
            # Ensure children are reset so next time they start fresh
            self._reset_children()
            self.current_child = 0
            return NodeStatus.SUCCESS

        # cond_status == NodeStatus.SUCCESS -> run children in sequence
        while self.current_child < len(self.children):
            status = self.children[self.current_child].tick()

            if status == NodeStatus.SUCCESS:
                self.current_child += 1
                continue

            if status == NodeStatus.RUNNING:
                return NodeStatus.RUNNING

            if status == NodeStatus.FAILURE:
                # children failed -> propagate failure and reset
                self.reset()
                return NodeStatus.FAILURE

        # all children succeeded
        self.reset()
        return NodeStatus.SUCCESS

    def _reset_children(self):
        for child in self.children:
            child.reset()

    def reset(self):
        # Reset both condition node and children
        try:
            self.condition.reset()
        except Exception:
            # Some condition nodes may not implement reset; ignore
            pass
        self._reset_children()
        self.current_child = 0

