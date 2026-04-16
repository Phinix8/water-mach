import json
import os
import sys
import time
from multiprocessing import freeze_support

from client.eve_client import EvEClient
from memory.memory import EveMemoryReader


def load_config(path: str = "config.json") -> dict:
    sample_config = """
{
    "character_names": ["player1", "player2", "player3"],
    "discord_url": "https://discord.com/api/webhooks/...
}"""

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(sample_config.strip())
        print(f"Created example config at `{path}`. Edit it and re-run.")
        sys.exit(0)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("Taking memory reading...")
    config = load_config()
    pids = [EvEClient._get_pid_from_window_name(f"EVE - {name}")
            for name in config["character_names"]]
    initialized = [False] * len(pids)

    readers = [EveMemoryReader(pid) for pid in pids]
    for reader in readers: reader.initialize()

    while not all(initialized):
        for i in range(len(pids)):
            if not initialized[i] and readers[i].get_ui_tree():
                initialized[i] = True

    for reader in readers:
        tree = reader.get_ui_tree()
        file_name = f"{reader.handle.pid}_{time.time()}.json"
        with open(file_name, "w") as debug_file:
            debug_file.write(json.dumps(tree, indent=2))


if __name__ == "__main__":
    freeze_support()
    main()