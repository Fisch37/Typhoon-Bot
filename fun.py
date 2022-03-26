from libs import config, utils
import random, logging, json
from typing import *
from collections import OrderedDict

import discord
from discord.ext import commands
from discord.ext.commands.converter import Option

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

    @commands.command(brief="Enable/Disable your clone",description="Enable/Disable your clone")
    @commands.guild_only()
    async def clone(self, ctx : commands.Context, state : bool):
        session : asql.AsyncSession = SESSION_FACTORY()
        result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id==str(ctx.guild.id)))
        
        guildObj : Guild = result.scalar_one_or_none()
        if guildObj is None: # If there is no data, there is no cloning
            isEnabled = False
        else:
            isEnabled = guildObj.clone_enabled
            try:
                isEnabled = guildObj.clone_filter[str(ctx.channel.id)]
            except KeyError:
                pass
            pass


        await session.rollback(); await session.close() # Close session

        if not isEnabled: # If cloning is not enabled, don't allow this command
            await ctx.send("Awwww... The machines are down... Maybe talk to the administrators if they could enable cloning, as it is disabled at the moment.",ephemeral=True)
            return
            pass

        self.CLONE_STATES.setdefault(ctx.guild.id,{}) # Make sure that there is dictionary for the current guild
        
        self.CLONE_STATES[ctx.guild.id][ctx.author.id] = state # Set the state

        await ctx.send(f"Cloning is now {'enabled' if state else 'disabled'}",ephemeral=True)
        pass

    ## Manage clones

    @commands.group(name="manage_clones", brief="Configuration for the clone system")
    async def manage_clones(self, ctx : commands.Context):
        pass

    @manage_clones.command(name="enable",brief="Completely enable/disable clones")
    @commands.guild_only()
    async def set_clone_mode(self, ctx : commands.Context, state : bool = Option(True,description="Whether or not cloning should be enabled")):
        if not ctx.author.guild_permissions.is_superset(discord.Permissions(manage_guild=True)):
            await ctx.send("You do not have permission for this command",ephemeral=True)
            return
            pass

        if not state: # Disable all clone in this guild if state==False
            self.CLONE_STATES.setdefault(ctx.guild.id,{}) # Make sure a dictionary for this guild exists
            self.CLONE_STATES[ctx.guild.id].clear()
            pass

        session : asql.AsyncSession = SESSION_FACTORY()

        result = await session.execute(sql.select(Guild).where(Guild.id == str(ctx.guild.id))) # Get the guild obj
        sqlGuild = result.scalar_one_or_none() # Actually assemble the Guild Obj from the row
        if sqlGuild is None: # Create new sql Guild Obj if it doesn't exist 
            sqlGuild = Guild(id=str(ctx.guild.id))
            session.add(sqlGuild) # Add Guild Obj to database
            pass
        sqlGuild.clone_enabled = state # Update state

        await session.commit() # Commit & close
        await session.close()

        if state:
            await ctx.send("So, cloning, eh? Interesting field of science... _Alright, start the machines! We trained this; come on!_",ephemeral=True)
        else:
            await ctx.send("Alright, alright, we'll shut the machines down... " + ("_Yes, shut them dow-- I know, I know, it's fine!_" if random.randrange(0,100)<30 else ""),ephemeral=True)
        pass

    @manage_clones.group(name="filter")
    async def manage_clones_filter(self, ctx : commands.Context):
        pass
    
    @manage_clones_filter.command(name="set",brief="Overrides the default clone setting for this channel")
    @commands.guild_only()
    @utils.perm_message_check("Sorry, but this action is only for the lab administrators (i.e. No Permission [need Manage Channel])\nhttps://tenor.com/view/no-i-dont-think-i-will-captain-america-old-capt-gif-17162888",manage_channels=True)
    async def set_clone_filter(self, ctx : commands.Context, state : bool = Option(description="Whether cloning should be enabled or disabled in this channel")):
        session : asql.AsyncSession = SESSION_FACTORY()

        result : CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(ctx.guild.id))) # Get the current guild from the SQL Table
        sqlGuild = result.scalar_one_or_none() # Retrieve the Guild object (or None if it doesn't exist)
        if sqlGuild is None: # Create a new entry if there is none at the moment
            sqlGuild = Guild(id=str(ctx.guild.id))
            session.add(sqlGuild)
            pass

        sqlGuild.clone_filter[str(ctx.channel.id)] = state # Update the filter for that specific channel

        self.CLONE_OVERRIDES.setdefault(ctx.guild.id,[None,None])
        self.CLONE_OVERRIDES[ctx.guild.id][1] = dict(sqlGuild.clone_filter) # Save overrides in RAM

        await session.commit()
        await session.close()

        await ctx.send(f"Well, this will get a little more complicated. Anyway, regardless of the original setting, you now {'''can''' if state else '''can't'''} use the clone system in this channel.",ephemeral=True)
        pass

    @manage_clones_filter.command("remove",brief="Removes any override for this channel")
    @commands.guild_only()
    @utils.perm_message_check("Sorry, this room is reserved for lab administrators only (No Permission [need Manage Channel])", manage_channels=True)
    async def rem_clone_filter(self, ctx : commands.Context):
        session : asql.AsyncSession = SESSION_FACTORY()

        result : CursorResult = await session.execute(sql.select(Guild.clone_filter).where(Guild.id == str(ctx.guild.id)))
        clone_filter : dict = result.scalar_one_or_none()

        if clone_filter is None: # Add new guild obj if it doesn't exist yet
            sqlGuild = Guild(id=str(ctx.guild.id))
            session.add(sqlGuild)
            clone_filter = sqlGuild.clone_filter
            pass

        try:
            clone_filter.pop(str(ctx.channel.id)) # Remove the channel override
        except KeyError:
            await ctx.send("As there is no actual override for this channel, nothing was changed. I admire your engagement, though!",ephemeral=True)
            pass
        else:
            await ctx.send("The override was removed. This channel will now conform to the regular settings.")
            pass

        self.CLONE_OVERRIDES.setdefault(ctx.guild.id,[None,None])
        self.CLONE_OVERRIDES[ctx.guild.id][1] = dict(clone_filter) # Save overrides in RAM
        
        await session.commit() # Commit & Close
        await session.close()
        pass

    @manage_clones_filter.command("show",brief="List all the clone overrides on this server")
    @commands.guild_only()
    @utils.perm_message_check("Oi! This data's classified! (No Permission [need Manage Channel])",manage_channels=True)
    async def show_clone_filter(self, ctx : commands.Context):
        session : asql.AsyncSession = SESSION_FACTORY()
        filterResult : CursorResult = await session.execute(sql.select(Guild.clone_filter).where(Guild.id == str(ctx.guild.id))) # Get all channel overrides
        
        cloneOverride : dict = filterResult.scalar_one_or_none() # Assemble channel overrides into a dict
        if cloneOverride is None:
            cloneOverride = {}
            pass
        del filterResult
        
        isEnabled : Optional[bool] = (await session.execute(sql.select(Guild.clone_enabled).where(Guild.id == str(ctx.guild.id)))).scalar_one_or_none() # Get if cloning is currently enabled
        
        self.CLONE_OVERRIDES[ctx.guild.id] = (bool(isEnabled),dict(cloneOverride)) # Copy overrides to RAM for the listener

        # Create dictionary with channel objects instead of ids
        channel_overrides = {}
        for channel_id, override in cloneOverride.items():
            channel = ctx.guild.get_channel(int(channel_id))
            channel_overrides[channel] = override
            pass
        # Create new sorted channel override dictionary
        ordered_channel_overrides : OrderedDict[discord.TextChannel,bool] = OrderedDict()
        for channel in sorted(channel_overrides,key=lambda key: key.position):
            ordered_channel_overrides[channel] = channel_overrides[channel]
            pass
        del channel_overrides, cloneOverride
        await session.close()

        embed = discord.Embed(colour=ctx.author.colour,title="Clone Channel Override")
        embed.description=f"Non-override cloning is {'Enabled' if isEnabled else 'Disabled'}"
        for channel, override in ordered_channel_overrides.items():
            embed.add_field(name=channel.name,value="Enabled" if override else "Disabled")
            pass

        await ctx.send(embed=embed,ephemeral=True)
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
            session : asql.AsyncSession = SESSION_FACTORY()
            result : CursorResult = await session.execute(sql.select(Guild.clone_enabled).where(Guild.id == str(msg.guild.id)))
            self.CLONE_OVERRIDES[msg.guild.id][0] = bool(result.scalar_one_or_none()) # Save clone_enabled in RAM (False if not in database)

            await session.close()
            pass

        if self.CLONE_OVERRIDES[msg.guild.id][1] is None:
            session : asql.AsyncSession = SESSION_FACTORY()
            result : CursorResult = await session.execute(sql.select(Guild.clone_filter).where(Guild.id == str(msg.guild.id)))
            try:
                self.CLONE_OVERRIDES[msg.guild.id][1] = dict(result.scalar_one()) # Retrieve overrides
                pass
            except KeyError:
                self.CLONE_OVERRIDES[msg.guild.id][1] = {} # Set overrides to an empty dict if not in SQL table
                pass
            await session.close() # Close session because that is neccessary
            pass

        clone_settings = self.CLONE_OVERRIDES[msg.guild.id]
        if not clone_settings[1].get(str(msg.channel.id)): return # Return if the channel is disabled via override
        elif not str(msg.channel.id) in clone_settings[1].keys() and not clone_settings[0]: return # Return if no override for this channel exists and cloning is off

        webhook = await WEBHOOK_POOL.get(msg.channel) # Get a webhook for this channel
        await webhook.send(msg.content,username=msg.author.display_name,avatar_url=msg.author.avatar.url)
        pass
    
    # Hehe, Tableshrug
    @commands.command("tableshrug",brief="Send a message with a tableshrug appended (┻━┻¯\_(ツ)_/¯┻━┻)")
    async def tableshrug(self, ctx : commands.Context, message : str = ""):
        webhook = await WEBHOOK_POOL.get(ctx.channel,reason="Tableshrug!")
        await webhook.send(message + " ┻━┻¯\_(ツ)_/¯┻━┻",username=ctx.author.display_name,avatar_url=ctx.author.avatar.url)
        await ctx.send("Message sent! (Well, obviously)",ephemeral=True)
        pass

    # GIF related stuff
    PATPATS : list[str] = []
    CUDDLES : list[str] = []

    @commands.command(name="passtheburrito",brief="Passes the burrito (or multiple, actually)")
    async def passtheburrito(self, ctx : commands.Context, amount : int = Option(1,description="The amount of burritos to pass (max 10)")):
        amount = min(amount,CONFIG.MAX_BURRITOS)
        for i in range(amount):
            await ctx.send("https://cdn.discordapp.com/attachments/734461254747553826/754372969890840627/image0-29.gif")
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

    @commands.command(name="patpat",brief="Pats are neat, I like 'em")
    async def patpat(
        self, 
        ctx : commands.Context, 
        target : discord.Member = Option(description="The server member to pat. Choose whoever you like!"), 
        comment : str = Option(None,description="An optional comment to attach to the message")
        ):
        message : discord.Message = ...

        class ResponseView(discord.ui.View):
            async def on_timeout(self) -> None:
                await message.edit(view=None)
                pass

            @discord.ui.button(label=f"Respond to {ctx.author.display_name}",style=discord.ButtonStyle.green)
            async def respond(view, button : discord.ui.Button, interaction : discord.Interaction):
                if interaction.user != target: # Only allow response for target
                    return
                    pass

                await ctx.send(embed=self.assemblePatpat(target,ctx.author,None,True))
                button.disabled = True
                view.stop()

                await message.edit(view=view)
                pass
            pass
        
        message = await ctx.send(embed=self.assemblePatpat(ctx.author,target,comment),view=ResponseView(timeout=CONFIG.PAT_CUDDLE_RESP_TIMEOUT))
        pass

    @commands.command(name="cuddle",brief="Cuddles! Nice, warm cuddles and hugs!")
    async def cuddle(
        self, 
        ctx : commands.Context,
        target : discord.Member = Option(description="The server member to hug. Choose whoever you like. Or don't like..."), 
        comment : str = Option(None,description="An optional comment to attach to the message")
        ): 
        message : discord.Message = ...

        class ResponseView(discord.ui.View):
            async def on_timeout(self) -> None:
                await message.edit(view=None)
                pass

            @discord.ui.button(label=f"Hug {ctx.author.display_name} back",style=discord.ButtonStyle.green)
            async def respond(view, button : discord.ui.Button, interaction : discord.Interaction):
                if interaction.user != target: # Only allow response for target
                    return
                    pass

                await ctx.send(embed=self.assembleCuddle(target,ctx.author,None,True))
                button.disabled = True
                view.stop()

                await message.edit(view=view)
                pass
            pass
        
        message = await ctx.send(embed=self.assembleCuddle(ctx.author,target,comment),view=ResponseView(timeout=CONFIG.PAT_CUDDLE_RESP_TIMEOUT))
        pass
    pass


def setup(bot : commands.Bot):
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
    bot.add_cog(Fun())

    with open(CONFIG.PATPAT_COLLECTION) as file:
        Fun.PATPATS = json.loads(file.read())
        pass

    with open(CONFIG.CUDDLE_COLLECTION) as file:
        Fun.CUDDLES = json.loads(file.read())
        pass
    logging.info("Added fun extension")
    pass

def teardown(bot : commands.Bot):
    bot.remove_cog("Fun")
    pass