from discord import threads
from sqlalchemy.exc import NoResultFound
from loop import loop

from libs import utils, config
import logging, random, asyncio, dataclasses, json
from datetime import datetime
from typing import Union, Optional, Literal
from difflib import SequenceMatcher
from libs.logging_utils import LoggingSettings

import discord
from discord.ext import commands, tasks
from discord.ext.commands.converter import Option

from ormclasses import *

# Declare constants
CONFIG : config.Config = ...

BOT : commands.Bot = ...
WEBHOOK_POOL : utils.WebhookPool = ...
COG : commands.Cog = ...

ENGINE : asql.AsyncEngine
SESSION_FACTORY : orm.sessionmaker = ...

async def get_sql_guild(guild_id : int) -> tuple[Guild,asql.AsyncSession]:
    session : asql.AsyncSession = SESSION_FACTORY()
    result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(guild_id)))
    try:
        obj = result.scalar_one()
    except KeyError:
        obj = Guild(id=str(guild_id))
        session.add(obj)
        pass
    return obj, session
    pass

async def wait_for_role(ctx : commands.Context, error_msg : str = "That message does not have a role associated to it. Please try again",*, check = None, return_message : bool = False) -> Union[discord.Role,tuple[discord.Role,discord.Message]]:
    converter = commands.RoleConverter()
    while True:
        message : discord.Message = await BOT.wait_for("message",check=lambda message: message.channel == ctx.channel and message.author == ctx.author)
        try:
            role = await converter.convert(ctx,message.content)
            if not(check is None or check(role)): raise commands.BadArgument()
            pass
        except commands.BadArgument:
            await message.delete()
            await ctx.send(error_msg,ephemeral=True)
            pass
        else:
            break
        pass

    if return_message:
        return role, message
    else:
        return role
    pass

uppercase_fraction = lambda text: sum([int(char.isupper()) for char in text])/len(text)
Channel = Union[discord.TextChannel,discord.VoiceChannel,discord.StageChannel]

@dataclasses.dataclass()
class AutomodState:
    #__slots__ = ("capsspam","spamspam","emotespam") # Use slots to safe memory space (Although that doesn't interact with dataclasses -.-)
    capsspam  : bool = None
    spamspam  : bool = None
    emotespam : bool = None


    def setdefault(self,  key : str, val : bool) -> None:
        if getattr(self,key) is None:
            setattr(self,key,val)
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
    
    def __init__(
        self, 
        spam_max_message_similarity : float = 0.9, spam_max_message_repetition : float = 4,
        caps_max_ratio : float = 0.8, caps_min_length : int = 4,
        emoji_max_ratio : float = 0.9, emoji_min_length : int = 10,
        spam_consequence : Optional[list[bool]] = None, caps_consequence : Optional[list[bool]] = None, emoji_consequence : Optional[list[bool]] = None):
        
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

    def __repr__(self):
        return f"<ModConfig {self.spam_max_message_similarity=}; {self.spam_max_message_repetition=}; {self.caps_max_ratio=}; {self.caps_min_length=}; {self.emoji_max_ratio=}; {self.emoji_min_length=}>"
        pass

    @classmethod
    async def load(cls, guild_id : int):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild.automod_settings).where(Guild.id == str(guild_id)))
            
            modconfig : dict = result.scalar_one_or_none()
            if modconfig is not None:   obj = cls(**modconfig)
            else:                       obj = cls()
        finally:
            await session.close()

        return obj
        pass
    pass

GuildId = ChannelId = RoleId = MemberId = int
Capsspam = Spamspam = Emotespam = bool
JSONMemberId = str

MuteInf = list[int,str]
MuteDict = dict[JSONMemberId,MuteInf]

# View Objects
class GodRoleView(discord.ui.View):
    def __init__(self, ctx : commands.Context, cog : commands.Cog, *, timeout : float):
        self.ctx = ctx
        self.message : discord.Message = ...
        self.cog = cog

        super().__init__(timeout=timeout)
        pass

    async def on_timeout(self) -> None:
        self.message.edit(content="```\nInteraction timed out```",view=None,embed=None)

        await super().on_timeout()
        pass

    async def update_embed(self):
        embed = discord.Embed()
        embed.title = "List of God Roles"
        embed.colour = discord.Color.red()
        
        embed.description = "\n".join([self.ctx.guild.get_role(int(role_id)).mention for role_id in self.cog.GOD_ROLES[self.ctx.guild.id]])

        await self.message.edit(embed=embed)
        pass

    @discord.ui.button(label="Add",style=discord.ButtonStyle.primary)
    async def add_god_role(self, button : discord.ui.Button, interaction : discord.Interaction):
        await interaction.response.send_message("Please send a message with the role you mean to add",ephemeral=True)
        
        
        while True:
            role, message = await wait_for_role(self.ctx,return_message=True)
            await message.delete()
            if str(role.id) in self.cog.GOD_ROLES[interaction.guild_id]:
                await self.ctx.send("This role is already a god. Please choose another one",ephemeral=True)
                pass
            else:
                break
            pass
        
        self.cog.GOD_ROLES[self.ctx.guild.id].add(str(role.id))

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(interaction.guild_id)))
            sql_guild : Guild = result.scalar_one()
            sql_guild.god_roles.append(str(role.id))
            await session.commit()
        finally:
            await session.close()

        await self.update_embed()
        pass

    @discord.ui.button(label="Remove",style=discord.ButtonStyle.secondary)
    async def rem_god_role(self, button : discord.ui.Button, interaction : discord.Interaction):
        await interaction.response.send_message("Please send a message with the role you mean to remove",ephemeral=True)
        
        
        while True:
            role, message = await wait_for_role(self.ctx,return_message=True)
            await message.delete()
            if str(role.id) not in self.cog.GOD_ROLES[interaction.guild_id]:
                await self.ctx.send("This is not a god... You realise that right?",ephemeral=True)
                pass
            else:
                break
            pass
        
        self.cog.GOD_ROLES[self.ctx.guild.id].remove(str(role.id))
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(interaction.guild_id)))
            sql_guild : Guild = result.scalar_one()
            sql_guild.god_roles.remove(str(role.id))
            await session.commit()
        finally:
            await session.close()

        await self.update_embed()
        pass

    @discord.ui.button(label="Close",style=discord.ButtonStyle.danger)
    async def exit_interaction(self, button : discord.ui.Button, interaction : discord.Interaction):
        await interaction.response.defer()
        await self.message.edit("```\nInteraction has been closed```",view=None)
        self.stop()
        pass
    pass


class LoggingSettingsView(discord.ui.View):
    def __init__(self, ctx : commands.Context, cog : commands.Cog, *, timeout : float):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.message : discord.Message = ...

        self.embed = discord.Embed(title=f"Logging Settings of {ctx.guild.name}",colour=discord.Colour.blue())
        self.embed.add_field(name="Setting Title",value="Empty")
        self.embed.add_field(name="Current State",value="Empty")

        self.selected_state = None
        pass

    async def update_message(self):
        settings = self.cog.LOGGING_SETTINGS[self.ctx.guild.id]

        translation_table = {
            "moderation" : "Moderation",
            "channels" : "Channels",
            "server_update" : "Server Update",
            "invites" : "Invites",
            "member_changes" : "Member Changes",
            "messages" : "Messages",
            "reactions_mod" : "Reactions Moderation",
            "roles" : "Roles",
            "threads_mod" : "Threads Moderation"
        }
        self.embed.set_field_at(0,name="Setting Title",value="\n".join(translation_table.values()))
        self.embed.set_field_at(1,name="Current State",value="\n".join([":white_check_mark: Enabled" if getattr(settings,var) else ":x: Disabled" for var in translation_table.keys()]))

        await self.message.edit(embed=self.embed,view=self)
        pass

    @discord.ui.button(label="Enable Event", style=discord.ButtonStyle.green,row=0)
    async def en_event(self, button : discord.ui.Button, interaction : discord.Interaction):
        self.selected_state = True
        utils.first(self.children,lambda item: isinstance(item,discord.ui.Select)).disabled = False
        await self.update_message()

        await interaction.response.defer()
        pass

    @discord.ui.button(label="Disable Event", style=discord.ButtonStyle.red,row=0)
    async def da_event(self, button : discord.ui.Button, interaction : discord.Interaction):
        self.selected_state = False
        utils.first(self.children,lambda item: isinstance(item,discord.ui.Select)).disabled = False
        await self.update_message()

        await interaction.response.defer()
        pass

    @discord.ui.select(placeholder="Select an event to update",disabled=True,row=1,options=[
        discord.SelectOption(label="Moderation",value="moderation",description="Logging of Automod or member kicks/bans"),
        discord.SelectOption(label="Channels",value="channels",description="Log changes to channels (creation, deletion, etc.)"),
        discord.SelectOption(label="Sever Updates",value="server_update",description="Log changes regarding the server (e.g. name, security, emojis/stickers)"),
        discord.SelectOption(label="Invites",value="invites",description="Log creation/deletion of invites"),
        # discord.SelectOption(label="Integrations",value="integrations",description="Log changes to integrations/webhooks"),
        discord.SelectOption(label="Member Changes",value="member_changes",description="Log changes to the members (joins, leaves, profile changes)"),
        discord.SelectOption(label="Messages",value="messages",description="Log message changes (deletion/edits)"),
        # discord.SelectOption(label="Reactions",value="reactions",description="Log added/removed reactions"),
        discord.SelectOption(label="Reaction Moderation",value="reactions_mod",description="Log moderation actions related to reactions"),
        discord.SelectOption(label="Roles",value="roles",description="Log changes to the roles of this server"),
        # discord.SelectOption(label="Threads",value="threads",description="Log member interactions with threads"),
        discord.SelectOption(label="Thread Moderation",value="threads_mod",description="Log changes to threads")
    ])
    async def select_event(self, select : discord.ui.Select, interaction : discord.Interaction):
        settings : LoggingSettings = self.cog.LOGGING_SETTINGS[interaction.guild_id]
        setattr(settings,interaction.data["values"][0],self.selected_state)
        
        select.disabled = True
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(interaction.guild_id)))
            sqlguild : Guild = result.scalar_one_or_none()
            if sqlguild is None:
                sqlguild = Guild(str(interaction.guild_id))
                session.add(sqlguild)
                pass
            sqlguild.logging_settings = settings.to_value()
            await session.commit()
        finally:
            await session.close()

        await self.update_message()

        await interaction.response.defer()
        pass
    pass

# Cog

class Moderation(commands.Cog):
    """A tool for... well moderation"""
    """TODO: Automod, Logging"""

    ANARCHIES       : dict[GuildId,set[str]]
    GOD_ROLES       : dict[GuildId,set[str]]            = {}
    AUTOMODS        : dict[GuildId,AutomodState]        = {}
    LOGGING_CHANNEL : dict[GuildId,Optional[int]]       = {}
    AUTOMOD_SETTINGS: dict[GuildId,ModConfig]           = {}
    LOGGING_SETTINGS  : dict[GuildId, LoggingSettings]  = {}

    LAST_MESSAGES : dict[GuildId,dict[ChannelId,dict[MemberId,list[Optional[str],int]]]] = {}

    def __init__(self):
        self.ANARCHIES          = BOT.DATA.ANARCHIES
        self.GOD_ROLES          = BOT.DATA.GOD_ROLES
        self.AUTOMODS           = BOT.DATA.AUTOMODS
        self.LOGGING_CHANNEL    = BOT.DATA.LOGGING_CHANNEL
        self.AUTOMOD_SETTINGS   = BOT.DATA.AUTOMOD_SETTINGS
        self.LOGGING_SETTINGS   = BOT.DATA.LOGGING_SETTINGS
        super().__init__()
        pass

    def cog_unload(self):

        return super().cog_unload()
        pass

    # Automod
    async def spam_actions(self, message : discord.Message, settings : ModConfig):
        response = "Is there an echo in here? (Spam Automod)"
        if settings.spam_consequence[0]:
            await message.delete()
            pass
        if settings.caps_consequence[1]:
            response = "".join((response,"\nMy moderators will hear about this!"))
        
        await message.channel.send(response,delete_after=5)

        add_logging_event(Event(Event.AUTOMOD_SPAM,message.guild,{"message":message,"member":message.author}))
        pass

    async def caps_actions(self, message : discord.Message, settings : ModConfig):
        response = "Could you please quiet down a little? This is not a rock concert! (Caps Automod)"
        if settings.caps_consequence[0]:
            await message.delete()
            pass
        if settings.caps_consequence[1]:
            response = "".join((response,"\nMy moderators will hear about this!"))

        await message.channel.send(response,delete_after=5)

        add_logging_event(Event(Event.AUTOMOD_CAPS,message.guild,{"message":message,"member":message.author}))
        pass

    @commands.Cog.listener("on_message")
    async def spam_listener(self, message : discord.Message):
        if message.author.bot: return # Ignore messages from bots
        if  not self.AUTOMODS[message.guild.id].spamspam or \
            len(self.GOD_ROLES[message.guild.id].intersection({role.id for role in message.author.roles})) > 0: return # Don't check for gods
        if message.guild.id not in self.AUTOMOD_SETTINGS.keys(): # Load in default settings if neccessary
            self.AUTOMOD_SETTINGS[message.guild.id] = ModConfig()
            pass
        
        self.LAST_MESSAGES.setdefault(message.guild.id,{})
        self.LAST_MESSAGES[message.guild.id].setdefault(message.channel.id,{})
        self.LAST_MESSAGES[message.guild.id][message.channel.id].setdefault(message.author.id,[None,0])

        spam_data = self.LAST_MESSAGES[message.guild.id][message.channel.id][message.author.id] # Using list instead of unpacking for easier manipulation of data
        settings = self.AUTOMOD_SETTINGS[message.guild.id]

        if spam_data[0] is not None: # Don't need to check for similarity if there is no previous message
            comparison = SequenceMatcher(None,message.content.lower(),spam_data[0])
            similarity : float = await asyncio.get_event_loop().run_in_executor(None,lambda: comparison.ratio())
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
    async def caps_listener(self, message : discord.Message):
        if message.author.bot: return # Ignore messages from bots
        if  not self.AUTOMODS[message.guild.id].capsspam or \
            len(self.GOD_ROLES[message.guild.id].intersection({role.id for role in message.author.roles})) > 0: return # Don't check for gods
        if message.guild.id not in self.AUTOMOD_SETTINGS.keys(): # Load in default settings if neccessary
            self.AUTOMOD_SETTINGS[message.guild.id] = ModConfig()
            pass

        settings = self.AUTOMOD_SETTINGS[message.guild.id]

        if len(message.clean_content) >= settings.caps_min_length:
            caps_fraction : float = await asyncio.get_event_loop().run_in_executor(None,uppercase_fraction,message.clean_content)
            if caps_fraction > settings.caps_max_ratio:
                await self.caps_actions(message,settings)
                pass
            pass
        pass

    # Channel Mod
    @commands.group("lock",brief="In a locked channel, people can't write by default")
    @commands.guild_only()
    @utils.perm_message_check("Hey! Wait! Put that lock down! Stop it! (No Permission)",manage_channels=True)
    async def lock(self,ctx):
        pass

    @lock.command("set",brief="Lock this channel")
    async def set_lock(self, ctx : commands.Context):
        await ctx.channel.set_permissions(ctx.guild.default_role,overwrite=discord.PermissionOverwrite(send_messages=False))
        await ctx.send("🔒 **This channel has been locked** 🔒")
        pass

    @lock.command("remove",brief="Unlock this channel")
    async def rem_lock(self, ctx : commands.Context):
        await ctx.channel.set_permissions(ctx.guild.default_role,overwrite=discord.PermissionOverwrite(send_messages=True))
        await ctx.send("🔓 **This channel has been unlocked** 🔓")
        pass

    ## Anarchy
    @commands.group("anarchy",brief="Anarchy is... well, it's a thing.")
    @commands.guild_only()
    @utils.perm_message_check("Now, this is interesting... I know what the command looks like, but to be honest that is kind of a lie... (No Permission)", manage_channels=True)
    async def anarchy(self,ctx):
        pass

    @anarchy.after_invoke
    async def anarchy_sql_update(self,ctx : commands.Context):
        try:
            sqlguild, session = await get_sql_guild(ctx.guild.id)
            # Remove all outdated channels (channels that were deleted)
            all_channel_ids : list[ChannelId] = [channel.id for channel in ctx.guild.text_channels]

            prev_anarchies = sqlguild.anarchies.copy()
            sqlguild.anarchies.clear()
            sqlguild.anarchies.extend(filter(lambda channel_str: int(channel_str) in all_channel_ids , prev_anarchies))
            # Update the RAM dict with the anarchy channels
            self.ANARCHIES.setdefault(ctx.guild.id,set())
            self.ANARCHIES[ctx.guild.id].clear()
            self.ANARCHIES[ctx.guild.id].update([int(channel_str) for channel_str in sqlguild.anarchies])

            await session.commit()
        finally:
            await session.close() # Commit & Close
        pass

    @anarchy.command("enable",brief="Excludes this channel from the automod")
    async def set_anarchy(self, ctx : commands.Context):
        try:
            sqlguild, session = await get_sql_guild(ctx.guild.id) # Get the SQL Reference to the guild
            if not str(ctx.channel.id) in sqlguild.anarchies:
                sqlguild.anarchies.append(str(ctx.channel.id)) # Add the channel to the anarchy channels
                await ctx.send("Woo! Anarchy... I guess..." + (" You know, as a moderation bot this is a rather weird thing to say..." if random.randint(1,25) == 25 else ""),ephemeral=True)
                pass
            else:
                await ctx.send("Hahaha! This is anarchy! I don't have to listen to you anymore! (Anarchy is already enabled)",ephemeral=True)
                pass
            
            await session.commit()
        finally:
            await session.close()
        pass

    @anarchy.command("disable",brief="(Re)includes this channel in the automod")
    async def rem_anarchy(self, ctx : commands.Context):
        try:
            sqlguild, session = await get_sql_guild(ctx.guild.id) # Get SQL Reference to the guild
            if str(ctx.channel.id) in sqlguild.anarchies:
                sqlguild.anarchies.remove(str(ctx.channel.id))
                await ctx.send("Alright, anarchy is disabled now. No, put that axe away; I said it is **disabled** now.",ephemeral=True)
                pass
            else:
                await ctx.send("But... there isn't any anarchy here, what should I do now?",ephemeral=True)
                pass

            await session.commit()
        finally:
            await session.close() # Commit & Close
        pass

    @anarchy.command("list",brief="List all anarchy channels on this server")
    async def list_anarchy(self, ctx : commands.Context):
        try:
            sqlguild, session = await get_sql_guild(ctx.guild.id) # Get SQL Reference to the guild
            
            embed = discord.Embed(title="Anarchy channels",colour=discord.Colour.blue(),description="")
            for channel_str in sqlguild.anarchies: # List every anarchy channel in the embed description
                channel = ctx.guild.get_channel(int(channel_str))
                embed.description = "".join((embed.description,channel.mention,"\n"))
                pass
        finally:
            await session.close()

        await ctx.send(embed=embed,ephemeral=True)
        pass

    # Message Mod
    @commands.command("move",brief="Move a specified amount of messages to a specified channel")
    @commands.guild_only()
    @utils.perm_message_check("You don't seem to have the right tools to lift these messages... (No Permission)",manage_messages=True)
    async def move_messages(self, ctx : commands.Context, channel : discord.TextChannel, messages : int = Option(description="The amount of messages to move. This is capped at 100")):
        messages = min(messages,CONFIG.MSG_MOVE_LIM)

        message_contents = [""]
        
        all_messages = [message async for message in ctx.channel.history(limit=messages)]
        all_messages.reverse()
        for message in all_messages:
            message : discord.Message

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

        if not channel.permissions_for(ctx.me).is_superset(discord.Permissions(send_messages=True)):
            await ctx.send("I am unable to send messages in the channel you specified. Please use a different channel or change the permissions of the selected channel to fix this issue.",ephemeral=True)
            return
            pass

        async def send_msgs():
            for content in message_contents:
                await channel.send(content)
                pass
            pass

        await asyncio.gather(send_msgs(),ctx.channel.purge(limit=messages))
        await ctx.send(f"This conversation has been moved to {channel.mention}")
        pass

    @commands.command("purge",brief="Remove a specified amount of messages in this channel")
    @commands.guild_only()
    @utils.perm_message_check("Now, these are some pretty destructive weapons. Wouldn't want them to fall into the wrong hands, eh? (No Permission)",manage_messages=True)
    async def purge_messages(self, ctx : commands.Context, messages : int):
        messages = min(messages,CONFIG.MSG_PURGE_LIM)
        await ctx.channel.purge(limit=messages)

        await ctx.send("Deleted {} message(s)! :white_check_mark:".format(messages),ephemeral=True)
        pass

    
    # User Mod
    @commands.command("mute",brief="Mute a specified member for a given amount of time")
    @commands.guild_only()
    @utils.perm_message_check("You put that tape away! That is my job! (No Permission: Need Mute Members Permission (voice chat))",manage_channels=True)
    async def mute_member(self, ctx : commands.Context, member : discord.Member, time : str = None, reason : str = None):
        """
        TODO:
        FIX: SAWarning: SELECT statement has a cartesian product between FROM element(s) "guilds" and FROM element "mutes".  Apply join condition(s) between each element to resolve.
        (maybe don't actually have to do that)
        """

        async def create_new_muted_role() -> discord.Role:
            return await ctx.guild.create_role(reason="Mute role needed, but doesn't exist yet.",name="Muted",colour=discord.Colour.light_gray())
            pass

        def convSecsToOutput(seconds : Optional[int]) -> str:
            if seconds is None:
                return "ever"
                pass
            else:
                nsecs  = seconds % 60
                nmins  = (seconds// 60) % 60
                nhours = seconds//3600
                pass

            return f"{nhours} hours {nmins} minutes and {nsecs}"
            pass

        if time is not None:
            try:
                seconds = utils.durationFromString(time) # Convert time string into an amount of seconds
                pass
            except ValueError: # Send an error if the string is invalid and cancel
                await ctx.send("That is not quite what I had in mind... Looks like your time is incorrect. (Argument 'time' is invalid)",ephemeral=True)
                return
                pass
            pass
        else: # Leave seconds as None if no time was passed
            seconds = None
            pass


        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(ctx.guild.id)))

            guild : Guild = result.scalar_one_or_none()

            if guild is None or guild.mute_role_id in (None,""): # Create a `muted` role if it doesn't exist yet
                role = await create_new_muted_role()
                pass
            else: # Get the muted role if it does exist
                role_id = int(guild.mute_role_id)
                role = ctx.guild.get_role(role_id)
                if role is None: # Or create one if some moron deleted it
                    role = await create_new_muted_role()
                    pass
                pass

            await member.add_roles(role,reason="Muted by a moderator")
            
            result = await session.execute(sql.select(GuildMutes).where(Guild.id == str(ctx.guild.id)))

            if seconds is not None:
                muted_until = int(datetime.utcnow().timestamp() + seconds)
                pass
            else:
                muted_until = None
                pass
            try:
                mutes : GuildMutes = result.scalar_one()
                pass
            except NoResultFound:
                await session.execute(sql.insert(GuildMutes).values(guild_id=str(ctx.guild.id),mutes={
                    str(member.id):[
                        muted_until,
                        reason
                    ]
                }))
                pass
            else:
                mutes.mutes[str(member.id)] = [
                    muted_until,
                    reason
                ]
                pass
            await session.commit()
        finally:
            await session.close() # Commit & Close

        mute_event_data : Event.Mute = {"manual":True,"member":member,"reason":reason,"until":muted_until,"actor":ctx.author}
        add_logging_event(Event(Event.MUTE_EVENT,ctx.guild,mute_event_data))

        await ctx.send(f"Muted {member.mention} for {convSecsToOutput(seconds)} with the following reason:```\n{reason}```",ephemeral=True)
        pass

    @commands.command("unmute",brief="Unmute a specified member")
    @utils.perm_message_check("Unmute a muted member again",mute_members=True)
    async def unmute_member(self, ctx : commands.Context, member : discord.Member, reason : str = None):
        pass

    ## Role exceptions
    @commands.group("god_roles",brief="Users with a god role will not be affected by any automod checks")
    @utils.perm_message_check("2 things: \n\t1. You're not a god\n\t2. You won't be able to make yourself one with this\n\t2.1 No Permission",manage_guild=True)
    async def god_roles(self, ctx):
        pass

    @god_roles.command("add",brief="Add a new role to the list of roles exempted from the automod")
    async def god_roles_add(self, ctx : commands.Context, role : discord.Role):
        if str(role.id) in self.GOD_ROLES[ctx.guild.id]:
            await ctx.send(f"Just as a check, I sent a prayer to `{role.name}` and I actually got an answer... So, yeah, that role already is a god role",ephemeral=True)
            return
            pass

        self.GOD_ROLES[ctx.guild.id].add(str(role.id))

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id==str(ctx.guild.id)))
            sql_guild : Guild = result.scalar_one()
            sql_guild.god_roles.append(str(role.id))
            await session.commit()
        finally:
            await session.close()

        await ctx.send(f"All hail {role.mention} or something... Anyway, that role is now a god role!",ephemeral=True)
        pass

    @god_roles.command("remove",brief="Remove a role from the list of roles exempted from the automod")
    async def god_roles_rem(self, ctx : commands.Context, role : discord.Role):
        if str(role.id) not in self.GOD_ROLES[ctx.guild.id]:
            await ctx.send(f"Who is this `{role.name}` you are talking about? Not a god at least...",ephemeral=True)
            return
            pass

        self.GOD_ROLES[ctx.guild.id].remove(str(role.id))

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id==str(ctx.guild.id)))
            sql_guild : Guild = result.scalar_one()
            sql_guild.god_roles.remove(str(role.id))
            await session.commit()
        finally:
            await session.close()

        await ctx.send("So what is this called? Let me just check... A, yes! Deicide, that's it!",ephemeral=True)
        pass

    @god_roles.command("list",brief="List all roles exempted from the automod")
    async def god_roles_list(self, ctx : commands.Context):
        view = GodRoleView(ctx,self,timeout=CONFIG.EDIT_TIMEOUT)
        message = await ctx.send("```\nSelect one of the options or disable the interaction```",view=view,ephemeral=True)
        view.message = message
        await view.update_embed()
        pass

    # Logging
    @commands.group("logging")
    @utils.perm_message_check("Now, there is something called privacy, you know? I know, it's a bit ironical considering this command's function, but that doesn't mean you get to do this! (No Permission)",manage_guild=True)
    async def logging(self, ctx): 
        pass

    @logging.command("channel",brief="Set the channel the logger will write to.")
    async def set_log_channel(self, ctx : commands.Context, channel : discord.TextChannel = Option(None,description="The channel to log events in. Leave empty to reset")):
        if not isinstance(channel,discord.TextChannel):
            await ctx.send("The channel you passed does not seem to be a text channel. Please check your input",ephemeral=True)
            return
            pass

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            await session.execute(sql.update(Guild).where(Guild.id==str(ctx.guild.id)).values(logging_channel=(str(channel.id) if channel is not None else None)))
            await session.commit()
        finally:
            await session.close()

        self.LOGGING_CHANNEL[ctx.guild.id] = (channel.id if channel is not None else None)

        if channel is None:
            await ctx.send("Logging is now disabled! Freedom! Yay!",ephemeral=True)
            pass
        else:
            await ctx.send("Logging is now enabled! Finally we can know what everyone on the server is doing! This... sounded better in my head",ephemeral=True)
            pass
        pass

    @logging.command("events",brief="Specify the events in which a log entry will be made")
    async def specify_log_events(self, ctx : commands.Context,
        moderation         : bool = Option(None, description="Set to true to enable logging of Automod or member kicks/bans"),

        channels            : bool = Option(None, description="Set to true to log changes to channels (creation, deletion, etc.)"),
        
        server_update       : bool = Option(None, description="Set to true to log changes regarding the server"),                                       # <-
        # server_update       : bool = Option(None, description="Set to true to log changes to the server settings"),
        # emoji_update        : bool = Option(None, description="Set to true to log the addition or removal of server emojis"),
        # sticker_update      : bool = Option(None, description="Set to true to log the addition or removal of server stickers"),

        invites             : bool = Option(None, description="Set to true to log edited invites"),

        member_changes      : bool = Option(None, description="Set to true to log changes to the members (like joining, leaving or nickname changes"),

        messages            : bool = Option(None, description="Set to true to log message changes (deletion/edits)"),
        
        reactions_mod       : bool = Option(None, description="Set to true to log moderation for reactions (reaction clears)"),
        
        roles               : bool = Option(None, description="Set to true to log changes to the roles of this server"),
        
        threads_mod         : bool = Option(None, description="Set to true to log changes to threads"),
        ):
        args = (moderation, channels, server_update, invites, member_changes, messages, reactions_mod, roles, threads_mod)
        self.LOGGING_SETTINGS[ctx.guild.id].update(*args)

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(ctx.guild.id)))
            sqlobj : Guild = result.scalar_one_or_none()
            if sqlobj is not None: sqlobj.logging_settings = self.LOGGING_SETTINGS[ctx.guild.id].to_value()

            await session.commit()
        finally:
            await session.close()

        view = LoggingSettingsView(ctx,self,timeout=CONFIG.EDIT_TIMEOUT)
        message = await ctx.send("```\nFirst select whether you wish to enable or disable an event\nand then use the select menu to specify the event```",view=view,ephemeral=True)
        view.message = message
        await view.update_message()
        pass

    # SQL Moderation collector
    async def moderation_inserter(self,sqlguild : Optional[Guild],*,guild_id : int = None):
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
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild))
            sqlobjs : list[Guild] = result.scalars().all()
            
            for sqlguild in sqlobjs:
                await self.moderation_inserter(sqlguild)
                pass
        finally:
            await session.close()
        pass

    @commands.Cog.listener("on_guild_join")
    async def moderation_inserter_event(self, guild : discord.Guild):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(guild.id)))

            sqlguild : Optional[Guild] = result.scalar_one_or_none()

            await self.moderation_inserter(sqlguild,guild_id=guild.id)
        finally:
            await session.close()
        pass

    @commands.Cog.listener("on_ready")
    async def task_creator(self):
        asyncio.create_task(logger_task())
        pass

    # Logging Event handlers ----------------------------------------
    # What? This isn't long! It's remarkably short! (Kind of...)
    @commands.Cog.listener("on_ready")
    @utils.call_once_async
    async def logging_creator(self):
        def check_event_logging_enabled(guild : discord.Guild, event_type : int) -> bool:
            if self.LOGGING_CHANNEL.get(guild.id) is None: return False
            return bool(self.LOGGING_SETTINGS[guild.id].to_value() & event_type)
            pass

        def guild_from_payload(payload) -> discord.Guild:
            if not hasattr(payload.data,"guild_id"): raise ValueError
            try:
                return BOT.get_guild(int(payload.data.guild_id))
            except (AttributeError, ValueError):
                raise ValueError
                pass
            pass

        guild_from_invite = lambda invite: invite.guild
        guild_from_sticker_emoji = lambda guild, before, after: guild
        guild_from_member = lambda member: member.guild
        guild_from_role = lambda role: role.guild
        guild_from_react_payload = lambda payload: BOT.get_guild(payload.guild_id)

        event_dict = {
                "on_guild_channel_create"       : (Event.GUILD_CHANNEL_CREATE,("channel",),lambda channel: channel.guild),
                "on_guild_channel_delete"       : (Event.GUILD_CHANNEL_DELETE,("channel",), lambda channel: channel.guild),
                "on_guild_channel_update"       : (Event.GUILD_CHANNEL_UPDATE,("before","after"), lambda before, after: after.guild),

                "on_guild_update"               : (Event.GUILD_SETTINGS_UPDATE,("before","after"), lambda before, after: after),
                "on_guild_emojis_update"        : (Event.GUILD_EMOJI_UPDATE,("guild","before","after"), guild_from_sticker_emoji),
                "on_guild_stickers_update"      : (Event.GUILD_STICKER_UPDATE,("guild","before","after"), guild_from_sticker_emoji),

                "on_invite_create"              : (Event.INVITE_CREATE,("invite",), guild_from_invite),
                "on_invite_delete"              : (Event.INVITE_DELETE,("invite",), guild_from_invite),
                
                "on_member_join"                : (Event.MEMBER_JOIN,("member",), guild_from_member),
                "on_member_leave"               : (Event.MEMBER_LEAVE,("member",), guild_from_member),
                "on_member_update"              : (Event.MEMBER_UPDATE,("before","after"), lambda before, after: after.guild),
                
                "on_member_ban"                 : (Event.MOD_BAN,("guild","user"), lambda guild, user: guild),
                "on_member_unban"               : (Event.MOD_UNBAN,("guild","user"), lambda guild, user: guild),
                
                "on_raw_message_edit"           : (Event.MESSAGE_EDIT,("payload",), lambda payload: BOT.get_guild(payload.guild_id)),
                "on_raw_message_delete"         : (Event.MESSAGE_DELETE,("payload",), lambda payload: BOT.get_guild(payload.guild_id)),
                "on_raw_bulk_message_delte"     : (Event.MESSAGE_BULK_DELETE,("payload",), lambda payload: BOT.get_guild(payload.guild_id)),
                
                "on_guild_role_create"          : (Event.ROLE_CREATE,("role",), guild_from_role),
                "on_guild_role_delete"          : (Event.ROLE_DELETE,("role",), guild_from_role),
                "on_guild_role_update"          : (Event.ROLE_UPDATE,("before","after"), lambda before, after: after.guild),
                
                "on_thread_update"              : (Event.THREADS_UPDATE,("before","after"), lambda before, after: after.guild),
                "on_thread_delete"              : (Event.THREADS_DELETE,("thread",), lambda thread: thread.guild),
                
                "on_raw_reaction_clear"         : (Event.REACTION_CLEAR_ALL,("payload",), guild_from_react_payload),
                "on_raw_reaction_clear_emoji"   : (Event.REACTION_CLEAR_SINGLE,("payload",), guild_from_react_payload)
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
def setup(bot : commands.Bot):
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
    bot.add_cog(COG)

    logging.info("Added moderation extension")
    pass

def teardown(bot : commands.Bot):
    bot.remove_cog("Moderation")
    pass


#----------------------------------------------------------------------------
class Severity:
    LOW = discord.Colour.green()
    MID = discord.Colour.yellow()
    HIGH= discord.Colour.red()

class Event:
    ACTIVE_COG = Moderation


    Mute    = dict[Literal["manual","member","reason","until","actor"],Union[bool,discord.Member,str,int]]
    Unmute  = dict[Literal["member","reason","actor"],Union[discord.Member,str]]
    Automod = dict[Literal["member","message"],Union[discord.Member,discord.Message]]
    GuildChannel_Create = dict[Literal["channel"],Channel]
    GuildChannel_Delete = dict[Literal["channel"],Channel]
    GuildChannel_Update = dict[Literal["before"],Literal["after"]]
    GuildSettings= dict[Literal["before","after"],discord.Guild]
    EmojiUpdate  = dict[Literal["guild","before","after"],Union[discord.Guild,list[discord.Emoji]]]
    EmojiUpdate  = dict[Literal["guild","before","after"],Union[discord.Guild,list[discord.Sticker]]]
    Invite       = dict[Literal["invite"],discord.Invite]
    Member_JL    = dict[Literal["member"],discord.Member]
    Member_Update= dict[Literal["before","after"],discord.Member]
    Message_Edit  = dict[Literal["payload"],discord.RawMessageUpdateEvent]
    Message_Delete= dict[Literal["payload"],discord.RawMessageDeleteEvent]
    Reaction_Clear= dict[Literal["message","reactions"],Union[discord.Message,list[Union[discord.Emoji,discord.PartialEmoji]]]]
    Role          = dict[Literal["role"],discord.Role]
    Role_Update   = dict[Literal["before","after"],discord.Role]
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
    def __init__(self, type : int, guild : discord.Guild, data):
        self.type = type
        self.data = data
        self.guild = guild
        pass
    pass

LOGGING_EVENTS : list[Event] = []
EMPTY_OVERRIDE = discord.PermissionOverwrite()

def state_to_str(state : Optional[bool]) -> str:
    if state is None: return ":heavy_minus_sign:"
    elif state is False: return ":x:"
    else: return ":white_check_mark:"
    pass

Permission_Overrides = dict[Union[discord.Role,discord.Member],discord.PermissionOverwrite]
def gen_permission_override_string(perm_overrides : Permission_Overrides) -> str:
    # This line seems unreasonably long... Debugging this will be fun! Hehe...
    return "\n\n".join("".join((target.mention,"\n\t".join((perm+": "+state_to_str(state) for perm, state in override))) for target, override in perm_overrides.items()))
    pass

def describe_perm_override(embed : discord.Embed, a : Permission_Overrides, b : Permission_Overrides) -> discord.Embed:
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

def channel_extra_description(event_type : int,channel : Channel) -> str:
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

def channel_diff_description(before : Channel, after : Channel) -> str:
    lines = []
    lines.append(f"Channel: {after.mention}")
    if before.name != after.name: lines.append(f"Name: {before.name} -> {after.name}")
    if before.category != after.category: lines.append(f"Category: {before.category} -> {after.category}")
    
    if isinstance(before,discord.TextChannel): # Text channel exclusive changes
        if before.slowmode_delay != after.slowmode_delay: lines.append(f"Slowmode: {utils.stringFromDuration(before.slowmode_delay)} -> {utils.stringFromDuration(after.slowmode_delay)}")
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

def role_diff_embed(embed : discord.Embed, before : discord.Role, after : discord.Role) -> discord.Embed:
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

def add_logging_event(event : Event):
    LOGGING_EVENTS.append(event)
    pass

def insert_member_changes(embed : discord.Embed, before : discord.Member, after : discord.Member) -> discord.Embed:
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

        added_str  = "\n".join([role.mention for role in added_roles])
        removed_str= "\n".join([role.mention for role in removed_roles])

        if added_str != "": embed.add_field(name="Added Roles",value=added_str)
        if removed_str != "": embed.add_field(name="Removed Roles",value=removed_str)
        pass

    return embed
    pass

def insert_thread_changes(embed : discord.Embed, before : discord.Thread, after : discord.Thread) -> discord.Thread:
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

def insert_emoji_sticker_changes(embed : discord.Embed, before : list[Union[discord.Emoji,discord.Sticker]], after : list[Union[discord.Emoji,discord.Sticker]]) -> discord.Embed:
    before : set = set(before)
    after  : set = set(after )

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

def insert_server_settings_update(embed : discord.Embed, before : discord.Guild, after : discord.Guild) -> discord.Embed:
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
            "guild_reminder_notification"   : "Helpful Tips for server setup",
            "join_notifications"            : "Random welcome messages",
            "premium_subscriptions"         : "Nitro Boost Messages"
        }

        names = []
        values= []
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
        def filter_to_str(content_filter : discord.ContentFilter) -> str:
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
        def nsfw_to_str(level : discord.NSFWLevel) -> str:
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
    standard("Voice Channel Region","region")
    standard("Rules Channel","rules_channel")
    standard_asset("Invite Splash Picture","splash")
    if different("verification_level"):
        embed.add_field(name="Verification Level:",value=f"{str(before.verification_level).capitalize()} -> {str(after.verification_level).capitalize()}",inline=False)
        pass

    return embed
    pass

def assemble_logging_embed(type : str, significance : discord.Colour, member : Union[discord.Member,discord.User], actor : discord.Member, message : discord.Message = None, reason : str = None, extra_description : str = None) -> discord.Embed:
    embed = discord.Embed(colour=significance,title=type,description="",timestamp=datetime.now())
    if actor is not None: embed.set_footer(text=f"Issued by {actor.mention}",icon_url=actor.avatar.url)
    if member is not None: embed.set_author(name=member.name,icon_url=member.avatar.url)

    if message is not None:
        embed.description = "".join((embed.description,f"Regarding message on <t:{int(message.created_at.timestamp())}>:\n{message.clean_content}\n\n"))
        pass
    embed.description = "".join((embed.description,f"Reason: {reason}\n"))
    if extra_description is not None:
        embed.description = "".join((embed.description,extra_description))
        pass

    return embed
    pass

async def handle_event(event : Event):
    """TODO: Include Audit Log lookup"""
    log_channel_id : int = event.ACTIVE_COG.LOGGING_CHANNEL.get(event.guild.id)
    if log_channel_id is None: return # This shouldn't happen, but safety!

    if event.type & Event.MOD_MASK:
        if event.type not in (Event.MOD_BAN, Event.MOD_UNBAN):
            event_data : Event.Automod = event.data
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
            event_data : Event.Unmute = event.data
            embed = assemble_logging_embed("Unmute",Severity.HIGH,event_data["member"],event_data["actor"],None,event_data["reason"])
            pass
        elif event.type == Event.MUTE_EVENT:
            event_data : Event.Mute = event.data
            embed = assemble_logging_embed("Mute",Severity.HIGH,event_data["member"],event_data["actor"],None,event_data["reason"],f"Muted until <t:{event_data['until']}>")
            pass
        pass
    elif event.type & Event.GUILD_CHANNEL_MASK:
        if event.type == Event.GUILD_CHANNEL_CREATE: type_str = "Channel Created"
        elif event.type == Event.GUILD_CHANNEL_DELETE: type_str = "Channel Deleted"
        elif event.type == Event.GUILD_CHANNEL_UPDATE: type_str = "Channel Updated"
        
        if event.type in (Event.GUILD_CHANNEL_CREATE,Event.GUILD_CHANNEL_DELETE):
            channel : Channel = event.data["channel"]
            extra_description = channel_extra_description(event.type,channel)
            pass
        else:
            before : Channel = event.data["before"]
            after : Channel = event.data["after"]

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
        invite : discord.Invite = event.data["invite"]
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
            member : discord.Member = event.data["member"]

            type_str = "Member Joined"
            extra_description = f"{member.mention} joined the server"
            msg_member = member
            pass
        elif event.type == Event.MEMBER_LEAVE:
            member : discord.Member = event.data["member"]
            
            type_str = "Member Left"
            extra_description = f"{member.name}{member.discriminator} left the server"
            msg_member = member
            pass
        else:
            before : discord.Member = event.data["before"]
            after  : discord.Member = event.data["after" ]

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
        payload : discord.RawMessageDeleteEvent = event.data["payload"]
        channel : discord.TextChannel = event.guild.get_channel(payload.channel_id)
        arg_message = None
        member : discord.Member = None
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
            before : discord.Role = event.data["before"]
            after  : discord.Role = event.data["after" ]

            if not role_changed(before,after): return
            embed = role_diff_embed(embed,before,after)
            pass
        else:
            role : discord.Role = event.data["role"]

            embed.add_field(name="Role:",value=role.mention if event.type == Event.ROLE_CREATE else role.name,inline=False)
            embed.add_field(name="Colour:",value=f"{role.colour}",inline=False)
            if role.icon is not None: embed.set_image(url=role.icon.url)
            pass
        pass
    elif event.type & Event.REACTION_MOD_MASK:
        if event.type == Event.REACTION_CLEAR_ALL: type_str = "Removed All Reactions From Message"
        else: type_str = "Removed Single Emoji From Message"

        payload : Union[discord.RawReactionClearEmojiEvent, discord.RawReactionClearEvent] = event.data["payload"]
        message : discord.Message = await BOT.get_guild(int(payload.guild_id)).get_channel(int(payload.channel_id)).fetch_message(int(payload.message_id))

        embed = assemble_logging_embed(type_str,Severity.LOW,None,None,message,"Unknown")
        embed.add_field(name="Message URL: ",value=message.jump_url,inline=False)
        if event.type == Event.REACTION_CLEAR_SINGLE: embed.add_field(name="Removed Emoji: ",value=str(payload.emoji))
        pass
    elif event.type & Event.THREADS_MASK:
        if event.type == Event.THREADS_DELETE:
            thread : discord.Thread = event.data["thread"]
            
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