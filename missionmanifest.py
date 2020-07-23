import discord
from discord.ext import commands
from discord import Embed
import os
import re
import datetime
# import sqlite3

date_fmt = re.compile(r"(\d){4}-(\d){2}-(\d){2}")
title_fmt = re.compile(r"[*?]")
ERRORS = [
    "Date parameter in the wrong format. Format is `YYYY-MM-DD`.",
    "Invalid date; date is before today.",
    "Date exceeds cache limit. Cache limit is 30 days from now."
]
last_scan = None

bot = commands.Bot(command_prefix="?manifest")#, "!manifest"])
# datastore_file = os.environ.get("MISSIONMANIFEST_DB") or "missionmanifest.db"
# data_store_conn = None


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


@bot.event
async def on_ready():
    print("MissionManifest has entered chat; id: {0}".format(bot.user))


@bot.event
async def on_disconnect():
    print("MissionManifest has exited.")


@bot.command
async def test(ctx, arg):
    await ctx.send("ECHO: {}".format(arg))


@bot.command(description="<FILL ME IN>")
async def scan(ctx: commands.Context, mission_name: str, channel_id: int):
    global last_scan
    print("In scan!")
    channel = await bot.fetch_channel(channel_id)
    player_role = [r for r in ctx.guild.roles if r.name == 'PC'][0]
    assert len(player_role) == 1
    now = datetime.datetime.utcnow()
    if not last_scan:
        last_scan = now - datetime.timedelta(days=14)
    num_signups = 0
    responses = []
    # query message history
    embed = Embed(title="Manifest for {}".format(mission_name))
    async for message in channel.history(limit=None, before=now, after=last_scan, oldest_first=True):
        lines = message.content.split('\n')
        if mission_name.lower() in lines[0].lower():
            # found the mission we're looking for
            if player_role in message.author.roles:
                num_signups += 1
                responses.append((message.author, message.id))
    embed.add_field(name="Total Signups", value=str(num_signups), inline=False)
    roster = ""
    for response in responses:
        roster += "* {}: {}".format(response[0], response[1])
    embed.add_field(name="Roster", value=roster, inline=False)
    await ctx.send(embed=embed)
    last_scan = now


@bot.command(description="<WHAT IS MY PURPOSE>")
async def track(ctx: commands.Context, mission_name: str, date: str):
    date_bad = validDate(date)
    if date_bad:
        await ctx.send(ERRORS[date_bad])
        return

token = os.environ.get("MISSIONMANIFEST_SECRET")
bot.run(token)
