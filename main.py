from loop import loop # Create own loop to prevent sqlalchemy's temper tantrum
import libs.config as cfg, libs.utils as utils
import asyncio, logging, os
from datetime import datetime

import sqlalchemy as sql
import sqlalchemy.ext.asyncio as asql
import sqlalchemy.orm as orm
from ormclasses import *

import discord
from discord.ext import commands

CONFIG : cfg.Config = ...
CONFIG_FILE = "config.cfg"

ENGINE : asql.AsyncEngine = ...
SESSION_FACTORY : orm.sessionmaker = ...

TOKEN : str = ...
BOT : commands.Bot = ...

INVITE_LINK = "https://discord.com/oauth2/authorize?client_id=897055320646492231&scope=bot%20applications.commands&permissions=8"

class DataStorage:
    pass

class Bot(commands.Bot):
    __slots__= "working_guilds", 
    def __init__(self, *args,guild_ids= None, **kwargs):
        super().__init__(*args,**kwargs)

        if guild_ids is not None:
            self.working_guilds= [discord.Object(id=gid) for gid in guild_ids]
            pass
        pass

    async def setup_hook(self) -> None:
        if self.working_guilds is not None:
            for guild in self.working_guilds:
                self.tree.copy_global_to(guild=guild)
                pass

            await self.tree.sync()
            pass
        pass
    pass

def setCustomLogger(level = logging.INFO):
    if not os.path.exists('logs'):
        os.mkdir("logs")

    currTime = datetime.now()
    logFileName = "logs/{0}-{1}-{2}-{3}.log".format(currTime.date(),currTime.hour,currTime.minute,currTime.second)
    formatStr = "[%(asctime)s | %(threadName)s / %(levelname)s] %(message)s"
    logging.basicConfig(filename = logFileName, level=level,format=formatStr)

    stdoutLogger = logging.StreamHandler()
    stdoutLogger.setFormatter(logging.Formatter(formatStr))
    logging.getLogger().addHandler(stdoutLogger)
    pass

async def main():
    global CONFIG
    global ENGINE, SESSION_FACTORY
    global TOKEN, BOT
    # Set up logger
    setCustomLogger()
    # Load neccessary values
    logging.info("Loading config")
    CONFIG = cfg.load(CONFIG_FILE)
    with open(CONFIG.TOKEN_FILE,"r") as file:
        TOKEN = file.read()
        pass
    TESTING_MODE = os.path.exists("testing.inf")
    
    # Load database

    logging.info("Loading the database & orm")
    
    ENGINE = asql.create_async_engine(CONFIG.DB_URL[1:-1],echo=False)

    # Create bot instance
    logging.info("Creating bot application")
    intents = discord.Intents(3180143)
    """This is the following configuration:
    GUILDS, GUILD_MEMBERS, GUILD_BANS, GUILD_EMOJIS_AND_STICKERS, GUILD_WEBHOOKS, GUILD_INVITES, GUILD_MESSAGES, \
        GUILD_MESSAGE_REACTIONS, MESSAGE_CONTENT,AUTO_MODERATION_CONFIGURATION, AUTO_MODERATION_EXECUTION"""
    if TESTING_MODE: guild_ids = (734461254747553823,)
    else: guild_ids = tuple()
    BOT = Bot("/",help_command=None,intents=intents,guild_ids=guild_ids,loop=loop,enable_debug_events=True)
    BOT.tasks = set()

    BOT.ENGINE = ENGINE
    BOT.CONFIG = CONFIG
    BOT.IS_TESTING = TESTING_MODE

    # Initialise ORM
    async with ENGINE.begin() as conn: # Create all tables to make sure that they actually... exist
        conn : asql.AsyncConnection
        await conn.run_sync(Base.metadata.create_all)
        pass

    SESSION_FACTORY = orm.sessionmaker(ENGINE,class_=asql.AsyncSession,expire_on_commit=False)
    BOT.SESSION_FACTORY = SESSION_FACTORY

    # Run system
    logging.info("Launching")

    BOT.WEBHOOK_POOL = utils.WebhookPool(BOT)
    BOT.DATA = DataStorage()

    @BOT.listen("on_ready")
    async def on_ready():
        logging.info(f"Logged in as {BOT.user.name}#{BOT.user.discriminator}!")
        pass

    @BOT.listen("on_guild_join")
    async def join_message(guild : discord.Guild):
        channel = guild.system_channel or guild.public_updates_channel or guild.text_channels[0]

        embed = discord.Embed(colour=discord.Colour.blue(),title="Hello!")
        embed.description = "Thanks for adding me to your server!\nThis bot runs with Slash Commands meaning you can use /help for a command list."
        embed.add_field(name="Support",value="[We also have a support server!](https://discord.gg/FCYvmXBXg6)",inline=False)
        embed.add_field(name="Invite Link",value=f"If you need an invite link for this bot, use `/invite` or click [here]({INVITE_LINK})",inline=False)

        await channel.send(embed=embed)
        pass

    @BOT.listen("on_guild_join")
    async def sql_creator(guild : discord.Guild):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(guild.id)))
            if result.first() is None:
                session.add(Guild(id=str(guild.id)))
                await session.commit()
                pass
        finally:
            await session.close()
        pass

    @BOT.listen("on_guild_remove")
    async def sql_deleter(guild : discord.Guild):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            await session.execute(sql.delete(Guild).where(Guild.id == str(guild.id)))
            await session.commit()
        finally:
            await session.close()
        pass

    @BOT.listen("on_command_error")
    async def command_error_catch(ctx : commands.Context, error : commands.CommandError):
        cmd : commands.Command = ctx.invoked_subcommand or ctx.command
        if isinstance(error,commands.errors.MissingPermissions) and hasattr(cmd.callback,"permission_error_msg"): # If utils.perm_message_check was used
            await ctx.send(cmd.callback.permission_error_msg,ephemeral=True)
            pass

        else:
            if TESTING_MODE:
                raise error
            else:
                await ctx.send("Oh no! Some kind of error occured!",ephemeral=True)
                logging.error(error)
                pass
            pass
        pass

    await asyncio.gather(
        # BOT.load_extension("fun"),
        # BOT.load_extension("utility"),
        # BOT.load_extension("moderation"),
        # BOT.load_extension("leveling"),
        
        BOT.load_extension("help_ext"),
        # BOT.load_extension("config"),
    )

    try:
        async with BOT:
            await BOT.start(TOKEN)
            pass
    finally: 
        await ENGINE.dispose()
        pass
    pass

if __name__=="__main__":
    asyncio.run(main())
    pass