import asyncio
import json
import os
import sys
from multiprocessing import freeze_support

from jiaoben.jiaoben import SmartbombJiaoben


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


async def main():
    print("Starting main process")
    config = load_config()
    assert config["character_names"]

    jiaoben = SmartbombJiaoben(config["character_names"], discord_url=config["discord_url"], bookmark_name="Safe (1)")
    await jiaoben.run()
    print("Main process exiting")


if __name__ == "__main__":
    freeze_support()
    asyncio.run(main())


"""
todo:
    reset position after dread (in case of bump)
    bookmark dread guristas
"""