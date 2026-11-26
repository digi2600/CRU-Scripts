import asyncio
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import aiohttp
from twitchio.ext import commands

# pip install twitchio==2.10.0
# use https://twitchtokengenerator.com to get the Access Token and the Client ID that belongs to it with new token scopes: chat:read, chat:edit, moderator:read:followers
# use https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/ for Broadcaster ID (only needed if CHECK_FOLLOWERS = True)
# NOTE: for the follower check, the account that owns the token must be the broadcaster OR a moderator of the channel.

# ========== FILL THESE IN ==========
TOKEN = "oauth:xxxxxxxxxxxxxxxxxxxxxxx"          # Your OAuth token (see below)
CLIENT_ID = "xxxxxxxxxxxxxxxxxxxxxxx"                       # From Twitch Developer Console
CHANNEL = "untouchablecru"                    # lowercase, no #
NICK = "Insider46_og"                           # your account name (lowercase)
OUTPUT_FILE = "entries.txt"                             # the list file (one line per entry; a subscriber's 2 entries = their name twice)
IGNORE_FILE = "ignored.txt"                             # users the bot will ignore (managed with !ignore / !unignore)
CHECK_FOLLOWERS = True                                  # True = only followers (or subscribers/VIPs/mods/broadcaster) can enter
BROADCASTER_ID = "xxxxxxxx"                            # numeric ID of the channel (see below)
MAX_COUNT = 100                               # ← Maximum number of TOTAL entries (a subscriber's 2nd entry uses a slot too)
ENTRIES_PER_USER = 1                          # entries allowed per normal user
SUBSCRIBER_ENTRIES = 2                        # entries allowed per subscriber (they must type !enter once per entry)
START_OPEN = True                             # True = entries are open when the bot starts, False = closed until a mod types !open
USER_COOLDOWN = 30                            # seconds before the bot answers the same user again for the same command
GLOBAL_COOLDOWN = 5                           # seconds between ANY two bot answers of the same kind (flood protection)
# ===================================

MOD_COMMANDS = {"!open", "!close", "!reset", "!remove", "!count", "!ignore", "!unignore", "!help"}


def load_list(path: Path) -> list:
    """Load lowercase names from a text file, one per line. Duplicates are kept (they are extra entries)."""
    names = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip().lower()
                if name:
                    names.append(name)
    return names


def save_list(path: Path, names) -> None:
    """Rewrite a names file from scratch."""
    with open(path, "w", encoding="utf-8") as f:
        for name in names:
            f.write(name + "\n")


def clean_name(raw: str) -> str:
    """'@SomeName' -> 'somename'"""
    return raw.strip().lstrip("@").lower()


def is_privileged(author) -> bool:
    """Broadcaster is NOT automatically flagged as a mod by Twitch, so check both."""
    return bool(author.is_mod or author.is_broadcaster)


def is_subscriber(author) -> bool:
    """Subscriber or founder badge."""
    badges = author.badges or {}
    return bool(author.is_subscriber or "subscriber" in badges or "founder" in badges)


# In-memory state. `entries` is every entry in order; `counts` is entries per user.
file_path = Path(OUTPUT_FILE)
ignore_path = Path(IGNORE_FILE)
entries = load_list(file_path)
counts = Counter(entries)
ignored = dict.fromkeys(load_list(ignore_path))

if entries:
    print(f"Loaded {len(entries)} existing entries ({len(counts)} people) from {OUTPUT_FILE}")
if ignored:
    print(f"Loaded {len(ignored)} ignored users from {IGNORE_FILE}")


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=TOKEN,
            client_id=CLIENT_ID,
            nick=NICK,
            prefix="!",
            initial_channels=[CHANNEL]
        )
        self.is_open = START_OPEN
        self._last_user_reply = {}    # (user, key) -> time of last reply
        self._last_global_reply = {}  # key -> time of last reply
        self._pending = set()         # users whose follower check is currently running

    # ---------- helpers ----------
    def slots_left(self) -> int:
        return max(0, MAX_COUNT - len(entries))

    def can_reply(self, user: str, key: str, bypass: bool = False) -> bool:
        """Flood protection. Returns True if the bot may answer now, and records that it did."""
        if bypass:
            return True
        now = time.monotonic()
        if now - self._last_global_reply.get(key, -1e9) < GLOBAL_COOLDOWN:
            return False
        if now - self._last_user_reply.get((user, key), -1e9) < USER_COOLDOWN:
            return False
        self._last_global_reply[key] = now
        self._last_user_reply[(user, key)] = now
        return True

    # ---------- events ----------
    async def event_ready(self):
        state = "OPEN" if self.is_open else "CLOSED"
        print(f"Connected as {self.nick} | Watching #{CHANNEL} for !enter")
        print(f"Entries will be written to: {file_path.absolute()}")
        print(f"Max entries: {MAX_COUNT} | Per user: {ENTRIES_PER_USER} | Subscribers: {SUBSCRIBER_ENTRIES}")
        print(f"Entries are {state} | Follower check: {'ON' if CHECK_FOLLOWERS else 'OFF'}")
        if CHECK_FOLLOWERS:
            await self.verify_follower_access()
        print("Press Ctrl+C to stop.\n")

    async def event_message(self, message):
        # Ignore messages sent by the bot itself
        if message.echo or message.author is None:
            return

        content = message.content.strip()
        if not content.startswith("!"):
            return

        parts = content.split()
        cmd = parts[0].lower()
        args = parts[1:]
        user = message.author.name.lower()
        display = message.author.name
        mod = is_privileged(message.author)

        # Ignored users get no response at all (mods/broadcaster can't be locked out)
        if not mod and user in ignored:
            return

        # Mod / broadcaster commands (everyone else's attempts are silently ignored)
        if mod and cmd in MOD_COMMANDS:
            await self.handle_mod_command(message, cmd, args, user)
            return

        # ---------- public commands ----------
        if cmd == "!slots":
            if not self.is_open:
                return
            if self.can_reply(user, "slots", bypass=mod):
                await message.channel.send(
                    f"🤖 @{display} → {len(entries)}/{MAX_COUNT} entries, {self.slots_left()} slots left!"
                )
            return

        if cmd == "!help":
            if not self.is_open:
                return
            if self.can_reply(user, "help", bypass=mod):
                await message.channel.send(
                    f"🤖 @{display} → Type !enter to join and !slots to see the open spots."
                )
            return

        if cmd == "!enter":
            await self.handle_enter(message, user, display)
            return

    # ---------- !enter ----------
    async def blocked(self, message, user: str, display: str, limit: int) -> bool:
        """If this user can't add an entry right now, reply (throttled) and return True.
        This never awaits unless it is blocking, so a passing check can't be interleaved with another entry."""
        if counts[user] >= limit:
            if self.can_reply(user, "dup"):
                text = f"You've already used all {limit} of your entries." if limit > 1 else "You already entered."
                left = self.slots_left()
                if left > 0:
                    text += f" {left} slots left!"
                await message.channel.send(f"🤖 @{display} → {text}")
            print(f"[DUPLICATE] {user} ({counts[user]}/{limit})")
            return True

        if len(entries) >= MAX_COUNT:
            if self.can_reply(user, "full"):
                await message.channel.send(f"🤖 @{display} → Sorry, all slots are full!")
            print(f"[FULL] {user} tried to enter (limit: {MAX_COUNT})")
            return True

        return False

    async def handle_enter(self, message, user: str, display: str):
        # Entries closed?
        if not self.is_open:
            if self.can_reply(user, "closed"):
                await message.channel.send(f"🤖 @{display} → Entries are currently closed.")
            print(f"[CLOSED] {user} tried to enter")
            return

        author = message.author
        sub = is_subscriber(author)
        limit = SUBSCRIBER_ENTRIES if sub else ENTRIES_PER_USER

        # A follower check for this user is already running: skip the repeat
        if user in self._pending:
            return

        if await self.blocked(message, user, display, limit):
            return

        # Follower check (subscribers, VIPs, mods and the broadcaster are "above" follower, so they skip it)
        if CHECK_FOLLOWERS and not (sub or is_privileged(author) or author.is_vip):
            self._pending.add(user)
            try:
                result = await self.is_follower(author.id)
            finally:
                self._pending.discard(user)

            if result is None:
                if self.can_reply(user, "apierr"):
                    await message.channel.send(
                        f"🤖 @{display} → I couldn't verify your follow status right now. Try again in a moment."
                    )
                return
            if result is False:
                if self.can_reply(user, "nofollow"):
                    await message.channel.send(
                        f"🤖 @{display} → You’re not following yet. Follow the channel and type !enter again."
                    )
                print(f"[NOT FOLLOWING] {user}")
                return

            # The list may have changed while we waited on the API, so check again
            if await self.blocked(message, user, display, limit):
                return

        # Valid new entry
        entries.append(user)
        counts[user] += 1
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(user + "\n")

        n = counts[user]
        text = "has been entered!" if n == 1 else f"has been entered again (entry #{n})!"
        text += f" {self.slots_left()} slots left!"
        if n < limit:
            text += " As a subscriber you can type !enter once more."
        await message.channel.send(f"🤖 @{display} → {text}")
        print(f"[ADDED] {user} entry #{n} (total: {len(entries)}/{MAX_COUNT})")

    # ---------- mod commands ----------
    async def handle_mod_command(self, message, cmd: str, args: list, user: str):
        send = message.channel.send

        if cmd == "!help":
            status = "OPEN" if self.is_open else "CLOSED"
            await send(
                f"🤖 Status: {status} | Commands: !close, !open, !reset, !remove <name>, "
                f"!count, !ignore <name>, !unignore <name> | {self.slots_left()} slots open"
            )

        elif cmd == "!close":
            if not self.is_open:
                await send("🤖 Entries are already closed.")
                return
            self.is_open = False
            await send(f"🤖 Entries are now CLOSED. {len(entries)} entries.")
            print(f"[MOD] {user} closed entries")

        elif cmd == "!open":
            if self.is_open:
                await send("🤖 Entries are already open.")
                return
            self.is_open = True
            await send(f"🤖 Entries are now OPEN! {self.slots_left()} slots left. Type !enter to join!")
            print(f"[MOD] {user} opened entries")

        elif cmd == "!count":
            status = "OPEN" if self.is_open else "CLOSED"
            await send(
                f"🤖 {len(entries)}/{MAX_COUNT} entries from {len(counts)} people, "
                f"{self.slots_left()} slots left. Entries are {status}."
            )

        elif cmd == "!remove":
            if not args:
                await send("🤖 Usage: !remove <name>")
                return
            name = clean_name(args[0])
            if name not in counts:
                await send(f"🤖 {name} is not on the list.")
                return
            removed = counts.pop(name)
            entries[:] = [e for e in entries if e != name]
            save_list(file_path, entries)
            plural = "entry" if removed == 1 else "entries"
            await send(f"🤖 Removed {removed} {plural} for {name}. {self.slots_left()} slots left.")
            print(f"[MOD] {user} removed {name} ({removed} {plural}; total: {len(entries)}/{MAX_COUNT})")

        elif cmd == "!reset":
            # Safety: require a second word so an accidental !reset can't wipe the list
            if not args or args[0].lower() != "confirm":
                await send(
                    f"🤖 This clears all {len(entries)} entries. Type !reset confirm to proceed "
                    f"(the old list is saved as a backup file first)."
                )
                return
            if file_path.exists() and entries:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = file_path.with_name(f"{file_path.stem}_backup_{stamp}{file_path.suffix}")
                file_path.replace(backup)
                print(f"[MOD] Old list saved to {backup.name}")
            entries.clear()
            counts.clear()
            save_list(file_path, entries)
            await send(f"🤖 Entries cleared. {self.slots_left()} slots open.")
            print(f"[MOD] {user} reset the list")

        elif cmd == "!ignore":
            if not args:
                await send("🤖 Usage: !ignore <name>")
                return
            name = clean_name(args[0])
            if name in (user, NICK.lower()):
                await send("🤖 I can't ignore that user.")
                return
            if name in ignored:
                await send(f"🤖 {name} is already ignored.")
                return
            ignored[name] = None
            save_list(ignore_path, ignored)
            note = " (they are still on the entry list; use !remove to take them off)" if name in counts else ""
            await send(f"🤖 Now ignoring {name}.{note}")
            print(f"[MOD] {user} ignored {name}")

        elif cmd == "!unignore":
            if not args:
                await send("🤖 Usage: !unignore <name>")
                return
            name = clean_name(args[0])
            if name not in ignored:
                await send(f"🤖 {name} is not ignored.")
                return
            del ignored[name]
            save_list(ignore_path, ignored)
            await send(f"🤖 No longer ignoring {name}.")
            print(f"[MOD] {user} unignored {name}")

    # ---------- follower check ----------
    def _api_headers(self) -> dict:
        return {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {TOKEN.replace('oauth:', '')}"
        }

    async def verify_follower_access(self):
        """Startup self-test so a bad token/permission shows up here instead of as confusing chat replies."""
        url = "https://api.twitch.tv/helix/channels/followers"
        params = {"broadcaster_id": BROADCASTER_ID, "first": 1}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._api_headers(), params=params) as resp:
                    if resp.status == 200:
                        print("Follower check: OK (token can read this channel's followers)")
                    elif resp.status == 401:
                        print("Follower check: FAILED (401). The token was rejected: it may be expired, "
                              "belong to a different Client ID, or be missing the moderator:read:followers scope.")
                    elif resp.status == 403:
                        print("Follower check: FAILED (403). The account that owns the token must be the "
                              "broadcaster or a moderator of the channel.")
                    else:
                        print(f"Follower check: FAILED ({resp.status}): {await resp.text()}")
        except Exception as e:
            print(f"Follower check self-test failed: {e}")

    async def is_follower(self, user_id: str):
        """True = follows, False = does not follow, None = couldn't tell (API/network error)."""
        url = "https://api.twitch.tv/helix/channels/followers"
        params = {
            "broadcaster_id": BROADCASTER_ID,
            "user_id": user_id
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self._api_headers(), params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return len(data.get("data", [])) > 0
                    text = await resp.text()
                    print(f"API Error {resp.status}: {text}")
                    return None
        except Exception as e:
            print(f"Follower check failed: {e}")
            return None

    async def event_command_error(self, ctx, error):
        # Silently ignore "command not found" errors
        if isinstance(error, commands.CommandNotFound):
            return
        print(f"Command error: {error}")


if __name__ == "__main__":
    bot = Bot()
    bot.run()