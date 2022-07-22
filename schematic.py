"""
This is a schematic for how an extension of this bot should look
"""
from libs import utils, config
import asyncio

import discord
from discord.ext import commands
from discord import app_commands

import sqlalchemy as sql, sqlalchemy.ext.asyncio as asql
from ormclasses import *
# Declare constants
CONFIG : config.Config = ...

BOT : commands.Bot = ...
WEBHOOK_POOL : utils.WebhookPool = ...

ENGINE : asql.AsyncEngine = ...
SESSION_FACTORY : orm.sessionmaker = ...

# Cog

class Example_Cog(commands.Cog):
    # Put your commands here
    async def cog_load(self):
        pass

    async def cog_unload(self):
        pass
    pass

# Setup & Teardown
async def setup(bot : commands.Bot):
    global CONFIG
    global BOT, WEBHOOK_POOL
    global ENGINE, SESSION_FACTORY
    # Set constants
    CONFIG          = bot.CONFIG
    
    BOT             = bot
    WEBHOOK_POOL    = bot.WEBHOOK_POOL

    ENGINE          = bot.ENGINE
    SESSION_FACTORY = bot.SESSION_FACTORY

    # Add cog to system
    await bot.add_cog(Example_Cog())
    pass

async def teardown(bot : commands.Bot):
    await bot.remove_cog("Example_Cog")
    pass