import ctypes
import json
import multiprocessing
import time
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Optional, Dict, Any


@dataclass
class WorkerHandle:
    pid: int
    process: "multiprocessing.Process"
    stop_event: "multiprocessing.Event"
    pause_event: "multiprocessing.Event"
    shm_name: str
    data_capacity: int
    shm: Optional[shared_memory.SharedMemory] = None
    shm_owner: Optional[shared_memory.SharedMemory] = None
    last_seq: int = 0


class EveMemoryReader:
    """
    Multiprocess EVE Online memory reader, allowing the reading of
    multiple game clients from one application.

    Uses a separate process for each game client and communicates the
    received JSON bytes using shared memory.
    """
    _SHM_HEADER_SIZE = 64
    _STATUS_TOO_LARGE = -2
    _STATUS_ERROR = -1
    _STATUS_INIT = 0
    _STATUS_OK = 1

    def __init__(self, process_id: int, dll_path: str = "./eve-memory-reader.dll"):
        """

        :param process_id: Process id of the target game client
        :param dll_path: Optional path to the EVE Memory Reader DLL.
        """
        self.pid = process_id
        self.dll_path = dll_path
        self.handle = None

    def initialize(
            self,
            period_s: float = 0.25,
            data_capacity: int = 2_000_000,
            error_capacity: int = 4096
    ) -> None:
        """
        Initializes and starts the EVE Memory Reader child process.

        :param period_s: Target update frequency
        :param data_capacity: Shared memory capacity reserved for the JSON data
        :param error_capacity: Shared memory capacity reserved for error messages
        """
        ctx = multiprocessing.get_context("spawn")

        shm_name = f"emr_bytes_{self.pid}_{time.time_ns()}"
        shm_size = self._shm_total_size(data_capacity, error_capacity)
        shm_owner = shared_memory.SharedMemory(name=shm_name, create=True, size=shm_size)
        shm_owner.buf[:self._SHM_HEADER_SIZE] = b"\x00" * self._SHM_HEADER_SIZE
        stop_event = ctx.Event()
        pause_event = ctx.Event()
        proc = ctx.Process(
            target=self._worker_read_loop,
            args=(
                self.pid,
                shm_name,
                stop_event,
                pause_event,
                period_s,
                data_capacity,
                error_capacity,
            ),
            daemon=True
        )
        proc.start()

        self.handle = WorkerHandle(
            pid=self.pid,
            process=proc,
            stop_event=stop_event,
            pause_event=pause_event,
            shm_name=shm_name,
            data_capacity=data_capacity,
            shm_owner=shm_owner
        )

    def get_ui_tree(self, max_retries: int = 5) -> Optional[Dict[str, Any]]:
        """
        Gets the latest UI tree data from the worker process, retrying up to
        'max_retries' times if the data is not yet available.

        :param max_retries: Maximum number of retries.
        :return: Dict representation of the UI tree, or None if no data is available yet.
        """
        for _ in range(max_retries):
            if json_bytes := self._try_read_latest_frame():
                json_str = json_bytes.decode("utf-8", errors="replace")
                return json.loads(json_str, strict=False)
        return None


    def _shm_total_size(self, data_capacity: int, error_capacity: int) -> int:
        return self._SHM_HEADER_SIZE + data_capacity + error_capacity

    ##########################
    # Shared memory utilities
    @staticmethod
    def _u64_from(buf: memoryview, off: int) -> int:
        return int.from_bytes(buf[off: off + 8], "little", signed=False)

    @staticmethod
    def _i32_from(buf: memoryview, off: int) -> int:
        return int.from_bytes(buf[off: off + 4], "little", signed=True)

    @staticmethod
    def _u32_from(buf: memoryview, off: int) -> int:
        return int.from_bytes(buf[off: off + 4], "little", signed=False)

    @staticmethod
    def _put_u64(buf: memoryview, off: int, v: int) -> None:
        buf[off: off + 8] = int(v).to_bytes(8, "little", signed=False)

    @staticmethod
    def _put_u32(buf: memoryview, off: int, v: int) -> None:
        buf[off: off + 4] = int(v).to_bytes(4, "little", signed=False)

    @staticmethod
    def _put_i32(buf: memoryview, off: int, v: int) -> None:
        buf[off: off + 4] = int(v).to_bytes(4, "little", signed=True)

    def _worker_write_frame(self, memory_view: memoryview, data: bytes, elapsed_ns: int) -> None:
        now_ns = time.time_ns()
        seq = self._u64_from(memory_view, 0)
        seq = (seq + 1) | 1

        self._put_u64(memory_view, 0, seq)
        self._put_u64(memory_view, 8, now_ns)
        self._put_u32(memory_view, 16, len(data))
        self._put_i32(memory_view, 20, self._STATUS_OK)
        self._put_u32(memory_view, 24, 0)
        self._put_u32(memory_view, 28, 0)
        self._put_u64(memory_view, 32, int(elapsed_ns))

        payload_off = self._SHM_HEADER_SIZE
        memory_view[payload_off: payload_off + len(data)] = data

        # Set seq to even, commit changes
        self._put_u64(memory_view, 0, seq + 1)

    def _worker_write_error(
            self,
            memory_view: memoryview,
            error_text: str,
            elapsed_ns: int,
            error_capacity: int,
            required_len: int = 0,
            status: int = _STATUS_ERROR
    ) -> None:
        now_ns = time.time_ns()
        seq = self._u64_from(memory_view, 0)
        seq = (seq + 1) | 1
        self._put_u64(memory_view, 0, seq)

        err_bytes = (error_text or "").encode("utf-8", errors="replace")
        err_bytes = err_bytes[:error_capacity]

        self._put_u64(memory_view, 8, now_ns)
        self._put_u32(memory_view, 16, 0)
        self._put_i32(memory_view, 20, int(status))
        self._put_u32(memory_view, 24, int(required_len) if required_len > 0 else 0)
        self._put_u32(memory_view, 28, len(err_bytes))
        self._put_u64(memory_view, 32, int(elapsed_ns))

        total_len = len(memory_view)
        err_region_off = total_len - error_capacity
        memory_view[err_region_off: err_region_off + len(err_bytes)] = err_bytes

        self._put_u64(memory_view, 0, seq + 1)

    def _worker_read_loop(
            self,
            process_id: int,
            shm_name: str,
            stop_event: "multiprocessing.Event",
            pause_event: "multiprocessing.Event",
            period_s: float,
            data_capacity: int,
            error_capacity: int
    ) -> None:
        """
        Main worker loop for taking memory readings from the target process.

        Takes a fresh snapshot of the memory every given 'period_s' seconds,
        then writes the JSON bytes to the shared memory buffer.
        """
        shm: Optional[shared_memory.SharedMemory] = None
        memory_view: Optional[memoryview] = None
        dll = self._initialize_dll()

        try:
            last_exc: Optional[Exception] = None
            for _ in range(50):  # The mapping may not be immediately visible
                try:
                    shm = shared_memory.SharedMemory(name=shm_name, create=False); break
                except FileNotFoundError:
                    last_exc = Exception("Shared memory not found")
                    time.sleep(0.02)

            if shm is None:
                raise last_exc

            memory_view = shm.buf

            if not dll.initialize(process_id) == 0:
                self._worker_write_error(
                    memory_view,
                    "failed to initialize memory reader",
                    0,
                    error_capacity,
                    status=self._STATUS_ERROR
                )
                return

            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.25)
                    continue

                start = time.time()
                dll.read_ui_trees()
                json_bytes = dll.get_ui_json()
                dll.free_ui_json()
                elapsed = time.time() - start
                elapsed_ns = int(elapsed * 1e9)

                if json_bytes is None:
                    self._worker_write_error(
                        memory_view,
                        "read_ui_tree_bytes returned None",
                        elapsed_ns,
                        error_capacity
                    )
                elif len(json_bytes) > data_capacity:
                    self._worker_write_error(
                        memory_view,
                        f"frame too large for slot: {len(json_bytes)} > {data_capacity}",
                        elapsed_ns,
                        error_capacity,
                        required_len=len(json_bytes),
                        status=self._STATUS_TOO_LARGE,
                    )
                else:
                    self._worker_write_frame(memory_view, json_bytes, elapsed_ns)

                sleep_for = period_s - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except Exception as e:
            if memory_view is not None:
                self._worker_write_error(
                    memory_view,
                    str(e),
                    int(time.time_ns()),
                    error_capacity,
                    status=self._STATUS_ERROR
                )
        finally:
            dll.cleanup()
            if shm is not None:
                shm.close()

    def _try_read_latest_frame(self, error_capacity=4096) -> Optional[bytes]:
        assert self.handle is not None, "Must be initialized"

        shm = self._attach_shm_if_needed()
        memory_view = shm.buf

        seq1 = self._u64_from(memory_view, 0)
        if seq1 == 0 or (seq1 & 1) == 1 or seq1 == self.handle.last_seq:
            return None  # No data yet, currently being written to, or already read

        data_len = self._u32_from(memory_view, 16)
        status = self._i32_from(memory_view, 20)
        required_len = self._u32_from(memory_view, 24)
        err_len = self._u32_from(memory_view, 28)
        elapsed_ns = self._u64_from(memory_view, 32)

        if status in (self._STATUS_ERROR, self._STATUS_TOO_LARGE):
            if err_len > 0:  # Error reading game client memory, likely a bad process id
                err_region_off = len(memory_view) - error_capacity
                err_bytes = bytes(memory_view[err_region_off : err_region_off + err_len])
                err = err_bytes.decode("utf-8", errors="replace")
                if status == self._STATUS_TOO_LARGE:
                    err = f"frame too large for slot: {required_len} > {self.handle.data_capacity}"
                raise Exception(err)

        if status == self._STATUS_INIT:
            return None  # Still initializing, no data yet

        payload_off = self._SHM_HEADER_SIZE
        data_bytes = bytes(memory_view[payload_off: payload_off + data_len])

        # Check if the frame has been overwritten during read, race condition
        seq2 = self._u64_from(memory_view, 0)
        if seq1 != seq2 or (seq2 & 1) == 1:
            return None

        self.handle.last_seq = seq2
        return data_bytes


    def _attach_shm_if_needed(self) -> shared_memory.SharedMemory:
        if self.handle.shm is not None:
            return self.handle.shm

        last_exc: Optional[Exception] = None
        shm = None
        for _ in range(50):
            try:
                shm = shared_memory.SharedMemory(name=self.handle.shm_name, create=False)
                break
            except FileNotFoundError as e:
                last_exc = e
                time.sleep(0.02)
        if shm is None:
            raise last_exc
        self.handle.shm = shm
        return shm

    def _initialize_dll(self) -> ctypes.WinDLL:
        """
        Loads and configures function signatures for the EVE Memory Reader DLL.
        """
        dll = ctypes.WinDLL(self.dll_path)

        dll.initialize.argtypes = [ctypes.c_ulong]
        dll.initialize.restype = ctypes.c_int

        dll.read_ui_trees.argtypes = []
        dll.read_ui_trees.restype = None

        dll.read_ui_trees_from_address.argtypes = [ctypes.c_ulonglong]
        dll.read_ui_trees_from_address.restype = None

        dll.get_ui_json.argtypes = []
        dll.get_ui_json.restype = ctypes.c_char_p

        dll.free_ui_json.argtypes = []
        dll.free_ui_json.restype = None

        dll.cleanup.argtypes = []
        dll.cleanup.restype = None

        return dll

    def shutdown(self) -> None:
        """
        Stop the child memory-reader process and clean up shared memory.

        This is needed when initialization fails and we want to retry with a fresh
        native reader process.
        """
        if self.handle is None:
            return

        try:
            self.handle.stop_event.set()

            if self.handle.process.is_alive():
                self.handle.process.join(timeout=2.0)

            if self.handle.process.is_alive():
                self.handle.process.terminate()
                self.handle.process.join(timeout=2.0)

        finally:
            if self.handle.shm is not None:
                try:
                    self.handle.shm.close()
                except Exception:
                    pass

            if self.handle.shm_owner is not None:
                try:
                    self.handle.shm_owner.close()
                except Exception:
                    pass

                try:
                    self.handle.shm_owner.unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass

            self.handle = None

def pause(self) -> None:
    """Pause the background native reader loop."""
    if self.handle is not None:
        self.handle.pause_event.set()


def resume(self) -> None:
    """Resume the background native reader loop."""
    if self.handle is not None:
        self.handle.pause_event.clear()

if __name__ == "__main__":
    readers = [EveMemoryReader(25812), EveMemoryReader(27676)]
    for reader in readers: reader.initialize()

    initialized = [0, 0]
    while not all(initialized):
        for i in range(2):
            if not initialized[i] and readers[i].get_ui_tree():
                initialized[i] = 1

    print("Initialized")
    while True:
        for reader in readers:
            if ui_tree := reader.get_ui_tree():
                print(f"[{reader.handle.pid}] {ui_tree.get("address")}")