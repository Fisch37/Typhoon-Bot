import discord
from discord.ext import commands, tasks
from libs import config as cfg
from ormclasses import *
import asyncio
from typing import Optional

SESSION_FACTORY : orm.sessionmaker = ...
BOT : commands.Bot = ...
CONFIG_FILE = "config.cfg"

MESSAGE = """Test"""
if len(MESSAGE) == 0: raise RuntimeError("Don't forget to actually attach a message...")

loop = asyncio.new_event_loop()

async def send_single(guild : discord.Guild, channel_id : Optional[int]):
    channel : discord.TextChannel = None
    if channel_id is not None:
        try:
            channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)
        except discord.NotFound: print("Could not find override channel")
        pass

    if channel is None:
        channel = guild.text_channels[0]
        pass

    await channel.send(MESSAGE)
    pass

@tasks.loop(count=1,loop=loop)
async def send_announcement():
    print("Sending out announcements now...")
    session : asql.AsyncSession = SESSION_FACTORY()
    try:
        result : CursorResult = await session.execute(sql.select(Guild))
        announcement_overrides = {int(guild.id):guild.announcement_override for guild in result.scalars()}

        aws = set()
        for guild in BOT.guilds:
            channel_id = announcement_overrides.get(guild.id)
            if channel_id is not None: channel_id = int(channel_id)
            aws.add(send_single(guild,channel_id))
            pass
        pass
    finally:
        await session.close()
        pass

    print(aws)
    await asyncio.gather(*aws)
    print("Announcement has been sent!")
    pass

def main():
    print(MESSAGE)
    if input("Are you sure that you want to send this message? (y/N) ").upper() != "Y":
        print("Message sending cancelled")
        return
        pass

    global SESSION_FACTORY, BOT

    CONFIG = cfg.load(CONFIG_FILE)
    with open(CONFIG.TOKEN_FILE,"r") as file:
        TOKEN = file.read()
        pass

    ENGINE = asql.create_async_engine(CONFIG.DB_URL[1:-1],echo=False)
    async def async_metacreate(): # Create all tables to make sure that they actually... exist
        async with ENGINE.begin() as conn:
            conn : asql.AsyncConnection
            await conn.run_sync(Base.metadata.create_all)
            pass
        pass
    loop.run_until_complete(async_metacreate())
    SESSION_FACTORY = orm.sessionmaker(ENGINE,class_=asql.AsyncSession,expire_on_commit=False)

    intents = discord.Intents(
        guilds=True
    )
    BOT = commands.Bot("/",intents=intents,loop=loop)
    
    @BOT.event
    async def on_ready():
        send_announcement.start()

    BOT.run(TOKEN)
    pass

if __name__ == "__main__": main()