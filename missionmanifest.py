import random
import discord
from discord.ext import commands
from discord import Embed
import os
import re
import datetime
import sqlite3
from time import sleep
from threading import Lock
from typing import List
import pickle


datetime_fmt = re.compile(r"(\d{4})-((?:0\d)|(?:1(?:0|1|2)))-((?:0\d)|(?:1\d)|(?:2\d)|(?:3(?:0|1))) ((?:0\d)|(?:1\d)|(?:2(?:0|1|2|3))):([0-5]\d)")
channel_id_fmt = re.compile(r"<#(\d+)>")
level_fmt = re.compile(r"(3\-4)|(5\-8)|(9\-12)|(13\-15)|(17\-20)")


ERRORS = [
    "Date parameter in the wrong format. Format is `YYYY-MM-DD HH:MM`. Time must be in UTC.",
    "Invalid date; date is before today.",
]

bot = commands.Bot(command_prefix="!manifest ")
datastore_file = os.environ.get("MISSIONMANIFEST_DB") or "missionmanifest.db"
data_store_conn = None
data_store_lock = None
initialize = False


def validDate(date_str: str):
    date_match = datetime_fmt.fullmatch(date_str)
    if not date_match:
        return None, 0
    now = datetime.datetime.now(datetime.timezone.utc)
    parsed = datetime.datetime(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)),
                               hour=int(date_match.group(4)), minute=int(date_match.group(5)),
                               tzinfo=datetime.timezone.utc)
    if now > parsed:
        return None, 1
    return parsed.timestamp(), None


def valid_levels(levels: str) -> bool:
    if level_fmt.match(levels):
        return True
    return False


@bot.command()
async def emojis(ctx):
    all_emojis = bot.get_guild(ctx.guild.id).emojis
    emoji_list = ["<:{}:{}>".format(e.name, e.id) for e in all_emojis]
    await ctx.send("Server's emojis: {}".format(" ".join(emoji_list)))


def get_available_emojis(server: int) -> List[str]:
    assert isinstance(data_store_conn, sqlite3.Connection)
    used = []
    with data_store_conn.cursor() as curs:
        for row in curs.execute("SELECT emoji FROM Emoji WHERE server=?;", (server,)):
            used.append(pickle.loads(row[0]))
    used = set(used)
    # Get all emojis
    all_emojis = set(bot.get_guild(server).emojis)
    return list(all_emojis - used)


def create_mission_embed(channel_id, dm_name, description, emoji, levels, mission_name, when):
    embed = Embed(title="Manifest for \"{}\"".format(mission_name))
    embed.add_field(name="Tier", value=levels, inline=False)
    embed.add_field(name="DM", value=dm_name, inline=False)
    embed.add_field(name="Date", value=when, inline=False)
    embed.add_field(name="Description", value=description, inline=False)
    embed.add_field(name="RSVP In", value="<#{}>".format(channel_id), inline=False)
    embed.add_field(name="Signup Emoji", value=emoji, inline=False)
    embed.set_thumbnail(url=bot.user.avatar_url)
    embed.set_footer(text="Last Scanned: {}".format(str(datetime.datetime.utcnow())))
    return embed


def poll_thread():
    assert isinstance(data_store_conn, sqlite3.Connection)
    to_remove = []
    to_scan = {}
    oldest_per_channel = {}  # ?? maybe? for tracking oldest post on a per channel basis
    with data_store_conn.cursor() as curs:
        for row in curs.execute("SELECT Mission.*, Emoji.emoji FROM Mission, Emoji "
                                "WHERE Mission.emojiId=Emoji.emojiId;"):
            when = int(row[4])
            if when <= datetime.datetime.now(datetime.timezone.utc).timestamp():
                # Mission already started or is in the past, clean it up.
                to_remove.append((int(row[0]), int(row[6])))
                continue
            # Mission still active
            scan_location = (int(row[1]), int(row[2]))  # Item 1: server_id, Item 2: scan_channel_id
            scan_target = (row[5], row[7])  # Item 1: discord.Message blob, Item 2: emoji blob

            if scan_location in to_scan:
                to_scan[scan_location].append(scan_target)
            else:
                to_scan[scan_location] = [scan_target]
            mission_time = int(row[3])
            if scan_location in oldest_per_channel:
                if oldest_per_channel[scan_location] < mission_time:
                    continue
            oldest_per_channel[scan_location] = mission_time
    ''' BIG BRAIN: collect relevant info from Db first, then iterate through server.scan_channels and
    find all replies at once instead of re-scanning.'''
    # Iterate through scan_channel's history between mission_create_time and present to look for emoji
    for scan_location, scan_target in to_scan.items():
        server = bot.get_guild(scan_location[0])
        assert isinstance(server, discord.Guild)
        scan_channel = server.get_channel(scan_location[1])
        scan_limit = datetime.datetime.utcfromtimestamp(oldest_per_channel[scan_location])
        for message in await scan_channel.history(after=scan_limit):
            if scan_target[1] in message.reactions:  # Need to get actual emoji entity (id:name)
                pass
        tracking_msg = pickle.loads(scan_target[0])
        tracking_embed = tracking_msg.embeds[0]
    # delete anything in the to_remove list
    pass


@bot.event
async def on_ready():
    global data_store_lock
    global data_store_conn
    global initialize
    if not data_store_lock:
        data_store_lock = Lock()
    if not data_store_conn:
        data_store_lock.acquire()
        initialize = not os.path.exists(datastore_file)
        data_store_conn = sqlite3.connect(datastore_file)
        if initialize:
            assert isinstance(data_store_conn, sqlite3.Connection)
            curs = data_store_conn.cursor()
            curs.execute("CREATE TABLE Emoji (emojiId INTEGER PRIMARY KEY, server INTEGER, emoji BLOB);")
            curs.execute("CREATE TABLE Mission "
                         "(missionId INTEGER PRIMARY KEY, serverId INTEGER, scanChannelId INTEGER, "
                         "missionCreateTime INTEGER, missionTime INTEGER,"
                         "tracking_msg BLOB, emojiId INTEGER);")
            data_store_conn.commit()
            initialize = False
        data_store_lock.release()
    print("MissionManifest has entered chat; id: {0}".format(bot.user))


@bot.event
async def on_disconnect():
    global data_store_conn
    if data_store_conn:
        assert isinstance(data_store_lock, Lock)
        data_store_lock.acquire()
        assert isinstance(data_store_conn, sqlite3.Connection)
        data_store_conn.close()
        data_store_conn = None
        data_store_lock.release()
    print("MissionManifest has exited.")


@bot.command(description="<FILL ME IN>")
async def scan(ctx: commands.Context, mission_name: str, channel_id: str):
    global last_scan
    channel_id = channel_id_fmt.match(channel_id).group(1)
    channel = await bot.fetch_channel(channel_id)
    now = datetime.datetime.utcnow()
    if not last_scan:
        last_scan = now - datetime.timedelta(days=14)
    num_signups = 0  # This will end up pulled from the cache eventually
    responses = []
    # query message history
    async for message in channel.history(limit=None, before=now, after=last_scan, oldest_first=True):
        lines = message.content.split('\n')
        try:
            assert len(lines) > 1
        except AssertionError:
            # Skip any single-line messages; sign-up messages must have the mission name as the first line.
            continue
        if mission_name.lower() in lines[0].lower():
            # found the mission we're looking for
            if player_role in message.author.roles:
                num_signups += 1
                # The format assumes line 0 = mission name, line 1 = character name, line i...n = extra info
                character = lines[1]
                message_url = r"https://discordapp.com/channels/{}/{}/{}".format(ctx.guild.id, ctx.channel.id, message.id)
                responses.append((message.author.nick or message.author.name, character, message_url))
    # Build the response Embed
    embed = Embed(title="Manifest for \"{}\"".format(mission_name))
    embed.add_field(name="Total Signups", value=str(num_signups), inline=False)
    roster = ""
    for response in responses:
        roster += "* {}: {}\n".format(response[0], "[{}]({})".format(response[1], response[2]))
    embed.add_field(name="Roster", value=roster, inline=False)

    await ctx.send(embed=embed)
    # Record the current scan as the most recent for caching purposes.
    last_scan = now


@bot.command(description="<WHAT IS MY PURPOSE>")
async def track(ctx: commands.Context, mission_name: str, when: str, levels: str, track_channel: str,
                *description):
    if not valid_levels(levels):
        await ctx.send("Invalid level range.")
        return
    player_role = [r for r in ctx.guild.roles if r.name == 'DM']
    if len(player_role) != 1:
        await ctx.send("Server does not provide a DM role.")
        return
    player_role = player_role[0]
    if player_role not in ctx.author.roles:
        await ctx.send("Only users with the DM role can create missions.")
        return
    channel_id = channel_id_fmt.match(track_channel).group(1)
    when_posix, err = validDate(when)
    if not when_posix:
        await ctx.send(ERRORS[err])
        return

    emoji = random.choice(get_available_emojis(ctx.guild.id))
    description = " ".join(description)

    embed = create_mission_embed(channel_id, ctx.author.nick or ctx.author.name,
                                 description, emoji, levels, mission_name, when)
    tracking_msg = await ctx.send(embed=embed)

    assert isinstance(data_store_conn, sqlite3.Connection)
    # Create entry in db for new mission.
    data_store_lock.acquire()
    emoji_blob = pickle.dumps(emoji)
    data_store_conn.execute("INSERT INTO Emoji (server, emoji) VALUES (?, ?);", (ctx.guild.id, emoji_blob))
    curs = data_store_conn.cursor()
    curs.execute("SELECT emojiId from Emoji WHERE emojiId=(SELECT MAX(emojiId) FROM Emoji);")
    emoji_id = curs.fetchone()[0]
    curs.close()
    tracking_msg_blob = pickle.dumps(tracking_msg)
    data_store_conn.execute("INSERT INTO Mission (serverId, scanChannelId, "
                            "missionCreateTime, missionTime, "
                            "tracking_msg, emojiId) "
                            "VALUES (?, ?, ?, ?, ?, ?);",
                            (ctx.guild.id, channel_id,
                             datetime.datetime.now(tz=datetime.timezone.utc).timestamp(), when_posix,
                             tracking_msg_blob, emoji_id))
    data_store_conn.commit()
    data_store_lock.release()


token = os.environ.get("MISSIONMANIFEST_SECRET")
bot.run(token)
