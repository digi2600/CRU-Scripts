# CRU-Scripts

Small Twitch chat tools for the **#untouchablecru** channel. Every script reads the same `settings.ini`, so your Twitch token and IDs only live in one place.

Currently included:

| Script | What it does |
| --- | --- |
| `enter_collector.py` | Collects `!enter` entries from chat into a text file (for a giveaway / wheel spin), with slot limits, follower checks, subscriber bonus entries and mod controls. |

---

## enter_collector.py

Viewers type `!enter` in chat. The bot adds their name to a text file, tells them how many slots are left, and stops when the list is full. Mods control it from chat.

### Requirements

- Python 3
- `pip install twitchio==2.10.0`
- A Twitch account for the bot (it must be a **moderator** of the channel if you use the follower check)

### Setup

1. Copy `settings.example.ini` to `settings.ini` (same folder as the script, or one folder above it).
2. Fill in the `[twitch]` section:
   - **Token and Client ID:** get both from [twitchtokengenerator.com](https://twitchtokengenerator.com). Log in as the bot account and request these scopes: `chat:read`, `chat:edit`, `moderator:read:followers`.
   - **Broadcaster ID:** the channel's numeric ID. Look it up with [this converter](https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/). Only needed when `check_followers = true`.
   - **Nick:** the bot account's name (lowercase). It must match the account that owns the token.
3. Run it: `python enter_collector.py`

If `settings.ini` is missing, the script creates a template and exits. If a value is missing, still a placeholder, or invalid, it lists every problem and exits instead of connecting. When the follower check is on, the startup output also reports whether the token can read the channel's followers (and tells you what to fix if it can't).

> **Keep `settings.ini` private.** It contains your token and is listed in `.gitignore`. Only `settings.example.ini` (placeholders) belongs in the repo. If a token is ever posted publicly, regenerate it.

### Settings

`[twitch]` is shared by every script that reads `settings.ini`. `[enter_collector]` is specific to this script. Changes apply the next time the script starts.

| Setting | Default | Meaning |
| --- | --- | --- |
| `output_file` | `enter_collector_entries.txt` | The entry list, one line per entry |
| `ignore_file` | `enter_collector_ignored.txt` | Users the bot ignores (managed with `!ignore` / `!unignore`) |
| `state_file` | `enter_collector_state.txt` | Remembers whether entries were open or closed |
| `check_followers` | `true` | Only followers, subscribers, VIPs and mods can enter |
| `max_count` | `100` | Maximum **total** entries (hard cap) |
| `entries_per_user` | `1` | Entries per normal user |
| `subscriber_entries` | `2` | Entries per subscriber |
| `start_open` | `true` | Open/closed state to use before the state file exists |
| `user_cooldown` | `30` | Seconds before the bot answers the same user again for the same command |
| `global_cooldown` | `5` | Seconds between any two bot answers of the same kind |

File names are relative to the script's folder (absolute paths also work).

### Who can enter

- **Followers, subscribers, VIPs and mods** can enter. A VIP or subscriber who doesn't follow is fine.
- **Everyone else** is asked to follow first.
- **Subscribers** (including founders) get a second entry, entered by typing `!enter` again. Being only a VIP or only a mod doesn't count. A mod who is also subscribed gets two.
- **The broadcaster** can't enter. The bot ignores their `!enter` (add their name to the file by hand if you really want it there).
- **Ignored users** get no response at all.

Each entry uses one slot, so a subscriber's second entry counts toward `max_count`. The entry file never goes past `max_count` lines, and a subscriber's name appears on two lines (two spots on the wheel).

### Commands

**Everyone**

| Command | What it does |
| --- | --- |
| `!enter` | Add yourself to the list |
| `!slots` | Show entries used and slots left |
| `!help` | Short instructions (only answers while entries are open) |

**Mods and the broadcaster**

| Command | What it does |
| --- | --- |
| `!open` / `!close` | Open or close entries (saved, so it survives a restart) |
| `!count` | Entries, number of people, slots left, and open/closed status |
| `!remove <name>` | Remove all of that person's entries |
| `!reset` | Shows a warning. Use `!reset confirm` to clear the list; the old list is saved first as `<entries file>_backup_<timestamp>.txt` |
| `!ignore <name>` / `!unignore <name>` | Block or unblock a user (they stay on the list until you `!remove` them) |
| `!help` | Status, the command list, and open slots |

Mod commands typed by anyone else are silently ignored.

### Flood protection

The bot answers the same user at most once per `user_cooldown` seconds per command, and any command at most once per `global_cooldown` seconds overall. Mods are exempt. This only limits the bot's **replies**: every valid new entry is always recorded, even when many people type `!enter` at the same moment. Throttled replies are dropped, not queued.

### Files it creates

| File | Purpose |
| --- | --- |
| `settings.ini` | Your settings (private, not committed) |
| enter_collector_entries file | The list of entries. Open it to copy names into your wheel |
| enter_collector_ignored file | Ignored users |
| enter_collector_state file | Open/closed status |

These runtime files are listed in `.gitignore`. If any of them were committed before being ignored, run `git rm --cached <file>` once to stop tracking them.

### Notes

- Restarting the script keeps the existing entries and the open/closed state.
- If the Twitch API can't be reached during a follower check, the viewer is asked to try again instead of being told they aren't following.
- Race conditions are handled: repeat `!enter` messages while a follower check is running are skipped, and the list is re-checked after the check finishes so the cap can't be exceeded.

---

## Possible future additions

Not implemented yet: a `!draw` command, a Discord bridge, and a general channel bot, all reading the same `settings.ini`.

## License

MIT. See `LICENSE`.
