import discord
from discord.ext import commands
from discord import Embed
import os
# import sqlite3

bot = commands.Bot(command_prefix="!topics ")
# datastore_file = os.environ.get("TOPICPUBSUB_DB") or "topicpubsub.db"
# data_store_conn = None


@bot.event
async def on_ready():
    print("MissionManifest has entered chat; id: {0}".format(bot.user))


@bot.event
async def on_disconnect():
    print("MissionManifest has exited.")


@bot.command(description="<FILL ME IN>")
async def sub(ctx: commands.Context, topic: str):
    pass


@bot.command(name="<ALT_NAME>", description="<WHAT IS MY PURPOSE>")
async def _list(ctx: commands.Context):
    pass


token = os.environ.get("DISCORD_BOT_SECRET")
bot.run(token)
