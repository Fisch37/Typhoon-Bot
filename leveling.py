from typing import Optional
import discord
from discord.ext import commands, tasks
from discord.ext.commands.converter import Option

from libs import utils, config
from loop import loop
import logging, random, asyncio, time
from datetime import datetime

from ormclasses import *

CONFIG : config.Config = ...
WEBHOOK_POOL : utils.WebhookPool = ...

BOT : commands.Bot = ...
COG : commands.Cog = ...

SESSION_FACTORY : asql.AsyncSession = ...
ENGINE : asql.AsyncEngine = ...

GuildId = MemberId = int


# Some other stuff

level_to_xp = lambda level: int((5*level**3)/3 + (45/2)*level**2+(455/6)*level)
"""But why are you not solving for the xp and then check for the level the current xp will give?
Because: https://www.wolframalpha.com/input/?i=solve+for+x+in+y%3D%285%2F6%29*x%5E3+%2B+%2845%2F2%29*x%5E2+%2B+%28455%2F6%29*x
Please send a working version in, if you have one"""
xp_to_progress = lambda level, xp: round(((xp - level_to_xp(level)) / (level_to_xp(level+1) - level_to_xp(level)))*100)

class LevelStats:
    __slots__ = ("internal","timestamps")
    def __init__(self) -> None:
        self.internal : dict[MemberId,tuple[int,int]] = {}
        """1. is xp, 2. is level"""
        self.timestamps : dict[MemberId,int] = {}
        pass

    def __getitem__(self, indices : MemberId):
        if not isinstance(indices,MemberId): raise IndexError(f"Index is of type {indices.__class__}, expected type {MemberId}")

        return self.internal.get(indices,(0,0))
        pass

    def __setitem__(self, indices : MemberId, value : tuple[int,int]):
        if not isinstance(indices,MemberId): raise IndexError(f"Index is of type {indices.__class__}, expected type {MemberId}")
        if not isinstance(value,tuple) or not isinstance(value[0],int) or not isinstance(value[1],int): raise TypeError(f"value has to be of type tuple[int,int], is {type(value)}[{type(value[0])},{type(value[1])}]")

        self.internal[indices] = value
        pass

    def __iter__(self):
        return iter(self.internal.items())
        pass

    def xp(self, target : MemberId) -> int:
        if not isinstance(target,MemberId): raise TypeError(f"Argument target is of type {type(target)}, expected type {MemberId}")
        return self.internal.get(target,(0,0))[0]
        pass

    def level(self, target : MemberId) -> int:
        if not isinstance(target,MemberId): raise TypeError(f"Argument target is of type {type(target)}, expected type {MemberId}")
        return self.internal.get(target,(0,0))[1]
        pass

    def rank(self, target : MemberId) -> int:
        target_xp = self.xp(target)
        people_above = 0
        for _, xp in self.internal.values():
            if xp > target_xp: people_above+=1
            pass
        return people_above + 1
        pass

    def set(self, target : MemberId, xp : int, level : int,*,overwrite : bool = False) -> None:
        if not overwrite and target in self.internal.keys(): raise RuntimeError("set would have overriden a value and was stopped. If this is intentional, set overwrite to true")
        self.internal[target] = (xp,level)
        pass

    def raise_xp(self, target : MemberId, xp_raise : int) -> tuple[int,int]:
        if not isinstance(target,MemberId): raise TypeError(f"target has to be of type {MemberId}, is {type(target)}")
        if not isinstance(xp_raise, int): raise TypeError(f"xp_raise has to be of type {int}, is {type(xp_raise)}")
        if xp_raise <= 0: raise ValueError(f"xp_raise has to be a positive integer, is {xp_raise}")
        xp, level = self[target]
        
        xp += xp_raise
        while level_to_xp(level + 1) <= xp: level += 1 # Update level to fit the xp

        self.set(target,xp,level,overwrite=True)
        pass

    def check_can_gain(self,target : MemberId, timeout : float):
        return time.time() - self.timestamps.get(target,0) >= timeout
        pass

    @classmethod
    def from_raw(cls, data : dict[MemberId,tuple[int,int]]):
        obj = cls()
        for target, (xp,level) in data.items():
            obj[int(target)] = (xp,level)
            pass

        return obj
        pass

    def to_raw(self):
        return self.internal.copy()
        pass
    pass

class LevelSettings:
    __slots__ = ("lower_gain","upper_gain","timeout", "enabled", "channel_id","level_msg")
    def __init__(
        self, 
        enabled : bool = Guild.level_state.default.arg, 
        lower_gain : int = Guild.lower_xp_gain.default.arg, 
        upper_gain : int = Guild.upper_xp_gain.default.arg, 
        timeout : int = Guild.xp_timeout.default.arg,
        channel_id : Optional[int] = Guild.level_channel.default,
        level_msg : str = Guild.level_msg.default.arg
        ):
        self.lower_gain = lower_gain
        self.upper_gain = upper_gain
        self.timeout = timeout
        self.enabled = enabled
        self.channel_id = channel_id
        self.level_msg = level_msg
        pass

    async def save(self, guild_id : GuildId):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            await session.execute(sql.update(Guild).where(Guild.id == str(guild_id)).values(lower_xp_gain=self.lower_gain,upper_xp_gain=self.upper_gain,xp_timeout=self.timeout,level_channel=str(self.channel_id)))
            await session.commit()
        finally:
            await session.close()
        pass
    pass

####### Cog

class Leveling(commands.Cog):
    "A system which grants members points based on their activity"
    LEVELS : dict[GuildId,LevelStats] = {}
    LEVEL_SETTINGS : dict[GuildId,LevelSettings] = {}

    def __init__(self):
        super().__init__()
        self.sql_saver_task.start()
        pass

    def cog_unload(self):
        super().__init__()
        self.sql_saver_task.stop()
        pass

    async def send_levelup(self, message : discord.Message, level : int):
        """TODO: A full implementation"""
        logging.warn("This is not completely implemented. Custom levelup messages should be implemented as well, but aren't yet")

        await message.channel.send(f"Geez! You leveled up to level {level}") # Actually a format string is quickest (I suspect that's because it's C)
        pass

    async def reward_roles_check(self, message : discord.Message):
        raise NotImplementedError("Wow! Reward Roles! If only there was a function that managed those!")
        pass

    @commands.Cog.listener("on_message")
    async def xp_gain(self,message : discord.Message):
        member = message.author
        guild  = message.guild
        
        if guild is None or member.bot: return # We don't need any bot levelling, do we? # Nor do we need any commands to start this

        level_settings = self.LEVEL_SETTINGS[guild.id] # This will throw KeyError sometimes, but I'll fix that later

        if not level_settings.enabled: return # Should be obvious, I think

        self.LEVELS.setdefault(guild.id,LevelStats())
        levels = self.LEVELS[guild.id] # This will also throw KeyError sometimes
        if not levels.check_can_gain(member.id,level_settings.timeout): return # If the user has gained XP recently, don't add any

        prev_level = levels.level(member.id)
        levels.raise_xp(member.id,random.randint(level_settings.lower_gain,level_settings.upper_gain)) # This also updates the level
        post_level = levels.level(member.id)

        if prev_level != post_level:
            # Doing this in relative sync for consistency (Note: With modern versions of discord.py this won't affect other on_message events as they are scheduled as tasks)
            await self.send_levelup(message,post_level)
            await self.reward_roles_check(message)
            pass
        pass

    @commands.Cog.listener("on_ready")
    @utils.call_once_async
    async def leveling_collector(self):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild))
            for sqlobj in result.scalars():
                sqlobj : Guild
                guild_id = int(sqlobj.id)

                self.LEVEL_SETTINGS[guild_id] = LevelSettings(sqlobj.level_state, sqlobj.lower_xp_gain,sqlobj.upper_xp_gain,sqlobj.xp_timeout,sqlobj.level_channel,sqlobj.level_msg)
                pass

            result : CursorResult = await session.execute(sql.select(GuildLevels))
            for sqlobj in result.scalars():
                sqlobj : GuildLevels
                guild_id = int(sqlobj.guild_id)

                self.LEVELS[guild_id] = LevelStats.from_raw(sqlobj.levels)
                pass
        finally:
            await session.close()
        pass


    @commands.command("level")
    async def level_get(self, ctx : commands.Context, user : discord.Member = Option(None,description="The member to get the level and xp for. If unset it will default to yourself")):
        lvl_settings = self.LEVEL_SETTINGS[ctx.guild.id]

        if not lvl_settings.enabled:
            await ctx.send("Levels? What levels? (Leveling is disabled)",ephemeral=True)
            return
            pass
        if user is None: user = ctx.author
        if user.bot:
            await ctx.send("Bots? Bots don't get any XP!")
            return

        levels = self.LEVELS.get(ctx.guild.id,LevelStats())
        xp, level = levels[user.id]
        progress = xp_to_progress(level,xp)

        embed = discord.Embed(colour=user.colour,title=f"Leveling Stats")
        embed.set_author(name=user.display_name,icon_url=user.display_avatar.url)
        embed.description=f"Level: {level}\nXP: {xp} ({progress}%)"
        await ctx.send(embed=embed,ephemeral=True)
        pass

    @commands.command("leaderboard",brief="Ranks every member that ever got xp")
    async def leaderboard(self, ctx : commands.Context):
        lvl_settings = self.LEVEL_SETTINGS.get(ctx.guild.id,LevelSettings(False,0,0,0))

        if not lvl_settings.enabled:
            await ctx.send("Levels? What levels? (Leveling is disabled)",ephemeral=True)
            return
            pass
        
        def sort():
            levels = self.LEVELS.get(ctx.guild.id,LevelStats())
            return sorted(levels,key=lambda item:item[1][0],reverse=True)
            pass
        sorted_iter : list[tuple[MemberId,tuple[int,int]]] = await asyncio.get_event_loop().run_in_executor(None,sort)
        

        embed = discord.Embed(colour = discord.Colour.green(),title=f"Leaderboard of {ctx.guild.name}",timestamp=datetime.utcnow())
        if len(sorted_iter) > 0:
            target_list = []
            level_list = []
            xp_list = []
            for target, (xp, level) in sorted_iter:
                target_list.append(f"<@{target}>") # I did a smart thing!
                # Format strings are quick, I found out
                level_list.append(f"{level}")
                xp_list.append(f"{xp} ({xp_to_progress(level,xp)}%)")
                pass

            embed.add_field(name="Member",value="\n".join(target_list))
            embed.add_field(name="Level",value="\n".join(level_list))
            embed.add_field(name="XP",value="\n".join(xp_list))
        else:
            embed.description = "It's empty here... Just a vast nothingness"

        await ctx.send(embed=embed,ephemeral=True)
        pass

    @tasks.loop(minutes=1,loop=loop)
    async def sql_saver_task(self):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            for guild_id, stats in self.LEVELS.items():
                sqlobj : GuildLevels = (await session.execute(sql.select(GuildLevels).where(GuildLevels.guild_id == str(guild_id)))).scalar_one_or_none()
                if sqlobj is None:
                    sqlobj = GuildLevels(guild_id=str(guild_id))
                    sqlobj.levels = stats.to_raw()
                    session.add(sqlobj)
                    pass
                else:
                    sqlobj.levels = stats.to_raw()
                    pass
                await session.commit()
                pass
        finally:
            await session.close()
        pass
    pass


def setup(bot : commands.Bot):
    global CONFIG, WEBHOOK_POOL
    global BOT, COG
    global SESSION_FACTORY, ENGINE

    CONFIG = bot.CONFIG
    WEBHOOK_POOL = bot.WEBHOOK_POOL
    BOT = bot
    COG = Leveling()
    SESSION_FACTORY = bot.SESSION_FACTORY
    ENGINE = bot.ENGINE

    BOT.DATA.LEVELS = Leveling.LEVELS
    BOT.DATA.LEVEL_SETTINGS = Leveling.LEVEL_SETTINGS

    bot.add_cog(COG)
    logging.info("Loaded Leveling extension!")
    pass

def teardown(bot : commands.Bot):
    pass