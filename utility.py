"""
This is a schematic for how an extension of this bot should look
"""
from discord.ext.commands.errors import BadArgument, PartialEmojiConversionFailure
from loop import loop

from libs import utils, config
from libs.converters import TimeConverter
import asyncio, random, logging, time, emoji as emojilib
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import *

import discord
from discord.ext import commands, tasks
from discord.ext.commands.converter import Option

import sqlalchemy as sql, sqlalchemy.ext.asyncio as asql
from ormclasses import *
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.exc import NoResultFound

# Declare constants
CONFIG : config.Config = ...

BOT : commands.Bot = ...
WEBHOOK_POOL : utils.WebhookPool = ...
COG : commands.Cog = ...

ENGINE : asql.AsyncEngine = ...
SESSION_FACTORY : orm.sessionmaker = ...

# Cog

def text2Die(text : str) -> list[tuple[int,int]]:
    interpreted : list[tuple[int,int]] = []
    for die_desc in text.split("+"): # Split dies up (E.g. 5d10+3d6 => [5d10,3d6])
        strN, strD = die_desc.split("d") # Get n and d ((n)d(d))
        n = int(strN)
        d = int(strD)
        interpreted.append((n,d)) # Append to list of all interpreted dies
        pass

    return interpreted
    pass

def durationFromString(text : str) -> int:
    hourPoint = text.find("H")
    minPoint  = text.find("M")
    secPoint = text.find("S")

    hours   = int(text[:hourPoint])           if hourPoint!=-1 else 0
    minutes = int(text[hourPoint+1:minPoint]) if minPoint !=-1 else 0
    seconds = int(text[minPoint+1:secPoint])  if secPoint !=-1 else 0

    return hours*3600 + minutes*60 + seconds
    pass

START_TIME = time.time()
def formatActivity(activity : discord.Activity):
    uptimeRaw = time.time() - START_TIME
    uptimeMin = int(uptimeRaw // 60 % 60)
    uptimeH   = int(uptimeRaw // (60**2))

    currentTime : datetime = datetime.now()

    name : str = activity.name.format(
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

class VoteView(discord.ui.View):
    def __init__(self,vote_duration : int,vote_options : list[str], author : discord.Member, option_ids : list[int] = None):
        super().__init__(timeout=vote_duration)
        self.vote_ends_on = datetime.utcnow().timestamp() + vote_duration
        self.option_votes : dict[int,int] = {} # Member_id : Vote_index (Will ensure every user only casts one vote)
        self.options : list[tuple[str,int]] = []
        self.author = author
        
        if option_ids is None: option_ids = [None]*len(vote_options)
        for i, (option,snowflake_id) in enumerate(zip(vote_options,option_ids)):
            async def button_callback(interaction : discord.Interaction):
                self.option_votes[interaction.user.id] = i # Update user's vote
                await interaction.response.send_message("Thank you for your vote! You may override your choice at any time!",ephemeral=True)
                pass

            if snowflake_id is None: snowflake_id = utils.generate_snowflake()

            button = discord.ui.Button( # Create Button obj
                style=discord.ButtonStyle.gray,
                label=option,
                row=0,
                custom_id=snowflake_id
            )
            button.callback = button_callback # Set callback
            self.add_item(button) # Add to the view

            self.options.append((option,snowflake_id))
            pass
        pass

    async def on_timeout(self):
        # Everything is handled in self.handle_process, so nothing occurs here
        pass

    @discord.ui.button(label="Withdraw vote",style=discord.ButtonStyle.blurple,row=1)
    async def withdraw_vote(self, button : discord.ui.Button, interaction : discord.Interaction):
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
    async def stop_vote(self, button : discord.ui.Button, interaction : discord.Interaction):
        if self.author != interaction.user:
            await interaction.response.send_message("You did not start this vote, therefore you cannot end it",ephemeral=True)
            return
            pass

        view = discord.ui.View(timeout=10)
        confirm_button = discord.ui.Button(
            style=discord.ButtonStyle.green,
            label="Confirm premature finish"
        )
        async def confirm(cinteraction : discord.Interaction):
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

        vote_count : list[int] = [0]*len(self.options)
        for voted_option in self.option_votes.values():
            vote_count[voted_option] += 1
            pass
        total_votes = sum(vote_count)

        resultString = ""
        if total_votes > 0:
            for i in range(len(self.options)):
                resultString = "".join((resultString,self.options[i][0],": ", str(vote_count[i]),"votes (",str(round(vote_count[i]/total_votes,2)),"%)\n\t"))
                pass
            pass
        else:
            resultString = "No one participated"

        self.embed.set_footer(text="".join(("Vote has ended." if ended_regularly else "Vote was ended prematurely." ,"\nResults:\n\t",resultString)))
        await self.message.edit(embed=self.embed)

        # Removing vote from database since it is now over
        session = SESSION_FACTORY()
        try:
            sql_guild = await utils.get_guild(session,self.message.guild.id)
            raw_vote = None
            for raw_vote in sql_guild.votes: # Looks for the first entry matching this message and uses it. Otherwise it results in None
                if raw_vote["message"] == (self.message.guild.id,self.message.channel.id,self.message.id): 
                    break
                pass
            if raw_vote is not None: sql_guild.votes.remove(raw_vote)
            await session.commit()
        finally:
            await session.close()
        pass

    async def set_message(self, message : discord.Message, embed : discord.Embed):
        self.message = message
        self.embed = embed

        await self.message.edit(view=self)
        pass

    def to_dict(self) -> dict:
        return {
            "votes":self.option_votes.copy(),
            "options":self.options.copy(),
            "author":self.author.id,
            "vote_ends_on":self.vote_ends_on,
            "message":(self.message.guild.id,self.message.channel.id,self.message.id)
        }
        pass

    async def from_dict(cls : "VoteView", src : dict) -> "VoteView":
        raw_votes : dict[int, int] = src["votes"] # This is mapping MemberId:vote_index
        raw_options : list[tuple[str,int]] = src["options"] # This is (OptionName,OptionSnowflake)
        author_id : int = src["author"]
        vote_ends_on : float = src["vote_ends_on"]
        guild_id, channel_id, message_id = src["message"]

        guild = BOT.get_guild(guild_id)
        message : discord.Message = await guild.get_channel(channel_id).fetch_message()
        author = await guild.fetch_member(author_id)

        vote_duration = vote_ends_on - datetime.utcnow().timestamp()
        
        options, option_ids = zip(*raw_options) # Unzipping


        obj : VoteView = cls(vote_duration,options,author,option_ids)
        obj.option_votes = raw_votes.copy()
        await obj.set_message(message,message.embeds[0])

        asyncio.create_task(obj.handle_process())
        pass
    pass

async def vote_message_converter(ctx, message : str) -> int:
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

async def check_vote_perms(member : discord.Member, channel_id : int, guild_id : int) -> bool:
    session : asql.AsyncSession = SESSION_FACTORY()
    try:
        result : CursorResult = await session.execute(sql.select(Guild.vote_permissions).where(Guild.id==str(guild_id)))
        vote_permissions : dict = result.scalar_one_or_none()
    finally:
        await session.close()

    if vote_permissions is None:
        return True
        pass
    else:
        # Check for role overrides first
        role_override = None
        roles = member.roles.copy()
        roles.reverse()
        for role in roles:
            role : discord.Role
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

MessageId = int
ChannelId = int
GuildId = int
RoleId = int
Timestamp = float
AvatarUrl = str
MemberName = str

ReactionRoleDict = dict[str,tuple[GuildId,RoleId]] # Added for thinking purposes (How it will be represented in SQL)

class Utility(commands.Cog):
    """A set of useful commands"""
    def __init__(self):
        super().__init__()

        # Run once
        self.schedule_msg_collector.start()
        self.vote_collector.start()
        # Run in loop
        self.schedule_msg_worker.start()
        self.activity_changer.start()
        pass

    def cog_unload(self):
        self.schedule_msg_worker.stop()
        self.activity_changer.cancel()

        super().cog_unload()
        pass


    VOTE_PROCESSES : dict[int,VoteView]                                                             = {}
    SCHEDULED_MSGS : dict[GuildId,list[tuple[Timestamp,ChannelId,str,tuple[MemberName,AvatarUrl]]]] = {}
    REACTION_ROLES : dict[MessageId,dict[discord.PartialEmoji,discord.Role]]                        = {}

    @commands.command(name="roll",brief="Roll a dice!",description="Roll a dice! The format for a roll should be (numberofrolls)d(maxnumber)+(numberofrolls)d(maxnumber)...")
    async def roll_dice(
        self, 
        ctx : commands.Context, 
        die : str = Option(description="The dice to roll. (E.g. 10d8+5d6)"),
        sort : bool = Option(False,description="Set to true, to sort the results")
        ):
        if die.count("+") > CONFIG.MAX_ROLL_COMBOS: # Check if the command has more than the maximum amount of die types.
            await ctx.send("Oh no! I'm sorry, that's just to complicated for me. Try to limit your excitement to {} combinations".format(CONFIG.MAX_ROLL_COMBOS))
            return
            pass

        try:
            interpreted_dies = text2Die(die) # Convert text argument into usable list of n, d tuples
        except ValueError: # Send error message and stop if the die argument was invalid
            await ctx.send("Oops, it seems you haven't given your dies in the right format.\nCheck `/help roll` for a description",ephemeral=True)
            return
            pass

        if sum([n for n, _ in interpreted_dies]) > CONFIG.MAX_ROLLS: # Check that the command doesn't have to call randint to many times (because performance)
            await ctx.send("That's... a lot. Sorry, you gave me too many rolls; try to limit your rolls to {}\n(Note that this number is added for every roll)".format(CONFIG.MAX_ROLLS),ephemeral=True)
            return
        if any([d>CONFIG.MAX_ROLL_D for _, d in interpreted_dies]): # Check that no d argument is greater than the maximum amount saved in config.cfg
            await ctx.send("Big numbers... Too big numbers, it turns out; please limit your die-size to {}".format(CONFIG.MAX_ROLL_D),ephemeral=True)
            return
        if any([d<1 for _, d in interpreted_dies]): # Check that no die is smaller than 1 because that wouldn't make any sense.
            await ctx.send("It really doesn't make sense to roll a d0 or lower... Please don't do that",ephemeral=True)
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

        await ctx.send(response) # Send off
        pass
    
    @commands.command(name="set_announcement",brief="Set a channel to receive Typhoon announcements in",description="Set a channel to receive Typhoon announcements in. Needs Manage Server Permission")
    @utils.perm_message_check("Now, hold on! I cannot let you do this (No Permission)",manage_guild=True)
    async def set_announcement_override(self, ctx : commands.Context, channel : discord.TextChannel):
        if not isinstance(channel,discord.TextChannel):
            await ctx.send("Please only use Text Channels as arguments. Otherwise it just won't work",ephemeral=True)
            return
            pass

        session : asql.AsyncSession = SESSION_FACTORY() # Create new session
        try:
            await session.execute(sql.update(Guild).values(announcement_override=str(channel.id)).where(Guild.id==str(ctx.guild.id))) # Set new override
            await session.commit() # Commit & Close
        finally:
            await session.close()

        await ctx.send(f"Override set. Bot Announcements will now be sent to {channel.mention}",ephemeral=True)
        pass
    
    # Voting
    @commands.group(name="vote",brief="Voting, you know? Ask a question, give some answers, and wait.",slash_command_guilds=(734461254747553823,))
    @commands.guild_only()
    async def vote(self, ctx : commands.Context):
        pass

    @vote.command(name="create",brief="Create a new vote",description="Create a new vote sent in an embed format with buttons as options.")
    async def create_vote(
        self, 
        ctx : commands.Context, 
        title : str = Option(None,description="Title of the embed. You can leave this unset to later edit it in the embed creator."),
        description : str = Option(None,description="Description of the embed. You can leave this unset to later edit it in the embed creator."),
        colour : str = Option(None,description="The colour of the embed. You can leave this unset to later edit it in the embed creator."),
        channel : discord.TextChannel = Option(None,description="May be set to schedule the vote to be sent in another channel.")
        ):

        if not await check_vote_perms(ctx.author,ctx.channel.id,ctx.guild.id):
            await ctx.send("You do not have permission to use the voting system. Ask your adminstrators for permission",ephemeral=True)
            return
            pass

        if channel is not None and not isinstance(channel,discord.TextChannel): # Return an error if the channel argument was not a TextChannel
            await ctx.send("Channel has to be a text channel, not... whatever you gave me",ephemeral=True)
            return
            pass
        
        cog = self
        embed = discord.Embed()
        colour_converter = commands.ColourConverter()
        # Apply arguments if given
        if title is not None: embed.title = title
        if description is not None: set_vote_description = description
        else: set_vote_description = ""
        if colour is not None:
            try:
                embed.colour = await colour_converter.convert(ctx,colour)
            except commands.BadArgument:
                embed.colour = discord.Colour.blurple()
                await ctx.send("Colour couldn't be set as the entered value is not valid. Ignoring for now",ephemeral=True)
                pass
            pass
        embed.set_author(name=ctx.author.display_name,icon_url=ctx.author.display_avatar.url)


        if channel is None: channel = ctx.channel # Set channel to be the current one if not set
        # The edit interaction stuff
        vote_options : list[str] = []

        justThis = lambda msg: msg.author == ctx.author and msg.channel == ctx.channel
        edit_message : discord.Message = ...
        class EditView(discord.ui.View):
            vote_duration : int = None
            vote_description : str = set_vote_description

            def getDiscordTimestamp(self) -> str:
                if self.vote_duration is not None:
                    return f"<t:{int(time.time()) + self.vote_duration}>"
                else:
                    return "Unspecified"
                pass

            def updateDescription(self):
                embed.description = "".join((self.vote_description,"\n\nEnds on: ",self.getDiscordTimestamp()))
                pass

            def __init__(self):
                super().__init__(timeout=CONFIG.EDIT_TIMEOUT)
                pass

            def disable_all(self):
                utils.set_component_state_recursive(self,False)
                pass

            def enable_all(self):
                utils.set_component_state_recursive(self,True)
                pass

            async def interaction_check(self, interaction: discord.Interaction) -> bool:
                return interaction.user == ctx.author
                pass

            @discord.ui.select(
                placeholder="Please select one of these options to modify",
                options=[
                    discord.SelectOption(label="Title",value="title",description="Modify the title of the embed. This will appear at the very top"),
                    discord.SelectOption(label="Description",value="desc",description="Modify the description of the embed. This is a large text to appear below the title."),
                    discord.SelectOption(label="Colour",value="colour",description="Modify the embed's colour. This will just appear at the left side"),
                    discord.SelectOption(label="Time",value="time",description="Set the duration of the vote, i.e. after what amount of time the vote shall be finished."),
                    discord.SelectOption(label="Options",value="options_general",description="Modify the options of the votes. Will create a new edit tab.")
                ],
                row=1
            )
            async def main_select(self, select : discord.SelectMenu, interaction : discord.Interaction):

                await interaction.response.defer()
                selected_value = interaction.data.get("values")[0] # Get the value selected by the user

                self.disable_all() # Disable all components, so that the process can go by undisturbed
                await edit_message.edit(view=self) # Update the view with the disabled components
                if selected_value == "title":
                    await edit_message.edit(content="```\nPlease send a message to redefine the title```") # Add a note telling the user what to do
                    titleEditMsg : discord.Message = await BOT.wait_for("message",check=justThis) # Wait for a message in the same channel as the editor

                    embed.title = discord.utils.remove_markdown(titleEditMsg.clean_content) # Update the title
                    await titleEditMsg.delete() # Delete message to make the edit channel more comprehensible
                    pass

                elif selected_value == "desc":
                    await edit_message.edit(content="```\nPlease send a message to redefine the description of the embed```") # Add a not telling the user what to do
                    descriptionEditMsg : discord.Message = await BOT.wait_for("message",check=justThis) # Wait for a message in the same channel (and also from the same user) as the editor

                    self.vote_description = discord.utils.remove_markdown(descriptionEditMsg.clean_content)
                    self.updateDescription()
                    await descriptionEditMsg.delete()
                    pass

                elif selected_value == "colour":
                    await edit_message.edit(content="```\nPlease send a message to set the colour of the embed.\nThis may be hex RGB values or a colour name (like red)```")

                    while True: # Loop that will ask for a colour as long as the conversion failed
                        colourEditMsg : discord.Message = await BOT.wait_for("message",check=justThis)
                        try:
                            colour = await colour_converter.convert(ctx, colourEditMsg.content)
                        except commands.errors.BadArgument: # Send a (perhaps a little large) message if the colour converter could not convert correctly
                            await ctx.send("This is not a usable colour. Please conform to one of these:\n> #RRGGBB\n> 0xRRGGBB\n> 0x#RRGGBB\n> rgb(red,green,blue)\n> colour-name\n(\n\tRR = red value hexadecimal \n\tGG = green value hexadecimal \n\tBB = blue value hexadecimal\n\tred = red value decimal\n\tgreen = green value decimal\n\tblue = blue value decimal)",
                            ephemeral=True)
                            pass
                        else: # Break out of this loop if it worked
                            break
                        finally: # Always delete the sent message
                            await colourEditMsg.delete()
                            pass
                        pass

                    embed.colour = colour
                    pass

                elif selected_value == "time":
                    await edit_message.edit(content="```\nPlease send a message of the format XXHXXMXXS to define the duration of the vote. (e.g. 12H36M10S)```")
                    while True:
                        timeMsg : discord.Message = await BOT.wait_for("message",check=justThis)
                        try:
                            self.vote_duration = durationFromString(timeMsg.clean_content.upper()) # Try to convert the message content to a duration
                        except ValueError: # Send an error message back if the conversion did not succeed
                            await ctx.send("This duration does not confine to the format set up above. Did you perhaps misspell something?",ephemeral=True)
                            pass
                        else: # Break out if conversion succeeded
                            break
                        finally:
                            await timeMsg.delete() # Always delete the message (yes, even after the break)
                            pass
                        pass
                    
                    self.updateDescription()
                    pass

                elif selected_value == "options_general":
                    option_message : discord.Message = ...

                    class OptionSettingsView(discord.ui.View):
                        def __init__(self):
                            super().__init__(timeout=CONFIG.EDIT_TIMEOUT)

                            for option in vote_options:
                                self.add_item(discord.ui.Button(
                                    style=discord.ButtonStyle.gray,
                                    label=option,
                                    disabled=True
                                ))
                                pass
                            pass

                        async def interaction_check(self, interaction: discord.Interaction) -> bool:
                            return interaction.user == ctx.author
                            pass

                        def disable_all(self): utils.set_component_state_recursive(self,False)
                        def enable_all(self):  utils.set_component_state_recursive(self,True )

                        @discord.ui.button(label="Add an option",style=discord.ButtonStyle.green, disabled=len(vote_options) >= CONFIG.MAX_VOTE_OPTIONS,row=1)
                        async def option_add(self, button : discord.ui.Button, interaction : discord.Interaction):
                            await interaction.response.defer() # Tell the Discord API to stop worrying about this interaction

                            removeButton = utils.getButtonByLabel(self,"Remove an option") # Very bad implementation but it works
                            leaveButton  = utils.getButtonByLabel(self,"Leave this submenu") # Still bad

                            removeButton.disabled = leaveButton.disabled = True # Disable other control buttons
                            await option_message.edit(content="```\nPlease send a message with the title for the option you wish to add```",view=self)

                            while True:
                                option_name_msg : discord.Message = await BOT.wait_for("message",check=justThis)
                                if len(option_name_msg.clean_content) > 80: # If entered name is greater than Discord's character limit for buttons
                                    await ctx.send("This option name is too large. Please refrain to a maximum of 80 characters.",ephemeral=True)
                                    await option_name_msg.delete()
                                    pass
                                else:
                                    break
                                pass
                            
                            self.add_item(discord.ui.Button(
                                style=discord.ButtonStyle.gray,
                                label=option_name_msg.clean_content,
                                disabled=True
                            ))
                            await option_name_msg.delete()
                            vote_options.append(option_name_msg.clean_content) # Append option to vote_options list (for later)

                            removeButton.disabled = leaveButton.disabled = False # Enable both control buttons
                            button.disabled = len(vote_options) >= 5
                            await option_message.edit(content="```\nThis is the embed at the moment. (With options)\nWhat do you want to do?```",view=self)
                            pass

                        @discord.ui.button(label="Remove an option",style=discord.ButtonStyle.danger, disabled=len(vote_options) < 1,row=1)
                        async def option_rem(self, button : discord.ui.Button, interaction : discord.Interaction):
                            await interaction.response.defer() # Tell Discord to stop worrying

                            addButton   = utils.getButtonByLabel(self,"Add an option")
                            leaveButton = utils.getButtonByLabel(self,"Leave this submenu")

                            addButton.disabled = leaveButton.disabled = True # Disable other control buttons
                            await option_message.edit(content="```\nPlease send a message with the title of the option you wish to remove```",view=self)

                            while True:
                                option_name_msg : discord.Message = await BOT.wait_for("message",check=justThis)
                                button2Remove : discord.ui.Button = utils.getButtonByLabel(self,option_name_msg.clean_content)
                                if button2Remove is None:
                                    await ctx.send("There is no option with that name")
                                    pass
                                else:
                                    await option_name_msg.delete()
                                    break
                                pass

                            self.remove_item(button2Remove) # Remove dummy button
                            vote_options.remove(option_name_msg.clean_content) # Remove option from options list

                            addButton.disabled = leaveButton.disabled = False # Reenable other control buttons
                            await option_message.edit(content="```\nThis is the embed at the moment. (With options)\nWhat do you want to do?```",view=self)
                            pass

                        @discord.ui.button(label="Leave this submenu",style=discord.ButtonStyle.primary,row=1)
                        async def option_leave(self, button : discord.ui.Button, interaction : discord.Interaction):
                            await option_message.edit(content="This submenu has been closed",embed=None,view=None) # Remove the embed and the interaction system
                            self.stop() # Stop the view (saves some RAM and is good behaviour)
                            pass
                        pass

                    option_view = OptionSettingsView()
                    option_message : discord.WebhookMessage = await ctx.send(
                        "```\nThis is the embed at the moment. (With options)\nWhat do you want to do?```",
                        embed=embed,
                        ephemeral=True,
                        view=option_view
                    )
                    await option_view.wait()
                    pass

                self.enable_all() # Reenable all the components because we're back on the main level
                await edit_message.edit(content=None,view=self,embed=embed) # Apply the changes + Reset the instructions above the embed
                pass

            @discord.ui.button(label="Finish",style=discord.ButtonStyle.green,row=2)
            async def finish_editor(self, button : discord.ui.Button, interaction : discord.Interaction):
                if not (len(vote_options) > 1 and self.vote_duration is not None):
                    await ctx.send("This vote either didn't have more than one option or did not have a set ending time.\nPlease check these values and set them accordingly.",ephemeral=True)
                    return
                    pass

                vote_message : discord.WebhookMessage = ...
                vote_view = VoteView(self.vote_duration,vote_options,ctx.author)
                vote_message = await channel.send(embed=embed,view=vote_view)
                await vote_view.set_message(vote_message,embed)

                # Adding vote to database to allow for recovery after a bot restart
                session = SESSION_FACTORY()
                sql_guild = await utils.get_guild(session,ctx.guild.id)
                sql_guild.votes.append(vote_view.to_dict())
                await session.commit(); await session.commit()

                await edit_message.edit(content="Vote message created! :white_check_mark:",embed=None,view=None)
                self.stop()

                cog.VOTE_PROCESSES[vote_message.id] = vote_view
                
                asyncio.create_task(vote_view.handle_process(),name="Vote collector at {0}:{1}".format(ctx.guild.id,ctx.channel.id)) # Run vote collector in the background
                pass

            @discord.ui.button(label="Discard",style=discord.ButtonStyle.danger,row=2)
            async def discard_embed(self, button : discord.ui.Button, interaction : discord.Interaction):
                self.stop()
                
                await edit_message.edit(content="This vote has been discarded",embed=None,view=None)
                pass
            pass

        edit_message = await ctx.send(embed=embed,view=EditView(),ephemeral=True) # Send edit message
        pass
    
    @vote.command(name="cast",brief="Cast a vote into an existing poll", description="Cast a vote into an existing poll. This will do the exact same thing as clicking on the right button.")
    async def cast_vote(self, ctx : commands.Context, message : str = Option(description="The message the vote is associated with. This can be a message id or a URL."),option : int = Option(None,description="The number of what you want to vote for (left->right). Leave empty to reset your vote.")):
        converted_message_id = await vote_message_converter(ctx,message)
        if converted_message_id is None: return # Handling was already done in this case

        if option is not None and option < 1: # Check that option is not index format or similar (only applies if option is set)
            await ctx.send("The entered option number should range from 1 - the amount of options. 0 or lower is invalid.",ephemeral=True)
            return

        vote_view = self.VOTE_PROCESSES.get(converted_message_id) # Get the right vote
        if vote_view is None: # Send error if it couldn't find the vote
            await ctx.send("I looked at this a long while and I must say, I have no idea what you're talking about... (Message not a vote)",ephemeral=True)
            return
            pass

        channel_perms = vote_view.message.channel.permissions_for(ctx.author)
        if ctx.author.guild.id != vote_view.author.guild.id and channel_perms.is_superset(discord.Permissions(read_messages=True,read_message_history=True)): # Check if user has access to that channel (restricts to same guild vote casting)
            await ctx.send("I looked at this a long while and I must say, I have no idea what you're talking about... (Message not a vote)",ephemeral=True) # Send same error as couldn't find because Security (sparkles) [still not immune to timing attacks]
            return
            pass

        if option is not None and option > len(vote_view.options): # Check that option actually exists
            await ctx.send("Hmmm... That's not a existing option... (Option number too large)",ephemeral=True)
            pass

        # Cast the vote
        if option is not None:
            vote_view.option_votes[ctx.author.id] = option - 1 # Set the vote (-1 to convert to index format)
            await ctx.send("Thank you for your vote! You may override your choice at any time!",ephemeral=True)
            pass
        else:
            try:
                vote_view.option_votes.pop(ctx.author.id)
                pass
            except KeyError:
                await ctx.send("As you didn't vote yet, your vote could not be reset.",ephemeral=True)
                pass
            else:
                await ctx.send("Your vote has been reset!",ephemeral=True)
                pass
            pass
        pass

    @vote.command(name="finish",brief="End a vote prematurely")
    async def finish_vote(self, ctx : commands.Context, message : str = Option(description="The message the vote is associated with. This can be a message id or a URL")):
        converted_message_id = await vote_message_converter(ctx,message)
        if converted_message_id is None: return # If return is None an error was already handled.

        vote_view = self.VOTE_PROCESSES.get(converted_message_id)
        if vote_view is None:
            await ctx.send("These are not the votes you are looking for... I hope, because I couldn't find them. (Not a vote message)",ephemeral=True)
            return
            pass

        if vote_view.author != ctx.author:
            await ctx.send("Now hang on a minute! You didn't even start that vote! How do you imagine you could end it? (No Permission)", ephemeral=True)
            return
            pass

        vote_view.stop()
        await ctx.send("Vote was ended prematurely. I hope that wasn't an accident", ephemeral=True)
        pass

    @vote.command(name="restrict",brief="Restrict who can create votes and where that may be done. This will open an editor.")
    @utils.perm_message_check("Managing votes is not up to you... (No Permission [need Manage Server])",manage_guild=True)
    async def restrict_votes(self, ctx : commands.Context):
        justThis = lambda msg: msg.author == ctx.author and msg.channel == ctx.channel

        async def assemble_override_fields(role_not_channel : bool = False):
            object_string = ""
            state_string = ""
            for object_id, state in vote_permissions["role_overrides" if role_not_channel else "channel_overrides"].items():
                if not role_not_channel:
                    object = await ctx.guild.fetch_channel(int(object_id)) # Get channel object 
                    pass
                else:
                    object = ctx.guild.get_role(int(object_id))
                    pass
                
                object_string = "".join((object_string,object.mention if object is not None else "Not Found","\n")) # Append channel mention to the override channels and put a newline
                
                if state:
                    state_string = "".join((state_string,"Enabled\n"))
                else:
                    state_string = "".join((state_string,"Disabled\n"))
                pass

            return object_string, state_string
            pass


        main_message : discord.WebhookMessage = ...
        main_embed = discord.Embed(title="Poll restriction editor",colour=discord.Colour.blurple())

        session : asql.AsyncSession = SESSION_FACTORY()
        result : CursorResult = await session.execute(sql.select(Guild.vote_permissions).where(Guild.id==str(ctx.guild.id))) # Get vote permissions
        vote_permissions = result.scalar_one_or_none() # Get the vote permissions object (Beware! This object is not being observed by sqlalchemy => Manual Updates!)
        if vote_permissions is None: # If the object does not exist yet, add it back in and retrieve it again (for auto-updating)
            vote_permissions = {"state":True,"channel_overrides":{},"role_overrides":{}}
            await session.execute(sql.update(Guild).values(vote_permissions=vote_permissions).where(Guild.id==str(ctx.guild.id)))
            await session.commit()
            pass
        update_vote_perm_sql = sql.update(Guild).where(Guild.id == str(ctx.guild.id))

        original_description = """Here you can edit the restrictions on who may use the /vote command.
        The buttons in the 1st row can be used to set the original permissions when no override is applied.
        The buttons in the 2nd row can be used to set and remove overrides for either channels or roles. NOTE: Role overrides are prioritised.
        
        The polling system is currently {}"""
        main_embed.description = original_description.format("Enabled" if vote_permissions["state"] else "Disabled")

        class Restrictor(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=CONFIG.EDIT_TIMEOUT)
                pass

            async def interaction_check(view, interaction: discord.Interaction) -> bool: # Only allow interaction from the author
                return interaction.user == ctx.author
            
            async def on_timeout(view) -> None:
                await main_message.edit("```\nEditor timed out```",view=None,embed=None)
                pass

            def disable_all(view):
                utils.set_component_state_recursive(view,False)
                pass

            def enable_all(view):
                utils.set_component_state_recursive(view,True)
                pass

            # Interactable parts
            @discord.ui.button(label="Enable polls",style = discord.ButtonStyle.green,row=0)
            async def general_enable(view, button : discord.ui.Button, interaction : discord.Interaction):
                vote_permissions["state"] = True # Update dictionary
                await session.execute(update_vote_perm_sql.values(vote_permissions=vote_permissions)) # Update sql entry
                await session.commit()

                await interaction.response.send_message("The voting system is now enabled for everyone (as long as there is no override)!",ephemeral=True)
                
                main_embed.description = original_description.format("Enabled" if vote_permissions["state"] else "Disabled") # Update embed with new state info
                await main_message.edit(embed=main_embed) # Send out to Discord
                pass

            @discord.ui.button(label="Disable polls",style = discord.ButtonStyle.red,row=0)
            async def general_disable(view, button : discord.ui.Button, interaction : discord.Interaction):
                vote_permissions["state"] = False
                await session.execute(update_vote_perm_sql.values(vote_permissions=vote_permissions)) # Update sql entry
                await session.commit()

                await interaction.response.send_message("The voting system is now disabled for everyone (as long as they don't have an override associated with them)",ephemeral=True)
                
                main_embed.description = original_description.format("Enabled" if vote_permissions["state"] else "Disabled") # Update embed with new state info
                await main_message.edit(embed=main_embed) # Send out to Discord
                pass

            @discord.ui.button(label="Channel specific overrides",style=discord.ButtonStyle.primary,row=1)
            async def channel_specific(view, button : discord.ui.Button, interaction : discord.Interaction):
                await interaction.response.defer()
                view.disable_all()
                await main_message.edit(view=view)


                channel_override_embed = discord.Embed(title="Channel overrides",colour=discord.Colour.brand_green())

                channel_string, state_string = await assemble_override_fields()
                channel_override_embed.add_field(name="Override Channels",value=channel_string or "None")
                channel_override_embed.add_field(name="Override States",value=state_string or "None")

                channel_override_msg : discord.Message = ...
                class ChannelOverrideView(discord.ui.View):
                    def __init__(self):
                        super().__init__(timeout=CONFIG.EDIT_TIMEOUT)
                        pass

                    async def on_timeout(cview):
                        await channel_override_msg.edit(content="```\nEditor has timed out```",embed=None,view=None)
                        pass

                    async def wait_for_channel(cview):
                        while True:
                            channel_resp_msg : discord.Message = await BOT.wait_for("message",check=justThis)
                            if len(channel_resp_msg.channel_mentions) > 0:
                                channel = channel_resp_msg.channel_mentions[0] # Get first channel object from message
                            else:
                                channel = None
                            
                            await channel_resp_msg.delete()
                            if not isinstance(channel,discord.TextChannel): # Send error if user did not send a Text Channel and wait for next try
                                await ctx.send("The channel override has to use a Text Channel, which is not what you entered here.",ephemeral=True)
                                pass
                            else:
                                break
                            pass
                        return channel
                        pass

                    async def updateEmbed(cview):
                        channel_string, state_string = await assemble_override_fields()
                        channel_override_embed.set_field_at(0,name="Override Channels",value=channel_string)
                        channel_override_embed.set_field_at(1,name="Override States",  value=state_string)
                        await channel_override_msg.edit(content=None,embed=channel_override_embed,view=cview)
                        pass

                    @discord.ui.button(label="Add/Replace an override",style=discord.ButtonStyle.green)
                    async def override_add(cview, cbutton : discord.ui.Button, cinteraction : discord.Interaction):
                        await cinteraction.response.defer()

                        await channel_override_msg.edit(content="```\nPlease send a message containing the channel you want to add an override to```")
                        addChannel = await cview.wait_for_channel() # Wait to receive a channel object
                        
                        en_di_view = discord.ui.View(timeout=CONFIG.EDIT_TIMEOUT)

                        class EnDaButton(discord.ui.Button): # Not creative enough for another name
                            def __init__(self,state : bool):
                                self.state = state
                                if state:
                                    super().__init__(style=discord.ButtonStyle.green,label="Enable")
                                    pass
                                else:
                                    super().__init__(style=discord.ButtonStyle.red,label="Disable")
                                    pass
                                pass

                            async def callback(button, interaction):
                                vote_permissions["channel_overrides"][str(addChannel.id)] = button.state
                                en_di_view.stop()
                                pass
                            pass
                        en_di_view.add_item(EnDaButton(True)); en_di_view.add_item(EnDaButton(False))

                        await channel_override_msg.edit(content="```\nPlease select from one of the buttons below what state the override should have```",view=en_di_view)
                        await en_di_view.wait()
                        await cview.updateEmbed()
                        await session.execute(update_vote_perm_sql.values(vote_permissions=vote_permissions)) # Update sql entry
                        await session.commit()
                        pass

                    @discord.ui.button(label="Remove an override",style=discord.ButtonStyle.danger)
                    async def override_rem(cview, cbutton : discord.ui.Button, cinteraction : discord.Interaction):
                        await cinteraction.response.defer()

                        await channel_override_msg.edit(content="```\nPlease send a message containing the channel you want to add an override to```")
                        remChannel = await cview.wait_for_channel()

                        try:
                            vote_permissions["channel_overrides"].pop(str(remChannel.id))
                        except KeyError:
                            await ctx.send("As this channel does not have an override, it could not be reset.",ephemeral=True)
                            pass
                        else:
                            await ctx.send("Successfully removed {}'s override".format(remChannel.mention),ephemeral=True)
                        await cview.updateEmbed()
                        await session.execute(update_vote_perm_sql.values(vote_permissions=vote_permissions)) # Update sql entry
                        await session.commit()
                        pass

                    @discord.ui.button(label="Leave this submenu",style=discord.ButtonStyle.blurple)
                    async def close_submenu(cview, cbutton : discord.ui.Button, cinteraction : discord.Interaction):
                        await cinteraction.response.defer()

                        await channel_override_msg.edit(content="```\nThis editor was closed```",embed=None,view=None)
                        cview.stop()

                        await session.commit()
                        pass
                    pass

                cview = ChannelOverrideView()
                channel_override_msg = await ctx.send(embed=channel_override_embed,ephemeral=True,view=cview)

                await cview.wait()
                view.enable_all()
                await main_message.edit(view=view)
                pass

            @discord.ui.button(label="Role specific overrides",style=discord.ButtonStyle.primary,row=1)
            async def role_specific(view, button : discord.ui.Button, interaction : discord.Interaction):
                view.disable_all()
                await main_message.edit(view=view)
                
                role_override_embed = discord.Embed(title="Channel overrided",colour=discord.Colour.brand_red())

                role_string, state_string = await assemble_override_fields(True)
                role_override_embed.add_field(name="Override Roles",value=role_string or "None")
                role_override_embed.add_field(name="Override States",value=state_string or "None")

                role_override_msg : discord.Message = ...

                class RoleOverrideView(discord.ui.View):
                    def __init__(self):
                        super().__init__(timeout=CONFIG.EDIT_TIMEOUT)
                        pass
                    
                    async def on_timeout(rview) -> None:
                        await role_override_msg.edit(content="```\nEditor has timed out```",embed=None,view=None)
                        pass

                    async def wait_for_role(rview) -> discord.Role:
                        role_converter = commands.RoleConverter()
                        while True:
                            role_resp_msg : discord.Message = await BOT.wait_for("message",check=justThis) # Wait for a message containing the role (hopefully)
                            try:
                                role = await role_converter.convert(ctx,role_resp_msg.content)
                            except commands.BadArgument: # Send error message if the conversion did not succeed and let user try again
                                await ctx.send("A role is required for the override. What you delivered could not be interpreted as such",ephemeral=True)
                                pass
                            else:
                                break
                            finally:
                                await role_resp_msg.delete() # Always delete the message
                                pass
                            pass

                        return role
                        pass

                    async def updateEmbed(rview):
                        role_string, state_string = await assemble_override_fields(True)
                        role_override_embed.set_field_at(0,name="Override Roles",value=role_string or "None")
                        role_override_embed.set_field_at(1,name="Override States",value=state_string or "None")

                        await role_override_msg.edit(embed=role_override_embed,view=rview)
                        pass
                    
                    @discord.ui.button(label="Add/Replace an override",style=discord.ButtonStyle.green)
                    async def override_add(rview, rbutton : discord.ui.Button, rinteraction : discord.Interaction):
                        await rinteraction.response.defer() # Defer interaction because a response is going to follow seperatly

                        await role_override_msg.edit(content="```\nSend a message containing the role you wish to set an override for.```") # Tell the user what to do
                        role = await rview.wait_for_role()

                        en_di_view = discord.ui.View(timeout=CONFIG.EDIT_TIMEOUT) # Create view object with custom timeout
                        class EnDaButton(discord.ui.Button): # Not creative enough for another name
                            def __init__(self,state : bool):
                                self.state = state
                                if state:
                                    super().__init__(style=discord.ButtonStyle.green,label="Enable")
                                    pass
                                else:
                                    super().__init__(style=discord.ButtonStyle.red,label="Disable")
                                    pass
                                pass

                            async def callback(button, interaction):
                                vote_permissions["role_overrides"][str(role.id)] = button.state
                                en_di_view.stop()
                                await interaction.response.defer()
                                pass
                            pass
                        
                        en_di_view.add_item(EnDaButton(True)); en_di_view.add_item(EnDaButton(False))

                        await role_override_msg.edit(content="```\nPlease use one of the buttons below to determine the state of the override```",view=en_di_view)
                        
                        await en_di_view.wait() # Wait until interaction was used
                        await rview.updateEmbed() # Update embed to have override removed

                        await session.commit()
                        pass

                    @discord.ui.button(label="Remove an override",style=discord.ButtonStyle.red)
                    async def override_rem(rview, rbutton : discord.ui.Button, rinteraction : discord.Interaction):
                        await rinteraction.response.defer() # Defer interaction because a response is going to follow seperatly

                        await role_override_msg.edit(content="```\nSend a message containing the role whose override you wish to remove.```") # Tell the user what to do
                        role = await rview.wait_for_role()

                        try:
                            vote_permissions["role_overrides"].pop(role.id)
                        except KeyError:
                            await ctx.send("This role did not have an override. Thus, a deletion of said override is impossible",ephemeral=True)
                            pass
                        else:
                            await ctx.send("Role override removed!",ephemeral=True)
                            pass

                        await rview.updateEmbed()

                        await session.execute(update_vote_perm_sql.values(vote_permissions=vote_permissions)) # Update sql entry
                        await session.commit()
                        pass
                    
                    @discord.ui.button(label="Leave this submenu",style=discord.ButtonStyle.blurple)
                    async def close_submenu(cview, cbutton : discord.ui.Button, cinteraction : discord.Interaction):
                        await cinteraction.response.defer()

                        await role_override_msg.edit(content="```\nThis editor was closed```",embed=None,view=None)
                        cview.stop()

                        await session.commit()
                        pass
                    pass

                rview = RoleOverrideView()
                role_override_msg = await ctx.send(embed=role_override_embed,ephemeral=True,view=rview)
                await interaction.response.defer()

                await rview.wait()
                view.enable_all()
                await main_message.edit(view=view)

                await session.execute(update_vote_perm_sql.values(vote_permissions=vote_permissions)) # Update sql entry
                await session.commit()
                pass
            
            @discord.ui.button(label="Close this editor",style=discord.ButtonStyle.danger,row=2)
            async def close_editor(view, button : discord.ui.Button, interaction : discord.Interaction):
                await main_message.edit("```\nEditor was closed```",view=None,embed=None)
                await interaction.response.defer()

                await session.commit()
                view.stop()
                pass
            pass

        view = Restrictor()
        main_message = await ctx.send(embed=main_embed,view=view,ephemeral=True)
        
        await view.wait()
        await session.close()
        pass
    
    @tasks.loop(minutes=5)
    async def cleanVoteBuffer(self):
        """Removes all expired votes from the dictionary"""
        for expired_item in filter(lambda item: item[1].is_finished(),self.VOTE_PROCESSES.items()):
            self.VOTE_PROCESSES.pop(expired_item[0])
            pass
        pass
    
    # Reaction Roles

    @commands.group("reaction_role")
    @utils.perm_message_check("Oh, hold your horses! You cannot do this! (No Permission)",manage_roles = True)
    async def reaction_role(self, ctx):
        pass

    @reaction_role.command("add",brief="Adds a new reaction role to a message you define")
    async def reaction_role_add(self, ctx : commands.Context, message : str = None, emoji : str = None, role : discord.Role = None):
        """FIX: When using the full-arg form any text can be added. This cannot be fixed easily and will require some redesigning."""
        justThis = lambda msg: msg.author == ctx.author and msg.channel == ctx.channel

        if message is not None:
            message_converter = commands.MessageConverter()
            try:
                message_obj : discord.Message = await message_converter.convert(ctx,message)
                pass
            except BadArgument:
                await ctx.send("What is this? This doesn't look like a message! (Should look like one of these:\n> <channel_id>:<message_id>\n> <message_id> [only if in same channel]\n> <message_url>\n)",ephemeral=True)
                return
                pass
            pass

        class AlreadyExistsView(discord.ui.View): # Interaction Platform used for confirmation (if overriding a existing reaction role)
            @discord.ui.button(label="Yes",style=discord.ButtonStyle.green)
            async def confirm(view, button, interaction : discord.Interaction):
                await interaction.response.defer()
                view.result = True
                view.stop()
                pass

            @discord.ui.button(label="No",style=discord.ButtonStyle.danger)
            async def reject(view, button, interaction : discord.Interaction):
                await interaction.response.defer()
                view.result = False
                view.stop()
                pass
            pass

        async def sql_write(message_id : MessageId, emoji : discord.PartialEmoji, guild_id : GuildId, role_id : RoleId):
            session : asql.AsyncSession = SESSION_FACTORY()
            try:
                result : CursorResult = await session.execute(sql.select(ReactionRoles).where(ReactionRoles.message_id == str(message_id)))
                
                sql_object : ReactionRoles = result.scalar_one_or_none()
                if sql_object is None: # Create new object if it didn't exist yet
                    sql_object = ReactionRoles(message_id=str(message_id),react_roles={})
                    session.add(sql_object)
                    pass
                sql_object.react_roles[str(emoji)] = (guild_id,role_id) # Create entry for this reaction role
                
                await session.commit()
            finally:
                await session.close() # Close SQL Session
            pass

        async def commit_rr(message : discord.Message, guild : discord.Guild, emoji : discord.PartialEmoji, role : discord.Role):
            self.REACTION_ROLES.setdefault(message.id,{})
            if emoji in self.REACTION_ROLES[message.id].keys(): # If there is already a reaction role like this
                view = AlreadyExistsView()
                confirm_msg = await ctx.send("There already is a reaction role with that emoji. Do you wish to replace it?",view=view,ephemeral=True)

                result = (not await view.wait()) and view.result # Wait for a response (timeout will mean cancel)
                await confirm_msg.edit(content="(Interaction complete)",view=None)

                if not result: # If was cancelled, stop program
                    return
                pass

            self.REACTION_ROLES[message.id][emoji] = role # Add to RAM
            await sql_write(message.id, emoji, guild.id, role.id) # Add to the SQL Database

            try:
                await message.add_reaction(emoji)
            except discord.errors.HTTPException:
                reaction_succeeded = False
                pass
            else:
                reaction_succeeded = True
                pass
            await ctx.send(f"Reaction Role has been created! React with {emoji} to be granted the role {role.mention}!",ephemeral=True)
            if not reaction_succeeded:
                await ctx.send("You will have to add the reaction yourself though, I was unable to do that.",ephemeral=True)
            pass

        if not None in (message,emoji,role): # If all arguments were passed, don't send a UI
            partial_emoji = discord.PartialEmoji.from_str(emoji)
            await commit_rr(message_obj,ctx.guild,partial_emoji,role)
            return
            pass
        else:
            origin_msg : discord.Message = ...
            origin_embed : discord.Embed = ...

            class ConfigView(discord.ui.View):
                def __init__(view,message : discord.Message = None, guild : discord.Guild = None, emoji : discord.PartialEmoji = None, role : discord.Role = None):
                    view.rrmessage = message # Message to apply the reaction role to
                    view.guild     = guild   # Guild the reaction role will be in
                    view.emoji     = emoji   # Emoji associated with the reaction role
                    view.role      = role    # Role to grant through the reaction role

                    super().__init__(timeout=CONFIG.EDIT_TIMEOUT)
                    pass

                # 
                def enable_all(view):
                    return utils.set_component_state_recursive(view,True)
                    pass

                def disable_all(view):
                    return utils.set_component_state_recursive(view,False)
                    pass


                async def update_msg(view):
                    if view.rrmessage is None:
                        msg_str = "Unset"
                        pass
                    else:
                        msg_str = f"From {view.rrmessage.author.mention} in {view.rrmessage.channel.mention} at {view.rrmessage.created_at.strftime('%Y-%m-%d %H-%M-%S')}"

                    origin_embed.description = f"""Emoji: {view.emoji if view.emoji is not None else 'Unset'}
                    \rRole: {view.role.mention if view.role is not None else 'Unset'}
                    \rMessage: {msg_str}"""

                    await origin_msg.edit(content=None,embed=origin_embed,view=view)
                    pass

                @discord.ui.button(label="Emoji",style=discord.ButtonStyle.primary)
                async def set_emoji(view, button : discord.ui.Button, interaction : discord.Interaction):
                    await interaction.response.defer()

                    view.disable_all()
                    await view.update_msg()

                    await origin_msg.edit(content="```\nPlease send the emoji you want the users to react to```")

                    emoji_converter = commands.converter.PartialEmojiConverter()
                    while True:
                        msg : discord.Message = await BOT.wait_for("message",check=justThis)
                        try:
                            if emojilib.is_emoji(msg.content):
                                emoji = discord.PartialEmoji.from_str(msg.content)
                                pass
                            else:
                                emoji : discord.PartialEmoji = await emoji_converter.convert(ctx,msg.content)
                                pass
                            pass
                        except PartialEmojiConversionFailure:
                            await ctx.send("What you sent does not seem to be a valid emoji. Please also make sure the emoji is either a server emoji or a default emoji. (This is due to API limitations)",ephemeral=True)
                            pass
                        else:
                            break # Leave loop if conversion was successful
                        finally:
                            await msg.delete()
                            pass
                        pass

                    view.emoji = emoji

                    view.enable_all(); await view.update_msg()
                    pass

                @discord.ui.button(label="Role",style=discord.ButtonStyle.secondary)
                async def set_role(view, button : discord.ui.Button, interaction : discord.Interaction):
                    await interaction.response.defer()
                    
                    view.disable_all(); await view.update_msg()

                    await origin_msg.edit(content="```\nPlease respond with a role you want to give out with the reaction```")

                    role_converter = commands.converter.RoleConverter()
                    while True:
                        msg : discord.Message = await BOT.wait_for("message", check=justThis)
                        try:
                            role : discord.Role = await role_converter.convert(ctx,msg.content)
                            if not role.is_assignable(): raise BadArgument
                        except BadArgument:
                            await ctx.send("""Your message does not seem to translate into a role or the bot would not be able to assign it. Make sure your message conforms to the following:
                            ```md
                            \r1. A role ID
                            \r2. A role mention
                            \r3. A role name```
                            \rif you are sure you have these correct, please check if this bot's role is above the role you are trying to assign""",ephemeral=True)
                            pass
                        else:
                            break
                        finally:
                            await msg.delete()
                            pass
                        pass

                    view.role = role
                    
                    view.enable_all(); await view.update_msg()
                    pass

                @discord.ui.button(label="Message",style=discord.ButtonStyle.green)
                async def set_message(view, button : discord.ui.Button, interaction : discord.Interaction):
                    await interaction.response.defer()
                    
                    view.disable_all(); await view.update_msg()

                    msg_converter = commands.converter.MessageConverter()
                    while True:
                        msg : discord.Message = await BOT.wait_for("message", check=justThis)
                        try:
                            rrmessage : discord.Message = await msg_converter.convert(ctx,msg.content)
                            if rrmessage.guild != ctx.guild: raise BadArgument
                            pass
                        except BadArgument:
                            await ctx.send("""Your message could not be interpreted as... well a reference to another message. Make sure your message conforms to the following: ```md
                            1. A combined channel id and message id (e.g. 5017-3012)
                            2. A singular message id within this channel
                            3. A message url
                            ``` Also make sure the message you referenced is in this server""",ephemeral=True)
                            pass
                        else:
                            break
                        finally:
                            await msg.delete()
                            pass
                        pass

                    view.rrmessage = rrmessage

                    view.enable_all(); await view.update_msg()
                    pass

                # Confirm/Discard
                @discord.ui.button(label="Confirm",style=discord.ButtonStyle.success,row=1)
                async def confirm_interaction(view, button : discord.ui.Button, interaction : discord.Interaction):
                    await commit_rr(view.rrmessage, ctx.guild, view.emoji,view.role)
                    view.result = True
                    view.stop()
                    pass

                @discord.ui.button(label="Discard",style=discord.ButtonStyle.danger,row=1)
                async def discard_interaction(view, button : discord.ui.Button, interaction : discord.Interaction):
                    view.disable_all(); await view.update_msg()

                    confirm_view = discord.ui.View()
                    async def confirm_deletion(interaction : discord.Interaction):
                        await interaction.response.defer()
                        confirm_view.stop()
                        pass
                    confirm_button = discord.ui.Button(label="Discard",style=discord.ButtonStyle.danger)
                    confirm_button.callback = confirm_deletion
                    confirm_view.add_item(confirm_button)
                    
                    await ctx.send("**Careful!** This will delete all your progress!",view=confirm_view,ephemeral=True)
                    await interaction.response.defer()

                    timed_out = await confirm_view.wait()
                    if timed_out: # Do nothing if the view timed out
                        view.enable_all(); await view.update_msg() # Enable all the buttons again
                        return
                        pass

                    view.result = False
                    view.stop()
                    pass
                pass

            origin_embed = discord.Embed(title="Reaction Role editor",colour=discord.Colour.red())

            view = ConfigView(
                message_obj,
                ctx.guild,
                discord.PartialEmoji.from_str(emoji) if emoji is not None else emoji,
                role
            )
            origin_msg = await ctx.send(embed=origin_embed, view=view, ephemeral=True)

            has_timed_out = await view.wait()
            if has_timed_out:
                await origin_msg.edit(content="```\nThis platform interaction timed out```",embed=None,view=None)
                pass
            else:
                await origin_msg.edit(content="```\nThis platform interaction is finished```",embed=None,view=None)
                pass
            pass
        pass

    @reaction_role.command("remove",brief="Removes an existing reaction role from a specified message")
    async def reaction_role_remove(self, ctx : commands.Context, message : str = Option(description="A URL to the message you want to remove reaction roles from")):
        msg_converter = commands.converter.MessageConverter()
        try:
            msg_obj = await msg_converter.convert(ctx,message)
            if msg_obj.guild != ctx.guild: raise BadArgument
            pass
        except BadArgument:
            await ctx.send("The message you specified can either not be interpreted is non-existent. Please use either a combination of a channel id and a message id combined with a dash or a message URL.",ephemeral=True)
            return
            pass
        if msg_obj.id not in self.REACTION_ROLES.keys() or len(self.REACTION_ROLES[msg_obj.id].values()) == 0:
            await ctx.send("This message does not have any reaction roles",ephemeral=True)
            return
            pass

        async def sql_write(message_id : MessageId, emoji : discord.PartialEmoji):
            session : asql.AsyncSession = SESSION_FACTORY()
            try:
                result : CursorResult = await session.execute(sql.select(ReactionRoles).where(ReactionRoles.message_id == str(message_id)))
                
                sql_object : ReactionRoles = result.scalar_one_or_none()
                if sql_object is None: # Create new object if it didn't exist yet
                    sql_object = ReactionRoles(message_id=str(message_id),react_roles={})
                    session.add(sql_object)
                    pass
                sql_object.react_roles.pop(str(emoji)) # Remove entry for this reaction
                
                await session.commit()
            finally:
                await session.close() # Close SQL Session
            pass

        origin_msg : discord.Message = ...
        origin_embed : discord.Embed = ...

        msg_rrs = self.REACTION_ROLES[msg_obj.id] # Reaction roles of the selected message
        class ConfigView(discord.ui.View):
            def __init__(view):
                super().__init__(timeout=CONFIG.EDIT_TIMEOUT)

                def rr_callback_gen(button : discord.ui.Button, emoji : discord.PartialEmoji):
                    async def wrapper(interaction : discord.Interaction):
                        await interaction.response.defer()

                        if await utils.confirmation_interact(ctx,"Do you really want to delete this reaction role? (This operation is irreversible)","Delete"):
                            msg_rrs.pop(emoji)
                            await sql_write(msg_obj.id,emoji)
                            try:
                                await msg_obj.remove_reaction(emoji,ctx.me)
                                pass
                            except discord.errors.HTTPException:
                                await ctx.send("I was unable to remove my reaction. This shouldn't cause any more issues though",ephemeral=True)
                                pass

                            view.remove_item(button)
                            await origin_msg.edit(view=view)
                            pass
                        pass

                    return wrapper
                    pass
                for emoji, role in msg_rrs.items():
                    button = discord.ui.Button(label=role.name,emoji=emoji if isinstance(emoji,discord.Emoji) else None,row=0)
                    button.callback = rr_callback_gen(button,emoji)

                    view.add_item(button)
                    pass
                pass

            async def update_msg(view):
                await origin_msg.edit(embed=origin_embed,view=view)
                pass

            @discord.ui.button(label="Exit",style=discord.ButtonStyle.danger,row=1)
            async def exit(view, button, interaction : discord.Interaction):

                view.stop()
                pass
            pass

        origin_embed = discord.Embed(title="Reaction Role Editor",colour=discord.Colour.red(),description="See below for all the reaction roles of the selected message and click on one if you want to remove it")
        cfg_view = ConfigView()
        origin_msg = await ctx.send(embed=origin_embed,view=cfg_view,ephemeral=True)

        timed_out = await cfg_view.wait()
        if timed_out:
            await origin_msg.edit(content="```\nThis platform interaction timed out```",embed=None,view=None)
            pass
        else:
            await origin_msg.edit(content="```\nEditor was closed```",embed=None,view=None)
            pass
        pass

    @reaction_role.command("list",brief="Lists all reaction roles of a specified message")
    async def reaction_role_list(self, ctx : commands.Context, message : str = Option(description="A URL to the message you want to see the reaction roles for")):
        msg_converter = commands.converter.MessageConverter()
        try:
            msg_obj = await msg_converter.convert(ctx,message)
            if msg_obj.guild != ctx.guild: raise BadArgument
            pass
        except BadArgument:
            await ctx.send("The message you specified can either not be interpreted is non-existent. Please use either a combination of a channel id and a message id combined with a dash or a message URL.",ephemeral=True)
            return
            pass
        if msg_obj.id not in self.REACTION_ROLES.keys() or len(self.REACTION_ROLES[msg_obj.id].values()) == 0:
            await ctx.send("This message does not have any reaction roles",ephemeral=True)
            return
            pass

        embed = discord.Embed(colour=discord.Colour.red(),title="List of Reaction Roles")
        embed.description = "\n".join([f"{emoji}: {role.mention}" for emoji, role in self.REACTION_ROLES[msg_obj.id].items()])

        await ctx.send(embed=embed,ephemeral=True)
        pass

    @commands.Cog.listener("on_raw_reaction_add")
    @commands.Cog.listener("on_raw_reaction_remove")
    async def reaction_role_listener(self, payload : discord.RawReactionActionEvent):
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

    @commands.Cog.listener("on_ready")
    @utils.call_once_async
    async def reaction_role_collector(self):
        """Collects all the reaction roles saved in the database and stores them in RAM"""
        session : asql.AsyncSession = SESSION_FACTORY()

        try:
            result : CursorResult = await session.execute(sql.select(ReactionRoles))
            all_reactionroles : list[ReactionRoles] = result.scalars().all() # Get all reaction role objects

            for reaction_roles in all_reactionroles:
                message_id = int(reaction_roles.message_id)
                react_roles : ReactionRoleDict = reaction_roles.react_roles

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

        finally:
            await session.close()
        pass

    # Message Webhooks

    async def getTimeZone(self, guild_id : int):
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(Guild.timezone).where(Guild.id == str(guild_id)))
            timezone_text = result.scalar_one_or_none()
        finally:
            await session.close()
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

    @commands.command("schedule_msg",brief="Schedule a message to be sent later")
    async def schedule_msg(self, ctx : commands.Context, time : str, content : str):
        tz = await self.getTimeZone(ctx.guild.id)

        time_converter = TimeConverter()
        try:
            timeObj = await time_converter.convert(ctx,time,tz=tz) # Convert argument into a datetime object
            pass
        except commands.errors.BadArgument: # Give custom error message if the conversion failed
            await ctx.send("The time you gave was not formatted correctly. Make sure it fits these requirements:\n> Year-month-day pattern\n> One of these seperators: -./: <SPACE key> or no seperator\n> The time part is seperated by a semi-colon (;)\n> The time part has ':' as a seperator\n> The time you entered exists",ephemeral=True)
            return
            pass

        if timeObj <= datetime.now(timezone.utc):
            await ctx.send("As I don't have a time machine, this will be sadly impossible (Time is in the past)",ephemeral=True)
            return
            pass

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            result : CursorResult = await session.execute(sql.select(ScheduledMessages).where(ScheduledMessages.guild_id == str(ctx.guild.id)))
            scheduled_obj : ScheduledMessages = result.scalar_one_or_none()
            if scheduled_obj is None:
                scheduled_obj = ScheduledMessages(guild_id=str(ctx.guild.id),schedules=[])
                session.add(scheduled_obj)
                pass

            self.SCHEDULED_MSGS.setdefault(ctx.guild.id,[]) # Create an entry in the SCHEDULED_MSGS RAM dict for this guild if there wasn't one already

            scheduled_msg = (timeObj.timestamp(),ctx.channel.id,content,(ctx.author.display_name,ctx.author.avatar.url)) # Create scheduled_msg object
            scheduled_obj.schedules.append(scheduled_msg) # Add new scheduled Message to Database
            self.SCHEDULED_MSGS[ctx.guild.id].append(scheduled_msg) # Add scheduled msg to RAM
            
            await session.commit()
        finally:
            await session.close() # Commit & Close
        await ctx.send(
            "".join(("Scheduled following message to be sent on <t:{}>:\n".format(int(timeObj.timestamp())),content)),
            ephemeral=True
        )
        pass

    @commands.command("send_anon",brief="Send a message anonymously (no one will know who did it)")
    async def send_anon(self, ctx : commands.Context, message : str):
        webhook = await WEBHOOK_POOL.get(ctx.channel,reason="/send_anon required Webhook") # Retrieve Webhook from pool
        
        await webhook.send(message,username="Anonymous User") # Send message
        await ctx.send("Your message has been sent! (As you no doubt see)",ephemeral=True) # Send confirmation to prevent "interaction failed" error
        pass

    

    @tasks.loop(count=1)
    async def vote_collector(self):
        session : asql.AsyncSession = SESSION_FACTORY()
        for sql_guild in await session.execute(sql.select(Guild)):
            sql_guild : Guild
            for raw_vote in sql_guild.votes:
                vote_view = await VoteView.from_dict(VoteView,raw_vote)
                pass
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
        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            for guild in BOT.guilds:
                result : CursorResult = await session.execute(sql.select(ScheduledMessages).where(ScheduledMessages.guild_id==str(guild.id)))

                try:
                    scheduled_msgs : list[list[Timestamp,ChannelId,str,tuple[MemberName,AvatarUrl]]] = result.scalar_one().schedules
                except NoResultFound: # When there is no entry for this guild, jump to the next one
                    continue
                    pass

                self.SCHEDULED_MSGS.setdefault(guild.id,[])
                self.SCHEDULED_MSGS[guild.id].extend(scheduled_msgs)
                pass
        finally:
            await session.close()
        pass

    @tasks.loop(minutes=1,loop=loop)
    async def schedule_msg_worker(self):
        """Sends all scheduled messages that are due
        1. Assemble tasks that will return all messages that need be scheduled
        2. Gather all due messages
        3. Create task for each message
        4. Send all the messages
        """
        
        currentTS = datetime.now(timezone.utc).timestamp()
        loop = asyncio.get_event_loop()

        async def find_due_messages(guild_id : GuildId) -> tuple[GuildId,list[tuple[Timestamp,ChannelId,str,tuple[MemberName,AvatarUrl]]]]:
            due_messages = await loop.run_in_executor(None,filter,lambda scheduled_msg: scheduled_msg[0] <= currentTS,self.SCHEDULED_MSGS[guild_id]) # Filter through all scheduled messages to find those that are due (Uses executor for higher speed)
            return guild_id, list(due_messages)
            pass

        due_messages = await asyncio.gather(*[find_due_messages(guild_id) for guild_id in self.SCHEDULED_MSGS.keys()])
        if sum([len(messages) for _, messages in due_messages]) == 0: return # Skip all the rest if there aren't any due messages
        

        async def send_due_message(guild_id : GuildId,scheduled_msg : tuple[Timestamp,ChannelId,str,tuple[MemberName,AvatarUrl]]):
            # Set up some variables to make the code easier to read
            channel_id = scheduled_msg[1]
            content    = scheduled_msg[2]
            author_name= scheduled_msg[3][0]
            avatar_url = scheduled_msg[3][1]

            channel = await BOT.fetch_channel(channel_id) # Get the channel object neccessary to get the Webhook
            webhook = await WEBHOOK_POOL.get(channel,reason="Scheduled Message required a new Webhook") # Get the Webhook for this channel (or create a new one)

            await webhook.send(content,username=author_name,avatar_url=avatar_url) # Send the message

            self.SCHEDULED_MSGS[guild_id].remove(scheduled_msg) # Remove the message from RAM
            
            sql_obj = sql_msgs.get(guild_id) # Get the ScheduledMessage SQL Object for this guild or None if not found
            if sql_obj is None: return # Do nothing if not found
            try:
                sql_obj.schedules.remove(scheduled_msg) # Remove this message from the SQL Table
                pass
            except ValueError: # Ignore if message was not in SQL Table
                pass
            pass

        session : asql.AsyncSession = SESSION_FACTORY()
        try:
            # Get all SQL Database entries for scheduled messages
            required_guilds = [str(guild_id) for guild_id in list(zip(*due_messages))[0]]
            result : CursorResult = (await session.execute(sql.select(ScheduledMessages).where(ScheduledMessages.guild_id.in_(required_guilds))))
            sql_msgs : dict[GuildId,ScheduledMessages] = {int(scalar.guild_id):scalar for scalar in result.scalars()}

            await asyncio.gather(*[
                send_due_message(guild_id,scheduled_msg)

                for guild_id, scheduled_messages in due_messages
                for scheduled_msg in scheduled_messages
            ]) # Send all the due messages

            await session.commit()
        finally:
            await session.close()
        pass
    
    
    @tasks.loop(count=1,loop=loop)
    async def activity_changer(self):
        import activities, importlib

        await BOT.wait_for("ready")

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
async def setup(bot : commands.Bot):
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
    bot.add_cog(COG)
    logging.info("Added utility extension")
    pass

async def teardown(bot : commands.Bot):
    bot.remove_cog("Utility")
    
    for vote_view in COG.VOTE_PROCESSES.values():
        vote_view : VoteView
        vote_view.stop()
        pass
    pass