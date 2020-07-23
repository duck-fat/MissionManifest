import discord
from discord.ext import commands
from discord import Embed
import os
import re
import datetime
# import sqlite3

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


@bot.command()
async def test(ctx, arg):
    print("In test")
    await ctx.send("ECHO: {}".format(arg))


@bot.command(description="<FILL ME IN>")
async def scan(ctx: commands.Context, mission_name: str, channel_id: str):
    global last_scan
    channel_id = channel_id_fmt.match(channel_id).group(1)
    channel = await bot.fetch_channel(channel_id)
    player_role = [r for r in ctx.guild.roles if r.name == 'PC']
    assert len(player_role) == 1
    player_role = player_role[0]
    now = datetime.datetime.utcnow()
    if not last_scan:
        last_scan = now - datetime.timedelta(days=14)
    num_signups = 0
    responses = []
    # query message history
    embed = Embed(title="Manifest for {}".format(mission_name))
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
                character = lines[1]
                message_url = r"https://discordapp.com/channels/{}/{}/{}".format(ctx.guild.id, ctx.channel.id, message.id)
                responses.append((message.author.nick or message.author.name, character, message_url))
    embed.add_field(name="Total Signups", value=str(num_signups), inline=False)
    roster = ""
    for response in responses:
        roster += "* {}: {}\n".format(response[0], "[{}]({})".format(response[1], response[2]))
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
