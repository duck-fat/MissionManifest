import random
import discord
from discord.ext import commands
from discord import Embed
import os
import re
import datetime
import sqlite3
from time import sleep
from threading import Thread, Lock
import asyncio
from typing import List, Tuple, Dict
import pickle
import atexit


datetime_fmt = re.compile(r"(\d{4})-((?:0\d)|(?:1(?:0|1|2)))-((?:0\d)|(?:1\d)|(?:2\d)|(?:3(?:0|1))) ((?:0\d)|(?:1\d)|(?:2(?:0|1|2|3))):([0-5]\d)")
channel_id_fmt = re.compile(r"<#(\d+)>")
level_fmt = re.compile(r"(3\-4)|(5\-8)|(9\-12)|(13\-15)|(17\-20)")


ERRORS = [
    "Date parameter in the wrong format. Format is `YYYY-MM-DD HH:MM`. Time must be in UTC.",
    "Invalid date; date is before today.",
]

bot = commands.Bot(command_prefix="!manifest ")
datastore_file = os.environ.get("MISSIONMANIFEST_DB") or "missionmanifest.db"
data_store_lock = None
initialize = False
poll_thread = None
run_threads = True


def vali_date(date_str: str):
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


@bot.command()
async def deconstruct(ctx: commands.Context, message_url: str):
    msg = await ctx.fetch_message(int(message_url.split("/")[-1]))
    assert isinstance(msg, discord.Message)
    embed = msg.embeds[0] if len(msg.embeds) > 0 else None
    if not embed:
        await ctx.send("Linked message contains no embeds.")
        return
    embed_dict = embed.to_dict()
    response = "***Key***: *Value*\n"
    for key, val in embed_dict.items():
        response += "**{}**: {}\n".format(key, val)
    await ctx.send(response)


def get_available_emojis(server: int) -> List[Tuple[int, str]]:
    used = []
    data_store_lock.acquire()
    with sqlite3.connect(datastore_file) as data_store_conn:
        curs = data_store_conn.cursor()
        for row in curs.execute("SELECT emoji FROM Emoji WHERE server=?;", (server,)):
            used.append(pickle.loads(row[0]))
        curs.close()
    data_store_lock.release()
    used = set(used)
    # Get all emojis
    all_emojis = set((e.id, e.name) for e in bot.get_guild(server).emojis)
    return list(all_emojis - used)


def create_mission_embed(channel_id: int, dm_name: str, description: str, emoji: Tuple[int, str], levels: str,
                         mission_name: str, when: str,
                         roster_size: int = None, responses: List[discord.Message] = None):
    embed = Embed(title="Manifest for \"{}\"".format(mission_name))
    embed.add_field(name="Tier", value=levels, inline=False)
    embed.add_field(name="DM", value=dm_name, inline=False)
    embed.add_field(name="Date", value=when, inline=False)
    embed.add_field(name="Description", value=description, inline=False)
    embed.add_field(name="RSVP In", value="<#{}>".format(channel_id), inline=False)
    embed.add_field(name="Signup Emoji", value=":{}:".format(emoji[1]), inline=False)
    embed.set_thumbnail(url=bot.user.avatar_url)
    embed.set_footer(text="Last Scanned: {}".format(str(datetime.datetime.utcnow())))
    if roster_size and responses:
        embed.add_field(name="Total Signups", value=str(roster_size), inline=False)
        roster = ""
        for response in responses:
            roster += "* [{}]({})\n".format(response.author.nick or response.author.name, response.jump_url)
        embed.add_field(name="Roster", value=roster, inline=False)
    return embed


def embed_to_friendly_dict(embed: discord.Embed) -> Dict[str, object]:
    embed_dict = embed.to_dict()
    embed_fields = embed_dict["fields"]  # List[Dict[str, object]] where object is usually str
    embed_fields = {el['name']: el['value'] for el in embed_fields}
    embed_fields["Title"] = embed_dict["Title"]
    # Parse channel_id field
    embed_fields["RSVP In"] = int(re.match(r"<#(\d)>", embed_fields["RSVP In"]).groups()[0])
    return embed_fields


def scan_history(oldest: int, scan_location: Tuple[int, int], scan_targets: Dict[Tuple[int, str], discord.Message]):
    server = bot.get_guild(scan_location[0])
    assert isinstance(server, discord.Guild)
    scan_channel = server.get_channel(scan_location[1])
    scan_limit = datetime.datetime.utcfromtimestamp(oldest)
    mission_emojis = set(scan_targets.keys())
    mission_updates = {tgt: None for tgt in scan_targets.values()}
    messages = asyncio.run(scan_channel.history(after=scan_limit).flatten())
    for message in messages:
        if len(message.reactions) == 1:  # Restrict to messages with a single emoji
            # get a list of emojis used to react to the message by the message's author (react.me)
            emoji_reacts = [(react.emoji[discord.Emoji].id, react.emoji[discord.Emoji].name)
                            for react in message.reactions if react.me]
            # find any mission emojis in the react list for this message
            emojis_on_msg = mission_emojis.intersection(set(emoji_reacts))
            assert len(emojis_on_msg) == 1
            tracker_msg = scan_targets[emojis_on_msg[0]]  # This is the mission tracking msg object
            if mission_updates[tracker_msg]:
                tmp = mission_updates[tracker_msg]
                new = (tmp[0] + 1, tmp[1] + [message])
                mission_updates[tracker_msg] = new
            else:
                mission_updates[tracker_msg] = (1, [message])  # how many responses found, list of responses
    for tracker_msg, responses in mission_updates.items():
        assert isinstance(tracker_msg, discord.Message)
        tracker_msg_obj = server.get_channel(tracker_msg[1]).fetch_message(tracker_msg[0])
        old_embed_dict = embed_to_friendly_dict(tracker_msg_obj.embeds[0])
        new_embed = create_mission_embed(old_embed_dict["RSVP In"], old_embed_dict["DM"], old_embed_dict["Description"],
                                         old_embed_dict["Signup Emoji"], old_embed_dict["Tier"], old_embed_dict["Title"],
                                         old_embed_dict["Date"], responses[0], responses[1])
        tracker_msg_obj.edit(embed=new_embed)


def poll_thread_body():
    to_remove = []
    to_scan = {}
    oldest_per_channel = {}  # ?? maybe? for tracking oldest post on a per channel basis
    data_store_lock.acquire()
    with sqlite3.connect(datastore_file) as data_store_conn:
        curs = data_store_conn.cursor()
        for row in curs.execute("SELECT Mission.*, Emoji.emoji FROM Mission, Emoji "
                                "WHERE Mission.emojiId=Emoji.emojiId;"):
            when = int(row[4])
            if when <= datetime.datetime.now(datetime.timezone.utc).timestamp():
                # Mission already started or is in the past, clean it up.
                to_remove.append((int(row[0]), int(row[6])))  # Item 1: missionId, Item 2: emojiId
                continue
            # Mission still active
            scan_location = (int(row[1]), int(row[2]))  # Item 1: server_id, Item 2: scan_channel_id
            if scan_location in to_scan:
                # Key: Tuple[int, str] representing discord. Emoji, Value: Tuple[int, int] representing message id, channel id
                to_scan[scan_location][pickle.loads(row[7])] = pickle.loads(row[5])
            else:
                to_scan[scan_location] = {pickle.loads(row[7]): pickle.loads(row[5])}
            mission_time = int(row[3])
            if scan_location in oldest_per_channel:
                if oldest_per_channel[scan_location] < mission_time:
                    continue
            oldest_per_channel[scan_location] = mission_time
        # Iterate through scan_channel's history between mission_create_time and present to look for emoji
        for scan_location, scan_targets in to_scan.items():
            t = Thread(target=scan_history, args=(oldest_per_channel[scan_location], scan_location, scan_targets))
            t.start()
        # delete anything in the to_remove list
        for el in to_remove:
            curs.execute("DELETE FROM Emoji WHERE emojiId=?", (el[1],))
            curs.execute("DELETE FROM Mission WHERE missionId=?", (el[0],))
        curs.close()
        data_store_conn.commit()
    data_store_lock.release()


def poll_thread_loop(frequency: float = 0.0033):  # default to once every 5 minutes
    while run_threads:
        poll_thread_body()
        sleep(1 / frequency)


@bot.event
async def on_ready():
    global data_store_lock
    global initialize
    global poll_thread
    if not data_store_lock:
        data_store_lock = Lock()
    initialize = not os.path.exists(datastore_file)
    if initialize:
        data_store_lock.acquire()
        with sqlite3.connect(datastore_file) as data_store_conn:
            curs = data_store_conn.cursor()
            curs.execute("CREATE TABLE Emoji (emojiId INTEGER PRIMARY KEY, server INTEGER, emoji BLOB);")
            curs.execute("CREATE TABLE Mission "
                         "(missionId INTEGER PRIMARY KEY, serverId INTEGER, scanChannelId INTEGER, "
                         "missionCreateTime INTEGER, missionTime INTEGER,"
                         "trackingMsg BLOB, emojiId INTEGER);")
            data_store_conn.commit()
            initialize = False
        data_store_lock.release()
    print("MissionManifest has entered chat; id: {0}".format(bot.user))
    poll_thread = Thread(target=poll_thread_loop)
    poll_thread.start()


@bot.event
async def on_disconnect():
    global run_threads
    run_threads = False
    poll_thread.join()
    print("MissionManifest has exited.")


@bot.command(description="<FILL ME IN>")
async def scan(ctx: commands.Context):
    print("called scan!")
    poll_thread_body()


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
    when_posix, err = vali_date(when)
    if not when_posix:
        await ctx.send(ERRORS[err])
        return

    emoji = random.choice(get_available_emojis(ctx.guild.id))
    emoji_blob = pickle.dumps(emoji)
    description = " ".join(description)

    embed = create_mission_embed(channel_id, ctx.author.nick or ctx.author.name,
                                 description, emoji, levels, mission_name, when)
    tracking_msg = await ctx.send(embed=embed)
    tracking_msg_url_parts = tracking_msg.jump_url.split("/")
    # Item 1: message id, Item 2: channel id
    tracking_msg_info = pickle.dumps((int(tracking_msg_url_parts[-1]), int(tracking_msg_url_parts[-2])))

    # Create entry in db for new mission.
    data_store_lock.acquire()
    with sqlite3.connect(datastore_file) as data_store_conn:
        data_store_conn.execute("INSERT INTO Emoji (server, emoji) VALUES (?, ?);", (ctx.guild.id, emoji_blob))
        curs = data_store_conn.cursor()
        curs.execute("SELECT emojiId from Emoji WHERE emojiId=(SELECT MAX(emojiId) FROM Emoji);")
        emoji_id = curs.fetchone()[0]
        curs.close()

        data_store_conn.execute("INSERT INTO Mission (serverId, scanChannelId, "
                                "missionCreateTime, missionTime, "
                                "trackingMsg, emojiId) "
                                "VALUES (?, ?, ?, ?, ?, ?);",
                                (ctx.guild.id, channel_id,
                                 datetime.datetime.now(tz=datetime.timezone.utc).timestamp(), when_posix,
                                 tracking_msg_info, emoji_id))
        data_store_conn.commit()
    data_store_lock.release()

atexit.register(lambda: on_disconnect())

token = os.environ.get("MISSIONMANIFEST_SECRET")
bot.run(token)
