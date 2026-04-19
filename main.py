import asyncio
import json
from json import JSONDecodeError
from pathlib import Path

from bots.bt_sbmachs import SmartbombBot


DEBUG_MODE = True

DEFAULT_CONFIG = {
    "character_names": ["player1", "player2", "player3"],
    "discord_url": "https://discord.com/api/webhooks/...",
    "bookmark_name": "Safe (1)",
}



def load_config(path: str = "config.json") -> dict[str, object]:
    # Using pathlib to handle relative paths
    config_path = Path(path)

    # Handling wrong config path and raising error on failure.
    if not config_path.exists():
        config_path.write_text(
            json.dumps(DEFAULT_CONFIG, indent=4),
            encoding="utf-8",
        )
        raise FileNotFoundError(
            f"Created example config at '{config_path}'. Edit it and re-run."
        )

    # Handling invalid JSON in config file and raising error on failure.
    try:
        with config_path.open("r", encoding="utf-8") as f:
            loaded_config = json.load(f)
    except JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in '{config_path}': {e}") from e

    config = DEFAULT_CONFIG | loaded_config

    # Minimal validation for the fields the bot actually needs.
    if not isinstance(config["character_names"], list) or not config["character_names"]:
        raise ValueError("'character_names' must be a non-empty list of character names.")

    if not isinstance(config["discord_url"], str) or not config["discord_url"].strip():
        raise ValueError("'discord_url' must be a non-empty string.")

    if not isinstance(config["bookmark_name"], str) or not config["bookmark_name"].strip():
        raise ValueError("'bookmark_name' must be a non-empty string.")

    return config


async def main():
    print("Starting main process")
    config = load_config()

    bot = SmartbombBot(
        client_names=config["character_names"],
        discord_url=config["discord_url"],
        bookmark_name=config["bookmark_name"],
        debug_mode=DEBUG_MODE,
        manual_client_init=MANUAL_CLIENT_INIT,
    )

    await bot.run()
    print("Main process exiting")


if __name__ == "__main__":
    asyncio.run(main())

#TODO: reset position after dread (in case of bump
#TODO: BM/Loot Dread Guristas

