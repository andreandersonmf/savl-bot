import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

TRANSACTIONS_CHANNEL_ID = int(os.getenv("TRANSACTIONS_CHANNEL_ID", "0"))
SELF_TRANSACTIONS_CHANNEL_ID = int(os.getenv("SELF_TRANSACTIONS_CHANNEL_ID", "0"))

CAPTAIN_ROLE_ID = int(os.getenv("CAPTAIN_ROLE_ID", "0"))
VICE_CAPTAIN_ROLE_ID = int(os.getenv("VICE_CAPTAIN_ROLE_ID", "0"))
REFEREE_ROLE_ID = int(os.getenv("REFEREE_ROLE_ID", "0"))
STREAMER_ROLE_ID = int(os.getenv("STREAMER_ROLE_ID", "0"))
PLAYER_ROLE_ID = int(os.getenv("PLAYER_ROLE_ID", "0"))

_staff_ids_raw = os.getenv("STAFF_APPROVER_ROLE_IDS", "")
STAFF_APPROVER_ROLE_IDS = [
    int(role_id.strip())
    for role_id in _staff_ids_raw.split(",")
    if role_id.strip().isdigit()
]