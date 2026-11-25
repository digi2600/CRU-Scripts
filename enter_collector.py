import asyncio
from twitchio.ext import commands
import aiohttp
from pathlib import Path

# pip install twitchio==2.10.0
# use https://twitchtokengenerator.com to get the Access Token and the Client ID that belongs to it with new token scopes: chat:read, chat:edit, moderator:read:followers
# use https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/ for Broadcaster ID (only needed if CHECK_FOLLOWERS = True)

# ========== FILL THESE IN ==========
TOKEN = "oauth:xxxxxxxxxxxxxxxxxxxxxxx"          # Your OAuth token (see below)
CLIENT_ID = "xxxxxxxxxxxxxxxxxxxxxxx"                       # From Twitch Developer Console
CHANNEL = "untouchablecru"                    # lowercase, no #
NICK = "Insider46"                           # your account name (lowercase)
OUTPUT_FILE = "entries.txt"                             # the list file
CHECK_FOLLOWERS = False                                 # set True if you want API follower checks
BROADCASTER_ID = "xxxxxxxx"                            # numeric ID of the channel (see below)
MAX_COUNT = 100                               # ← Maximum number of entries allowed
# ===================================

# Keep unique names in memory
seen = set()
file_path = Path(OUTPUT_FILE)

# Load any existing names so we don't duplicate across restarts
if file_path.exists():
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip().lower()
            if name:
                seen.add(name)
    print(f"Loaded {len(seen)} existing names from {OUTPUT_FILE}")

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=TOKEN,
            client_id=CLIENT_ID,
            nick=NICK,
            prefix="!",
            initial_channels=[CHANNEL]
        )

    async def event_ready(self):
        print(f"Connected as {self.nick} | Watching #{CHANNEL} for !enter")
        print(f"Unique names will be written to: {file_path.absolute()}")
        print(f"Max entries: {MAX_COUNT}")
        print("Press Ctrl+C to stop.\n")

    async def event_message(self, message):
        # Ignore messages sent by the bot itself
        if message.echo:
            return

        content = message.content.strip().lower()
        if content == "!enter" or content.startswith("!enter "):
            user = message.author.name.lower()
            display = message.author.name

            # Already entered?
            if user in seen:
                slots_left = MAX_COUNT - len(seen)
                if slots_left > 0:
                    await message.channel.send(
                        f"🤖 @{display} → You already entered. {slots_left} slots left!"
                    )
                else:
                    await message.channel.send(f"🤖 @{display} → You already entered.")
                print(f"[DUPLICATE] {user}")
                return

            # Check if slots are full
            if len(seen) >= MAX_COUNT:
                await message.channel.send(f"🤖 @{display} → Sorry, all slots are full!")
                print(f"[FULL] {user} tried to enter (limit: {MAX_COUNT})")
                return

            # Optional follower check
            if CHECK_FOLLOWERS:
                is_follower = await self.is_follower(message.author.id)
                if not is_follower:
                    await message.channel.send(
                        f"🤖 @{display} → You’re not following yet. Follow the channel and type !enter again."
                    )
                    print(f"[NOT FOLLOWING] {user}")
                    return

            # Valid new entry
            seen.add(user)
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(user + "\n")

            slots_left = MAX_COUNT - len(seen)
            await message.channel.send(
                f"🤖 @{display} → has been entered! {slots_left} slots left!"
            )
            print(f"[ADDED] {user} (total: {len(seen)}/{MAX_COUNT})")

    async def is_follower(self, user_id: str) -> bool:
        """Check if the user follows the broadcaster"""
        url = "https://api.twitch.tv/helix/channels/followers"
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {TOKEN.replace('oauth:', '')}"
        }
        params = {
            "broadcaster_id": BROADCASTER_ID,
            "user_id": user_id
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return len(data.get("data", [])) > 0
                    else:
                        text = await resp.text()
                        print(f"API Error {resp.status}: {text}")
                        return False
        except Exception as e:
            print(f"Follower check failed: {e}")
            return False

    async def event_command_error(self, ctx, error):
        # Silently ignore "command not found" errors
        if isinstance(error, commands.CommandNotFound):
            return
        print(f"Command error: {error}")

if __name__ == "__main__":
    bot = Bot()
    bot.run()