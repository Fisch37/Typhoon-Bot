from libs import config, utils
import random, logging, json
from typing import *
from collections import OrderedDict

import discord
from discord.ext import commands
from discord import app_commands

import sqlalchemy.ext.asyncio as asql
from ormclasses import * # Also imports a whole bunch of stuff
from sqlalchemy.engine.cursor import CursorResult

CONFIG : config.Config = ...

BOT : commands.Bot = ...
WEBHOOK_POOL : utils.WebhookPool = ...

ENGINE : asql.AsyncEngine = ...
SESSION_FACTORY : orm.sessionmaker

class Fun(commands.Cog):
    """Includes a small amount of unproductive commands"""
    # Cloning
    CLONE_STATES : dict[int,dict[int,bool]] = {}
    CLONE_OVERRIDES : dict[int,list[bool,dict[int,bool]]] = {}

    @app_commands.command(description="Enable/Disable your clone")
    @app_commands.guild_only()
    async def clone(self, interaction: discord.Interaction, state : bool):
        async with SESSION_FACTORY() as session:
            result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id==str(interaction.guild_id)))
            
            guildObj : Guild = result.scalar_one_or_none()
            if guildObj is None: # If there is no data, there is no cloning
                isEnabled = False
            else:
                isEnabled = guildObj.clone_enabled
                try:
                    isEnabled = guildObj.clone_filter[str(interaction.channel_id)]
                except KeyError:
                    pass
                pass
            pass

        if not isEnabled: # If cloning is not enabled, don't allow this command
            await interaction.response.send_message("Awwww... The machines are down... Maybe talk to the administrators if they could enable cloning, as it is disabled at the moment.",ephemeral=True)
            return
            pass

        self.CLONE_STATES.setdefault(interaction.guild_id,{}) # Make sure that there is dictionary for the current guild
        
        self.CLONE_STATES[interaction.guild_id][interaction.user.id] = state # Set the state

        await interaction.response.send_message(f"Cloning is now {'enabled' if state else 'disabled'}",ephemeral=True)
        pass

    ## Manage clones

    manage_clones= app_commands.Group(name="manage_clones",description="Configuration for the clone system",guild_only=True)

    @manage_clones.command(name="enable",description="Completely enable/disable clones")
    @app_commands.guild_only()
    @app_commands.describe(state="Whether or not cloning should be enabled")
    async def set_clone_mode(self, interaction: discord.Interaction, state : bool= True):
        if not interaction.user.guild_permissions.is_superset(discord.Permissions(manage_guild=True)):
            await interaction.response.send_message("You do not have permission for this command",ephemeral=True)
            return
            pass

        if not state: # Disable all clone in this guild if state==False
            self.CLONE_STATES.setdefault(interaction.guild_id,{}) # Make sure a dictionary for this guild exists
            self.CLONE_STATES[interaction.guild_id].clear()
            pass

        async with SESSION_FACTORY() as session:
            result = await session.execute(sql.select(Guild).where(Guild.id == str(interaction.guild_id))) # Get the guild obj
            sqlGuild = result.scalar_one_or_none() # Actually assemble the Guild Obj from the row
            if sqlGuild is None: # Create new sql Guild Obj if it doesn't exist 
                sqlGuild = Guild(id=str(interaction.guild_id))
                session.add(sqlGuild) # Add Guild Obj to database
                pass
            sqlGuild.clone_enabled = state # Update state

            await session.commit()
            pass

        if state:
            await interaction.response.send_message("So, cloning, eh? Interesting field of science... _Alright, start the machines! We trained this; come on!_",ephemeral=True)
        else:
            await interaction.response.send_message("Alright, alright, we'll shut the machines down... " + ("_Yes, shut them dow-- I know, I know, it's fine!_" if random.randrange(0,100)<30 else ""),ephemeral=True)
        pass

    
    manage_clones_filter= app_commands.Group(name="filter", description="Filter who may use the clone feature and where",parent=manage_clones,guild_only=True)
    
    @manage_clones_filter.command(name="set",description="Overrides the default clone setting for this channel")
    @app_commands.describe(state="Whether cloning should be enabled or disabled in this channel")
    @app_commands.guild_only
    @utils.perm_message_check("Sorry, but this action is only for the lab administrators (i.e. No Permission [need Manage Channel])\nhttps://tenor.com/view/no-i-dont-think-i-will-captain-america-old-capt-gif-17162888",manage_channels=True)
    async def set_clone_filter(self, interaction: discord.Interaction, state : bool):
        async with SESSION_FACTORY() as session:
            result : CursorResult = await session.execute(
                sql.select(Guild)\
                .where(Guild.id == str(interaction.guild_id))
            ) # Get the current guild from the SQL Table
            sqlGuild = result.scalar_one_or_none() # Retrieve the Guild object (or None if it doesn't exist)
            if sqlGuild is None: # Create a new entry if there is none at the moment
                sqlGuild = Guild(id=str(interaction.guild_id))
                session.add(sqlGuild)
                pass

            sqlGuild.clone_filter[str(interaction.channel_id)] = state # Update the filter for that specific channel

            self.CLONE_OVERRIDES.setdefault(interaction.guild_id,[None,None])
            self.CLONE_OVERRIDES[interaction.guild_id][1] = dict(sqlGuild.clone_filter) # Save overrides in RAM

            await session.commit()
            pass

        await interaction.response.send_message(f"Well, this will get a little more complicated. Anyway, regardless of the original setting, you now {'''can''' if state else '''can't'''} use the clone system in this channel.",ephemeral=True)
        pass

    @manage_clones_filter.command(name="remove",description="Removes any override for this channel")
    @app_commands.guild_only()
    @utils.perm_message_check("Sorry, this room is reserved for lab administrators only (No Permission [need Manage Channel])", manage_channels=True)
    async def rem_clone_filter(self, interaction: discord.Interaction):
        async with SESSION_FACTORY() as session:
            result : CursorResult = await session.execute(sql.select(Guild.clone_filter).where(Guild.id == str(interaction.guild_id)))
            clone_filter : dict = result.scalar_one_or_none()

            if clone_filter is None: # Add new guild obj if it doesn't exist yet
                sqlGuild = Guild(id=str(interaction.guild_id))
                session.add(sqlGuild)
                clone_filter = sqlGuild.clone_filter
                pass

            clone_filter.get(str(interaction.channel_id))
            try:
                clone_filter.pop(str(interaction.channel_id)) # Remove the channel override
            except KeyError:
                await interaction.response.send_message("As there is no actual override for this channel, nothing was changed. I admire your engagement, though!",ephemeral=True)
                pass
            else:
                await interaction.response.send_message("The override was removed. This channel will now conform to the regular settings.", ephemeral=True)
                pass

            self.CLONE_OVERRIDES.setdefault(interaction.guild_id,[None,None])
            self.CLONE_OVERRIDES[interaction.guild_id][1] = dict(clone_filter) # Save overrides in RAM
            
            await session.execute(sql.update(Guild).where(Guild.id == str(interaction.guild_id)).values(clone_filter=clone_filter))
            await session.commit() # Commit & Close
            pass
        pass

    @manage_clones_filter.command(name="show",description="List all the clone overrides on this server")
    @app_commands.guild_only()
    @utils.perm_message_check("Oi! This data's classified! (No Permission [need Manage Channel])",manage_channels=True)
    async def show_clone_filter(self, interaction: discord.Interaction):
        async with SESSION_FACTORY() as session:
            filterResult : CursorResult = await session.execute(
                sql.select(Guild.clone_filter)\
                .where(Guild.id == str(interaction.guild_id))
            ) # Get all channel overrides
            isEnabled : Optional[bool] = (await session.execute(
                sql.select(Guild.clone_enabled)\
                .where(Guild.id == str(interaction.guild_id)))
            ).scalar_one_or_none() # Get if cloning is currently enabled
            pass
        
        cloneOverride : dict = filterResult.scalar_one_or_none() # Assemble channel overrides into a dict
        if cloneOverride is None:
            cloneOverride = {}
            pass
        del filterResult
        
        self.CLONE_OVERRIDES[interaction.guild_id] = [bool(isEnabled),dict(cloneOverride)] # Copy overrides to RAM for the listener

        # Create dictionary with channel objects instead of ids
        channel_overrides = {}
        for channel_id, override in tuple(cloneOverride.items()): # Converting to a tuple beforehand allows us to change the dictionary while iterating over it
            channel = interaction.guild.get_channel(int(channel_id))
            if channel is not None:
                channel_overrides[channel] = override
                pass
            else: # Remove invalid channels for safety (specifically to prevent errors in sorting later)
                cloneOverride.pop(channel_id)
                pass
            pass
        # Create new sorted channel override dictionary
        ordered_channel_overrides : OrderedDict[discord.TextChannel,bool] = OrderedDict()
        for channel in sorted(channel_overrides,key=lambda key: key.position):
            ordered_channel_overrides[channel] = channel_overrides[channel]
            pass
        del channel_overrides, cloneOverride

        embed = discord.Embed(colour=interaction.user.colour,title="Clone Channel Override")
        embed.description=f"Non-override cloning is {'Enabled' if isEnabled else 'Disabled'}"
        for channel, override in ordered_channel_overrides.items():
            embed.add_field(name=channel.name,value="Enabled" if override else "Disabled")
            pass

        await interaction.response.send_message(embed=embed,ephemeral=True)
        pass

    @commands.Cog.listener("on_message")
    async def clone_listener(self, msg : discord.Message):
        if msg.guild is None or msg.author.bot: return # Do not catch private messages or bot messages

        self.CLONE_STATES.setdefault(msg.guild.id,{}) # Make sure that there is dictionary for the current guild
        if not self.CLONE_STATES[msg.guild.id].get(msg.author.id): # Do nothing if author has cloning disabled
            return
            pass

        self.CLONE_OVERRIDES.setdefault(msg.guild.id,[None,None])
        if self.CLONE_OVERRIDES[msg.guild.id][0] is None:
            async with SESSION_FACTORY() as session:
                result : CursorResult = await session.execute(sql.select(Guild.clone_enabled).where(Guild.id == str(msg.guild.id)))
                self.CLONE_OVERRIDES[msg.guild.id][0] = bool(result.scalar_one_or_none()) # Save clone_enabled in RAM (False if not in database)
            pass

        if self.CLONE_OVERRIDES[msg.guild.id][1] is None:
            async with SESSION_FACTORY() as session:
                result : CursorResult = await session.execute(sql.select(Guild.clone_filter).where(Guild.id == str(msg.guild.id)))
                try:
                    self.CLONE_OVERRIDES[msg.guild.id][1] = dict(result.scalar_one()) # Retrieve overrides
                    pass
                except KeyError:
                    self.CLONE_OVERRIDES[msg.guild.id][1] = {} # Set overrides to an empty dict if not in SQL table
                    pass
                pass
            pass

        clone_settings = self.CLONE_OVERRIDES[msg.guild.id]
        if not clone_settings[1].get(str(msg.channel.id),True): return # Return if the channel is disabled via override
        elif not str(msg.channel.id) in clone_settings[1].keys() and not clone_settings[0]: return # Return if no override for this channel exists and cloning is off

        webhook = await WEBHOOK_POOL.get(msg.channel) # Get a webhook for this channel
        await webhook.send(msg.content,username=msg.author.display_name,avatar_url=msg.author.avatar.url)
        pass
    
    # Hehe, Tableshrug
    @app_commands.command(name="tableshrug",description="Send a message with a tableshrug appended (┻━┻¯\_(ツ)_/¯┻━┻)")
    async def tableshrug(self, interaction: discord.Interaction, message : str = ""):
        webhook = await WEBHOOK_POOL.get(interaction.channel,reason="Tableshrug!")
        await webhook.send(message + " ┻━┻¯\_(ツ)_/¯┻━┻",username=interaction.user.display_name,avatar_url=interaction.user.avatar.url)
        await interaction.response.send_message("Message sent! (Well, obviously)",ephemeral=True)
        pass

    # GIF related stuff
    PATPATS : list[str] = []
    CUDDLES : list[str] = []

    @app_commands.command(name="passtheburrito",description="Passes the burrito (or multiple, actually)")
    @app_commands.describe(amount="The amount of burritos to pass (max 10)")
    async def passtheburrito(self, interaction: discord.Interaction, amount: int= 1):
        await interaction.response.defer()

        amount = min(amount,CONFIG.MAX_BURRITOS)
        for i in range(amount):
            await interaction.followup.send("https://cdn.discordapp.com/attachments/734461254747553826/754372969890840627/image0-29.gif")
            pass
        pass


    def assembleCuddle(self,author : discord.Member,target : discord.Member, comment : str = None,is_response : bool = False) -> discord.Embed:
        embed = discord.Embed(
            type="gifv",
            colour=author.colour,
        )
        if is_response:
            if target==author:
                embed.title = "This is getting immensly complex... Anyway, you're hugging yourself back!"
                pass
            else:
                embed.title = "{0} is hugging {1} back; neat!".format(author.display_name,target.display_name)
                pass
            pass
        else:
            if target==author:
                embed.title = "You want a hug, {0}? Come here!".format(author.display_name)
                pass
            else:
                embed.title = "{0} is hugging {1}! ".format(author.display_name,target.display_name)
            pass

        embed.set_image(url=random.choice(self.CUDDLES))
        embed.set_author(name=author.display_name,icon_url=author.avatar.url)
        if comment is not None:
            embed.description = comment
            pass

        return embed
        pass

    def assemblePatpat(self, author : discord.Member, target : discord.Member, comment : str = None, is_response : bool = False) -> discord.Embed:
        embed = discord.Embed(
            type="gifv",
            colour=author.colour,
        )
        if is_response:
            if target==author:
                embed.title = "Hmmmm... I assume that's possible, yeah. Pat yourself back!"
                pass
            else:
                embed.title = "Patting back? A little unusual, but if {0} wants to pat {1} back, that's fine of course.".format(author.display_name,target.display_name)
                pass
            pass
        else:
            if target==author:
                embed.title = "Pats are good even if you give them yourself!"
                pass
            else:
                embed.title = "{0} is patting {1}; how cute! ".format(author.display_name,target.display_name)
            pass

        embed.set_image(url=random.choice(self.PATPATS))
        embed.set_author(name=author.display_name,icon_url=author.avatar.url)
        if comment is not None:
            embed.description = comment
            pass

        return embed
        pass

    @app_commands.command(name="patpat",description="Pats are neat, I like 'em")
    @app_commands.describe(target="The server member to pat. Choose whoever you like!", comment="An optional comment to attach to the message")
    @app_commands.guild_only
    async def patpat(
        self, 
        interaction: discord.Interaction, 
        target : discord.Member, 
        comment : str = None
        ):
        await interaction.response.defer()

        message : discord.Message = ...

        class ResponseView(discord.ui.View):
            async def on_timeout(self) -> None:
                await message.edit(view=None)
                pass

            @discord.ui.button(label=f"Respond to {interaction.user.display_name}",style=discord.ButtonStyle.green)
            async def respond(view, vinteraction : discord.Interaction, button : discord.ui.Button):
                if vinteraction.user != target: # Only allow response for target
                    return
                    pass

                await vinteraction.response.send_message(embed=self.assemblePatpat(target,interaction.user,None,True))
                button.disabled = True
                view.stop()

                await message.edit(view=view)
                pass
            pass
        
        message = await interaction.followup.send(
            embed=self.assemblePatpat(interaction.user,target,comment),
            view=ResponseView(timeout=CONFIG.PAT_CUDDLE_RESP_TIMEOUT)
        )
        pass

    @app_commands.command(name="cuddle",description="Cuddles! Nice, warm cuddles and hugs!")
    @app_commands.describe( target="The server member to hug. Choose whoever you like. Or don't like...", 
                            comment="An optional comment to attach to the message"
    )
    @app_commands.guild_only
    async def cuddle(
        self, 
        interaction: discord.Interaction,
        target : discord.Member, 
        comment : str = None
        ): 
        await interaction.response.defer()

        message : discord.WebhookMessage = ...

        class ResponseView(discord.ui.View):
            async def on_timeout(self) -> None:
                await message.edit(view=None)
                pass

            @discord.ui.button(label=f"Hug {interaction.user.display_name} back",style=discord.ButtonStyle.green)
            async def respond(view, vinteraction : discord.Interaction, button : discord.ui.Button):
                if interaction.user != target: # Only allow response for target
                    return
                    pass

                await vinteraction.response.send_message(embed=self.assembleCuddle(target,interaction.user,None,True))
                button.disabled = True
                view.stop()

                await message.edit(view=view)
                pass
            pass
        
        message = await interaction.followup.send(
            embed=self.assembleCuddle(interaction.user,target,comment),
            view=ResponseView(timeout=CONFIG.PAT_CUDDLE_RESP_TIMEOUT)
        )
        pass
    pass


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
    # The rest
    bot.DATA.CLONE_OVERRIDES= Fun.CLONE_OVERRIDES

    await bot.add_cog(Fun())

    with open(CONFIG.PATPAT_COLLECTION) as file:
        Fun.PATPATS = json.loads(file.read())
        pass

    with open(CONFIG.CUDDLE_COLLECTION) as file:
        Fun.CUDDLES = json.loads(file.read())
        pass
    logging.info("Added fun extension")
    pass

async def teardown(bot : commands.Bot):
    await bot.remove_cog("Fun")
    pass