import random
import discord
from discord.ext import commands
from discord import Embed
import os
import re
import datetime
import sqlite3
from threading import Lock
from typing import List


date_fmt = re.compile(r"(\d){4}-(\d){2}-(\d){2}")
title_fmt = re.compile(r"[*?]")
channel_id_fmt = re.compile(r"<#(\d+)>")
ERRORS = [
    "Date parameter in the wrong format. Format is `YYYY-MM-DD`.",
    "Invalid date; date is before today.",
    "Date exceeds cache limit. Cache limit is 30 days from now."
]
last_scan = None

bot = commands.Bot(command_prefix="!manifest ")
datastore_file = os.environ.get("MISSIONMANIFEST_DB") or "missionmanifest.db"
data_store_conn = None
data_store_lock = None
initialize = False


def validDate(date_str: str):
    date_match = date_fmt.fullmatch(date_str)
    if not date_match:
        return 0
    now = datetime.date.today()
    if int(date_match.group(1)) < now.year:
        if int(date_match.group(2)) < now.month:
            if int(date_match.group(3)) < now.day:
                return 1
            else:
                if int(date_match.group(2)) - now.month > 1:
                    return 2
        else:
            if int(date_match.group(1)) - now.year > 0:
                return 2
    return None


def get_available_emojis(server: int) -> List[str]:
    assert isinstance(data_store_conn, sqlite3.Connection)
    curs = data_store_conn.cursor()
    used = []
    for emoji in curs.execute("SELECT emoji FROM Emoji WHERE server=?;", (server,)):
        used.append(emoji)
    # Get all emojis




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
            curs.execute("CREATE TABLE Emoji (emojiId INTEGER PRIMARY KEY, server INTEGER, emoji STRING);")
            curs.execute("CREATE TABLE Mission (missionId INTEGER PRIMARY KEY, serverId ITNEGER, gameDate INTEGER, dm INTEGER);")
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


@bot.command()
async def test(ctx, arg):
    print("In test")
    await ctx.send("ECHO: {}".format(arg))


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
async def track(ctx: commands.Context, mission_name: str, when: str, track_channel: str,
                *description):
    player_role = [r for r in ctx.guild.roles if r.name == 'PC']
    assert len(player_role) == 1
    player_role = player_role[0]
    if player_role not in ctx.author.roles:
        await ctx.send("Only users with the DM role can create missions.")
        return
    channel_id = channel_id_fmt.match(track_channel).group(1)
    date_bad = validDate(when)
    if date_bad:
        await ctx.send(ERRORS[date_bad])
        return

    emoji = random.choice(get_available_emojis(ctx.guild))
    description = " ".join(description)

    embed = Embed(title="Manifest for \"{}\"".format(mission_name))
    embed.add_field(name="DM", value=ctx.author.nick or ctx.author.name, inline=False)
    embed.add_field(name="Date", value=when, inline=False)
    embed.add_field(name="", value=description, inline=False)
    embed.add_field(name="RSVP In", value=channel_id, inline=False)
    embed.add_field(name="Signup Emoji", value=emoji, inline=False)
    signup_msg = await ctx.send(embed=embed)

    assert isinstance(data_store_conn, sqlite3.Connection)
    assert isinstance(data_store_lock, Lock)
    # Create entry in db for new mission.
    data_store_lock.acquire()
    data_store_conn.execute("INSERT INTO Mission (serverId, scanChannel, missionName, emoji, datetime, tracking_msg)"
                            " VALUES (?, ?, ?, ?, ?);",
                            (ctx.guild, channel_id, mission_name, emoji, when, signup_msg.id))
    data_store_lock.release()

token = os.environ.get("MISSIONMANIFEST_SECRET")
bot.run(token)
