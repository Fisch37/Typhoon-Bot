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

CONFIG: cfg.Config = ...
CONFIG_FILE = "config.cfg"

ENGINE: asql.AsyncEngine = ...
SESSION_FACTORY: Sessionmaker = ...

TOKEN: str = ...
BOT: "Bot" = ...

class DataStorage:
    pass

def _sql_entry_creator(session, table, primary_key, value):
    # This function is a high-arbitration of several other pieces of code
    # It checks for the existance of a table entry and
    # if the entry does not exist, creates it
    async def run():
        result = await session.execute(
            sql.select(getattr(table,primary_key)).
            where(
                sql.select(getattr(table,primary_key)).
                where(getattr(table,primary_key) == value).
                exists()
            )
        )
        if result.scalar() is None:
            session.add(table(**{primary_key:value}))
            pass
        pass
    return asyncio.create_task(run())
    pass

def create_sql_guild_entries(session, guild_id):
    tasks = []
    def task_wrapping(*args):
        tasks.append(_sql_entry_creator(*args))
        pass
    task_wrapping(session,Guild,"id",str(guild_id))
    task_wrapping(session,GuildWarning,"guild_id",str(guild_id))
    task_wrapping(session,GuildLevels,"guild_id",str(guild_id))
    task_wrapping(session,ScheduledMessages,"guild_id",str(guild_id))

    return tasks
    pass

class Bot(commands.Bot):
    INVITE_LINK = "https://discord.com/oauth2/authorize?client_id={id}&scope=bot%20applications.commands&permissions=8"
    
    __slots__= (
        "working_guilds", 
        "CONFIG",
        "IS_TESTING",
        "ENGINE",
        "WEBHOOK_POOL",
        "DATA"
    )
    def __init__(self, testing: bool, *args,guild_ids = None, **kwargs):
        super().__init__(*args,**kwargs)

        if guild_ids is not None:
            self.working_guilds = [discord.Object(id=gid) for gid in guild_ids]
            pass

        self.CONFIG = cfg.load(CONFIG_FILE)
        self.IS_TESTING = testing
        self.WEBHOOK_POOL = utils.WebhookPool(self)
        self.DATA = DataStorage()
        pass

    async def sql_entry_maker(self):
        tasks = []
        async with SESSION_FACTORY() as session:
            async for guild in self.fetch_guilds(limit=None):
                tasks.extend(create_sql_guild_entries(session,guild.id))
                pass

            await asyncio.gather(*tasks)

            await session.commit()
            pass
        pass

    async def setup_hook(self) -> None:
        if self.working_guilds is not None:
            for guild in self.working_guilds:
                self.tree.copy_global_to(guild=guild)
                pass
            pass

        await self.tree.sync()
        logging.info("Synced commands with Discord!")
        
        await self.sql_entry_maker()
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
    BOT = Bot(TESTING_MODE,"/",help_command=None,intents=intents,guild_ids=guild_ids,loop=loop,enable_debug_events=True)
    BOT.tasks = set()

    BOT.ENGINE = ENGINE

    # Initialise ORM
    async with ENGINE.begin() as conn: # Create all tables to make sure that they actually... exist
        conn: asql.AsyncConnection
        await conn.run_sync(Base.metadata.create_all)
        pass

    SESSION_FACTORY = orm.sessionmaker(ENGINE,class_=asql.AsyncSession,expire_on_commit=False)
    BOT.SESSION_FACTORY = SESSION_FACTORY

    # Run system
    logging.info("Launching")

    @BOT.listen("on_ready")
    async def on_ready():
        logging.info(f"Logged in as {BOT.user.name}#{BOT.user.discriminator}!")
        pass

    @BOT.listen("on_guild_join")
    async def join_message(guild: discord.Guild):
        channel = guild.system_channel or guild.public_updates_channel or guild.text_channels[0]

        embed = discord.Embed(colour=discord.Colour.blue(),title="Hello!")
        embed.description = "Thanks for adding me to your server!\nThis bot runs with Slash Commands meaning you can use /help for a command list."
        embed.add_field(name="Support",value="[We also have a support server!](https://discord.gg/FCYvmXBXg6)",inline=False)
        embed.add_field(
            name="Invite Link",
            value=f"If you need an invite link for this bot, use `/invite` or click [here]({BOT.INVITE_LINK.format(id=BOT.user.id)})",inline=False)
        embed.set_author(name=f"{BOT.user.name} developed by Fisch37")

        await channel.send(embed=embed)
        pass

    @BOT.listen("on_guild_join")
    async def sql_creator(guild: discord.Guild):
        async with SESSION_FACTORY() as session:
            await asyncio.gather(*create_sql_guild_entries(session,guild.id))
            pass
        pass

    @BOT.listen("on_guild_remove")
    async def sql_deleter(guild: discord.Guild):
        async with SESSION_FACTORY() as session:
            await session.execute(sql.delete(Guild).where(Guild.id == str(guild.id)))
            await session.commit()
            pass
        pass

    @BOT.listen("on_command_error")
    async def command_error_catch(ctx: commands.Context, error: commands.CommandError):
        cmd: commands.Command = ctx.invoked_subcommand or ctx.command
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

    try:
        async with BOT:
            await asyncio.gather(
                BOT.load_extension("fun"),
                BOT.load_extension("utility"),
                BOT.load_extension("moderation"),
                BOT.load_extension("leveling"),
                
                BOT.load_extension("help_ext"),
                BOT.load_extension("config"),
            )

            await BOT.start(TOKEN)
            pass
    finally: 
        await ENGINE.dispose()
        pass
    pass

if __name__=="__main__":
    asyncio.run(main())
    pass