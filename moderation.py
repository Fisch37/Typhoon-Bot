import emoji
from loop import loop

from libs import utils, config
import logging, random, asyncio, dataclasses
from datetime import datetime
from typing import Union, Optional, Literal
from difflib import SequenceMatcher
from libs.logging_utils import LoggingSettings

import discord
from discord.ext import commands, tasks
from discord import app_commands

from ormclasses import *

# Declare constants
CONFIG: config.Config = ...

BOT: commands.Bot = ...
WEBHOOK_POOL: utils.WebhookPool = ...
COG: commands.Cog = ...

ENGINE: asql.AsyncEngine
SESSION_FACTORY: Sessionmaker = ...

async def get_warnings(session: asql.AsyncSession, guild_id: int):
    result: CursorResult = await session.execute(sql.select(GuildWarning).where(GuildWarning.guild_id == str(guild_id)))
    warnings = result.scalar_one_or_none()
    if warnings is None:
        warnings = GuildWarning(guild_id=str(guild_id))
        session.add(warnings)
        pass

    return warnings
    pass

uppercase_fraction = lambda text: sum([int(char.isupper()) for char in text])/len(text)
def emoji_fraction(message: discord.Message) -> float:
    emoji_count = emoji.emoji_count(message.clean_content)

    investigation_text = message.clean_content
    for emoji_obj in message.guild.emojis:
        emoji_str = str(emoji_obj)
        while True:
            before, this, after = investigation_text.partition(emoji_str)
            if this == "": break
            investigation_text = before + after
            emoji_count += 1
            pass
        pass

    visual_length = emoji_count + len(investigation_text)
    return emoji_count/visual_length
    pass

Channel = Union[discord.TextChannel,discord.VoiceChannel,discord.StageChannel]

@dataclasses.dataclass()
class AutomodState:
    #__slots__ = ("capsspam","spamspam","emotespam") # Use slots to safe memory space (Although that doesn't interact with dataclasses -.-)
    capsspam: bool = None
    spamspam: bool = None
    emotespam: bool = None


    def setdefault(self,  key: str, val: bool) -> None:
        if getattr(self,key) is None:
            setattr(self,key,val)
            pass
        pass

    async def save(self, guild_id: int):
        value = 0
        if self.capsspam:  value += 0b001
        if self.spamspam:  value += 0b010
        if self.emotespam: value += 0b100 

        session = SESSION_FACTORY()
        try:
            sql_guild = await utils.get_guild(session,guild_id)
            sql_guild.automod_state = value
            await session.commit()
            pass
        finally:
            await session.close()
            pass
        pass
    pass

class ModConfig:
    __slots__= (
        "spam_max_message_similarity","spam_max_message_repetition",
        "caps_max_ratio","caps_min_length",
        "emoji_max_ratio","emoji_min_length",
        "spam_consequence", "caps_consequence", "emoji_consequence"
    )
    DEFAULTS = {
        "spam_max_message_similarity":0.9,
        "spam_max_message_repetition":4,
        "caps_max_ratio":0.8,
        "caps_min_length":4,
        "emoji_max_ratio":0.9,
        "emoji_min_length":10
    }
    
    def __init__(
        self, 
        spam_max_message_similarity: float = 0.9, spam_max_message_repetition: float = 4,
        caps_max_ratio: float = 0.8, caps_min_length: int = 4,
        emoji_max_ratio: float = 0.9, emoji_min_length: int = 10,
        spam_consequence: Optional[list[bool]] = None, caps_consequence: Optional[list[bool]] = None, emoji_consequence: Optional[list[bool]] = None):
        
        self.spam_max_message_similarity = spam_max_message_similarity
        self.spam_max_message_repetition = spam_max_message_repetition

        self.caps_max_ratio = caps_max_ratio
        self.caps_min_length = caps_min_length

        self.emoji_max_ratio = emoji_max_ratio
        self.emoji_min_length = emoji_min_length

        if spam_consequence is None: self.spam_consequence = [False,False]
        else: self.spam_consequence = spam_consequence

        if caps_consequence is None: self.caps_consequence = [False,False]
        else: self.caps_consequence = caps_consequence
        
        if emoji_consequence is None: self.emoji_consequence = [False,False]
        else: self.emoji_consequence = emoji_consequence
        pass

    def to_dict(self) -> dict:
        return {slot:getattr(self,slot) for slot in self.__slots__}
        pass

    def __repr__(self):
        return f"<ModConfig {self.spam_max_message_similarity=}; {self.spam_max_message_repetition=}; {self.caps_max_ratio=}; {self.caps_min_length=}; {self.emoji_max_ratio=}; {self.emoji_min_length=}>"
        pass

    @classmethod
    async def load(cls, guild_id: int):
        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            result: CursorResult = await session.execute(sql.select(Guild.automod_settings).where(Guild.id == str(guild_id)))
            
            modconfig: dict = result.scalar_one_or_none()
            if modconfig is not None:   obj = cls(**modconfig)
            else:                       obj = cls()
        finally:
            await session.close()

        return obj
        pass
    pass

@dataclasses.dataclass(frozen=True,order=True)
class Warn:
    guild: discord.Guild = dataclasses.field(compare=False)
    target: discord.Member = dataclasses.field(compare=False)
    author: discord.Member = dataclasses.field(compare=False)
    time: datetime = dataclasses.field(compare=True)
    reason: str = dataclasses.field(compare=False)

    def to_raw(self) -> tuple[int,int,float,str]:
        return self.target.id, self.author.id, self.time.timestamp(), self.reason
        pass

    async def save(self):
        guild = self.target.guild

        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            result: CursorResult = await session.execute(sql.select(GuildWarning).where(GuildWarning.guild_id == str(guild.id)))
            sqlobj = result.scalar_one_or_none()
            if sqlobj is None:
                sqlobj = GuildWarning(guild_id = str(guild.id), warns=[])
                session.add(sqlobj)
                pass

            sqlobj.warns.append(self.to_raw())
            await session.commit()
            pass
        finally:
            await session.close()
            pass
        pass

    @staticmethod
    def from_database(guild: discord.Guild, member_id: int, author_id: int, timestamp: float, reason: str) -> "Warn":
        member = guild.get_member(member_id)
        author = guild.get_member(author_id)
        time = datetime.fromtimestamp(timestamp)
        return Warn(guild,member,author,time,reason)
        pass

    @staticmethod
    async def database_load_all(guild: discord.Guild) -> tuple["Warn"]:
        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            result: CursorResult = await session.execute(sql.select(GuildWarning.warns).where(GuildWarning.guild_id == str(guild.id)))
            raw_warnings = result.scalar_one_or_none() or []

            converted = []
            for raw in raw_warnings:
                member_id = int(raw[0])
                author_id = int(raw[1])
                timestamp = float(raw[2])
                reason = raw[3]

                converted.append(Warn.from_database(guild,member_id,author_id,timestamp,reason))
                pass
            pass
        finally:
            await session.close()
            pass

        return tuple(converted)
        pass

    @staticmethod
    async def database_save_all(guild: discord.Guild, warnings: list["Warn"]):
        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            result: CursorResult = await session.execute(sql.select(GuildWarning).where(GuildWarning.guild_id == str(guild.id)))
            sqlobj: GuildWarning = result.scalar_one_or_none()
            if sqlobj is None:
                sqlobj = GuildWarning(guild_id = str(guild.id))
                session.add(sqlobj)
                pass

            sqlobj.warns = [warn.to_raw() for warn in warnings]
            await session.commit()
            pass
        finally:
            await session.close()
            pass
        pass
    pass


GuildId = ChannelId = RoleId = MemberId = int
Capsspam = Spamspam = Emotespam = bool
JSONMemberId = str

MuteInf = list[int,str]
MuteDict = dict[JSONMemberId,MuteInf]

# Cog

class Moderation(commands.Cog):
    """A tool for... well moderation"""
    """TODO: Automod, Logging"""

    ANARCHIES: dict[GuildId,set[str]]
    GOD_ROLES: dict[GuildId,set[str]]
    AUTOMODS: dict[GuildId,AutomodState]
    LOGGING_CHANNEL: dict[GuildId,Optional[int]]
    AUTOMOD_SETTINGS: dict[GuildId,ModConfig]
    LOGGING_SETTINGS: dict[GuildId, LoggingSettings]

    LAST_MESSAGES: dict[GuildId,dict[ChannelId,dict[MemberId,list[Optional[str],int]]]] = {}

    def __init__(self):
        # Calling the class is necessary here because otherwise Python will do ~weird~ stuf
        self.__class__.ANARCHIES          = BOT.DATA.ANARCHIES
        self.__class__.GOD_ROLES          = BOT.DATA.GOD_ROLES
        self.__class__.AUTOMODS           = BOT.DATA.AUTOMODS
        self.__class__.LOGGING_CHANNEL    = BOT.DATA.LOGGING_CHANNEL
        self.__class__.AUTOMOD_SETTINGS   = BOT.DATA.AUTOMOD_SETTINGS
        self.__class__.LOGGING_SETTINGS   = BOT.DATA.LOGGING_SETTINGS
        super().__init__()
        pass

    async def cog_unload(self):
        self.warn_archive_task.stop()
        pass

    async def cog_load(self):
        self.warn_archive_task.start()
        asyncio.create_task(logger_task())
        self.logging_creator.start()
        pass

    # Automod
    def check_for_god_role(self, member: discord.Member):
        return len(self.GOD_ROLES[member.guild.id].intersection({str(role.id) for role in member.roles})) > 0
        pass

    async def spam_actions(self, message: discord.Message, settings: ModConfig):
        response = "Is there an echo in here? (Spam Automod)"
        if settings.spam_consequence[0]:
            await message.delete()
            pass
        if settings.caps_consequence[1]:
            await self.create_new_warning(message.guild,message.author,message.guild.me,"Automod Message Spam")

            response = "".join((response,"\nMy moderators will hear about this!"))
        
        await message.channel.send(response,delete_after=5)

        add_logging_event(Event(Event.AUTOMOD_SPAM,message.guild,{"message":message,"member":message.author}))
        pass

    async def caps_actions(self, message: discord.Message, settings: ModConfig):
        response = "Could you please quiet down a little? This is not a rock concert! (Caps Automod)"
        if settings.caps_consequence[0]:
            await message.delete()
            pass
        if settings.caps_consequence[1]:
            await self.create_new_warning(message.guild,message.author,message.guild.me,"Automod Caps Spam")

            response = "".join((response,"\nMy moderators will hear about this!"))

        await message.channel.send(response,delete_after=5)

        add_logging_event(Event(Event.AUTOMOD_CAPS,message.guild,{"message":message,"member":message.author}))
        pass

    async def emoji_actions(self, message: discord.Message, settings: ModConfig):
        response = "Wow there! Don't get overly emotional! (Emoji Spam Automod)"
        if settings.emoji_consequence[0]:
            await message.delete()
            pass
        if settings.emoji_consequence[1]:
            await self.create_new_warning(message.guild,message.author,message.guild.me,"Automod Emoji Spam")

            response = "".join((response,"\nMy moderators will hear about this!"))
            pass

        await message.channel.send(response,delete_after=5)

        add_logging_event(Event(Event.AUTOMOD_EMOTE,message.guild,{"message":message,"member":message.author}))
        pass

    @commands.Cog.listener("on_message")
    async def spam_listener(self, message: discord.Message):
        if message.author.bot: return # Ignore messages from bots
        if  not self.AUTOMODS[message.guild.id].spamspam or self.check_for_god_role(message.author): return # Don't check for gods
        if message.guild.id not in self.AUTOMOD_SETTINGS.keys(): # Load in default settings if neccessary
            self.AUTOMOD_SETTINGS[message.guild.id] = ModConfig()
            pass
        
        self.LAST_MESSAGES.setdefault(message.guild.id,{})
        self.LAST_MESSAGES[message.guild.id].setdefault(message.channel.id,{})
        self.LAST_MESSAGES[message.guild.id][message.channel.id].setdefault(message.author.id,[None,1])

        spam_data = self.LAST_MESSAGES[message.guild.id][message.channel.id][message.author.id] # Using list instead of unpacking for easier manipulation of data
        settings = self.AUTOMOD_SETTINGS[message.guild.id]

        if spam_data[0] is not None: # Don't need to check for similarity if there is no previous message
            comparison = SequenceMatcher(None,message.content.lower(),spam_data[0])
            similarity: float = await asyncio.get_event_loop().run_in_executor(None,lambda: comparison.ratio())
            if similarity > settings.spam_max_message_similarity:
                spam_data[1] += 1
                pass
            if spam_data[1] > settings.spam_max_message_repetition:
                await self.spam_actions(message,settings)
                pass
            pass
        spam_data[0] = message.content.lower() # Comparison should be case-insensitive
        pass

    @commands.Cog.listener("on_message")
    async def caps_listener(self, message: discord.Message):
        if message.author.bot: return # Ignore messages from bots
        if  not self.AUTOMODS[message.guild.id].capsspam or self.check_for_god_role(message.author): return # Don't check for gods
        if message.guild.id not in self.AUTOMOD_SETTINGS.keys(): # Load in default settings if neccessary
            self.AUTOMOD_SETTINGS[message.guild.id] = ModConfig()
            pass

        settings = self.AUTOMOD_SETTINGS[message.guild.id]

        if len(message.clean_content) >= settings.caps_min_length:
            caps_fraction: float = await asyncio.get_event_loop().run_in_executor(None,uppercase_fraction,message.clean_content)
            if caps_fraction > settings.caps_max_ratio:
                await self.caps_actions(message,settings)
                pass
            pass
        pass

    @commands.Cog.listener("on_message")
    async def emote_listener(self, message: discord.Message):
        if message.author.bot: return # Ignore messages from bots
        
        automod_state = self.AUTOMODS[message.guild.id]
        if not automod_state.emotespam or self.check_for_god_role(message.author): return # Still don't check for gods (the whole point is that they're unaffected)

        self.AUTOMOD_SETTINGS.setdefault(message.guild.id,ModConfig())
        settings = self.AUTOMOD_SETTINGS[message.guild.id]

        if len(message.clean_content) >= settings.caps_min_length: # Assure message meets minimum length of content
            emote_fraction: float = await asyncio.get_event_loop().run_in_executor(None,emoji_fraction,message)
            if emote_fraction > settings.emoji_max_ratio:
                await self.emoji_actions(message,settings)
                pass
            pass
        pass

    # Warnings

    @app_commands.command(name="warn")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(target="The member you want to warn", reason="A reason for warning said member")
    # @utils.perm_message_check("Oh? Warnings? I'll give you warnings! (No Permission -- Need Manage Roles)", manage_roles=True)
    async def warn_user(self, interaction: discord.Interaction, target: discord.Member, reason: str = None):
        if len(reason) > 200:
            await interaction.response.send_message(f"Please keep your reasons short and compact. Was {len(reason)} characters, should be 200 or below",ephemeral=True)
            return

        await self.create_new_warning(interaction.guild,target,interaction.user,reason)

        await interaction.response.send_message(f"Warned {target.mention} with reason\n```\n{reason}```",ephemeral=True)
        pass

    async def create_new_warning(self, guild: discord.Guild, target: discord.Member, author: discord.Member, reason: str):
        warnobj = Warn(guild,target,author,datetime.utcnow(),reason)
        asyncio.create_task(self.on_new_warn(warnobj))
        await warnobj.save()

        add_logging_event(Event(Event.MOD_WARN,guild,{"member":target,"actor":author,"reason":reason}))
        pass

    async def on_new_warn(self, warning: Warn):
        guild = warning.guild
        
        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            warnings = await get_warnings(session,guild.id)
            warnings.warning_counts.setdefault(str(guild.id),0)
            warnings.warning_counts[str(guild.id)] += 1

            await session.commit()
            pass
        finally:
            await session.close()
            pass
        pass

    async def single_archiver(self, guild: discord.Guild, current_timestamp: float):
        warnings = await Warn.database_load_all(guild)

        is_outdated = lambda warn: (warn.time.timestamp() - current_timestamp) > CONFIG.WARNING_ARCHIVE_TIME*60
        new_warnings = [warn for warn in warnings if not is_outdated(warn)]

        await Warn.database_save_all(guild,new_warnings)
        pass

    @tasks.loop(minutes=5)
    async def warn_archive_task(self):
        timestamp = datetime.utcnow().timestamp()

        await asyncio.gather(*[self.single_archiver(guild,timestamp) for guild in BOT.guilds])
        pass

    # Channel Mod
    lock = app_commands.Group(
        name="lock",
        description="In a locked channel, people can't write by default",
        guild_only=True,
        default_permissions=discord.Permissions(manage_channels=True)
    )

    @lock.command(name="set",description="Lock this channel")
    async def set_lock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            overwrite=discord.PermissionOverwrite(send_messages=False)
        )
        await interaction.response.send_message("\U0001F50F **This channel has been locked** \U0001F50F")
        pass

    @lock.command(name="remove",description="Unlock this channel")
    async def rem_lock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(
            interaction.guild.default_role,
            overwrite=discord.PermissionOverwrite(send_messages=True)
        )
        await interaction.response.send_message("\U0001F513 **This channel has been unlocked** \U0001F513")
        pass

    ## Anarchy
    anarchy = app_commands.Group(name="anarchy",description="Anarchy is... well, it's a thing.",
    guild_only=True, default_permissions=discord.Permissions(manage_channels=True))

    @anarchy.command(name="enable",description="Excludes this channel from the automod")
    async def set_anarchy(self, interaction: discord.Interaction):
        try:
            sqlguild, session = await utils.get_guild(interaction.guild_id) # Get the SQL Reference to the guild
            if not str(interaction.channel_id) in sqlguild.anarchies:
                sqlguild.anarchies.append(str(interaction.channel_id)) # Add the channel to the anarchy channels
                await interaction.response.send_message("Woo! Anarchy... I guess..." + (" You know, as a moderation bot this is a rather weird thing to say..." if random.randint(1,25) == 25 else ""),ephemeral=True)
                pass
            else:
                await interaction.response.send_message("Hahaha! This is anarchy! I don't have to listen to you anymore! (Anarchy is already enabled)",ephemeral=True)
                pass
            
            await session.commit()
        finally:
            await session.close()
        asyncio.create_task(self.anarchy_sql_update(interaction))
        pass

    @anarchy.command(name="disable",description="(Re)includes this channel in the automod")
    async def rem_anarchy(self, interaction: discord.Interaction):
        try:
            sqlguild, session = await utils.get_guild(interaction.guild_id) # Get SQL Reference to the guild
            if str(interaction.channel_id) in sqlguild.anarchies:
                sqlguild.anarchies.remove(str(interaction.channel_id))
                await interaction.response.send_message("Alright, anarchy is disabled now. No, put that axe away; I said it is **disabled** now.",ephemeral=True)
                pass
            else:
                await interaction.response.send_message("But... there isn't any anarchy here, what should I do now?",ephemeral=True)
                pass

            await session.commit()
        finally:
            await session.close() # Commit & Close
        asyncio.create_task(self.anarchy_sql_update(interaction))
        pass

    @anarchy.command(name="list",description="List all anarchy channels on this server")
    async def list_anarchy(self, interaction: discord.Interaction):
        try:
            sqlguild, session = await utils.get_guild(interaction.guild_id) # Get SQL Reference to the guild
            
            embed = discord.Embed(title="Anarchy channels",colour=discord.Colour.blue(),description="")
            for channel_str in sqlguild.anarchies: # List every anarchy channel in the embed description
                channel = interaction.guild.get_channel(int(channel_str))
                embed.description = "".join((embed.description,channel.mention,"\n"))
                pass
        finally:
            await session.close()

        await interaction.response.send_message(embed=embed,ephemeral=True)
        pass

    async def anarchy_sql_update(self,interaction: discord.Interaction):
        try:
            sqlguild, session = await utils.get_guild(interaction.guild_id)
            # Remove all outdated channels (channels that were deleted)
            all_channel_ids: list[ChannelId] = [channel.id for channel in interaction.guild.text_channels]

            prev_anarchies = sqlguild.anarchies.copy()
            sqlguild.anarchies.clear()
            sqlguild.anarchies.extend(filter(lambda channel_str: int(channel_str) in all_channel_ids , prev_anarchies))
            # Update the RAM dict with the anarchy channels
            self.ANARCHIES.setdefault(interaction.guild_id,set())
            self.ANARCHIES[interaction.guild_id].clear()
            self.ANARCHIES[interaction.guild_id].update([int(channel_str) for channel_str in sqlguild.anarchies])

            await session.commit()
        finally:
            await session.close() # Commit & Close
        pass

    # Message Mod
    @app_commands.command(name="move",description="Move a specified amount of messages to a specified channel")
    @app_commands.guild_only()
    @app_commands.describe(messages="The amount of messages to move. This is capped at 100")
    @utils.perm_message_check("You don't seem to have the right tools to lift these messages... (No Permission)",manage_messages=True)
    async def move_messages(self, interaction: discord.Interaction, channel: discord.TextChannel, messages: int):
        if channel.id == interaction.channel_id:
            await interaction.response.send_message("Now that would be pretty silly... (Channel is same as current)",ephemeral=True)
            return
            pass
        messages = min(messages,CONFIG.MSG_MOVE_LIM)

        await interaction.response.defer()

        all_messages = [message async for message in interaction.channel.history(limit=messages+2,oldest_first=False)]
        all_messages.pop(0)
        prev_message_url = all_messages.pop(-1).jump_url
        # This might seem a little weird, but it does make sense:
        # all_messages[0] is the response from the bot. We don't want to move that
        # all_messages[1] is the latest message we don't want to move. We'll mention that in our move result
        # all_messages.pop(0) removes all_messages[0] which is obviously completely unnecessary
        all_messages.reverse()
        # This reverse makes all the order statements inferred from the above completely useless. Now the oldest message is first.
        
        
        message_contents = [f"_Originating from {prev_message_url}_\n"]

        for message in all_messages:
            message: discord.Message

            author_str = message.author.name + "#" + message.author.discriminator
            datetime_str = f"<t:{int((message.edited_at or message.created_at).timestamp())}>"
            
            completed_content = f"**{author_str}** on {datetime_str}\n> {message.content}\n\n"

            message_contents[-1] = "".join((message_contents[-1],completed_content))
            if len(message_contents[-1]) > CONFIG.DISCORD_MAX_MSG_LEN:
                # Split up the message
                new_message_start = message_contents[-1][CONFIG.DISCORD_MAX_MSG_LEN:] # Get everything beyond (and including) 2000 characters
                if len(new_message_start) > 0: new_message_start = "> " + new_message_start # Put a quote marker at the beginning
                message_contents.append(new_message_start)

                message_contents[-2] = message_contents[-2][:CONFIG.DISCORD_MAX_MSG_LEN] # Cut everything from the previous message that is longer than 2000 characters
                pass
            pass

        if not channel.permissions_for(interaction.guild.me).is_superset(discord.Permissions(send_messages=True)):
            await interaction.response.send_message("I am unable to send messages in the channel you specified. Please use a different channel or change the permissions of the selected channel to fix this issue.",ephemeral=True)
            return
            pass

        async def send_msgs():
            for content in message_contents:
                await channel.send(content)
                pass
            pass

        await asyncio.gather(
            send_msgs(),
            interaction.channel.purge(
                limit=messages+1,
                check=lambda msg: msg in all_messages
            )
        )
        # Purging messages+1 since we need to cover our original response as well
        await interaction.followup.send(f"This conversation has been moved to {channel.mention}")
        pass

    @app_commands.command(name="purge",description="Remove a specified amount of messages in this channel")
    @app_commands.guild_only()
    @utils.perm_message_check("Now, these are some pretty destructive weapons. Wouldn't want them to fall into the wrong hands, eh? (No Permission)",manage_messages=True)
    async def purge_messages(self, interaction: discord.Interaction, messages: int):
        messages = min(messages,CONFIG.MSG_PURGE_LIM)
        await interaction.response.defer(ephemeral=True)
        await interaction.channel.purge(limit=messages)
        await interaction.followup.send(f"Deleted {messages} message(s)! :white_check_mark:",ephemeral=True)
        pass
    
    # Removed these since they are already included in /config
    ## Role exceptions
    # @utils.perm_message_check("2 things: \n\t1. You're not a god\n\t2. You won't be able to make yourself one with this\n\t2.1 No Permission",manage_guild=True)
    # god_roles = app_commands.Group(name="god_roles",description="Users with a god role will not be affected by any automod checks",
    # guild_only=True, default_permissions=discord.Permissions(manage_guild=True))

    # @god_roles.command(name="add",description="Add a new role to the list of roles exempted from the automod")
    # async def god_roles_add(self, interaction: discord.Interaction, role: discord.Role):
    #     if str(role.id) in self.GOD_ROLES[interaction.guild_id]:
    #         await interaction.response.send_message(f"Just as a check, I sent a prayer to `{role.name}` and I actually got an answer... So, yeah, that role already is a god role",ephemeral=True)
    #         return
    #         pass

    #     self.GOD_ROLES[interaction.guild_id].add(str(role.id))

    #     session: asql.AsyncSession = SESSION_FACTORY()
    #     try:
    #         result: CursorResult = await session.execute(sql.select(Guild).where(Guild.id==str(interaction.guild_id)))
    #         sql_guild: Guild = result.scalar_one()
    #         sql_guild.god_roles.append(str(role.id))
    #         await session.commit()
    #     finally:
    #         await session.close()

    #     await interaction.response.send_message(f"All hail {role.mention} or something... Anyway, that role is now a god role!",ephemeral=True)
    #     pass

    # @god_roles.command(name="remove",description="Remove a role from the list of roles exempted from the automod")
    # async def god_roles_rem(self, interaction: discord.Interaction, role: discord.Role):
    #     if str(role.id) not in self.GOD_ROLES[interaction.guild_id]:
    #         await interaction.response.send_message(f"Who is this `{role.name}` you are talking about? Not a god at least...",ephemeral=True)
    #         return
    #         pass

    #     self.GOD_ROLES[interaction.guild_id].remove(str(role.id))

    #     session: asql.AsyncSession = SESSION_FACTORY()
    #     try:
    #         result: CursorResult = await session.execute(sql.select(Guild).where(Guild.id==str(interaction.guild_id)))
    #         sql_guild: Guild = result.scalar_one()
    #         sql_guild.god_roles.remove(str(role.id))
    #         await session.commit()
    #     finally:
    #         await session.close()

    #     await interaction.response.send_message("So what is this called? Let me just check... A, yes! Deicide, that's it!",ephemeral=True)
    #     pass

    # @god_roles.command(name="list",description="List all roles exempted from the automod")
    # async def god_roles_list(self, interaction: discord.Interaction):
    #     logging.warn(NotImplementedError("Implement modals for GodRoleView interactions"))
    #     view = GodRoleView(interaction,self,timeout=CONFIG.EDIT_TIMEOUT)
    #     await interaction.response.defer(ephemeral=True,thinking=False)
    #     message = await interaction.followup.send("```\nSelect one of the options or disable the interaction```",view=view,ephemeral=True)
    #     view.message = message
    #     await view.update_embed()
    #     pass

    # Logging
    # @utils.perm_message_check("Now, there is something called privacy, you know? I know, it's a bit ironical considering this command's function, but that doesn't mean you get to do this! (No Permission)",manage_guild=True)
    # logging = app_commands.Group(name="logging",description="Moderate the logging feature",
    # guild_only=True, default_permissions=discord.Permissions(manage_guild=True))

    # @logging.command(name="channel",description="Set the channel the logger will write to.")
    # @app_commands.describe(channel="The channel to log events in. Leave empty to reset")
    # async def set_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
    #     if channel is not None and not isinstance(channel,discord.TextChannel):
    #         await interaction.response.send_message("The channel you passed does not seem to be a text channel. Please check your input",ephemeral=True)
    #         return
    #         pass

    #     session: asql.AsyncSession = SESSION_FACTORY()
    #     try:
    #         await session.execute(sql.update(Guild).where(Guild.id==str(interaction.guild_id)).values(logging_channel=(str(channel.id) if channel is not None else None)))
    #         await session.commit()
    #     finally:
    #         await session.close()

    #     self.LOGGING_CHANNEL[interaction.guild_id] = (channel.id if channel is not None else None)

    #     if channel is None:
    #         await interaction.response.send_message("Logging is now disabled! Freedom! Yay!",ephemeral=True)
    #         pass
    #     else:
    #         await interaction.response.send_message("Logging is now enabled! Finally we can know what everyone on the server is doing! This... sounded better in my head",ephemeral=True)
    #         pass
    #     pass

    # @logging.command(name="events",description="Specify the events in which a log entry will be made")
    # @app_commands.describe(
    #     moderation="Set to true to enable logging of Automod or member kicks/bans",
    #     channels="Set to true to log changes to channels (creation, deletion, etc.)",
    #     server_update="Set to true to log changes regarding the server",
    #     invites="Set to true to log edited invites",
    #     member_changes="Set to true to log changes to the members (like joining, leaving or nickname changes)",
    #     messages="Set to true to log message changes (deletion/edits)",
    #     reactions_mod="Set to true to log moderation for reactions (reaction clears)",
    #     roles="Set to true to log changes to the roles of this server",
    #     threads_mod="Set to true to log changes to threads"
    # )
    # async def specify_log_events(self, interaction: discord.Interaction,
    #     moderation: bool = None,

    #     channels: bool = None,
        
    #     server_update: bool = None,

    #     invites: bool = None,

    #     member_changes: bool = None,

    #     messages: bool = None,
        
    #     reactions_mod: bool = None,
        
    #     roles: bool = None,
        
    #     threads_mod: bool = None,
    #     ):
    #     await interaction.response.defer(ephemeral=True,thinking=False)

    #     args = (moderation, channels, server_update, invites, member_changes, messages, reactions_mod, roles, threads_mod)
    #     self.LOGGING_SETTINGS[interaction.guild_id].update(*args)

    #     session: asql.AsyncSession = SESSION_FACTORY()
    #     try:
    #         result: CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(interaction.guild_id)))
    #         sqlobj: Guild = result.scalar_one_or_none()
    #         if sqlobj is not None: sqlobj.logging_settings = self.LOGGING_SETTINGS[interaction.guild_id].to_value()

    #         await session.commit()
    #     finally:
    #         await session.close()

    #     view = LoggingSettingsView(interaction,self,timeout=CONFIG.EDIT_TIMEOUT)
    #     message = await interaction.followup.send("```\nFirst select whether you wish to enable or disable an event\nand then use the select menu to specify the event```",view=view,ephemeral=True)
    #     view.message = message
    #     await view.update_message()
    #     pass

    # SQL Moderation collector
    async def insert_one_moderation_entry(self,sqlguild: Optional[Guild],*,guild_id: int = None):
        guild_id = int(sqlguild.id) if sqlguild is not None else guild_id
        
        # Anarchy channels
        self.ANARCHIES.setdefault(guild_id,set())
        if sqlguild is not None: self.ANARCHIES[guild_id].update(sqlguild.anarchies)
        
        # Role exceptions
        self.GOD_ROLES.setdefault(guild_id,set())
        if sqlguild is not None: self.GOD_ROLES[guild_id].update(sqlguild.god_roles)
        
        # Automod States
        self.AUTOMODS.setdefault(guild_id,AutomodState())
        
        if sqlguild is not None: 
            self.AUTOMODS[guild_id].setdefault("capsspam",  bool(sqlguild.automod_state & 0b001) )
            self.AUTOMODS[guild_id].setdefault("spamspam",  bool(sqlguild.automod_state & 0b010) )
            self.AUTOMODS[guild_id].setdefault("emotespam", bool(sqlguild.automod_state & 0b100) )
            pass

        # Automod settings
        self.AUTOMOD_SETTINGS[guild_id] = await ModConfig.load(guild_id)

        # Logging
        if sqlguild is not None:self.LOGGING_CHANNEL[guild_id] = int(sqlguild.logging_channel) if sqlguild.logging_channel is not None else None
        else:                   self.LOGGING_CHANNEL[guild_id] = None

        # Logging events
        if sqlguild is not None:self.LOGGING_SETTINGS[guild_id] = LoggingSettings.from_value(sqlguild.logging_settings)
        else:                   self.LOGGING_SETTINGS.setdefault(guild_id,LoggingSettings())
        pass

    @commands.Cog.listener("on_ready")
    async def moderation_collector(self):
        """Loads SQL Table into RAM to improve performance"""
        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            result: CursorResult = await session.execute(sql.select(Guild))
            sqlobjs: list[Guild] = result.scalars().all()
            
            for sqlguild in sqlobjs:
                await self.insert_one_moderation_entry(sqlguild)
                pass
        finally:
            await session.close()
        pass

    @commands.Cog.listener("on_guild_join")
    async def moderation_inserter_event(self, guild: discord.Guild):
        session: asql.AsyncSession = SESSION_FACTORY()
        try:
            result: CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(guild.id)))

            sqlguild: Optional[Guild] = result.scalar_one_or_none()

            await self.insert_one_moderation_entry(sqlguild,guild_id=guild.id)
        finally:
            await session.close()
        pass

    # Logging Event handlers ----------------------------------------
    # What? This isn't long! It's remarkably short! (Kind of...)
    @tasks.loop(count=1)
    async def logging_creator(self):
        def check_event_logging_enabled(guild: discord.Guild, event_type: int) -> bool:
            if self.LOGGING_CHANNEL.get(guild.id) is None: return False
            return bool(self.LOGGING_SETTINGS[guild.id].to_value() & event_type)
            pass

        guild_from_invite = lambda invite: invite.guild
        guild_from_sticker_emoji = lambda guild, before, after: guild
        guild_from_member = lambda member: member.guild
        guild_from_role = lambda role: role.guild
        guild_from_react_payload = lambda payload: BOT.get_guild(payload.guild_id)

        event_dict = {
                "on_guild_channel_create": (Event.GUILD_CHANNEL_CREATE,("channel",),lambda channel: channel.guild),
                "on_guild_channel_delete": (Event.GUILD_CHANNEL_DELETE,("channel",), lambda channel: channel.guild),
                "on_guild_channel_update": (Event.GUILD_CHANNEL_UPDATE,("before","after"), lambda before, after: after.guild),

                "on_guild_update": (Event.GUILD_SETTINGS_UPDATE,("before","after"), lambda before, after: after),
                "on_guild_emojis_update": (Event.GUILD_EMOJI_UPDATE,("guild","before","after"), guild_from_sticker_emoji),
                "on_guild_stickers_update": (Event.GUILD_STICKER_UPDATE,("guild","before","after"), guild_from_sticker_emoji),

                "on_invite_create": (Event.INVITE_CREATE,("invite",), guild_from_invite),
                "on_invite_delete": (Event.INVITE_DELETE,("invite",), guild_from_invite),
                
                "on_member_join": (Event.MEMBER_JOIN,("member",), guild_from_member),
                "on_member_leave": (Event.MEMBER_LEAVE,("member",), guild_from_member),
                "on_member_update": (Event.MEMBER_UPDATE,("before","after"), lambda before, after: after.guild),
                
                "on_member_ban": (Event.MOD_BAN,("guild","user"), lambda guild, user: guild),
                "on_member_unban": (Event.MOD_UNBAN,("guild","user"), lambda guild, user: guild),
                
                "on_raw_message_edit": (Event.MESSAGE_EDIT,("payload",), lambda payload: BOT.get_guild(payload.guild_id)),
                "on_raw_message_delete": (Event.MESSAGE_DELETE,("payload",), lambda payload: BOT.get_guild(payload.guild_id)),
                "on_raw_bulk_message_delte": (Event.MESSAGE_BULK_DELETE,("payload",), lambda payload: BOT.get_guild(payload.guild_id)),
                
                "on_guild_role_create": (Event.ROLE_CREATE,("role",), guild_from_role),
                "on_guild_role_delete": (Event.ROLE_DELETE,("role",), guild_from_role),
                "on_guild_role_update": (Event.ROLE_UPDATE,("before","after"), lambda before, after: after.guild),
                
                "on_thread_update": (Event.THREADS_UPDATE,("before","after"), lambda before, after: after.guild),
                "on_thread_delete": (Event.THREADS_DELETE,("thread",), lambda thread: thread.guild),
                
                "on_raw_reaction_clear": (Event.REACTION_CLEAR_ALL,("payload",), guild_from_react_payload),
                "on_raw_reaction_clear_emoji": (Event.REACTION_CLEAR_SINGLE,("payload",), guild_from_react_payload)
        }
        def listener_factory(event_name):
            async def listener(*args):
                event_n, arg_names, guild_extractor = event_dict[event_name]
                kwargs = {argname:argval for argname, argval in zip(arg_names,args)}

                try: guild = guild_extractor(**kwargs)
                except ValueError: return
                if guild is not None and check_event_logging_enabled(guild,event_n):
                    add_logging_event(Event(event_n,guild,kwargs))
                    pass
                pass

            return listener
            pass

        for event_name in event_dict.keys():
            BOT.add_listener(listener_factory(event_name),event_name)
            pass
        logging.info("Logging events created")
        pass
    pass

# Setup & Teardown
async def setup(bot: commands.Bot):
    global CONFIG
    global BOT, WEBHOOK_POOL, COG
    global ENGINE, SESSION_FACTORY
    # Set constants
    CONFIG          = bot.CONFIG
    
    BOT             = bot
    WEBHOOK_POOL    = bot.WEBHOOK_POOL

    ENGINE          = bot.ENGINE
    SESSION_FACTORY = bot.SESSION_FACTORY

    BOT.DATA.ANARCHIES          = {}
    BOT.DATA.GOD_ROLES          = {}
    BOT.DATA.AUTOMODS           = {}
    BOT.DATA.LOGGING_CHANNEL    = {}
    BOT.DATA.AUTOMOD_SETTINGS   = {}
    BOT.DATA.LOGGING_SETTINGS   = {}

    COG = Moderation()
    await bot.add_cog(COG)

    logging.info("Added moderation extension")
    pass

async def teardown(bot: commands.Bot):
    bot.remove_cog("Moderation")
    pass


#----------------------------------------------------------------------------
class Severity:
    LOW = discord.Colour.green()
    MID = discord.Colour.yellow()
    HIGH = discord.Colour.red()

class Event:
    ACTIVE_COG = Moderation


    Mute    = dict[Literal["manual","member","reason","until","actor"],Union[bool,discord.Member,str,int]]
    Unmute  = dict[Literal["member","reason","actor"],Union[discord.Member,str]]
    Automod = dict[Literal["member","message"],Union[discord.Member,discord.Message]]
    Warn    = dict[Literal["member","reason","actor"],Union[discord.Member,str]]
    GuildChannel_Create = dict[Literal["channel"],Channel]
    GuildChannel_Delete = dict[Literal["channel"],Channel]
    GuildChannel_Update = dict[Literal["before"],Literal["after"]]
    GuildSettings = dict[Literal["before","after"],discord.Guild]
    EmojiUpdate = dict[Literal["guild","before","after"],Union[discord.Guild,list[discord.Emoji]]]
    EmojiUpdate = dict[Literal["guild","before","after"],Union[discord.Guild,list[discord.Sticker]]]
    Invite = dict[Literal["invite"],discord.Invite]
    Member_JL = dict[Literal["member"],discord.Member]
    Member_Update = dict[Literal["before","after"],discord.Member]
    Message_Edit = dict[Literal["payload"],discord.RawMessageUpdateEvent]
    Message_Delete = dict[Literal["payload"],discord.RawMessageDeleteEvent]
    Reaction_Clear = dict[Literal["message","reactions"],Union[discord.Message,list[Union[discord.Emoji,discord.PartialEmoji]]]]
    Role = dict[Literal["role"],discord.Role]
    Role_Update = dict[Literal["before","after"],discord.Role]
    Thread_Update = dict[Literal["before","after"],discord.Thread]
    Thread_Delete = dict[Literal["thread"],discord.Thread]

    # See now: _Big_ Numbers! (I think I spend 30 minutes just writing these numbers)
    # I'm taking a break now...
    ########################################___

    AUTOMOD_SPAM            = 0b0000000001000
    AUTOMOD_CAPS            = 0b0000000001001
    AUTOMOD_EMOTE           = 0b0000000001010
    MOD_UNBAN               = 0b0000000001011
    MOD_BAN                 = 0b0000000001100
    MOD_WARN                = 0b0000000001101
    MOD_MASK                = 0b0000000001000

    GUILD_CHANNEL_CREATE    = 0b0000000010000
    GUILD_CHANNEL_DELETE    = 0b0000000010001
    GUILD_CHANNEL_UPDATE    = 0b0000000010010
    GUILD_CHANNEL_MASK      = 0b0000000010000

    GUILD_SETTINGS_UPDATE   = 0b0000000100000
    GUILD_EMOJI_UPDATE      = 0b0000000100001
    GUILD_STICKER_UPDATE    = 0b0000000100010
    GUILD_MASK              = 0b0000000100000

    INVITE_CREATE           = 0b0000001000000
    INVITE_DELETE           = 0b0000001000001
    INVITE_MASK             = 0b0000001000000

    MEMBER_JOIN             = 0b0000010000000
    MEMBER_LEAVE            = 0b0000010000001
    MEMBER_UPDATE           = 0b0000010000010
    MEMBER_MASK             = 0b0000010000000

    MESSAGE_EDIT            = 0b0000100000000
    MESSAGE_DELETE          = 0b0000100000001
    MESSAGE_BULK_DELETE     = 0b0000100000010
    # MESSAGE_PIN_ADD         = 0b0000100000011 # This doesn't seem possible at the moment because of Discord Events
    # MESSAGE_PIN_REMOVE      = 0b0000100000100
    MESSAGE_MASK            = 0b0000100000000

    REACTION_CLEAR_ALL      = 0b0001000000000
    REACTION_CLEAR_SINGLE   = 0b0001000000001
    REACTION_MOD_MASK       = 0b0001000000000

    ROLE_CREATE             = 0b0010000000000
    ROLE_DELETE             = 0b0010000000001
    ROLE_UPDATE             = 0b0010000000010
    ROLE_MASK               = 0b0010000000000

    THREADS_UPDATE          = 0b0100000000000
    THREADS_DELETE          = 0b0100000000001
    THREADS_MASK            = 0b0100000000000

    MUTE_EVENT              = 0b1000000000000
    UNMUTE_EVENT            = 0b1000000000001
    MUTE_MASK               = 0b1000000000000

    __slots__ = ("type","data", "guild")
    def __init__(self, type: int, guild: discord.Guild, data):
        self.type = type
        self.data = data
        self.guild = guild
        pass
    pass

LOGGING_EVENTS: list[Event] = []
EMPTY_OVERRIDE = discord.PermissionOverwrite()

def state_to_str(state: Optional[bool]) -> str:
    if state is None: return ":heavy_minus_sign:"
    elif state is False: return ":x:"
    else: return ":white_check_mark:"
    pass

Permission_Overrides = dict[Union[discord.Role,discord.Member],discord.PermissionOverwrite]
def gen_permission_override_string(perm_overrides: Permission_Overrides) -> str:
    # This line seems unreasonably long... Debugging this will be fun! Hehe...
    return "\n\n".join("".join((target.mention,"\n\t".join((perm+": "+state_to_str(state) for perm, state in override))) for target, override in perm_overrides.items()))
    pass

def describe_perm_override(embed: discord.Embed, a: Permission_Overrides, b: Permission_Overrides) -> discord.Embed:
    """TODO: Optimize this code because it is wayyyy too slow"""
    for key in set(a.keys()).union(b.keys()):
        override_a = a.get(key,EMPTY_OVERRIDE)
        override_b = b.get(key)
        if override_b is None:
            embed.description = "".join((embed.description,"\nRemoved permission overwrite for ",key.mention))
            continue
        elif override_a is EMPTY_OVERRIDE:
            embed.description = "".join((embed.description,"\nAdded permission overwrite for ",key.mention))
            pass

        permissions = []
        perms_a = []
        perms_b = []
        for override_1, override_2 in ((override_a, override_b),(override_b,override_a)):
            perms_1 = []
            perms_2 = []

            for permission, perm_1 in override_1:
                perm_2 = getattr(override_2, permission)

                if perm_1 == perm_2 or permission in permissions: continue
                perms_1.append(state_to_str(perm_1))
                perms_2.append(state_to_str(perm_2))
                permissions.append(permission)
                pass

            if override_1 == override_a:
                perms_a.extend(perms_1)
                perms_b.extend(perms_2)
                pass
            else:
                perms_b.extend(perms_1)
                perms_a.extend(perms_2)
                pass
            pass

        if len(permissions) > 0:
            embed.add_field(name=f"Permissions (@{key.name})",value="\n".join(permissions))
            embed.add_field(name="Before",value="\n".join(perms_a))
            embed.add_field(name="After",value="\n".join(perms_b))
        pass

    return embed
    pass

def channel_extra_description(event_type: int,channel: Channel) -> str:
    if isinstance(channel  ,discord.TextChannel ): channel_type = "Text"
    elif isinstance(channel,discord.VoiceChannel): channel_type = "Voice"
    elif isinstance(channel,discord.StageChannel): channel_type = "Stage"
    elif isinstance(channel,discord.CategoryChannel): channel_type = "Category"

    lines = []
    lines.append(f"Type: {channel_type}")
    lines.append(f"Name: {channel.name}")
    lines.append(f"Category: {channel.category}")
    
    if event_type == Event.GUILD_CHANNEL_CREATE:
        if isinstance(channel,discord.TextChannel):
            lines.append(f"Slowmode: {channel.slowmode_delay}s")
            pass
        elif isinstance(channel,discord.VoiceChannel):
            lines.append(f"Bitrate: {channel.bitrate}kb/s")
            lines.append(f"User Limit: {channel.user_limit}")
            lines.append(f"Video Quality: {channel.video_quality_mode.name}")
            lines.append(f"Region Override: {channel.rtc_region}")
            pass
        elif isinstance(channel,discord.StageChannel):
            lines.append("".join(("Moderators:\n\t","\n\t".join(channel.moderators))))
            lines.append(f"Region Override: {channel.rtc_region}")
            pass

        lines.append(gen_permission_override_string(channel.overwrites))

    return "\n".join(lines)
    pass

def channel_diff_description(before: Channel, after: Channel) -> str:
    lines = []
    lines.append(f"Channel: {after.mention}")
    if before.name != after.name: lines.append(f"Name: {before.name} -> {after.name}")
    if before.category != after.category: lines.append(f"Category: {before.category} -> {after.category}")
    
    if isinstance(before,discord.TextChannel): # Text channel exclusive changes
        if before.slowmode_delay != after.slowmode_delay: lines.append(f"Slowmode: {utils.stringFromDuration(before.slowmode_delay)} -> {utils.stringFromDuration(after.slowmode_delay)}")
        if before.default_auto_archive_duration != after.default_auto_archive_duration: lines.append(f"Thread Auto Archive Duration: {utils.stringFromDuration(before.default_auto_archive_duration*60)} -> {utils.stringFromDuration(after.default_auto_archive_duration*60)}")
        if before.nsfw != after.nsfw: lines.append(f"NSFW: {'Enabled' if before.nsfw else 'Disabled'} -> {'Enabled' if after.nsfw else 'Disabled'}")
        pass
    elif isinstance(before,discord.VoiceChannel): # Voice channel exclusive changes
        if before.bitrate != after.bitrate: lines.append(f"Bitrate: {before.bitrate}kb/s -> {after.bitrate}kb/s")
        if before.user_limit != after.user_limit: lines.append(f"User Limit: {before.user_limit} -> {after.user_limit}")
        if before.video_quality_mode != after.video_quality_mode: lines.append(f"Video Quality: {before.video_quality_mode.name} -> {after.video_quality_mode.name}")
        if before.rtc_region != after.rtc_region: lines.append(f"Region Override: {before.rtc_region} -> {after.rtc_region}")
        pass
    elif isinstance(before,discord.StageChannel):
        if before.rtc_region != after.rtc_region: lines.append(f"Region Override: {before.rtc_region} -> {after.rtc_region}")
        before_mods = set(before.moderators)
        after_mods  = set(after.moderators)
        removed_moderators = before_mods.difference(after_mods)
        added_moderators = after_mods.difference(before_mods)

        lines.append("".join((
            "Moderators:\n\t",
            "\n\t:heavy_plus_sign: ".join([mod.mention for mod in added_moderators]),
            "\n\t:heavy_minus_sign: ".join([mod.mention for mod in removed_moderators])
        )))
        pass

    return "\n".join(lines)
    pass

def role_diff_embed(embed: discord.Embed, before: discord.Role, after: discord.Role) -> discord.Embed:
    add_standard_field = lambda name, attr: embed.add_field(name=f"{name}:",value=f"{getattr(before,attr)} -> {getattr(after,attr)}",inline=False)
    if before.name != after.name:
        add_standard_field("Name","name")
        pass
    if before.colour != after.colour:
        add_standard_field("Colour","colour")
        pass
    if before.icon != after.icon:
        icon_link = lambda title,icon: f"[{title}]({icon.url})" if icon is not None else "None"

        embed.add_field(name="Icon:",value=f"{icon_link('before',before.icon)} -> {icon_link('after',after.icon)}",inline=False)
        pass
    if before.emoji != after.emoji:
        add_standard_field("Emoji","emoji")
        pass

    if before.permissions != after.permissions:
        permissions = []
        change_strs = []

        for name, before_state in before.permissions:
            after_state = getattr(after.permissions,name)
            if before_state != after_state:
                permissions.append(name)
                change_strs.append(f"{state_to_str(before_state)} -> {state_to_str(after_state)}")
                pass
            pass

        embed.add_field(name="Permission",value="\n".join(permissions))
        embed.add_field(name="State",value="\n".join(change_strs))
        pass

    return embed
    pass

def add_logging_event(event: Event):
    LOGGING_EVENTS.append(event)
    pass

def insert_member_changes(embed: discord.Embed, before: discord.Member, after: discord.Member) -> discord.Embed:
    if before.nick != after.nick:
        embed.add_field(name="Nickname:",value=f"{before.display_name} -> {after.display_name}",inline=False)
        pass
    elif before.pending != after.pending:
        embed.add_field(name="Pending Verification:",value="Verified :white_check_mark:",inline=False)
        pass
    elif before.roles != after.roles:
        before_roles = set(before.roles)
        after_roles  = set(after.roles)

        added_roles   = after_roles.difference(before_roles)
        removed_roles = before_roles.difference(after_roles)

        added_str = "\n".join([role.mention for role in added_roles])
        removed_str = "\n".join([role.mention for role in removed_roles])

        if added_str != "": embed.add_field(name="Added Roles",value=added_str)
        if removed_str != "": embed.add_field(name="Removed Roles",value=removed_str)
        pass

    return embed
    pass

def insert_thread_changes(embed: discord.Embed, before: discord.Thread, after: discord.Thread) -> discord.Thread:
    if before.name != after.name:
        embed.add_field(name="Name:",value=f"{before.name} -> {after.name}",inline=False)
        pass
    if before.slowmode_delay != after.slowmode_delay:
        embed.add_field(name="Slowmode:",value=f"{utils.stringFromDuration(before.slowmode_delay)} -> {utils.stringFromDuration(after.slowmode_delay)}")
        pass
    if before.auto_archive_duration != after.auto_archive_duration:
        embed.add_field(name="Auto Archive After:",value=f"{utils.stringFromDuration(before.auto_archive_duration*60)} -> {utils.stringFromDuration(after.auto_archive_duration*60)}")
        pass
    
    return embed
    pass

def insert_emoji_sticker_changes(embed: discord.Embed, before: list[Union[discord.Emoji,discord.Sticker]], after: list[Union[discord.Emoji,discord.Sticker]]) -> discord.Embed:
    before: set = set(before)
    after: set = set(after )

    added   = after .difference(before)
    removed = before.difference(after )
    diff_strings = []
    for sign, remadd in ((":heavy_plus_sign:",added),(":heavy_minus_sign:",removed)):
        for obj in remadd:
            diff_strings.append(f"{sign} :{obj.name}:")
            pass
        pass

    embed.add_field(name="Changed Emojis/Stickers:",value="\n".join(diff_strings))

    return embed
    pass

def insert_server_settings_update(embed: discord.Embed, before: discord.Guild, after: discord.Guild) -> discord.Embed:
    add_standard_field = lambda name, attr: embed.add_field(name=f"{name}:",value=f"{getattr(before,attr)} -> {getattr(after,attr)}",inline=False)
    different = lambda attr: getattr(before,attr) != getattr(after,attr)
    standard = lambda name, attr: add_standard_field(name,attr) if different(attr) else None
    
    embed_url = lambda title, url: f"[{title}]({url})"
    embed_asset = lambda title, asset: embed_url(title,asset.url) if asset is not None else "None"
    add_asset_field = lambda name, attr: embed.add_field(name=f"{name}:",value=f"{embed_asset(getattr(before,attr))} -> {embed_asset(getattr(after,attr))}")
    standard_asset = lambda name, attr: add_asset_field(name,attr) if different(attr) else None
    
    standard("Name","name")
    standard("AFK Channel","afk_channel")
    if different("afk_timeout"):
        embed.add_field(name="AFK Timeout:",value=f"{utils.stringFromDuration(before.afk_timeout)} -> {utils.stringFromDuration(after.afk_timeout)}")
        pass
    standard("System Messages Channel","system_channel")
    if different("system_channel_flags"):
        flag_equivs = {
            "guild_reminder_notification":"Helpful Tips for server setup",
            "join_notifications":"Random welcome messages",
            "premium_subscriptions":"Nitro Boost Messages"
        }

        names = []
        values = []
        for flag_name, before_val in before.system_channel_flags:
            after_val = getattr(after.system_channel_flags,flag_name)
            if before_val != after_val:
                names.append(flag_equivs[flag_name])
                values.append(f"{state_to_str(before_val)} -> {state_to_str(after_val)}")
                pass
            pass

        embed.add_field(name="System Messages",value="\n".join(names))
        embed.add_field(name="State",value="\n".join(values))
        pass
    if different("default_notifications"):
        notify_type_to_str = lambda notify: "All" if notify == discord.NotificationLevel.all_messages else "Mentions"
        embed.add_field(name="Default Notification Setting",value=f"{notify_type_to_str(before.default_notifications)} -> {notify_type_to_str(after.default_notifications)}",inline=False)
        pass
    if different("description"):
        embed.add_field(name="Description (Before)",value=before.description)
        embed.add_field(name="Description (Now)",value=after.description)
        pass
    if different("explicit_content_filter"):
        def filter_to_str(content_filter: discord.ContentFilter) -> str:
            if content_filter == discord.ContentFilter.disabled: return "Disabled"
            elif content_filter == discord.ContentFilter.no_role: return "Without Roles"
            elif content_filter == discord.ContentFilter.all_members: return "All"
            pass

        embed.add_field(name="Content Filter",value=f"{filter_to_str(before.explicit_content_filter)} -> {filter_to_str(after.explicit_content_filter)}",inline=False)
        pass
    standard_asset("Server Icon","icon")
    if different("mfa_level"):
        embed.add_field(name="Multi-Factor Authentication for Moderators:",value=f"{state_to_str(bool(before.mfa_level))} -> {state_to_str(bool(after.mfa_level))}",inline=False)
        pass
    if different("nsfw_level"):
        def nsfw_to_str(level: discord.NSFWLevel) -> str:
            if level == discord.NSFWLevel.default: return "None"
            elif level == discord.NSFWLevel.safe: return "Safe"
            elif level == discord.NSFWLevel.age_restricted: return "May contain NSFW content"
            elif level == discord.NSFWLevel.explicit: return "Explicit"
            pass

        embed.add_field(name="NSFW Level:",value=f"{nsfw_to_str(before.nsfw_level)} -> {nsfw_to_str(after.nsfw_level)}",inline=False)
        pass
    standard("Server Owner","owner")
    standard("Server Discovery Language","preferred_locale")
    standard("Nitro Booster Role","premium_subscriber_role")
    standard("Boost Tier","premium_tier")
    standard("Rules Channel","rules_channel")
    standard_asset("Invite Splash Picture","splash")
    if different("verification_level"):
        embed.add_field(name="Verification Level:",value=f"{str(before.verification_level).capitalize()} -> {str(after.verification_level).capitalize()}",inline=False)
        pass

    return embed
    pass

def assemble_logging_embed(type: str, significance: discord.Colour, member: Union[discord.Member,discord.User], actor: discord.Member, message: discord.Message = None, reason: str = None, extra_description: str = None) -> discord.Embed:
    embed = discord.Embed(colour=significance,title=type,description="",timestamp=datetime.now())
    if actor is not None: embed.set_footer(text=f"Issued by {actor}",icon_url=actor.avatar.url)
    if member is not None: embed.set_author(name=member.name,icon_url=member.avatar.url)

    if message is not None:
        embed.description = "".join((embed.description,f"Regarding message on <t:{int(message.created_at.timestamp())}>:\n{message.clean_content}\n\n"))
        pass
    embed.description = "".join((embed.description,f"Reason:\n```\n{reason}```\n"))
    if extra_description is not None:
        embed.description = "".join((embed.description,extra_description))
        pass

    return embed
    pass

async def handle_event(event: Event):
    """TODO: Include Audit Log lookup"""
    log_channel_id: int = event.ACTIVE_COG.LOGGING_CHANNEL.get(event.guild.id)
    if log_channel_id is None: return # This shouldn't happen, but safety!

    if event.type & Event.MOD_MASK:
        if event.type not in (Event.MOD_BAN, Event.MOD_UNBAN):
            if event.type == Event.MOD_WARN:
                embed = assemble_logging_embed("Warning",Severity.HIGH,**event.data)
                pass
            else:
                event_data: Event.Automod = event.data
                if   event.type == Event.AUTOMOD_CAPS: type_str = "Capslock"
                elif event.type == Event.AUTOMOD_SPAM: type_str = "Spam"
                elif event.type == Event.AUTOMOD_EMOTE:type_str = "Emotespam"

                embed = assemble_logging_embed(type_str,Severity.HIGH,event_data["member"],event_data["member"].guild.me,event_data["message"],"Automod Detection")
            pass
        else:
            if   event.type == Event.MOD_BAN: type_str = "Banned User"
            elif event.type == Event.MOD_UNBAN: type_str = "Unbanned (Pardoned) User"

            embed = assemble_logging_embed(type_str,Severity.HIGH, event.data["user"],None,None,"Unknown")
            pass
        pass
    elif event.type & Event.MUTE_MASK:
        if event.type == Event.UNMUTE_EVENT:
            event_data: Event.Unmute = event.data
            embed = assemble_logging_embed("Unmute",Severity.HIGH,event_data["member"],event_data["actor"],None,event_data["reason"])
            pass
        elif event.type == Event.MUTE_EVENT:
            event_data: Event.Mute = event.data
            embed = assemble_logging_embed("Mute",Severity.HIGH,event_data["member"],event_data["actor"],None,event_data["reason"],f"Muted until <t:{event_data['until']}>")
            pass
        pass
    elif event.type & Event.GUILD_CHANNEL_MASK:
        if event.type == Event.GUILD_CHANNEL_CREATE: type_str = "Channel Created"
        elif event.type == Event.GUILD_CHANNEL_DELETE: type_str = "Channel Deleted"
        elif event.type == Event.GUILD_CHANNEL_UPDATE: type_str = "Channel Updated"
        
        if event.type in (Event.GUILD_CHANNEL_CREATE,Event.GUILD_CHANNEL_DELETE):
            channel: Channel = event.data["channel"]
            extra_description = channel_extra_description(event.type,channel)
            pass
        else:
            before: Channel = event.data["before"]
            after: Channel = event.data["after"]

            extra_description = channel_diff_description(before,after)
            pass


        embed = assemble_logging_embed(type_str,Severity.LOW if event.type == Event.GUILD_CHANNEL_CREATE else Severity.MID, None, None, None, "Unknown", extra_description)
        if event.type == Event.GUILD_CHANNEL_UPDATE: embed = describe_perm_override(embed,before.overwrites,after.overwrites)
        pass
    elif event.type & Event.GUILD_MASK:
        severity = Severity.LOW
        if event.type == Event.GUILD_EMOJI_UPDATE:
            type_str = "Emoji List Updated"
            pass
        elif event.type == Event.GUILD_STICKER_UPDATE:
            type_str = "Sticker List Updated"
            pass
        else:
            type_str = "Guild Settings Updated"
            severity = Severity.HIGH
            pass

        embed = assemble_logging_embed(type_str,severity,None,None,None,"Unknown",None)
        if event.type != Event.GUILD_SETTINGS_UPDATE:
            embed = insert_emoji_sticker_changes(embed,event.data["before"],event.data["after"])
            pass
        else:
            embed = insert_server_settings_update(embed,event.data["before"],event.data["after"])
        pass
    elif event.type & Event.INVITE_MASK:
        invite: discord.Invite = event.data["invite"]
        if event.type == Event.INVITE_CREATE: 
            type_str = "Invite Created"
            inviter = invite.inviter
            pass
        else: 
            type_str = "Invite Deleted"
            inviter = None
            pass
        
        embed = assemble_logging_embed(type_str,Severity.LOW,None,inviter,None,"Unknown")
        embed.add_field(name="Link:",value=invite.BASE + "/" + invite.code,inline=False)
        embed.add_field(name="Channel:",value=invite.channel.mention,inline=False)
        if event.type == Event.INVITE_CREATE:
            if invite.max_age!=0: expiration_string = f"<t:{int(invite.created_at.timestamp()) + invite.max_age}:R>"
            else: expiration_string = "Never"

            embed.add_field(name="Maximum Uses:",value=(invite.max_uses if invite.max_uses is not None else "Unlimited"),inline=False)
            embed.add_field(name="Expires: ",value=expiration_string,inline=False)
            pass
        pass
    elif event.type & Event.MEMBER_MASK:
        severity = Severity.LOW
        if event.type == Event.MEMBER_JOIN:
            member: discord.Member = event.data["member"]

            type_str = "Member Joined"
            extra_description = f"{member.mention} joined the server"
            msg_member = member
            pass
        elif event.type == Event.MEMBER_LEAVE:
            member: discord.Member = event.data["member"]
            if member == member.guild.me: return # This fixes a race condition where the bot would sometimes try and report itself leaving
            
            type_str = "Member Left"
            extra_description = f"{member.name}{member.discriminator} left the server"
            msg_member = member
            pass
        else:
            before: discord.Member = event.data["before"]
            after: discord.Member = event.data["after" ]

            type_str = "Member Updated"
            extra_description = None
            msg_member = after
            pass

        embed = assemble_logging_embed(type_str,severity,msg_member,None,None,"Unknown",extra_description)
        if event.type == Event.MEMBER_UPDATE:
            embed = insert_member_changes(embed,before,after)
            if len(embed.fields) == 0: return
            pass
        pass
    elif event.type & Event.MESSAGE_MASK:
        payload: discord.RawMessageDeleteEvent = event.data["payload"]
        channel: discord.TextChannel = event.guild.get_channel(payload.channel_id)
        arg_message = None
        member: discord.Member = None
        if event.type == Event.MESSAGE_EDIT:          
            type_str = "Message Edited"

            if payload.cached_message is None: message = await channel.fetch_message(payload.message_id)
            else: message = payload.cached_message

            if message is not None: member = message.author

            arg_message = message
            pass
        elif event.type == Event.MESSAGE_DELETE:        
            type_str = "Message Deleted"
            pass
        elif event.type == Event.MESSAGE_BULK_DELETE:   
            type_str = "Messages Bulk Deleted"
            pass

        embed = assemble_logging_embed(type_str,Severity.MID if event.type == Event.MESSAGE_BULK_DELETE else Severity.LOW, member, None, arg_message,"Unknown")
        if event.type == Event.MESSAGE_DELETE:
            embed.add_field(name="Channel:",value=channel.mention)
            if payload.cached_message is not None:
                embed.add_field(name="Author:",value=payload.cached_message.author.mention)
                embed.add_field(name="Content:",value=payload.cached_message.clean_content,inline=False)
                pass
            else:
                embed.add_field(name="Note:",value="This message was not found in the cache. Information is very limited",inline=False)
                pass
            pass
        elif event.type == Event.MESSAGE_BULK_DELETE:
            embed.add_field(name="Channel:",value=channel.mention,inline=False)
            embed.add_field(name="Messages Deleted:",value=len(payload.message_ids),inline=False)
            pass
        pass
    elif event.type & Event.ROLE_MASK:
        if   event.type == Event.ROLE_CREATE: type_str = "Role Created"
        elif event.type == Event.ROLE_DELETE: type_str = "Role Deleted"
        elif event.type == Event.ROLE_UPDATE: type_str = "Role Changed"

        severity = Severity.LOW if event.type == Event.ROLE_CREATE else Severity.MID
        embed = assemble_logging_embed(type_str,severity,None,None,None,"Unknown")
        if event.type == Event.ROLE_UPDATE:
            role_changed = lambda before, after: before.name != after.name or before.colour != after.colour or before.emoji != after.emoji or before.icon != after.icon or before.permissions != after.permissions
            before: discord.Role = event.data["before"]
            after: discord.Role = event.data["after" ]

            if not role_changed(before,after): return
            embed = role_diff_embed(embed,before,after)
            pass
        else:
            role: discord.Role = event.data["role"]

            embed.add_field(name="Role:",value=role.mention if event.type == Event.ROLE_CREATE else role.name,inline=False)
            embed.add_field(name="Colour:",value=f"{role.colour}",inline=False)
            if role.icon is not None: embed.set_image(url=role.icon.url)
            pass
        pass
    elif event.type & Event.REACTION_MOD_MASK:
        if event.type == Event.REACTION_CLEAR_ALL: type_str = "Removed All Reactions From Message"
        else: type_str = "Removed Single Emoji From Message"

        payload: Union[discord.RawReactionClearEmojiEvent, discord.RawReactionClearEvent] = event.data["payload"]
        message: discord.Message = await BOT.get_guild(int(payload.guild_id)).get_channel(int(payload.channel_id)).fetch_message(int(payload.message_id))

        embed = assemble_logging_embed(type_str,Severity.LOW,None,None,message,"Unknown")
        embed.add_field(name="Message URL: ",value=message.jump_url,inline=False)
        if event.type == Event.REACTION_CLEAR_SINGLE: embed.add_field(name="Removed Emoji: ",value=str(payload.emoji))
        pass
    elif event.type & Event.THREADS_MASK:
        if event.type == Event.THREADS_DELETE:
            thread: discord.Thread = event.data["thread"]
            
            type_str = "Thread Deleted"
            severity = Severity.MID
            extra_description = f'Thread: "{thread.name}" in channel {thread.parent.mention}\nOwner: {thread.owner.mention}'
            pass
        else:
            before = event.data["before"]
            after  = event.data["after" ]

            type_str = "Thread Updated"
            severity = Severity.MID
            extra_description = f"{after.mention}"
            pass

        embed = assemble_logging_embed(type_str,severity,None,None,None,"Unknown",extra_description)

        if event.type == Event.THREADS_UPDATE:
            embed = insert_thread_changes(embed,before,after)
            if len(embed.fields) == 0: return
            pass
        pass

    log_channel = await event.guild.fetch_channel(log_channel_id)
    await log_channel.send(embed=embed)
    pass

async def logger_task():
    while True:
        if len(LOGGING_EVENTS) > 0:
            for _ in range(len(LOGGING_EVENTS)):
                event = LOGGING_EVENTS.pop(0)
                asyncio.create_task(handle_event(event)) # Schedule as task because... efficiency? Honestly, there's not much async stuff happening in there, but I hope for a small speed improvement (especially at larger scales)
                await asyncio.sleep(0)
                pass
            pass
        await asyncio.sleep(0.5)
        pass
    pass