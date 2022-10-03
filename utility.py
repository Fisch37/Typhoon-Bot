"""
This is a schematic for how an extension of this bot should look
"""
from discord.ext.commands.errors import BadArgument, PartialEmojiConversionFailure
from loop import loop

from libs import utils, config, editor
from libs.converters import TimeConverter
import asyncio, random, logging, time, emoji as emojilib
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import *

import discord
from discord.ext import commands, tasks
from discord import app_commands

import sqlalchemy as sql, sqlalchemy.ext.asyncio as asql
from ormclasses import *
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.exc import NoResultFound

# Declare constants
CONFIG: config.Config = ...

BOT: commands.Bot = ...
WEBHOOK_POOL: utils.WebhookPool = ...
COG: commands.Cog = ...

ENGINE: asql.AsyncEngine = ...
SESSION_FACTORY: Sessionmaker = ...

UserId = int
MessageId = int
ChannelId = int
GuildId = int
RoleId = int
Timestamp = float
AvatarUrl = str
MemberName = str
ScheduledMessage = tuple[Timestamp,ChannelId,str,tuple[MemberName,AvatarUrl]]

def text2Die(text: str) -> list[tuple[int,int]]:
    interpreted: list[tuple[int,int]] = []
    for die_desc in text.split("+"): # Split dies up (E.g. 5d10+3d6 => [5d10,3d6])
        strN, strD = die_desc.split("d") # Get n and d ((n)d(d))
        n = int(strN)
        d = int(strD)
        interpreted.append((n,d)) # Append to list of all interpreted dies
        pass

    return interpreted
    pass

def durationFromString(text: str) -> int:
    hourPoint = text.find("H")
    minPoint  = text.find("M")
    secPoint = text.find("S")

    hours   = int(text[:hourPoint])           if hourPoint!=-1 else 0
    minutes = int(text[hourPoint+1:minPoint]) if minPoint !=-1 else 0
    seconds = int(text[minPoint+1:secPoint])  if secPoint !=-1 else 0

    return hours*3600 + minutes*60 + seconds
    pass

START_TIME = time.time()
def formatActivity(activity: discord.Activity):
    uptimeRaw = time.time() - START_TIME
    uptimeMin = int(uptimeRaw // 60 % 60)
    uptimeH   = int(uptimeRaw // (60**2))

    currentTime: datetime = datetime.now()

    name: str = activity.name.format(
        year=currentTime.year,
        month=currentTime.month,
        day=currentTime.day,
        hour=currentTime.hour,
        minute=currentTime.minute,

        servers=len(BOT.guilds),
        uptimeH=uptimeH,
        uptimeM=uptimeMin,
        )

    return discord.Activity(type=activity.type,name=name)

# Cog
class VoteView(discord.ui.View):
    def gen_button_callback(self, i):
        # Creates a callback for vote buttons
        # This is done in a method because of for-loop weirdness
        async def button_callback(interaction: discord.Interaction):
            self.option_votes[interaction.user.id] = i # Update user's vote
            await interaction.response.send_message("Thank you for your vote! You may override your choice at any time!",ephemeral=True)
            pass

        return button_callback
        pass

    def __init__(self,vote_duration: int,vote_options: list[str], author: discord.Member, option_ids: list[str] = None):
        super().__init__(timeout=vote_duration)
        self.vote_ends_on = datetime.utcnow().timestamp() + vote_duration
        self.option_votes: dict[int,int] = {} # Member_id: Vote_index (Will ensure every user only casts one vote)
        self.options: list[tuple[str,str]] = []
        self.author = author
        
        if option_ids is None: option_ids = [None]*len(vote_options)
        for i, (option,snowflake_id) in enumerate(zip(vote_options,option_ids)):

            if snowflake_id is None: snowflake_id = str(utils.generate_snowflake())

            button = discord.ui.Button( # Create Button obj
                style=discord.ButtonStyle.gray,
                label=option,
                row=0,
                custom_id=snowflake_id
            )
            button.callback = self.gen_button_callback(i) # Set callback
            self.add_item(button) # Add to the view

            self.options.append((option,snowflake_id))
            pass
        pass

    async def on_timeout(self):
        # Everything is handled in self.handle_process, so nothing occurs here
        pass

    @discord.ui.button(label="Withdraw vote",style=discord.ButtonStyle.blurple,row=1)
    async def withdraw_vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            self.option_votes.pop(interaction.user.id)
        except KeyError:
            await interaction.response.send_message("As you didn't cast a vote, I couldn't remove it.",ephemeral=True)
            pass
        else:
            await interaction.response.send_message("Your vote was reset! You are now officially neutral!",ephemeral=True)
            pass
        pass

    @discord.ui.button(label="End vote prematurely",style=discord.ButtonStyle.green,row=1)
    async def stop_vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.author != interaction.user:
            await interaction.response.send_message("You did not start this vote, therefore you cannot end it",ephemeral=True)
            return
            pass

        view = discord.ui.View(timeout=10)
        confirm_button = discord.ui.Button(
            style=discord.ButtonStyle.green,
            label="Confirm premature finish"
        )
        async def confirm(cinteraction: discord.Interaction):
            await cinteraction.response.defer()
            self.stop()
            await interaction.followup.send(content="Vote was ended prematurely.",ephemeral=True)
            pass
        confirm_button.callback = confirm

        view.add_item(confirm_button)
        await interaction.response.send_message("Please press the button to confirm the action (and be quick)",view=view,ephemeral=True)
        pass

    async def handle_process(self):
        ended_regularly = await self.wait()
        await self.message.edit(view=None)

        vote_count: list[int] = [0]*len(self.options)
        for voted_option in self.option_votes.values():
            vote_count[voted_option] += 1
            pass
        total_votes = sum(vote_count)

        if total_votes > 0:
            result_lines = []
            for (option_name, _), votes in zip(self.options,vote_count):
                result_lines.append(f"{option_name}: {votes} votes ({(100*votes/total_votes):.2f}%)")
                pass
            result_string = "\n\t".join(result_lines) + "\n"
            pass
        else:
            result_string = "No one participated"

        if ended_regularly:
            end_message = "Vote has ended."
            pass
        else:
            end_message = "Vote was ended prematurely."
            pass

        self.embed.set_footer(
            text=f"{end_message}\nResults:\n\t{result_string}"
        )
        await self.message.edit(embed=self.embed)

        # Removing vote from database since it is now over
        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session,self.message.guild.id)
            raw_vote = None
            for raw_vote in sql_guild.votes: # Looks for the first entry matching this message and uses it. Otherwise it results in None
                if raw_vote["message"] == (self.message.guild.id,self.message.channel.id,self.message.id): 
                    break
                pass
            if raw_vote is not None: sql_guild.votes.remove(raw_vote)
            await session.commit()
            pass
        pass

    async def set_message(self, message: discord.Message, embed: discord.Embed):
        self.message = message
        self.embed = embed

        await self.message.edit(view=self)
        pass

    def to_dict(self) -> dict:
        return {
            "votes":{
                str(member_id): vi 
                for member_id, vi in self.option_votes.items()
            },
            "options":self.options.copy(),
            "author":self.author.id,
            "vote_ends_on":self.vote_ends_on,
            "message":(self.message.guild.id,self.message.channel.id,self.message.id)
        }
        pass

    @classmethod
    async def from_dict(cls: "VoteView", src: "RawVote") -> "VoteView":
        raw_votes: dict[int, int] = {
            int(member_id): vi 
            for member_id, vi in src["votes"].items()
        } # This is mapping MemberId:vote_index
        # For some reason MySQL doesn't accept integers as JSON-object keys, which is why they are converted to strings
        raw_options: list[tuple[str,int]] = src["options"] # This is (OptionName,OptionSnowflake)
        author_id: int = src["author"]
        vote_ends_on: float = src["vote_ends_on"]
        guild_id, channel_id, message_id = src["message"]

        guild = BOT.get_guild(guild_id)
        message: discord.Message = await guild.get_channel(channel_id).fetch_message(message_id)
        author = await guild.fetch_member(author_id)

        vote_duration = vote_ends_on - datetime.utcnow().timestamp()
        
        options, option_ids = zip(*raw_options) # Unzipping


        obj: VoteView = cls(vote_duration,options,author,option_ids)
        obj.option_votes = raw_votes.copy()
        await obj.set_message(message,message.embeds[0])

        asyncio.create_task(obj.handle_process())

        return obj
        pass
    pass

async def vote_message_converter(ctx, message: str) -> int:
    try:
        converted_message_id = int(message) # Try conversion to an integer
    except ValueError: # Use converter otherwise
        message_converter = commands.MessageConverter()
        try:
            converted_message_id = (await message_converter.convert(ctx,message)).id # Convert and store id
        except commands.errors.BadArgument: # Send error message if conversion did not succeed
            await ctx.send("This does not look like a message to me... (Bad Argument)",ephemeral=True)
            return
            pass
        pass
    return converted_message_id
    pass

async def check_vote_perms(member: discord.Member, channel_id: int, guild_id: int) -> bool:
    async with SESSION_FACTORY() as session:
        result: CursorResult = await session.execute(sql.select(Guild.vote_permissions).where(Guild.id==str(guild_id)))
        vote_permissions: dict = result.scalar_one_or_none()

    if vote_permissions is None:
        return True
        pass
    else:
        # Check for role overrides first
        role_override = None
        roles = member.roles.copy()
        roles.reverse()
        for role in roles:
            role: discord.Role
            current_override = vote_permissions["role_overrides"].get(str(role.id))
            if current_override is not None:
                role_override = current_override
                break
            pass

        if role_override is not None:
            return role_override

        # Then check for channel override
        channel_override = vote_permissions["channel_overrides"].get(str(channel_id))
        if channel_override is not None:
            return channel_override

        # Then the default state
        return vote_permissions["state"]
        pass
    pass

ReactionRolesDict = dict[MessageId,dict[discord.PartialEmoji,discord.Role]]
class ReactionRoleEditor(editor.CloseEditor):
    def __init__(self, 
        author: discord.Member, 
        target_message: discord.Message, 
        reaction_roles: ReactionRolesDict, 
        *, 
        timeout: Optional[float] = 180
        ):
        super().__init__(author,timeout=timeout)

        self._target_message = target_message

        reaction_roles.setdefault(target_message.id,{})
        self._reaction_roles = reaction_roles[target_message.id]
        
        self._is_sending = False
        pass

    async def on_close(self, timed_out: bool):
        if self._is_sending:
            await self._message.delete()

            author = self._editor_author
            self.embed.set_author(
                name=f"{author.name}#{author.discriminator}",
                icon_url=author.display_avatar.url,
                url=f"https://discord.com/users/{author.id}"
            )
            self.embed.timestamp = discord.utils.utcnow()
            self.embed.title="Reaction Role Listing"
            await self._target_message.reply(embed=self.embed)
            pass
        else:
            if timed_out:
                content = "```\nThis editor timed out```"
            else:
                content = "```\nThis editor was closed```"

            await self._message.edit(content=content,embed=None,view=None)
            pass
        pass

    async def update(self):
        self.embed.clear_fields()
        self.embed.add_field(
            name="Reaction",
            value="\n".join([str(emoji) for emoji in self._reaction_roles.keys()])
                if len(self._reaction_roles) > 0 else "None"
        )
        self.embed.add_field(
            name="Role",
            value="\n".join([role.mention for role in self._reaction_roles.values()])
                if len(self._reaction_roles) > 0 else "None"
        )

        return await super().update()

    def _available_roles(self) -> tuple[discord.Role]:
        is_owner = self._target_message.author == self._target_message.guild.owner
        authority = self._target_message.author.top_role
        bot_authority = self._target_message.guild.me.top_role
        return tuple(filter(
            lambda role: 
                (is_owner or authority > role)
                and bot_authority > role
                and role not in self._reaction_roles.values()
                and role != self._target_message.guild.default_role, 
            self._target_message.guild.roles
        ))
        pass
    
    async def _get_role_select(self, _) -> discord.Role:
        available_roles = self._available_roles()
        options = [
            discord.SelectOption(label=role.name)
            for role in available_roles
        ]
        
        view = utils.get_SingleSelectView(
            "Please select a role to add as a reaction role",
            options,
            owner=self._editor_author
        )(timeout=CONFIG.EDIT_TIMEOUT)
        await self._message.edit(view=view)
        await view.wait()
        return available_roles[options.index(view.result)]
        pass

    async def _get_role_message(self, interaction: discord.Interaction) -> discord.Role:
        error_prompt = """The message you sent could not be interpreted as a role or cannot be added as a role for one of these reasons:
        ```md
        1. You did not send a role mention
        2. You do not have permissions to add that role
        3. This bot does not have permissions to add that role
        ```
        """
        ctx = await commands.Context.from_interaction(interaction)
        return await utils.wait_for_role(BOT,ctx,error_prompt)
        pass

    async def _update_sql(self):
        async with SESSION_FACTORY() as session:
            result: CursorResult = await session.execute(
                sql.select(ReactionRoles)
                .where(ReactionRoles.message_id == str(self._target_message.id))
            )
            sql_rrs = result.scalar_one_or_none()
            if sql_rrs is None:
                sql_rrs = ReactionRoles(message_id=str(self._target_message.id))
                session.add(sql_rrs)
                pass

            sql_rrs.react_roles = {str(emoji): (role.guild.id,role.id) for emoji, role in self._reaction_roles.items()}

            await session.commit()
            pass
        pass
    
    @editor.button("Add",discord.ButtonStyle.primary,row=0)
    async def add_rr(self, interaction: discord.Interaction, button):
        def same_message_check(payload: discord.RawReactionActionEvent):
            return payload.message_id == self._message.id and payload.user_id == self._editor_author.id

        reaction: discord.PartialEmoji = ...
        role: discord.Role = ...

        await interaction.response.defer()

        # Getting the reaction
        await self._message.edit(content="```\nPlease react to this message with the reaction you wish to use```")
        while True:
            payload = await BOT.wait_for(
                "raw_reaction_add",
                check=same_message_check# lambda payload: payload.message_id == self._message.id
            )
            # This is done as a raw_reaction event since a normal reaction event doesn't pass the new user who reacted, but instead all users
            # This means however that we get a PartialEmoji which is fine, but makes it impossible to check for availability
            try:
                if not payload.emoji.is_unicode_emoji():
                    emoji = await interaction.guild.fetch_emoji(payload.emoji.id)
                    if not emoji.is_usable(): 
                        raise RuntimeError
                        # This matched most closely. Not that I like it
                        pass
                    pass
            except (RuntimeError,discord.errors.NotFound):
                await interaction.followup.send(
                    "This emoji is not from this server or I can't use it. Only default emojis and emojis from the current server are supported.",
                    ephemeral=True
                )
                pass
            else:
                reaction = payload.emoji
                break
            finally:
                await self._message.clear_reaction(payload.emoji)
                pass
            pass

        # Getting the role
        await self._message.edit(content="```\nPlease choose a role```")
        if len(self._available_roles()) <= 25:
            role = await self._get_role_select(interaction)
            pass
        else:
            role = await self._get_role_message(interaction)
            pass

        self._reaction_roles[reaction] = role
        await self._update_sql()
        await self._target_message.add_reaction(reaction)
        pass

    @editor.button("Remove",discord.ButtonStyle.secondary)
    async def rem_rr(self, interaction: discord.Interaction, button):
        reaction: discord.PartialEmoji = ...

        await interaction.response.defer()
        await asyncio.gather(
            *[
                self._message.add_reaction(emoji) 
                for emoji in self._reaction_roles.keys()
            ]
        )
        # This might cause high API spikes

        payload: discord.RawReactionActionEvent = await BOT.wait_for(
            "raw_reaction_add",
            check=lambda payload: 
                payload.message_id == self._message.id
                and payload.user_id == self._editor_author.id
                and payload.emoji in self._reaction_roles.keys()
        )
        reaction = payload.emoji
        
        self._reaction_roles.pop(reaction)
        await self._update_sql()
        
        await self._target_message.clear_reaction(reaction)

        await self._message.clear_reactions()
        pass

    @editor.button("Send info",discord.ButtonStyle.green,row=4)
    async def send(self, interaction: discord.Interaction, button):
        
        await interaction.response.defer()

        self._is_sending = True
        await self.close(self._target_message.channel)
        pass
    pass

class RawVote(TypedDict):
    votes: dict[int,int]
    options: list[tuple[str,int]]   # [(name,snowflake),...]
    author: int                     # AuthorId
    vote_ends_on: float             # Unix timestamp
    message: tuple[int,int,int]     # (guild_id, channel_id, message_id)
    pass

class VoteCreationModal(discord.ui.Modal):
    vote_title = discord.ui.TextInput(
        label="Title",
        style=discord.TextStyle.short,
        placeholder="Enter the title of the vote here..."
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.long,
        placeholder="Enter the description of your vote here...",
        required=False
    )
    duration = discord.ui.TextInput(
        label="Duration",
        style=discord.TextStyle.short
    )

    def __init__(self, timeout: float=None):
        super().__init__(
            title="Create Vote message",
            timeout=timeout
        )

        self.results: dict[str,Any] = None
        pass

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            duration_secs = durationFromString(self.duration.value)
        except ValueError:
            duration_secs = None
            pass
        
        self.results = {
            "duration": duration_secs,
            "title": self.vote_title.value,
            "description": self.description.value,
            "options": []
        }

        await interaction.response.defer(ephemeral=True)
        pass

    async def wait_for_results(self):
        await self.wait()
        return self.results
        pass
    pass

class VoteEditor(editor.SendCloseEditor):
    async def prompt_change_modal(
        self, 
        interaction: discord.Interaction, 
        *,
        title: str,
        **kwargs
    ):
        modal = utils.get_SingleTextModal(
            **kwargs
        )(title=title,timeout=CONFIG.EDIT_TIMEOUT)
        await interaction.response.send_modal(modal)

        return await modal.wait_for_results()
        pass


    @editor.button("Change title",discord.ButtonStyle.primary, row=0)
    async def change_title(self, interaction: discord.Interaction, button):
        modal_interaction, new_title = await self.prompt_change_modal(
            interaction,
            title="Change title",
            label="Title",
            placeholder="Please enter the title you want to use...",
            default=self.vote_config["title"],
            max_length=256
        )

        if modal_interaction is None:
            return
        # We should have timed out anyway, so just returning is fine

        self.vote_config["title"] = new_title
        await modal_interaction.response.send_message(f"Title changed to `{new_title}`", ephemeral=True)
        pass

    @editor.button("Change description", discord.ButtonStyle.secondary, row=0)
    async def change_description(self, interaction: discord.Interaction, button):
        modal_interaction, new_description = await self.prompt_change_modal(
            interaction,
            title="Change description",
            label="Vote Description",
            style=discord.TextStyle.long,
            placeholder="Please enter the title you want to use...",
            default=self.vote_config["description"],
            max_length=4000,
            required=False
        )

        if modal_interaction is None:
            return
        # We should have timed out anyway, so just returning is fine

        self.vote_config["description"] = new_description
        await modal_interaction.response.send_message(f"Description updated", ephemeral=True)
        pass

    @editor.button("Change duration", discord.ButtonStyle.success, row=0)
    async def change_duration(self, interaction: discord.Interaction, button):
        if self.vote_config["duration"] is not None:
            old_duration_string = utils.stringFromDuration(self.vote_config["duration"])
            pass
        else:
            old_duration_string = None
            pass
        
        modal_interaction, raw_duration = await self.prompt_change_modal(
            interaction,
            title="Change duration",
            label="Vote duration",
            default=old_duration_string,
            placeholder="Enter a duration string (e.g. 1H15M30S)"
        )

        if modal_interaction is None:
            return
        # We should have timed out anyway, so just returning is fine

        try:
            new_duration = utils.durationFromString(raw_duration)
        except ValueError:
            modal_interaction.response.send_message(f"The duration you entered is invalid. Expecting format like `1H15M30S`, got: `{raw_duration}`")
            return
            pass

        self.vote_config["duration"] = new_duration
        await modal_interaction.response.send_message(f"Changed vote duration to `{raw_duration}`!", ephemeral=True)
        pass

    @editor.button("Add option",discord.ButtonStyle.success,row=1)
    async def add_option(self, interaction: discord.Interaction, button):
        modal_interaction, option_name = await self.prompt_change_modal(
            interaction,
            title="Add option",
            label="Option name",
            placeholder="Enter the name of your vote option here..."
        )

        if modal_interaction is None:
            return
        # This occurs on timeout, in which case this editor has also timed out

        self.vote_config["options"].append(option_name)

        await modal_interaction.response.send_message(f"Added option `{option_name}`", ephemeral=True)
        pass

    @editor.button("Remove option",discord.ButtonStyle.danger,row=1)
    async def rem_option(self, interaction: discord.Interaction, button):
        if len(self.vote_config["options"]) == 0:
            await interaction.response.send_message("This vote currently does not provide any options. It would be pointless to try and remove any", ephemeral=True)
            return

        view = utils.get_SingleSelectView(
            "Select a option to remove", 
            [
                discord.SelectOption(label=name) 
                for name in self.vote_config["options"]
            ],
            self.vote_config["author"]
        )(timeout=CONFIG.EDIT_TIMEOUT)
        await self._message.edit(view=view)
        await interaction.response.defer(ephemeral=True)

        if await view.wait():
            return
        # This editor will time out simultaneously to the view, therefore any closing action is unneccessary

        self.vote_config["options"].remove(view.result.label)
        pass

    def __init__(self, 
        vote_processes_dict: dict[MessageId,VoteView],
        original_interaction: discord.Interaction, 
        vote_config: dict[str,Any], 
        *args, **kwargs
    ):
        super().__init__(vote_config["author"],*args,**kwargs)

        self.vote_processes = vote_processes_dict
        self.vote_config = vote_config
        self.original_interaction = original_interaction
        pass

    async def on_send(self, channel: discord.TextChannel):
        end_timestamp = int(discord.utils.utcnow().timestamp())+self.vote_config["duration"]

        embed = self.update_embed(discord.Embed())
        embed.remove_footer()
        embed.description += f"\n\nEnds <t:{end_timestamp}:R>"

        view = VoteView(
            vote_duration=self.vote_config["duration"],
            vote_options=self.vote_config["options"],
            author=self.vote_config["author"]
        )

        vote_message = await channel.send(embed=embed)
        await view.set_message(vote_message,embed)
        # Doing this concurrently creates a RACE CONDITION
        self.vote_processes[vote_message.id] = view
        asyncio.create_task(view.handle_process())

        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session,channel.guild.id)
            sql_guild.votes.append(view.to_dict())

            await session.commit()
            pass
        
        await self._message.edit(content="```\nThis editor has finished```",embed=None,view=None)
        pass

    async def on_close(self, timed_out: bool):
        await self._message.edit(content="```\nThis editor was closed```",embed=None)
        pass

    async def send_check(self, interaction: discord.Interaction) -> bool:
        return not any([v is None for v in self.vote_config.values()])
        pass

    async def update(self):
        self.update_embed(self.embed)

        self.content = "```\n"
        
        option_num = len(self.vote_config["options"])
        if option_num < 2:
            self.content += f"Too few arguments for vote. Minimum of two required, _{option_num}_ found.\n"
            pass
        elif option_num == CONFIG.MAX_VOTE_OPTIONS:
            self.content += f"Option limit of {CONFIG.MAX_VOTE_OPTIONS} reached. No more options can be added.\n"
            pass
        
        if self.vote_config["duration"] is None:
            self.content += f"No vote duration set. The last value you entered might have been invalid.\n"
            pass
        self.content += "```"

        return await super().update()

    
    def update_embed(self, embed: discord.Embed) -> discord.Embed:
        embed.title = self.vote_config["title"]
        embed.description = self.vote_config["description"]
        embed.colour = discord.Colour.green()
        embed.timestamp = discord.utils.utcnow()

        embed.set_author(
            name=self.vote_config["author"].name,
            icon_url=self.vote_config["author"].display_avatar.url
        ).set_footer(
            text="\n".join(["Options:"] + self.vote_config["options"])
        )

        return embed
        pass
    pass

class Utility(commands.Cog):
    """A set of useful commands"""
    def __init__(self):
        super().__init__()
        pass

    async def cog_load(self):
        # Run once
        self.schedule_msg_collector.start()
        self.vote_collector.start()
        self.reaction_role_collector.start()
        # Run in loop
        self.schedule_msg_worker.start()
        self.activity_changer.start()
        self.cleanVoteBuffer.start()
        self.vote_saver.start()
        
        # This needs to be done manually because of https://github.com/Rapptz/discord.py/issues/7823
        self.reaction_role_manager = app_commands.ContextMenu(
            name="Reaction Roles",
            callback = self.reaction_role_manager
        )
        BOT.tree.add_command(self.reaction_role_manager)
        pass

    async def cog_unload(self):
        self.schedule_msg_worker.stop()
        self.activity_changer.cancel()
        self.vote_saver.stop()
        
        await asyncio.gather(
            self.vote_saver()
        )
        pass


    VOTE_PROCESSES: dict[MessageId,VoteView]                                                       = {}
    SCHEDULED_MSGS: dict[GuildId,dict[str,ScheduledMessage]]                                       = {}
    REACTION_ROLES: ReactionRolesDict                                                              = {}

    @app_commands.command(name="roll",description="Roll a dice!")
    @app_commands.describe(die="The dice to roll. (e.g. 10d8+5d6)", sort="Set to true, to sort the results")
    async def roll_dice(
        self, 
        interaction: discord.Interaction, 
        die: str,
        sort: bool = False
        ):
        if die.count("+") > CONFIG.MAX_ROLL_COMBOS: # Check if the command has more than the maximum amount of die types.
            await interaction.response.send_message("Oh no! I'm sorry, that's just to complicated for me. Try to limit your excitement to {} combinations".format(CONFIG.MAX_ROLL_COMBOS))
            return
            pass

        try:
            interpreted_dies = text2Die(die) # Convert text argument into usable list of n, d tuples
        except ValueError: # Send error message and stop if the die argument was invalid
            await interaction.response.send_message("Oops, it seems you haven't given your dies in the right format.\nCheck `/help roll` for a description",ephemeral=True)
            return
            pass

        if sum([n for n, _ in interpreted_dies]) > CONFIG.MAX_ROLLS: # Check that the command doesn't have to call randint to many times (because performance)
            await interaction.response.send_message("That's... a lot. Sorry, you gave me too many rolls; try to limit your rolls to {}\n(Note that this number is added for every roll)".format(CONFIG.MAX_ROLLS),ephemeral=True)
            return
        if any([d>CONFIG.MAX_ROLL_D for _, d in interpreted_dies]): # Check that no d argument is greater than the maximum amount saved in config.cfg
            await interaction.response.send_message("Big numbers... Too big numbers, it turns out; please limit your die-size to {}".format(CONFIG.MAX_ROLL_D),ephemeral=True)
            return
        if any([d<1 for _, d in interpreted_dies]): # Check that no die is smaller than 1 because that wouldn't make any sense.
            await interaction.response.send_message("It really doesn't make sense to roll a d0 or lower... Please don't do that",ephemeral=True)
            return
            pass

        def doTheRoll() -> list[list[int]]: # Actually do the roll (aka call randint a bunch of times)
            allRolls = []
            for n, d in interpreted_dies:
                rolls = [random.randint(1,d) for i in range(n)]
                if sort: rolls.sort(reverse=True)
                allRolls.append(rolls)
                pass

            return allRolls
            pass

        allRolls = await asyncio.get_event_loop().run_in_executor(None,doTheRoll) # Roll in executor to improve performance

        response = ""
        for i in range(len(interpreted_dies)): # Assemble output message
            n, d = interpreted_dies[i]

            response = "".join((response,f"**{n}d{d}**: `"))
            rollString = ", ".join([str(roll) for roll in allRolls[i]])
            response = "".join((response,rollString,"`",f" Sum: {sum(allRolls[i])}","\n"))
            pass

        await interaction.response.send_message(response) # Send off
        pass
    
    @app_commands.command(name="set_announcement",description="Set a channel to receive Typhoon announcements in")
    @utils.perm_message_check("Now, hold on! I cannot let you do this (No Permission)",manage_guild=True)
    async def set_announcement_override(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not isinstance(channel,discord.TextChannel):
            await interaction.response.send_message("Please only use Text Channels as arguments. Otherwise it just won't work",ephemeral=True)
            return
            pass

        async with SESSION_FACTORY() as session:
            await session.execute(
                sql.update(Guild)\
                .values(announcement_override=str(channel.id))\
                .where(Guild.id==str(interaction.guild_id))) # Set new override
            await session.commit() # Commit & Close
            pass

        await interaction.response.send_message(f"Override set. Bot Announcements will now be sent to {channel.mention}",ephemeral=True)
        pass
    
    # Voting
    async def vote_creation(self, interaction: discord.Interaction):
        vote_config = {
            "author": interaction.user,
            "duration": ...,
            "title": ...,
            "description": ...,
            "options": []
        }

        base_modal = VoteCreationModal(timeout=CONFIG.EDIT_TIMEOUT)
        await interaction.response.send_modal(base_modal)
        vote_config.update(await base_modal.wait_for_results())

        editor = VoteEditor(
            self.VOTE_PROCESSES,
            interaction,
            vote_config,
            timeout=CONFIG.EDIT_TIMEOUT
        )

        embed = editor.update_embed(discord.Embed())
        editor_message = await interaction.followup.send(embed=embed,wait=True,ephemeral=True)
        editor.set_message(editor_message)
        
        await editor.update()
        pass

    vote = app_commands.Group(name="vote", description="Voting, you know? Ask a question, give some answers, and wait.",
    guild_only=True)

    @vote.command(name="create",description="Create a new vote sent in an embed format with buttons as options.")
    async def create_vote(
        self, 
        interaction: discord.Interaction
        ):
        await self.vote_creation(interaction)
        pass
    
    @vote.command(name="cast",description="Cast a vote into an existing poll")
    @app_commands.describe(message="The message the vote is associated with. This can be a message id or a URL.",
    option="The number of what you want to vote for (left->right). Leave empty to reset your vote.")
    async def cast_vote(self, interaction: discord.Interaction, message: str,option: int = None):
        ctx = await commands.Context.from_interaction(interaction)
        converted_message_id = await vote_message_converter(ctx,message)
        if converted_message_id is None: return # Handling was already done in this case

        if option is not None and option < 1: # Check that option is not index format or similar (only applies if option is set)
            await interaction.response.send_message("The entered option number should range from 1 - the amount of options. 0 or lower is invalid.",ephemeral=True)
            return

        vote_view = self.VOTE_PROCESSES.get(converted_message_id) # Get the right vote
        if vote_view is None: # Send error if it couldn't find the vote
            await interaction.response.send_message("I looked at this a long while and I must say, I have no idea what you're talking about... (Message not a vote)",ephemeral=True)
            return
            pass

        channel_perms = vote_view.message.channel.permissions_for(interaction.user)
        if interaction.guild_id != vote_view.author.guild.id and channel_perms.is_superset(discord.Permissions(read_messages=True,read_message_history=True)): # Check if user has access to that channel (restricts to same guild vote casting)
            await interaction.response.send_message("I looked at this a long while and I must say, I have no idea what you're talking about... (Message not a vote)",ephemeral=True) # Send same error as couldn't find because Security (sparkles) [still not immune to timing attacks]
            return
            pass

        if option is not None and option > len(vote_view.options): # Check that option actually exists
            await interaction.response.send_message("Hmmm... That's not a existing option... (Option number too large)",ephemeral=True)
            return
            pass

        # Cast the vote
        if option is not None:
            vote_view.option_votes[interaction.user.id] = option - 1 # Set the vote (-1 to convert to index format)
            await interaction.response.send_message("Thank you for your vote! You may override your choice at any time!",ephemeral=True)
            pass
        else:
            try:
                vote_view.option_votes.pop(interaction.user.id)
                pass
            except KeyError:
                await interaction.response.send_message("As you didn't vote yet, your vote could not be reset.",ephemeral=True)
                pass
            else:
                await interaction.response.send_message("Your vote has been reset!",ephemeral=True)
                pass
            pass
        pass

    @vote.command(name="finish",description="End a vote prematurely")
    @app_commands.describe(message="The message the vote is associated with. This can be a message id or a URL")
    async def finish_vote(self, interaction: discord.Interaction, message: str):
        ctx = await commands.Context.from_interaction(interaction)
        converted_message_id = await vote_message_converter(ctx,message)
        if converted_message_id is None: return # If return is None an error was already handled.

        vote_view = self.VOTE_PROCESSES.get(converted_message_id)
        if vote_view is None:
            await interaction.response.send_message("These are not the votes you are looking for... I hope, because I couldn't find them. (Not a vote message)",ephemeral=True)
            return
            pass

        if vote_view.author != interaction.user:
            await interaction.response.send_message("Now hang on a minute! You didn't even start that vote! How do you imagine you could end it? (No Permission)", ephemeral=True)
            return
            pass

        vote_view.stop()
        await interaction.response.send_message("Vote was ended prematurely. I hope that wasn't an accident", ephemeral=True)
        pass
    
    @tasks.loop(minutes=5)
    async def cleanVoteBuffer(self):
        """Removes all expired votes from the dictionary"""
        for expired_item in filter(lambda item: item[1].is_finished(),self.VOTE_PROCESSES.items()):
            self.VOTE_PROCESSES.pop(expired_item[0])
            pass
        pass
    
    @tasks.loop(minutes=5)
    async def vote_saver(self):
        guilded_votes: dict[GuildId,list] = {}
        for vote in self.VOTE_PROCESSES.values():
            guild_id = vote.message.guild.id
            guilded_votes.setdefault(guild_id,[])
            guilded_votes[guild_id].append(vote.to_dict())
            pass

        async with SESSION_FACTORY() as session:
            async def vote_commit_task(guild_id: GuildId, votes: list):
                sql_guild = await utils.get_guild(session,guild_id)
                sql_guild.votes = votes
                pass
            
            await asyncio.gather(*[
                vote_commit_task(*item) 
                for item in guilded_votes.items()
            ])
            await session.commit()
            pass
        pass
    
    # Reaction Roles

    @app_commands.default_permissions(manage_roles=True,manage_messages=True)
    async def reaction_role_manager(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=False)
        # Not doing this whole interaction ephemerally because then we can't use reactions later

        embed = discord.Embed(
            colour=discord.Colour.orange(),
            title=f"Reaction Roles for message from {message.author.display_name}",
            timestamp=datetime.now()
        )

        editor = ReactionRoleEditor(interaction.user,message,self.REACTION_ROLES)
        message = await interaction.followup.send("```\nThe editor should appear in a moment, please wait```",embed=embed)
        editor.set_message(message)
        await editor.update()
        pass


    @commands.Cog.listener("on_raw_reaction_add")
    @commands.Cog.listener("on_raw_reaction_remove")
    async def reaction_role_listener(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == BOT.user.id: return # Do nothing if reaction is outside of guild or user is this bot (to prevent the bot having 50 million roles and appearing in them as well)

        message_id = payload.message_id
        emoji      = payload.emoji
        
        guild = BOT.get_guild(payload.guild_id)
        channel = guild.get_channel_or_thread(payload.channel_id)
        
        try:
            reaction_roles = self.REACTION_ROLES[message_id]
            role = reaction_roles[(emoji)]
            pass
        except KeyError: # Stop if the emoji is not a reaction-role emoji
            return 
            pass
        
        if payload.event_type == "REACTION_ADD":
            try:
                await payload.member.add_roles(role,reason="Reaction Role Add") # Add the reaction role
                pass
            except discord.errors.Forbidden:
                logging.debug(f"No Role add permission for {payload.member.id} on {payload.member.guild.id}")
                await channel.send(f"Oops! It seems I don't have permission to add roles to {payload.member.mention}. Make sure this bot's role is above any user role.")
                pass
            pass
        else:
            guild = BOT.get_guild(payload.guild_id)
            member = await guild.fetch_member(payload.user_id)
            try:
                await member.remove_roles(role,reason="Reaction Role Remove") # Remove the reaction role
                pass
            except discord.errors.Forbidden:
                logging.debug(f"No Role remove permission for {payload.member.id} on {payload.member.guild.id}")
                await channel.send(f"Oops! It seems I don't have permission to remove roles from {payload.member.mention}. Make sure this bot's role is above any user role.")
                pass
        pass

    @tasks.loop(count=1)
    async def reaction_role_collector(self):
        """Collects all the reaction roles saved in the database and stores them in RAM"""
        await BOT.wait_until_ready()

        async with SESSION_FACTORY() as session:
            result: CursorResult = await session.execute(sql.select(ReactionRoles))
            all_reactionroles: list[ReactionRoles] = result.scalars().all() # Get all reaction role objects
            pass

        for reaction_roles in all_reactionroles:
            message_id = int(reaction_roles.message_id)
            react_roles: ReactionRolesDict = reaction_roles.react_roles

            # This could have been done in a dictionary comprehension, but, seeing as I do in fact have a soul and would like to keep my sanity, it wasn't done here.
            # Although if you really need it: {discord.PartialEmoji.from_str(emoji_str):BOT.get_guild(guild_id).get_role(role_id) for emoji_str, (guild_id, role_id) in react_roles}
            # I told you it would be horrible
            converted_react_roles = {}
            for emoji_str, (guild_id, role_id) in react_roles.items():

                guild = BOT.get_guild(guild_id)
                role = guild.get_role(role_id)
                partial_emoji = discord.PartialEmoji.from_str(emoji_str)

                converted_react_roles[partial_emoji] = role
                pass

            self.REACTION_ROLES[message_id] = converted_react_roles
            pass
        pass

    # Message Webhooks

    async def getTimeZone(self, guild_id: int):
        
        async with SESSION_FACTORY() as session:
            result: CursorResult = await session.execute(sql.select(Guild.timezone).where(Guild.id == str(guild_id)))
            timezone_text = result.scalar_one_or_none()
            pass

        if timezone_text is None:
            timezone_text = "0"
            pass
        try:
            utcoffset = int(timezone_text)
        except ValueError:
            tz = ZoneInfo(timezone_text)
            pass
        else:
            tz = timezone(timedelta(hours=utcoffset))
            pass

        return tz
        pass

    @app_commands.command(name="schedule_msg",description="Schedule a message to be sent later")
    async def schedule_msg(self, interaction: discord.Interaction, time: str, content: str):
        tz = await self.getTimeZone(interaction.guild_id)

        time_converter = TimeConverter()
        ctx = await commands.Context.from_interaction(interaction)
        try:
            timeObj = await time_converter.convert(ctx,time,tz=tz) # Convert argument into a datetime object
            pass
        except commands.errors.BadArgument: # Give custom error message if the conversion failed
            await interaction.response.send_message("The time you gave was not formatted correctly. Make sure it fits these requirements:\n> Year-month-day pattern\n> One of these seperators: -./: <SPACE key> or no seperator\n> The time part is seperated by a semi-colon (;)\n> The time part has ':' as a seperator\n> The time you entered exists",ephemeral=True)
            return
            pass

        if timeObj <= datetime.now(timezone.utc):
            await interaction.response.send_message("As I don't have a time machine, this will be sadly impossible (Time is in the past)",ephemeral=True)
            return
            pass


        scheduled_msg = (
            timeObj.timestamp(),
            interaction.channel_id,
            content,
            (
                interaction.user.display_name,
                interaction.user.avatar.url
            )
        ) # Create scheduled_msg object

        async with SESSION_FACTORY() as session:
            result: CursorResult = await session.execute(sql.select(ScheduledMessages).where(ScheduledMessages.guild_id == str(interaction.guild_id)))
            scheduled_obj: ScheduledMessages = result.scalar_one_or_none()
            if scheduled_obj is None:
                scheduled_obj = ScheduledMessages(guild_id=str(interaction.guild_id),schedules=[])
                session.add(scheduled_obj)
                pass
            msg_snowflake = str(utils.generate_snowflake())

            self.SCHEDULED_MSGS.setdefault(interaction.guild_id,{}) # Create an entry in the SCHEDULED_MSGS RAM dict for this guild if there wasn't one already

            scheduled_obj.schedules[msg_snowflake] = scheduled_msg # Add new scheduled Message to Database
            self.SCHEDULED_MSGS[interaction.guild_id][msg_snowflake] = scheduled_msg # Add scheduled msg to RAM
            
            await session.commit()
            pass

        await interaction.response.send_message(
            "".join(("Scheduled following message to be sent on <t:{}>:\n".format(int(timeObj.timestamp())),content)),
            ephemeral=True
        )
        pass

    @app_commands.command(name="send_anon",description="Send a message anonymously (no one will know who did it)")
    async def send_anon(self, interaction: discord.Interaction, message: str):
        webhook = await WEBHOOK_POOL.get(interaction.channel,reason="/send_anon required Webhook") # Retrieve Webhook from pool
        
        await webhook.send(
            message,
            username="Anonymous User",
            avatar_url=interaction.guild.me.display_avatar.url
        ) # Send message
        await interaction.response.send_message("Your message has been sent! (As you no doubt see)",ephemeral=True) # Send confirmation to prevent "interaction failed" error
        pass

    

    @tasks.loop(count=1)
    async def vote_collector(self):
        await BOT.wait_until_ready()

        raw_votes: list[dict] = []
        async with SESSION_FACTORY() as session:
            for sql_guild in (await session.execute(sql.select(Guild))).scalars():
                raw_votes.extend(sql_guild.votes)
                pass
            pass
        # Extracting all votes into a list to reduce session-lifetime

        for raw_vote in raw_votes:
            vote_view = await VoteView.from_dict(raw_vote)
            self.VOTE_PROCESSES[vote_view.message.id] = vote_view
            pass
        pass

    """
    But why didn't you create a type alias for the scheduled_msg?! You're repeating yourself so much!

    Becauuuuuuuse my IDE wouldn't show me what the scheduled_msg is made up of and only that it is one, which is not really helpful
    (in hindsight I was wrong about that, but I'm lazy and also I feel as soon as I touch my code it just falls apart)
    """
    @tasks.loop(count=1) # Rapptz told me not to use on_ready (well, he told everyone)
    async def schedule_msg_collector(self):
        """Collects scheduled messages from the SQL Server
        Can be a little slow, just shouldn't cause much overhead on the server"""
        await BOT.wait_until_ready()

        async with SESSION_FACTORY() as session:
            async def add_scheduled_messages(guild: discord.Guild):
                result: CursorResult = await session.execute(sql.select(ScheduledMessages).where(ScheduledMessages.guild_id==str(guild.id)))

                try:
                    scheduled_msgs: dict[str,ScheduledMessage] = result.scalar_one().schedules
                except NoResultFound: # When there is no entry for this guild, skip this one
                    return
                    pass

                self.SCHEDULED_MSGS.setdefault(guild.id,{})
                self.SCHEDULED_MSGS[guild.id].update(scheduled_msgs)
                # Using setdefault stuff here since it is not quite certain when this will be called.
                # A late call might lead to overwriting newly added message schedules
                pass

            await asyncio.gather(*[
                add_scheduled_messages(guild)
                for guild in BOT.guilds
            ])
            pass
        pass

    @tasks.loop(seconds=30)
    async def schedule_msg_worker(self):
        """Sends all scheduled messages that are due
        1. Assemble tasks that will return all messages that need be scheduled
        2. Gather all due messages
        3. Create task for each message
        4. Send all the messages
        """

        
        currentTS = datetime.now(timezone.utc).timestamp()
        loop = asyncio.get_event_loop()

        async def find_due_messages(guild_id: GuildId) -> tuple[GuildId,list[tuple[Timestamp,ChannelId,str,tuple[MemberName,AvatarUrl]]]]:
            due_messages = await loop.run_in_executor(
                None,
                filter,

                lambda item: item[1][0] <= currentTS,
                self.SCHEDULED_MSGS[guild_id].items()
            )
            # Filter through all scheduled messages to find those that are due (Uses executor for higher speed)
            return guild_id, {
                snowflake: scheduled_msg 
                for snowflake, scheduled_msg in due_messages
            }
            pass

        due_messages: list[tuple[GuildId,dict[str,ScheduledMessage]]] = await asyncio.gather(*[find_due_messages(guild_id) for guild_id in self.SCHEDULED_MSGS.keys()])
        if sum([len(messages) for _, messages in due_messages]) == 0: return # Skip all the rest if there aren't any due messages
        

        async def send_due_message(
            guild_id: GuildId, 
            snowflake: str,
            scheduled_msg: ScheduledMessage
        ):
            # Set up some variables to make the code easier to read
            channel_id = scheduled_msg[1]
            content = scheduled_msg[2]
            author_name = scheduled_msg[3][0]
            avatar_url = scheduled_msg[3][1]

            channel = await BOT.fetch_channel(channel_id) # Get the channel object neccessary to get the Webhook
            webhook = await WEBHOOK_POOL.get(channel,reason="Scheduled Message required a new Webhook") # Get the Webhook for this channel (or create a new one)

            await webhook.send(content,username=author_name,avatar_url=avatar_url) # Send the message

            self.SCHEDULED_MSGS[guild_id].pop(snowflake) # Remove the message from RAM
            
            sql_obj = sql_msgs.get(guild_id) # Get the ScheduledMessage SQL Object for this guild or None if not found
            if sql_obj is None: return # Do nothing if not found
            try:
                sql_obj.schedules.pop(snowflake) # Remove this message from the SQL Table
                pass
            except KeyError: # Ignore if message was not in SQL Table
                pass
            pass

        async with SESSION_FACTORY() as session:
            # Get all SQL Database entries for scheduled messages
            required_guilds = [str(guild_id) for guild_id, _ in due_messages]
            result: CursorResult = (await session.execute(sql.select(ScheduledMessages).where(ScheduledMessages.guild_id.in_(required_guilds))))
            sql_msgs: dict[GuildId,ScheduledMessages] = {int(scalar.guild_id):scalar for scalar in result.scalars()}

            await asyncio.gather(*[
                send_due_message(guild_id, snowflake,scheduled_msg)

                for guild_id, messages in due_messages
                for snowflake, scheduled_msg in messages.items()
            ]) # Send all the due messages
            # We need to keep the session open here, because send_due_message accesses the SQL objects

            await session.commit()
            pass
        pass
    
    
    @tasks.loop(count=1)
    async def activity_changer(self):
        import activities, importlib
        
        await BOT.wait_until_ready()

        if BOT.IS_TESTING:
            await BOT.change_presence(activity=discord.Activity(type = discord.ActivityType.listening,name="to nobody as I'm currently in Testing Mode"),status=discord.Status.do_not_disturb)
            return
        
        while True:
            importlib.reload(activities)
            await BOT.change_presence(activity=formatActivity(random.choice(activities.ACTIVITIES)))

            await asyncio.sleep(CONFIG.CHANGE_ACTIVITY_INTERVAL)
            pass
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

    # Add cog to system
    COG = Utility()
    await bot.add_cog(COG)
    logging.info("Added utility extension")
    pass

async def teardown(bot: commands.Bot):
    await bot.remove_cog("Utility")
    
    raw_votes: dict[GuildId,list[dict]] = {}
    for vote_view in COG.VOTE_PROCESSES.values():
        vote_view: VoteView
        guild_id = vote_view.message.guild.id
        vote_view.stop()
        raw_votes.setdefault(guild_id,[])
        raw_votes[guild_id].append(vote_view.to_dict())
        pass
    pass