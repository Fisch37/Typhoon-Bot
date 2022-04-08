"""
Configuration! That's all
"""
from leveling import LevelSettings
from libs import utils, config
from libs.config_base import branch_factory, element_factory, ConfigElement, ConfigButton, ConfigSelect, CONFIG_TIMEOUT
from libs.interpret_levelup import VAR_DESCR as LVL_UP_MSG_VAR_DESCR, raw_format as lvl_up_formatter
from libs.converters.time import DurationConverter, OutOfOrderException
from logging_utils import LoggingSettings, translation_table as LOGGING_TRANSLATE
import asyncio

import discord
from discord.ext import commands
from discord.ext.commands.converter import Option

import sqlalchemy as sql, sqlalchemy.ext.asyncio as asql
from ormclasses import *
# Declare constants
CONFIG : config.Config = ...

BOT : commands.Bot = ...
WEBHOOK_POOL : utils.WebhookPool = ...

ENGINE : asql.AsyncEngine = ...
SESSION_FACTORY : orm.sessionmaker = ...

#####################################################

#
async def update(self : ConfigElement):
    guild = self.ctx.guild
    
    god_role_ids = BOT.DATA.GOD_ROLES[self.ctx.guild.id]
    god_roles = [guild.get_role(int(role_id)) for role_id in god_role_ids]
    
    self.embed.clear_fields()
    self.embed.add_field(name="Current god roles",value="\n".join([role.mention for role in god_roles]) or "None")
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    BOT.DATA.GOD_ROLES.setdefault(self.ctx.guild.id,set())
    god_roles = BOT.DATA.GOD_ROLES[self.ctx.guild.id]
    if isinstance(element,discord.ui.Button):
        if element.label == "Add":
            await interaction.followup.send("Please reply with a role you wish to add as a God Role",ephemeral=True)
            role = await utils.wait_for_role(BOT,self.ctx,"The message you sent did not contain a role. Please try again.",timeout=CONFIG.EDIT_TIMEOUT)

            god_roles.add(str(role.id))
            await interaction.followup.send(f"Added {role.mention} as a god role!",ephemeral=True)
            pass
        elif element.label == "Remove":
            await interaction.followup.send("Please reply with a role you wish to remove as a God Role",ephemeral=True)
            while True:
                role = await utils.wait_for_role(BOT,self.ctx,"The message you sent did not contain a role. Please try again.",timeout=CONFIG.EDIT_TIMEOUT)
                if str(role.id) not in god_roles:
                    await interaction.followup.send("This role is not a god role. Please supply a god role.",ephemeral=True)
                    pass
                else:
                    break
                pass

            god_roles.remove(str(role.id))
            await interaction.followup.send(f"Removed {role.mention} from the list of god roles!",ephemeral=True)
            pass
        if element.label in ("Add","Remove"):
            session : asql.AsyncSession = SESSION_FACTORY()
            result = await session.execute(sql.select(Guild).where(Guild.id == str(self.ctx.guild.id)))
            
            sql_guild = result.scalar_one_or_none()
            if sql_guild is None: 
                sql_guild = Guild(id=str(self.ctx.guild.id))
                session.add(sql_guild)
                pass
            sql_guild.god_roles = list(god_roles)
            
            await session.commit(); await session.close()

            await self.update()
            pass
        pass
    pass

Mod_Gods = element_factory(
    "God roles",
    short_description="Select which roles will be unaffected by Automod",
    long_description="God roles are roles with which a user will be ignored by any Automod settings.",
    update_callback=update,
    view_interact_callback=on_interaction,
    colour=discord.Colour.yellow(),
    options = [
        ConfigButton(discord.ButtonStyle.primary,"Add",row=0),
        ConfigButton(discord.ButtonStyle.secondary,"Remove",row=0)
    ]
)

#

async def update(self : ConfigElement):
    guild = self.ctx.guild

    async with SESSION_FACTORY() as session:
        session : asql.AsyncSession
        result : CursorResult = await session.execute(sql.select(Guild.logging_settings).where(Guild.id == str(guild.id)))
        log_settings = LoggingSettings.from_value(result.scalar_one_or_none() or 0)
        pass

    for select_menu in self.view.children: 
        if isinstance(select_menu,discord.ui.Select): break
        pass
    
    for option in select_menu.options:
        option.default = not getattr(log_settings,option.value)
        pass
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    """TODO: Add functionality!"""
    if isinstance(element,discord.ui.Select):
        logging_settings = BOT.DATA.LOGGING_SETTINGS[self.ctx.guild.id] = LoggingSettings()
        for value in element.values:
            setattr(logging_settings,value,True)
            pass
        session = SESSION_FACTORY()
        sql_guild = await utils.get_guild(session,self.ctx.guild.id)
        sql_guild.logging_settings = logging_settings.to_value()
        await session.commit(); await session.close()
        pass
    elif element.label == "Set Channel":
        await interaction.followup.send("Please reply with the text channel you want logging to happen in", ephemeral=True)
        while True:
            channel : discord.TextChannel = await utils.wait_for_text_channel(BOT,self.ctx,"The message you sent could not be interpreted as a text channel. Please try again")
            if channel.guild == self.ctx.guild: break
            else: await interaction.followup.send("The channel you passed doesn't exist on this server. Please pass a channel on this server",ephemeral=True)
            pass
        
        BOT.DATA.LOGGING_CHANNEL[self.ctx.guild.id] = channel.id
        session : asql.AsyncSession = SESSION_FACTORY()
        sql_guild = await utils.get_guild(session,self.ctx.guild.id)
        sql_guild.logging_channel = str(channel.id)
        await session.commit(); await session.close()

        await interaction.followup.send(f"The Logging Channel has been changed to {channel.mention}!",ephemeral=True)
        pass
    elif element.label == "Disable":
        session : asql.AsyncSession = SESSION_FACTORY()
        sql_guild = await utils.get_guild(session, self.ctx.guild.id)
        sql_guild.logging_channel = None
        sql_guild.logging_state = False
        await session.commit(); await session.close()
        pass
    pass

Mod_Logging = element_factory(
    "Logging",
    short_description="Select which events will be logged where",
    long_description="The logging functionality enables you to observe what people are doing on your server (even mods). Here you can configure the events being logged as well as the channel logging will take place in.",
    update_callback=update,
    view_interact_callback=on_interaction,
    colour=discord.Colour.yellow(),
    options = [
        ConfigSelect(range(0,10),placehold_text="Select the events to enable logging for",options=(
            # Yes, I copy-pasted this from moderation.py. No, I'm not sorry
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
        )),
        ConfigButton(discord.ButtonStyle.primary,"Set Channel",row=1),
        ConfigButton(discord.ButtonStyle.secondary,"Disable",row=1)
    ]
)

#

async def update(self : ConfigElement):
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    pass

Mod_Automod = element_factory(
    "Automod",
    short_description="Configure settings for automatic moderation",
    long_description="Automod allows you to automatically moderate users on this server. This includes message spam, capslock spam, and emoji spam. Here, you can modify certain variables regarding these types.",
    update_callback=update,
    view_interact_callback=on_interaction,
    colour=discord.Colour.yellow(),
    options=[
        ConfigButton(discord.ButtonStyle.primary,"Spam Message Repetition",row=0), ConfigButton(discord.ButtonStyle.secondary,"Spam Message Similarity",row=0), ConfigButton(discord.ButtonStyle.success,"Message Spam Consequences",row=0),
        ConfigButton(discord.ButtonStyle.primary,"Caps Max Percentage",row=1), ConfigButton(discord.ButtonStyle.secondary,"Caps Min Length",row=1), ConfigButton(discord.ButtonStyle.success,"Caps Spam Consequences",row=1),
        ConfigButton(discord.ButtonStyle.primary,"Emoji Max Percentage",row=2), ConfigButton(discord.ButtonStyle.secondary,"Emoji Min Length",row=2), ConfigButton(discord.ButtonStyle.success,"Emoji Spam Consequences",row=2),
    ]
)

# 

Moderation = branch_factory(
    "Moderation",
    short_description="Settings for all Moderation features",
    long_description="Use the menu to select one of the branches listed",
    colour = discord.Colour.yellow(),
    children=[
        Mod_Gods,
        Mod_Logging,
        Mod_Automod
    ]
)
Mod_Gods.PARENT = Mod_Logging.PARENT = Mod_Automod.PARENT = Moderation
####

def assure_level_settings(guild_id) -> LevelSettings:
    BOT.DATA.LEVEL_SETTINGS.setdefault(guild_id,LevelSettings())
    return BOT.DATA.LEVEL_SETTINGS[guild_id]
    pass

async def update(self : ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)

    self.embed.clear_fields()
    self.embed.add_field(name="Leveling State",value="Enabled" if lvl_settings.enabled else "Disabled",inline=False)
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    if isinstance(element,discord.ui.Button):
        lvl_settings = assure_level_settings(self.ctx.guild.id)
        if element.label == "Enable":
            lvl_settings.enabled = True
            
            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild : Guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.level_state = True
            await session.commit(); await session.close()

            await interaction.followup.send("Leveling is now enabled!",ephemeral=True)
            pass
        elif element.label == "Disable":
            lvl_settings.enabled = False

            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild : Guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.level_state = False
            await session.commit(); await session.close()

            await interaction.followup.send("Leveling is now disabled!",ephemeral=True)
            pass
        pass
    pass

Lvl_state = element_factory(
    "Leveling State",
    short_description="Enable/Disable the Leveling system.",
    long_description="This branch does what it says on the tin. Press the respective button to enable/disable level ups.",
    colour = discord.Colour.brand_green(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(discord.ButtonStyle.green,"Enable"),
        ConfigButton(discord.ButtonStyle.red,"Disable")
    ]
)

#

async def update(self : ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)

    self.embed.clear_fields()
    self.embed.add_field(name="Lower gain",value=str(lvl_settings.lower_gain))
    self.embed.add_field(name="Upper gain",value=str(lvl_settings.upper_gain))
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    async def update_gain(ram_key, sql_key, val):
        lvl_settings = assure_level_settings(self.ctx.guild.id)

        session = SESSION_FACTORY()
        sql_guild = await utils.get_guild(session,self.ctx.guild.id)

        setattr(lvl_settings,ram_key,val)
        setattr(sql_guild,sql_key,val)

        await session.commit(); await session.close()
        pass


    if isinstance(element, discord.ui.Button):
        # Sets
        if element.label == "Set Lower Gain":
            await interaction.followup.send("Please send a message with the Upper Gain you want to set",ephemeral=True)

            lvl_settings = assure_level_settings(self.ctx.guild.id)
            gain = await utils.wait_for_convert(
                BOT,self.ctx,utils.IntConverter(),
                "Your message could not be interpreted as a positive integer (i.e. whole number >0). Also check that the value is not larger than the current Upper Gain.",
                lambda new_lower_gain: new_lower_gain <= lvl_settings.upper_gain
            )

            await update_gain("lower_gain","lower_xp_gain",gain)

            await interaction.followup.send(f"Updated lower gain to {lvl_settings.lower_gain}!",ephemeral=True)
            pass
        elif element.label == "Set Upper Gain":
            await interaction.followup.send("Please send a message with the Upper Gain you want to set",ephemeral=True)

            lvl_settings = assure_level_settings(self.ctx.guild.id)
            gain = await utils.wait_for_convert(
                BOT,self.ctx,utils.IntConverter(),
                "Your message could not be interpreted as a positive integer (i.e. whole number >0). Also check that the value is not larger than the current Upper Gain.",
                lambda new_upper_gain: new_upper_gain >= lvl_settings.lower_gain
            )
            
            await update_gain("upper_gain","upper_xp_gain",gain)

            await interaction.followup.send(f"Updated upper gain to {lvl_settings.upper_gain}!",ephemeral=True)
            pass

        # Resets
        elif element.label == "Reset Lower Gain":
            default_gain = Guild.lower_xp_gain.default.arg
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            if lvl_settings.upper_gain < default_gain:
                await interaction.followup.send(f"This action would cause the Lower Gain to be lower than the Upper Gain.\nPlease set the Upper Gain to a value smaller than {default_gain} and try again.",ephemeral=True)
            else:
                await update_gain("lower_gain","lower_xp_gain",default_gain)
            pass
        elif element.label == "Reset Upper Gain":
            default_gain = Guild.upper_xp_gain.default.arg
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            if lvl_settings.lower_gain > default_gain:
                await interaction.followup.send(f"This action would cause the Upper Gain to be lower than the Lower Gain.\nPlease set the Lower Gain to a value smaller than {default_gain} and try again.",ephemeral=True)
            else:
                await update_gain("upper_gain","upper_xp_gain",default_gain)
            pass
        pass
    pass

Lvl_xp = element_factory(
    "XP Gain",
    short_description="Manage how much XP a user gets per message",
    long_description="The XP gain for a message is randomised according to two values.\n1. is the Lower Bound. It is the minimal amount of XP a user can get per message.\n2. Is the Upper Bound. It is the maximum amount of XP a user can get per message.",
    colour=discord.Colour.brand_green(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(discord.ButtonStyle.primary,"Set Lower Gain",row=0), ConfigButton(discord.ButtonStyle.secondary,"Reset Lower Gain",row=0), 
        ConfigButton(discord.ButtonStyle.primary,"Set Upper Gain",row=1), ConfigButton(discord.ButtonStyle.secondary,"Reset Upper Gain",row=1)
    ]
)

#
async def update(self : ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)
    
    self.embed.clear_fields()
    self.embed.add_field(name="XP Timeout",value=utils.stringFromDuration(lvl_settings.timeout),inline=False)
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    if isinstance(element,discord.ui.Button):
        lvl_settings = assure_level_settings(self.ctx.guild.id)
        
        if element.label == "Set Timeout":
            await interaction.followup.send("Please send a time formatted like `<hours>H<minutes>M<seconds>S` to change the cooldown for xp gain",ephemeral=True)
            converter = DurationConverter()
            while True:
                msg : discord.Message = await BOT.wait_for("message",check=lambda msg: msg.channel == self.ctx.channel and msg.author == self.ctx.author,timeout=CONFIG.EDIT_TIMEOUT)
                try:
                    timeout = await converter.convert(self.ctx,msg.content)
                except OutOfOrderException:
                    await interaction.followup.send("Your message breaks the format specified previously. It seems you messed up the order of some values. Please check that you are following this format.",ephemeral=True)
                    pass
                except commands.BadArgument:
                    await interaction.followup.send("The values specified with the format cannot be interpreted. Please check all values are integers and no text other than that specified with the format exists.",ephemeral=True)
                    pass
                else:
                    break
                finally:
                    await msg.delete()
                    pass
                pass

            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            lvl_settings.timeout = sql_guild.xp_timeout = timeout
            await session.commit(); await session.close()

            await interaction.followup.send(f"Set XP Gain Timeout to {utils.stringFromDuration(timeout)}",ephemeral=True)
            pass
        elif element.label == "Reset Timeout":
            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            lvl_settings.timeout = sql_guild.xp_timeout = Guild.xp_timeout.default.arg
            await session.commit(); await session.close()

            await interaction.followup.send(f"Reset XP Gain Timeout to {utils.stringFromDuration(lvl_settings.timeout)}!",ephemeral=True)
            pass
        pass
    pass

Lvl_timeout = element_factory(
    "Message Timeout",
    short_description="Manage how long it should take until a user can gain XP again",
    long_description="To prevent spamming, the Leveling feature only allows a user to gain XP a certain amount of time after the last gain. This value can be set to anything you like. Setting it to 0 will allow users to gain XP without any timeout. Do consider though, that messages deleted by the Automod will still count towards the user's XP.",
    colour = discord.Colour.brand_green(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(discord.ButtonStyle.primary,"Set Timeout"),
        ConfigButton(discord.ButtonStyle.secondary,"Reset Timeout")
    ]
)

#
async def update(self : ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)
    
    if lvl_settings.channel_id is not None:
        channel = self.ctx.guild.get_channel(lvl_settings.channel_id)
        if channel is None: 
            lvl_settings.channel_id = None
            channel_str = "Current"
        else: channel_str = channel.mention
    else:
        channel_str = "Current"

    self.embed.clear_fields()
    self.embed.add_field(name="Channel",value=channel_str,inline=False)
    self.embed.add_field(name="Current message template",value=lvl_settings.level_msg,inline=False)
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    if isinstance(element,discord.ui.Button):
        if element.label == "Set Message":
            embed = discord.Embed(colour=discord.Colour.brand_green(),title="Variables")
            
            var_names, var_descr = zip(*LVL_UP_MSG_VAR_DESCR)
            embed.add_field(name="Variables",value="\n".join(var_names))
            embed.add_field(name="Description",value="\n".join(var_descr))
            # TODO: Fix misalignment of descriptions when using multiple lines
            
            await interaction.followup.send("Please send the message template you want to apply. Below is a list of variables that will be applied. A variable must always be surrounded by {}",embed=embed,ephemeral=True)

            while True:
                msg : discord.Message = await BOT.wait_for("message",check=lambda msg: msg.channel == self.ctx.channel and msg.author == self.ctx.author)
                new_template = msg.content
                await msg.delete()
                if len(new_template) > 200:
                    await interaction.followup.send("The template cannot be larger than 200 characters. Please shorten your template.",ephemeral=True)
                    pass
                else: break
                pass

            example_message = lvl_up_formatter(
                new_template,
                msg.author.name,
                msg.author.display_name,
                msg.author.mention,
                msg.guild.name,
                msg.guild.member_count,
                9001,
                42,
                -5,
                "#example_channel",
                "#example_send_channel"
            )

            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.level_msg = new_template
            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.level_msg = new_template
            await session.commit(); await session.close()

            await interaction.followup.send(f"The template has been set. Following is an example message:\n\n{example_message}",ephemeral=True)
            pass
        elif element.label == "Set Channel":
            await interaction.followup.send("Please send a channel you wish to have your level-ups appear in.",ephemeral=True)
            while True:
                """FIX: TypeError: 'NoneType' object is not callable"""
                channel = await utils.wait_for_text_channel(
                    BOT,self.ctx,
                    "The message you sent could not be interpreted as a text channel. Please make sure to only send a #text_channel format.",
                    CONFIG.EDIT_TIMEOUT
                )
                if channel.guild != self.ctx.guild:
                    await interaction.followup.send("The channel you specified doesn't exist on this server. Please supply a channel on this server.",ephemeral=True)
                    pass
                else:
                    break
                pass
            # Update setting in RAM
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.channel_id = channel.id
            # Update setting in database
            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.level_channel = str(channel.id)
            await session.commit(); await session.close()
            pass

        elif element.label == "Reset Message":
            new_template = Guild.level_msg.default.arg # This is just because I couldn't be bothered to change two lines of code
            # Update setting in RAM
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.level_msg = new_template
            # Update setting in Database
            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.level_msg = new_template
            await session.commit(); await session.close()

            await interaction.followup.send("Reset message template!", ephemeral=True)
            pass
        elif element.label == "Reset message location":
            # Update setting in RAM
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.channel_id = None
            # Update setting in database
            session : asql.AsyncSession = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.level_channel = None
            await session.commit(); await session.close()
            pass
        pass
    pass

Lvl_msgs = element_factory(
    "Level Up Messages",
    short_description="Set a custom message to be sent when a user levels up.",
    long_description="When a user gains enough XP, they will gain a Level Up. These Level Ups are usually sent in the channel they sent their last message and take the form of `Geez, {user.mention}! You leveled up to level {level}`.\nHere you can set a custom channel for the level ups and also change the message sent.",
    colour = discord.Colour.brand_green(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(discord.ButtonStyle.primary,"Set Message",row=0), ConfigButton(discord.ButtonStyle.secondary,"Reset Message",row=0),
        ConfigButton(discord.ButtonStyle.primary,"Set Channel",row=1), ConfigButton(discord.ButtonStyle.secondary,"Reset message location",row=1)
    ]
)

#

Leveling = branch_factory(
    "Leveling",
    short_description="Settings for the Leveling feature",
    long_description="Leveling is a feature that allows users to gain XP by sending messages on a server. These XP are local to the server and thus the server moderators (i.e. you) can change the governing values however they like. Below are three categories managing different bits and pieces of the Leveling system.",
    colour=discord.Colour.brand_green(),
    children=[
        Lvl_state,
        Lvl_xp,
        Lvl_timeout,
        Lvl_msgs
    ]
)
Lvl_state.PARENT = Lvl_xp.PARENT = Lvl_timeout.PARENT = Lvl_msgs.PARENT = Leveling

####

async def assure_clone_overrides(guild_id : int) -> tuple[bool,dict[int,bool]]:
    data = BOT.DATA.CLONE_OVERRIDES.get(guild_id)
    if data is None:
        session = SESSION_FACTORY()
        sql_guild = await utils.get_guild(session,guild_id)
        data = BOT.DATA.CLONE_OVERRIDES[guild_id] = [sql_guild.clone_enabled, {int(k):v for k,v in sql_guild.clone_filter.items()}]
        pass

    return data
    pass

async def store_clone_overrides(guild_id : int, overrides : dict[int,bool]):
    session = SESSION_FACTORY()
    sql_guild = await utils.get_guild(session,guild_id)
    sql_guild.clone_filter = overrides
    await session.commit(); await session.close()
    pass

async def update(self : ConfigElement):
    session : asql.AsyncSession = SESSION_FACTORY()
    result : CursorResult = await session.execute(sql.select(Guild.clone_enabled).where(Guild.id == str(self.ctx.guild.id)))
    clone_enabled = result.scalar_one_or_none()
    await session.close()

    self.embed.clear_fields()
    self.embed.add_field(name="Clone State",value="Enabled" if clone_enabled else "Disabled")
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    async def update_state(state : bool):
        session = SESSION_FACTORY()
        (await utils.get_guild(session,self.ctx.guild.id)).clone_enabled = True
        await session.commit(); await session.close()

        await interaction.followup.send(f"Cloning is now {'enabled' if state else 'disabled'}!", ephemeral=True)
        pass
    if isinstance(element,discord.ui.Button):
        if element.label == "Enable":
            await update_state(True)
            pass
        elif element.label == "Disable":
            await update_state(True)
            pass
        pass
    pass

Clone_State = element_factory(
    "Clone State",
    short_description="Enable/Disable clones",
    long_description="This is what it says on the tin. You can enable or disable the clone functionality here. Note that this does not reset the filters.",
    colour = discord.Colour.dark_magenta(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(discord.ButtonStyle.success,"Enable",None),
        ConfigButton(discord.ButtonStyle.danger,"Disable",None)
    ]
)

#

async def update(self : ConfigElement):
    _, overrides = await assure_clone_overrides(self.ctx.guild.id)
    channel_ids, states = zip(*overrides.items())

    self.embed.clear_fields()
    channel_str = "\n".join([self.ctx.guild.get_channel(int(channel_id)).mention for channel_id in channel_ids if self.ctx.guild.get_channel(int(channel_id)) is not None])
    override_str= "\n".join(["Enabled" if override_state else "Disabled" for override_state in states])
    self.embed.add_field(name="Filter Channel",value=channel_str if len(channel_str) > 0 else "Empty")
    self.embed.add_field(name="Override",value=override_str if len(override_str) > 0 else "Empty")
    pass

async def on_interaction(self : ConfigElement, element : discord.ui.Item, interaction : discord.Interaction):
    async def get_filter_channel(start_message : str, error_msg : str = None, extra_check = lambda channel: True):
        await interaction.followup.send(start_message,ephemeral=True)
        while True:
            channel = await utils.wait_for_text_channel(
                BOT,self.ctx,
                "The argument you supplied is not a text channel or does not exist on this server.",
                CONFIG.EDIT_TIMEOUT
            )
            if not extra_check(channel):
                await interaction.followup.send(error_msg,ephemeral=True)
            else: break
            pass

        return channel
        pass

    if isinstance(element, discord.ui.Button):
        if element.label == "Add deny filter":
            channel = await get_filter_channel("Please enter a channel to add the filter for")

            _, overrides = await assure_clone_overrides(self.ctx.guild.id)
            overrides[channel.id] = False
            await store_clone_overrides(self.ctx.guild.id,overrides)

            await interaction.followup.send(f"Cloning is now disabled in {channel.mention}!",ephemeral=True)
            pass
        elif element.label == "Add allow filter":
            channel = await get_filter_channel(
                "Please enter a channel to add the filter for"
                )
            
            _, overrides = await assure_clone_overrides(self.ctx.guild.id)
            overrides : dict[int,bool]
            overrides[channel.id] = True
            await store_clone_overrides(self.ctx.guild.id,overrides)

            await interaction.followup.send(f"Cloning is now enabled in {channel.mention}!",ephemeral=True)
            pass
        elif element.label == "Remove filter":
            _, overrides = await assure_clone_overrides(self.ctx.guild.id)
            channel = await get_filter_channel(
                "Please enter a channel you want to remove the filter for",
                "There is no filter for this channel",
                lambda channel: channel.id in overrides.keys()
            )

            overrides.pop(channel.id)
            await store_clone_overrides(self.ctx.guild.id,overrides)

            await interaction.followup.send(f"The filter for {channel.mention} has been removed. The channel will now follow the default setting for cloning.",ephemeral=True)
            pass
        pass
    pass

Clone_Filter = element_factory(
    "Clone Filter",
    short_description="Enable/Disable clones for specific channels",
    long_description="Here you can set filters for any channel you like. These will override the default Clone State meaning you can enable clones for just one channel",
    colour = discord.Colour.dark_magenta(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(discord.ButtonStyle.red,"Add deny filter"), ConfigButton(discord.ButtonStyle.green,"Add allow filter"),
        ConfigButton(discord.ButtonStyle.gray,"Remove filter",row=1)
    ]
)

#

Clones = branch_factory(
    "Clones",
    short_description="Manage settings for the clone functionality",
    long_description="The clone feature stems from the Fun category. Enabling it makes a webhook copy every message a user sends in the same channel. I do not see a practical use for it, however if you want to let your users have fun in #spam, this is perfect.\nYou can restrict the channels the Clone will work in, outside them, the bot will just not reply.",
    colour=discord.Colour.dark_magenta(),
    children=[
        Clone_State,
        Clone_Filter
    ]
)

Clone_State.PARENT = Clone_Filter.PARENT = Clones

####

async def update(self): ... # Nothing should change on updates, so this is just empty

async def on_interaction(self, element : discord.ui.Item, interaction : discord.Interaction):
    if isinstance(element,discord.ui.Button):
        if element.label == "Set Channel":
            await interaction.followup.send("Please send a mention of the channel you want to use as an announcement channel.",ephemeral=True)

            channel = await utils.wait_for_text_channel(
                BOT,self.ctx,
                "The message you sent did not contain a text channel or does not exist on this server. Please select a channel on this server and make sure to mention it.",
                CONFIG.EDIT_TIMEOUT,
                lambda msg: msg.guild == self.ctx.guild,
            )
            
            session = SESSION_FACTORY()
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.announcement_override = str(channel.id)
            await session.commit(); await session.close()
            pass
        pass
    pass

Announcement_Channel = element_factory(
    "Announcement Channel",
    short_description="Set a channel for developer announcement to appear in",
    long_description="As you will have noticed at the release of Typhoon 2.0, I can send messages to all of you. Here you can set a channel these announcements will now appear in. If not set, the bot will just pick the topmost channel.",
    colour=discord.Colour.dark_orange(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options = [
        ConfigButton(discord.ButtonStyle.primary,"Set Channel")
    ]
)

####

Main = branch_factory(
    "Configuration",
    short_description="Main Menu",
    long_description="Welcome to the configuration menu! Use the menu below to select a branch to go down into.\nThe \"Back\" button will transport you to the last menu.\nThe \"Back to top\" button will transport you to this menu.",
    children=[
        Moderation,
        Leveling,
        Clones,
        Announcement_Channel
    ]
    )

Moderation.PARENT = Leveling.PARENT = Clones.PARENT = Announcement_Channel.PARENT = Main

######################################################
# Command

@commands.command(name="config",brief="A UI command to configure Typhoon",description="A command providing all configuration possibilites of Typhoon in a neat UI")
@commands.guild_only()
@utils.perm_message_check("Configuration?! By you?! (No Permission)",manage_guild=True)
async def config_cmd(ctx : commands.Context):
    embed = discord.Embed(title="Config",colour=discord.Colour.dark_gray())
    message = await ctx.send(embed=embed,ephemeral=True)

    config = Main(embed, message, ctx)
    await config.activate()
    pass

# Setup & Teardown
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

    CONFIG_TIMEOUT = CONFIG.EDIT_TIMEOUT
    bot.add_command(config_cmd)    
    pass

def teardown(bot : commands.Bot):
    bot.remove_command("config")
    pass