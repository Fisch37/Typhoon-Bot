"""
Configuration!
You will find a lot of `update` and `on_interaction` functions.
This module heavily uses libs.config_base, which should be seen as a part of this extension.
Here only the ConfigBranch and ConfigElement objects are created as well as the config command, which loads the topmost branch.
"""
# Yeah, that's a lot of imports
from leveling import LevelSettings, RewardRoles
from libs import utils, config
from libs.config_base import branch_factory, element_factory, ConfigElement, ConfigButton, ConfigSelect, CONFIG_TIMEOUT
from libs.interpret_levelup import VAR_DESCR as LVL_UP_MSG_VAR_DESCR, raw_format as lvl_up_formatter
from libs.converters.time import DurationConverter, OutOfOrderException
from libs.logging_utils import LoggingSettings, translation_table as LOGGING_TRANSLATE
import asyncio
from typing import Any, Literal

import discord
from discord.ext import commands
from discord import app_commands
from discord import ButtonStyle

import sqlalchemy as sql, sqlalchemy.ext.asyncio as asql
from moderation import AutomodState, ModConfig
from ormclasses import *
# Declare constants
# These will be redefined in the load function at the bottom
CONFIG: config.Config = ...

BOT: commands.Bot = ...
WEBHOOK_POOL: utils.WebhookPool = ...

ENGINE: asql.AsyncEngine = ...
SESSION_FACTORY: Sessionmaker = ...

#####################################################

async def send_ephemeral(interaction, content): 
    """This is a short-hand for something that will be used a lot later"""
    await interaction.followup.send(content,ephemeral=True)
    
async def EMPTY_UPDATE(_): ...

# Moderation
async def update(self: ConfigElement):
    # This will always add a list of all current god roles to the embed
    guild = self.ctx.guild
    
    god_role_ids = BOT.DATA.GOD_ROLES[self.ctx.guild.id]
    god_roles = [guild.get_role(int(role_id)) for role_id in god_role_ids]
    
    self.embed.clear_fields()
    self.embed.add_field(name="Current god roles",value="\n".join([role.mention for role in god_roles]) or "None")
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    # Get all the current god roles from RAM
    BOT.DATA.GOD_ROLES.setdefault(self.ctx.guild.id,set())
    god_roles = BOT.DATA.GOD_ROLES[self.ctx.guild.id]
    
    if isinstance(element,discord.ui.Button):
        if element.label == "Add":
            await send_ephemeral(interaction,"Please reply with a role you wish to add as a God Role")
            role = await utils.wait_for_role(BOT,self.ctx,"The message you sent did not contain a role. Please try again.",timeout=CONFIG.EDIT_TIMEOUT)

            god_roles.add(str(role.id))
            await send_ephemeral(interaction,f"Added {role.mention} as a god role!")
            pass
        elif element.label == "Remove":
            await send_ephemeral(interaction,"Please reply with a role you wish to remove as a God Role")
            while True:
                role = await utils.wait_for_role(BOT,self.ctx,"The message you sent did not contain a role. Please try again.",timeout=CONFIG.EDIT_TIMEOUT)
                if str(role.id) not in god_roles:
                    await send_ephemeral(interaction,"This role is not a god role. Please supply a god role.")
                    pass
                else:
                    break
                pass

            god_roles.remove(str(role.id))
            await send_ephemeral(interaction,f"Removed {role.mention} from the list of god roles!")
            pass
        if element.label in ("Add","Remove"):
            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.god_roles = list(god_roles)
                await session.commit()
                pass

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
        ConfigButton(ButtonStyle.primary,"Add",row=0),
        ConfigButton(ButtonStyle.secondary,"Remove",row=0)
    ]
)

#

async def update(self: ConfigElement):
    guild = self.ctx.guild

    async with SESSION_FACTORY() as session:
        sql_guild = await utils.get_guild(session,guild.id)
        log_settings = LoggingSettings.from_value(sql_guild.logging_settings)
        log_state = sql_guild.logging_state
        log_channel_id = sql_guild.logging_channel
        pass

    for select_menu in self.view.children: 
        if isinstance(select_menu,discord.ui.Select): break
        pass
    
    for option in select_menu.options:
        option.default = getattr(log_settings,option.value)
        pass
    
    if log_state:
        log_channel = guild.get_channel(int(log_channel_id))
        pass
    self.embed.clear_fields()
    self.embed.add_field(name="State/Channel",value="Disabled" if not log_state else log_channel.mention)
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element,discord.ui.Select):
        logging_settings = BOT.DATA.LOGGING_SETTINGS[self.ctx.guild.id] = LoggingSettings()
        for value in element.values:
            setattr(logging_settings,value,True)
            pass
        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.logging_settings = logging_settings.to_value()
            await session.commit()
            pass
        pass
    elif element.label == "Set Channel":
        await send_ephemeral(interaction,"Please reply with the text channel you want logging to happen in")
        while True:
            channel: discord.TextChannel = await utils.wait_for_text_channel(BOT,self.ctx,"The message you sent could not be interpreted as a text channel. Please try again")
            if channel.guild == self.ctx.guild: break
            else: await send_ephemeral(interaction,"The channel you passed doesn't exist on this server. Please pass a channel on this server")
            pass
        
        BOT.DATA.LOGGING_CHANNEL[self.ctx.guild.id] = channel.id
        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)
            sql_guild.logging_channel = str(channel.id)
            sql_guild.logging_state = True
            await session.commit()
            pass

        await send_ephemeral(interaction,f"The Logging Channel has been changed to {channel.mention}!")
        pass
    elif element.label == "Disable":
        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session, self.ctx.guild.id)
            sql_guild.logging_channel = None
            sql_guild.logging_state = False
            await session.commit()
            pass

        await send_ephemeral(interaction,"Logging is now disabled!")
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
        ConfigButton(ButtonStyle.primary,"Set Channel",row=1),
        ConfigButton(ButtonStyle.secondary,"Disable",row=1)
    ]
)

# ---
def assure_mod_config(guild_id: int) -> ModConfig:
    BOT.DATA.AUTOMOD_SETTINGS.setdefault(guild_id, ModConfig())
    return BOT.DATA.AUTOMOD_SETTINGS[guild_id]
    pass

def assure_automod_state(guild_id: int) -> AutomodState:
    BOT.DATA.AUTOMODS.setdefault(guild_id, AutomodState())
    return BOT.DATA.AUTOMODS[guild_id]
    pass

def update_automod_config_page(self: ConfigElement, values: tuple[tuple[str,Any],...]):
    apply_specials = lambda state: (":white_check_mark:" if state else ":x:") if isinstance(state,bool) else f"`{state}`"
    value_str = "\n".join([f"{value}: {apply_specials(state)}" for value, state in values])
    self.embed.clear_fields()
    self.embed.add_field(name="Config Values",value=value_str,inline=False)
    pass

async def update_sql_mod_config(guild_id: int, mod_config: ModConfig):
    async with SESSION_FACTORY() as session:
        sql_guild = await utils.get_guild(session,guild_id)
        sql_guild.automod_settings = mod_config.to_dict()
        await session.commit()
        pass
    pass

async def change_automod_setting_state(guild_id: int, automod: str, state: bool):
    states = assure_automod_state(guild_id)
    setattr(states,automod,state)
    await states.save(guild_id)
    pass

async def change_mod_config_value(guild_id: int, setting: str, value: Any):
    mod_config = assure_mod_config(guild_id)
    setattr(mod_config,setting,value)
    
    await update_sql_mod_config(guild_id,mod_config)
    pass

async def specified_convert(ctx: commands.Context, converter, error_msg: str, check = lambda obj: True) -> Any:
    return await utils.wait_for_convert(bot=BOT, ctx=ctx, converter=converter, error_prompt=error_msg, check=check, timeout=CONFIG.EDIT_TIMEOUT)
    pass

async def update_consequences(guild_id: int, target: str, selected_consequences: list[str]):
    mod_config = assure_mod_config(guild_id)
    # Doing these seperately so as to not create a new list object preserving potential weirdness in other code segments
    getattr(mod_config,target)[0] = "delete" in selected_consequences
    getattr(mod_config,target)[1] = "warn" in selected_consequences

    await update_sql_mod_config(guild_id, mod_config)
    pass

def update_select_menu(self: ConfigElement, consequences: list[bool,bool]):
    select_menu: discord.ui.Select = next(filter(lambda item: isinstance(item,discord.ui.Select),self.view.children))
    for option in select_menu.options:
        if option.value == "delete":
            option.default = consequences[0]
            pass
        elif option.value == "warn":
            option.default = consequences[1]
            pass
        pass
    pass


async def update(self: ConfigElement):
    mod_config = assure_mod_config(self.ctx.guild.id)

    update_select_menu(self,mod_config.spam_consequence)

    update_automod_config_page(self,(
        ("Delete Message", mod_config.spam_consequence[0]),
        ("Warn Member", mod_config.spam_consequence[1]),
        ("Maximum Repetition", mod_config.spam_max_message_repetition),
        ("Maximum Similarity",f"{round(mod_config.spam_max_message_similarity*100,1)}%")
    ))
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element, discord.ui.Button):
        if element.label == "Enable":
            await change_automod_setting_state(self.ctx.guild.id,"spamspam",True)
            await send_ephemeral(interaction,"Spam Automod is now enabled!")
            pass
        
        elif element.label == "Disable":
            await change_automod_setting_state(self.ctx.guild.id,"spamspam",False)
            await send_ephemeral(interaction,"Spam Automod is now disabled!")
            pass
        
        elif element.label == "Change Maximum Repetition":
            await send_ephemeral(interaction,"Please send an integer specifying the maximum amount a message may be repeated before the next similar message qualifies as spam.")
            repetition = await specified_convert(
                self.ctx,utils.IntConverter(),
                "The message you sent could not be interpreted as a positive integer. Check that you did not send redundant spaces or other characters.",
                check=lambda repetition: repetition > 0
            )
            await change_mod_config_value(self.ctx.guild.id,"spam_max_message_repetition",repetition)
            pass
        elif element.label == "Reset Maximum Repetition":
            val = "spam_max_message_repetition"
            await change_mod_config_value(self.ctx.guild.id,val,ModConfig.DEFAULTS[val])
            pass

        elif element.label == "Change Maximum Similarity":
            await send_ephemeral(interaction,"Please send a decimal denoting the maximum message similarity (in percent)")
            
            similarity_percent = await specified_convert(
                self.ctx, utils.FloatConverter(),
                "The message you sent could not be interpreted as a similarity value. Make sure there is no % sign in your message. Also make sure your number is not less or equal to zero and not higher than 100.",
                check=lambda similarity: similarity < 100 and similarity > 0
            )
            similarity = similarity_percent/100 # Entered number is percentage, therefore converting to ratio
            await change_mod_config_value(self.ctx.guild.id,"spam_max_message_similarity",similarity)

            await send_ephemeral(interaction,f"Maximum message similarity is now {similarity_percent:.1f}%!")
            pass
        elif element.label == "Reset Maximum Similarity":
            val = "spam_max_message_similarity"
            await change_mod_config_value(self.ctx.guild.id,val,ModConfig.DEFAULTS[val])
            pass
        pass

    else:
        await update_consequences(self.ctx.guild.id,"spam_consequence",element.values)
        pass
    pass

Automod_Spam = element_factory(
    "Message Spam",
    short_description="Prevent people sending similar messages quickly in series",
    long_description="""Message Spam prevention is a part of automod catching spammers by comparing the similarity of their last messages.
    This is moderated by two values:
    The first one is the maximum amount of similar messages until the next one is classified as spam.
    The second one is the similarity required for two messages to be tagged as similar.
    
    You can also configure the consequences for spamming with the select menu below the config buttons.""",
    colour=discord.Colour.yellow(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(ButtonStyle.green,"Enable",row=0), ConfigButton(ButtonStyle.red,"Disable",row=0),
        ConfigButton(ButtonStyle.primary,"Change Maximum Repetition",row=1), ConfigButton(ButtonStyle.secondary,"Reset Maximum Repetition",row=1),
        ConfigButton(ButtonStyle.primary,"Change Maximum Similarity",row=2), ConfigButton(ButtonStyle.secondary,"Reset Maximum Similarity",row=2),
        ConfigSelect(range(2+1),[
            discord.SelectOption(label="Delete Message",value="delete",description="Enable this to delete messages detected as spam"),
            discord.SelectOption(label="Warn Member",value="warn",description="Enable this to automatically warn members sending spam")
        ],row=3)
    ]
)

#

async def update(self: ConfigElement):
    mod_config = assure_mod_config(self.ctx.guild.id)

    update_select_menu(self,mod_config.caps_consequence)

    update_automod_config_page(self,(
        ("Delete Message", mod_config.caps_consequence[0]),
        ("Warn Member", mod_config.caps_consequence[1]),
        ("Minimum Message Length", mod_config.caps_min_length),
        ("Maximum Caps Percentage",f"{round(mod_config.caps_max_ratio*100,1)}%")
    ))
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element, discord.ui.Button):
        if element.label == "Enable":
            await change_automod_setting_state(self.ctx.guild.id,"capsspam",True)
            await send_ephemeral(interaction,"Caps Spam Automod is now enabled!")
            pass
        elif element.label == "Disable":
            await change_automod_setting_state(self.ctx.guild.id,"capsspam",False)
            await send_ephemeral(interaction,"Caps Spam Automod is now disabled!")
            pass

        elif element.label == "Change Minimum Length":
            await send_ephemeral(interaction,"Please enter an integer denoting the minimum length for a message to be checked for Caps Spam.")

            min_length = await specified_convert(
                self.ctx,utils.IntConverter(),
                "The number you entered could not be interpreted as a positive integer. Make sure there are no trailing whitespaces or accidental dots in your message.",
                check = lambda length: length > 0
            )
            await change_mod_config_value(self.ctx.guild.id,"caps_min_length",min_length)

            await send_ephemeral(interaction,f"Changed minimum message length to {min_length}!")
            pass
        elif element.label == "Reset Minimum Length":
            val = "caps_min_length"
            await change_mod_config_value(self.ctx.guild.id,val,ModConfig.DEFAULTS[val])
            pass

        elif element.label == "Change Maximum Ratio":
            await send_ephemeral(interaction,"Please enter a decimal number describing the maximum percentage of caps a message may have.")

            percentage = await specified_convert(
                self.ctx, utils.FloatConverter(),
                "The number you entered could not be interpreted as a valid percentage. Make sure to use `.` instead of `,` and that your value is between 0 and 100.",
                check = lambda percentage: percentage > 0 and percentage <= 100
            )
            ratio = percentage/100 # Getting percentage for ease of use, but needs ratio internally
            await change_mod_config_value(self.ctx.guild.id,"caps_max_ratio",ratio)
            
            await send_ephemeral(interaction,f"Maximum allowed caps/no caps ratio is now set to {percentage:.1f}%!")
            pass
        elif element.label == "Reset Maximum Ratio":
            val = "caps_max_ratio"
            await change_mod_config_value(self.ctx.guild.id,val,ModConfig.DEFAULTS[val])
            pass
        pass
    else:
        await update_consequences(self.ctx.guild.id,"caps_consequence",element.values)
        pass
    pass

Automod_Caps = element_factory(
    "Caps Spam",
    short_description="Prevent people from SHOUTING IN YOUR CHANNELS",
    long_description="""Capslock Spamming is the act of using capslock in your messages (i.e. writing in all capital letters).
    Moderation for Capslock usage includes two values:
    The first one is the minimum length required until the bot checks for caps spam. This is necessary so that short messages won't be tagged accidentally (e.g. accidentally typing HI instead of Hi)
    The second one is the percentage of characters in upper case. This does not include special characters.
    If the message is above the specified length and more than the set percentage of the message is upper case, it will qualify as Caps Spam.
    
    Besides these values you can also configure the consequences for Caps Spam using the select menu below.""",
    colour=discord.Colour.yellow(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(ButtonStyle.green,"Enable",row=0), ConfigButton(ButtonStyle.red,"Disable",row=0),
        ConfigButton(ButtonStyle.primary,"Change Minimum Length",row=1), ConfigButton(ButtonStyle.secondary,"Reset Minimum Length",row=1),
        ConfigButton(ButtonStyle.primary,"Change Maximum Ratio",row=2), ConfigButton(ButtonStyle.secondary,"Reset Maximum Ratio",row=2),
        ConfigSelect(range(2+1),[
            discord.SelectOption(label="Delete Message",value="delete",description="Enable this to delete messages detected as spam"),
            discord.SelectOption(label="Warn Member",value="warn",description="Enable this to automatically warn members sending spam")
        ],row=3)
    ]
)

#

async def update(self: ConfigElement):
    mod_config = assure_mod_config(self.ctx.guild.id)

    update_select_menu(self,mod_config.emoji_consequence)

    update_automod_config_page(self,(
        ("Delete Message", mod_config.emoji_consequence[0]),
        ("Warn Member", mod_config.emoji_consequence[1]),
        ("Minimum Message Length", mod_config.emoji_min_length),
        ("Maximum Emoji Percentage",f"{round(mod_config.emoji_max_ratio*100,1)}%")
    ))
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element, discord.ui.Button):
        if element.label == "Enable":
            await change_automod_setting_state(self.ctx.guild.id,"emotespam",True)
            await send_ephemeral(interaction,"Emoji Spam Automod is now enabled!")
            pass
        elif element.label == "Disable":
            await change_automod_setting_state(self.ctx.guild.id,"emotespam",False)
            await send_ephemeral(interaction,"Emoji Spam Automod is now disabled!")
            pass

        elif element.label == "Change Minimum Length":
            await send_ephemeral(interaction,"Please enter an integer denoting the minimum length for a message to be checked for Emoji Spam.")

            min_length = await specified_convert(
                self.ctx,utils.IntConverter(),
                "The number you entered could not be interpreted as a positive integer. Make sure there are no trailing whitespaces or accidental dots in your message.",
                check = lambda length: length > 0
            )
            await change_mod_config_value(self.ctx.guild.id,"emoji_min_length",min_length)
            pass
        elif element.label == "Reset Minimum Length":
            val = "emoji_min_length"
            await change_mod_config_value(self.ctx.guild.id,val,ModConfig.DEFAULTS[val])
            pass

        elif element.label == "Change Maximum Ratio":
            await send_ephemeral(interaction,"Please enter a decimal number describing the maximum percentage of emojis a message may have.")

            percentage = await specified_convert(
                self.ctx, utils.FloatConverter(),
                "The number you entered could not be interpreted as a positive integer. Make sure there are no trailing whitespaces or accidental dots in your message.",
                check = lambda percentage: percentage > 0 and percentage <= 100
            )
            ratio = percentage/100 # Getting percentage for ease of use, but needs ratio internally
            await change_mod_config_value(self.ctx.guild.id,"emoji_max_ratio",ratio)
            pass
        elif element.label == "Reset Maximum Ratio":
            val = "emoji_max_ratio"
            await change_mod_config_value(self.ctx.guild.id,val,ModConfig.DEFAULTS[val])
            pass
        pass
    else:
        await update_consequences(self.ctx.guild.id,"emoji_consequence",element.values)
        pass
    pass

Automod_Emote = element_factory(
    "Emoji Spam",
    short_description="Prevent people from getting overly excited using emojis",
    long_description="""Emoji Spam is quite similar to Caps Spam. The only difference is that Emoji Spam checks for emojis instead of capital letters.
    The same as Caps Spam it has two governing values:
    Firstly, the minimum length required for the bot to check the message. (Required so that :thumbsup: doesn't become spam)
    Secondly, the maximum percentage of a message being emotes before it qualifies as spam.
    
    You can also configure the consequences for sending Emoji Spam using the select menu.""",
    colour=discord.Colour.yellow(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(ButtonStyle.green,"Enable",row=0), ConfigButton(ButtonStyle.red,"Disable",row=0),
        ConfigButton(ButtonStyle.primary,"Change Minimum Length",row=1), ConfigButton(ButtonStyle.secondary,"Reset Minimum Length",row=1),
        ConfigButton(ButtonStyle.primary,"Change Maximum Ratio",row=2), ConfigButton(ButtonStyle.secondary,"Reset Maximum Ratio",row=2),
        ConfigSelect(range(2+1),[
            discord.SelectOption(label="Delete Message",value="delete",description="Enable this to delete messages detected as spam"),
            discord.SelectOption(label="Warn Member",value="warn",description="Enable this to automatically warn members sending spam")
        ],row=3)
    ]
)

#

Mod_Automod = branch_factory(
    "Automod",
    short_description="Automatically moderate the messages on your server",
    long_description="Automod allows you to hand off some of the dirty work of moderating to this bot. It currently implements three types of automod seen below.",
    colour=discord.Colour.yellow(),
    children=[
        Automod_Spam,
        Automod_Caps,
        Automod_Emote
    ]
)

Automod_Spam.PARENT = Automod_Caps.PARENT = Automod_Emote.PARENT = Mod_Automod

# ---

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

def assure_reward_roles(guild_id) -> RewardRoles:
    BOT.DATA.REWARD_ROLES.setdefault(guild_id,RewardRoles({}))
    return BOT.DATA.REWARD_ROLES[guild_id]
    pass

async def update(self: ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)

    self.embed.clear_fields()
    self.embed.add_field(name="Leveling State",value="Enabled" if lvl_settings.enabled else "Disabled",inline=False)
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element,discord.ui.Button):
        lvl_settings = assure_level_settings(self.ctx.guild.id)
        if element.label == "Enable":
            lvl_settings.enabled = True
            
            async with SESSION_FACTORY() as session:
                sql_guild: Guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.level_state = True
                await session.commit()
                pass

            await send_ephemeral(interaction,"Leveling is now enabled!")
            pass
        elif element.label == "Disable":
            lvl_settings.enabled = False

            async with SESSION_FACTORY() as session:
                sql_guild: Guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.level_state = False
                await session.commit()
                pass

            await send_ephemeral(interaction,"Leveling is now disabled!")
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
        ConfigButton(ButtonStyle.green,"Enable"),
        ConfigButton(ButtonStyle.red,"Disable")
    ]
)

#

async def update(self: ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)

    self.embed.clear_fields()
    self.embed.add_field(name="Lower gain",value=str(lvl_settings.lower_gain))
    self.embed.add_field(name="Upper gain",value=str(lvl_settings.upper_gain))
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    async def update_gain(ram_key, sql_key, val):
        lvl_settings = assure_level_settings(self.ctx.guild.id)

        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session,self.ctx.guild.id)

            setattr(lvl_settings,ram_key,val)
            setattr(sql_guild,sql_key,val)

            await session.commit()
            pass
        pass


    if isinstance(element, discord.ui.Button):
        # Sets
        if element.label == "Set Lower Gain":
            await send_ephemeral(interaction,"Please send a message with the Lower Gain you want to set")

            lvl_settings = assure_level_settings(self.ctx.guild.id)
            gain = await specified_convert(
                self.ctx,utils.IntConverter(),
                "Your message could not be interpreted as a positive integer (i.e. whole number >0). Also check that the value is not larger than the current Upper Gain and less than 256.",
                lambda new_lower_gain: new_lower_gain <= lvl_settings.upper_gain and new_lower_gain < 256
            )

            await update_gain("lower_gain","lower_xp_gain",gain)

            await send_ephemeral(interaction,f"Updated Lower Gain to {lvl_settings.lower_gain}!")
            pass
        elif element.label == "Set Upper Gain":
            await send_ephemeral(interaction,"Please send a message with the Upper Gain you want to set")

            lvl_settings = assure_level_settings(self.ctx.guild.id)
            gain = await specified_convert(
                self.ctx,utils.IntConverter(),
                "Your message could not be interpreted as a positive integer (i.e. whole number >0). Also check that the value is not larger than the current Upper Gain and less than 256.",
                lambda new_upper_gain: new_upper_gain >= lvl_settings.lower_gain and new_upper_gain < 256
            )
            
            await update_gain("upper_gain","upper_xp_gain",gain)

            await send_ephemeral(interaction,f"Updated Upper Gain to {lvl_settings.upper_gain}!")
            pass

        # Resets
        elif element.label == "Reset Lower Gain":
            default_gain = Guild.lower_xp_gain.default.arg
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            if lvl_settings.upper_gain < default_gain:
                await send_ephemeral(interaction,f"This action would cause the Lower Gain to be lower than the Upper Gain.\nPlease set the Upper Gain to a value greater than {default_gain} and try again.")
            else:
                await update_gain("lower_gain","lower_xp_gain",default_gain)
            pass
        elif element.label == "Reset Upper Gain":
            default_gain = Guild.upper_xp_gain.default.arg
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            if lvl_settings.lower_gain > default_gain:
                await send_ephemeral(interaction,f"This action would cause the Upper Gain to be lower than the Lower Gain.\nPlease set the Lower Gain to a value smaller than {default_gain} and try again.")
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
        ConfigButton(ButtonStyle.primary,"Set Lower Gain",row=0), ConfigButton(ButtonStyle.secondary,"Reset Lower Gain",row=0), 
        ConfigButton(ButtonStyle.primary,"Set Upper Gain",row=1), ConfigButton(ButtonStyle.secondary,"Reset Upper Gain",row=1)
    ]
)

#
async def update(self: ConfigElement):
    lvl_settings = assure_level_settings(self.ctx.guild.id)
    
    self.embed.clear_fields()
    self.embed.add_field(name="XP Timeout",value=utils.stringFromDuration(lvl_settings.timeout),inline=False)
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element,discord.ui.Button):
        lvl_settings = assure_level_settings(self.ctx.guild.id)
        
        if element.label == "Set Timeout":
            await send_ephemeral(interaction,"Please send a time formatted like `<hours>H<minutes>M<seconds>S` to change the cooldown for xp gain")
            converter = DurationConverter()
            while True:
                msg: discord.Message = await BOT.wait_for("message",check=lambda msg: msg.channel == self.ctx.channel and msg.author == self.ctx.author,timeout=CONFIG.EDIT_TIMEOUT)
                try:
                    timeout = await converter.convert(self.ctx,msg.content)
                except OutOfOrderException:
                    await send_ephemeral(interaction,"Your message breaks the format specified previously. It seems you messed up the order of some values. Please check that you are following this format.")
                    pass
                except commands.BadArgument:
                    await send_ephemeral(interaction,"The values specified with the format cannot be interpreted. Please check all values are integers and no text other than that specified with the format exists.")
                    pass
                else:
                    break
                finally:
                    await msg.delete()
                    pass
                pass

            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                lvl_settings.timeout = sql_guild.xp_timeout = timeout
                await session.commit()
                pass

            await send_ephemeral(interaction,f"Set XP Gain Timeout to {utils.stringFromDuration(timeout)}")
            pass
        elif element.label == "Reset Timeout":
            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                lvl_settings.timeout = sql_guild.xp_timeout = Guild.xp_timeout.default.arg
                await session.commit()
                pass

            await send_ephemeral(interaction,f"Reset XP Gain Timeout to {utils.stringFromDuration(lvl_settings.timeout)}!")
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
        ConfigButton(ButtonStyle.primary,"Set Timeout"),
        ConfigButton(ButtonStyle.secondary,"Reset Timeout")
    ]
)

#
async def update(self: ConfigElement):
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

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element,discord.ui.Button):
        if element.label == "Set Message":
            list_assembles = []
            for var_name, var_descr in LVL_UP_MSG_VAR_DESCR:
                list_assembles.append(f"[{var_name}]\n\t{var_descr}")
                pass
            markdown = "```css\n{}```".format('\n'.join(list_assembles))
            
            await send_ephemeral(interaction,"Please send the message template you want to apply. Below is a list of variables that will be applied. A variable must always be surrounded by {}" + markdown)

            while True:
                msg: discord.Message = await BOT.wait_for("message",check=lambda msg: msg.channel == self.ctx.channel and msg.author == self.ctx.author)
                new_template = msg.content
                await msg.delete()
                if len(new_template) > 200:
                    await send_ephemeral(interaction,"The template cannot be larger than 200 characters. Please shorten your template.")
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
            with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.level_msg = new_template
                await session.commit()
                pass

            await send_ephemeral(interaction,f"The template has been set. Following is an example message:\n\n{example_message}")
            pass
        elif element.label == "Set Channel":
            await send_ephemeral(interaction,"Please send a channel you wish to have your level-ups appear in.")
            while True:
                """FIX: TypeError: 'NoneType' object is not callable"""
                channel = await utils.wait_for_text_channel(
                    BOT,self.ctx,
                    "The message you sent could not be interpreted as a text channel. Please make sure to only send a #text_channel format.",
                    CONFIG.EDIT_TIMEOUT
                )
                if channel.guild != self.ctx.guild:
                    await send_ephemeral(interaction,"The channel you specified doesn't exist on this server. Please supply a channel on this server.")
                    pass
                else:
                    break
                pass
            # Update setting in RAM
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.channel_id = channel.id
            # Update setting in database
            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.level_channel = str(channel.id)
                await session.commit()
                pass
            pass

        elif element.label == "Reset Message":
            new_template = Guild.level_msg.default.arg # This is just because I couldn't be bothered to change two lines of code
            # Update setting in RAM
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.level_msg = new_template
            # Update setting in Database
            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.level_msg = new_template
                await session.commit()
                pass

            await send_ephemeral(interaction,"Reset message template!")
            pass
        elif element.label == "Reset message location":
            # Update setting in RAM
            lvl_settings = assure_level_settings(self.ctx.guild.id)
            lvl_settings.channel_id = None
            # Update setting in database
            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.level_channel = None
                await session.commit()
                pass
            pass
        pass
    pass

Lvl_msgs = element_factory(
    "Level Up Messages",
    short_description="Set a custom message to be sent when a user levels up.",
    long_description="When a user gains enough XP, they will gain a Level Up. These Level Ups are usually sent in the channel they sent their last message and take the form of `Geez, {user_mention}! You leveled up to level {level}`.\nHere you can set a custom channel for the level ups and also change the message sent.",
    colour = discord.Colour.brand_green(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(ButtonStyle.primary,"Set Message",row=0), ConfigButton(ButtonStyle.secondary,"Reset Message",row=0),
        ConfigButton(ButtonStyle.primary,"Set Channel",row=1), ConfigButton(ButtonStyle.secondary,"Reset message location",row=1)
    ]
)

#

async def update(self: ConfigElement):
    reward_roles = assure_reward_roles(self.ctx.guild.id)
    inverse: dict[int,list[discord.Role]] = {}
    for role_id, level in reward_roles.internal.items():
        role = self.ctx.guild.get_role(role_id)

        inverse.setdefault(level,[])
        inverse[level].append(role)
        pass
    inverse_list = sorted(inverse.items(),key=lambda item: item[0],reverse=True)

    role_strs, levels = [], []
    for level, roles in inverse_list:
        for role in roles:
            role_strs.append(role.mention)
            levels.append(str(level))
            pass
        pass

    self.embed.clear_fields()
    self.embed.add_field(name="Role",value="\n".join(role_strs) if len(role_strs) > 0 else "None")
    self.embed.add_field(name="Level",value="\n".join(levels) if len(levels) > 0 else "None")
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    guild = self.ctx.guild
    author = self.ctx.author
    if isinstance(element,discord.ui.Button):
        if element.label == "Add Reward Role":
            await send_ephemeral(interaction,"Please send a message mentioning the role you want to add as a reward role")
            role = await utils.wait_for_role(BOT,self.ctx,"The message you sent could not be interpreted as a role. Make sure your message actually mentions the role.",timeout=CONFIG.EDIT_TIMEOUT)
            
            await send_ephemeral(interaction,"Now send a message containing the level you wish to reward the role at.")
            level: int = await specified_convert(
                self.ctx, utils.IntConverter(),
                "The message you sent is not interpretable as a positive integer. Please make sure your message only contains a whole number that is not below one.",
                lambda lvl: lvl > 0
            )

            reward_roles = assure_reward_roles(guild.id)
            reward_roles.add_reward_role(role.id,level)
            await reward_roles.save(guild.id)

            await send_ephemeral(interaction,f"The role {role.mention} is now set to be granted once a user achieves level {level}")
            pass
        elif element.label == "Remove Reward Role":
            await send_ephemeral(interaction,"Please send the message containing the role you want to remove as a reward role")
            role = await utils.wait_for_role(BOT,self.ctx,"The message you sent could not be interpreted as a role. Check that you are actually mentioning the role.",timeout=CONFIG.EDIT_TIMEOUT)
            
            reward_roles = assure_reward_roles(guild.id)
            reward_roles.remove_reward_role(role.id)
            await reward_roles.save(guild.id)

            await send_ephemeral(interaction,f"Removed the reward role for {role.mention}!")
            pass

        elif element.label == "Post Reward Roles":
            is_sure = await utils.confirmation_interact(
                interaction,
                "This action will post a list of **all current** reward roles to the current channel. Are you sure you wish to do that?"
            )
            if not is_sure: return
            
            reward_roles = assure_reward_roles(guild.id)
            reversed_rewards: dict[int,list[discord.Role]] = {}
            for role_id, level in reward_roles.internal.items():
                role = guild.get_role(role_id)
                if role is not None:
                    reversed_rewards.setdefault(level,[])
                    reversed_rewards[level].append(role)
                    pass
                pass

            level_lines = []
            role_lines = []
            for level, roles in reversed_rewards.items():
                has_added_level = False
                for role in roles:
                    if has_added_level:
                        level_lines.append("")
                        pass
                    else:
                        level_lines.append(str(level))
                        pass

                    role_lines.append(role.mention)
                    pass
                pass

            embed = discord.Embed(
                title="Level Reward Roles",
                colour=discord.Colour.brand_green(),
                description="This is a list of all reward roles spread across the different levels. Once you reach a certain level a fitting reward role will be bestowed upon you.",
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Level",value="\n".join(level_lines),inline=True)
            embed.add_field(name="Level",value="\n".join(role_lines),inline=True)
            embed.set_author(
                name=f"{author.display_name}",
                url=f"https://discord.com/users/{author.id}",
                icon_url=author.display_avatar.url
            )

            await self.ctx.channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none())
            pass
        pass
    pass

Lvl_rewards = element_factory(
    "Reward Roles",
    short_description="Roles that get added to a user when they level up",
    long_description="Reward Roles are roles that get rewarded to a user once they have achieved a certain level. Here you can configure these roles.",
    colour = discord.Colour.brand_green(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options=[
        ConfigButton(ButtonStyle.green,"Add Reward Role"),
        ConfigButton(ButtonStyle.red,"Remove Reward Role"),
        ConfigButton(ButtonStyle.gray,"Post Reward Roles",row=1)
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
        Lvl_rewards,
        Lvl_msgs
    ]
)
Lvl_state.PARENT = Lvl_xp.PARENT = Lvl_timeout.PARENT = Lvl_rewards.PARENT = Lvl_msgs.PARENT = Leveling

####

async def assure_clone_overrides(guild_id: int) -> tuple[bool,dict[int,bool]]:
    data = BOT.DATA.CLONE_OVERRIDES.get(guild_id)
    if data is None:
        async with SESSION_FACTORY() as session:
            sql_guild = await utils.get_guild(session,guild_id)
            data = BOT.DATA.CLONE_OVERRIDES[guild_id] = [sql_guild.clone_enabled, {int(k):v for k,v in sql_guild.clone_filter.items()}]
            pass
        pass

    return data
    pass

async def store_clone_overrides(guild_id: int, overrides: dict[int,bool]):
    async with SESSION_FACTORY() as session:
        sql_guild = await utils.get_guild(session,guild_id)
        sql_guild.clone_filter = overrides
        await session.commit()
        pass
    pass

async def update(self: ConfigElement):
    async with SESSION_FACTORY() as session:
        result: CursorResult = await session.execute(sql.select(Guild.clone_enabled).where(Guild.id == str(self.ctx.guild.id)))
        clone_enabled = result.scalar_one_or_none()
        pass

    self.embed.clear_fields()
    self.embed.add_field(name="Clone State",value="Enabled" if clone_enabled else "Disabled")
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    async def update_state(state: bool):
        async with SESSION_FACTORY() as session:
            (await utils.get_guild(session,self.ctx.guild.id)).clone_enabled = state
            await session.commit()
            pass

        await send_ephemeral(interaction,f"Cloning is now {'enabled' if state else 'disabled'}!")
        pass
    if isinstance(element,discord.ui.Button):
        if element.label == "Enable":
            await update_state(True)
            pass
        elif element.label == "Disable":
            await update_state(False)
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
        ConfigButton(ButtonStyle.success,"Enable",None),
        ConfigButton(ButtonStyle.danger,"Disable",None)
    ]
)

#

async def update(self: ConfigElement):
    _, overrides = await assure_clone_overrides(self.ctx.guild.id)
    channel_ids, states = overrides.keys(), overrides.values()

    self.embed.clear_fields()
    channel_str = "\n".join([self.ctx.guild.get_channel(int(channel_id)).mention for channel_id in channel_ids if self.ctx.guild.get_channel(int(channel_id)) is not None])
    override_str= "\n".join(["Enabled" if override_state else "Disabled" for override_state in states])
    self.embed.add_field(name="Filter Channel",value=channel_str if channel_str else "Empty")
    self.embed.add_field(name="Override",value=override_str if override_str else "Empty")
    pass

async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
    async def get_filter_channel(start_message: str, error_msg: str = None, extra_check = lambda channel: True):
        await send_ephemeral(interaction,start_message)
        while True:
            channel = await utils.wait_for_text_channel(
                BOT,self.ctx,
                "The argument you supplied is not a text channel or does not exist on this server.",
                CONFIG.EDIT_TIMEOUT
            )
            if not extra_check(channel):
                await send_ephemeral(interaction,error_msg)
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

            await send_ephemeral(interaction,f"Cloning is now disabled in {channel.mention}!")
            pass
        elif element.label == "Add allow filter":
            channel = await get_filter_channel(
                "Please enter a channel to add the filter for"
                )
            
            _, overrides = await assure_clone_overrides(self.ctx.guild.id)
            overrides: dict[int,bool]
            overrides[channel.id] = True
            await store_clone_overrides(self.ctx.guild.id,overrides)

            await send_ephemeral(interaction,f"Cloning is now enabled in {channel.mention}!")
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

            await send_ephemeral(interaction,f"The filter for {channel.mention} has been removed. The channel will now follow the default setting for cloning.")
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
        ConfigButton(ButtonStyle.red,"Add deny filter"), ConfigButton(ButtonStyle.green,"Add allow filter"),
        ConfigButton(ButtonStyle.gray,"Remove filter",row=1)
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

async def update(self: ConfigElement):
    guild = self.ctx.guild

    async with SESSION_FACTORY() as session:
        sql_guild = await utils.get_guild(session,guild.id)
        if sql_guild.announcement_override is None:
            announcement_channel_id = None
            pass
        else:
            announcement_channel_id = int(sql_guild.announcement_override)
            pass
        pass
    if announcement_channel_id is not None:
        current_channel = guild.get_channel(announcement_channel_id)
        pass
    else:
        current_channel = None
        pass
    if None in (announcement_channel_id, current_channel):
        current_channel = guild.text_channels[0]
        pass

    self.embed.clear_fields()
    self.embed.add_field(name="Current Announcement Channel",value=current_channel.mention)
    pass

async def on_interaction(self, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element,discord.ui.Button):
        if element.label == "Set Channel":
            await send_ephemeral(interaction,"Please send a mention of the channel you want to use as an announcement channel.")

            channel = await utils.wait_for_text_channel(
                BOT,self.ctx,
                "The message you sent did not contain a text channel or does not exist on this server. Please select a channel on this server and make sure to mention it.",
                CONFIG.EDIT_TIMEOUT,
                lambda msg: msg.guild == self.ctx.guild,
            )
            
            async with SESSION_FACTORY() as session:
                sql_guild = await utils.get_guild(session,self.ctx.guild.id)
                sql_guild.announcement_override = str(channel.id)
                await session.commit()
                pass
            pass
        pass
    pass

Announcement_Channel = element_factory(
    "Announcement Channel",
    short_description="Set a channel for developer announcements to appear in",
    long_description="As you will have noticed at the release of Typhoon 2.0, I can send messages to all of you. Here you can set a channel these announcements will now appear in. If not set, the bot will just pick the topmost channel.",
    colour=discord.Colour.dark_orange(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options = [
        ConfigButton(ButtonStyle.primary,"Set Channel")
    ]
)

####

async def update(self: ConfigElement): 
    async with SESSION_FACTORY() as session:
        guild = await utils.get_guild(session,self.ctx.guild.id)
        vote_state = guild.vote_permissions.get("state",True)
        pass

    self.embed.clear_fields()
    self.embed.add_field(name="Voting State",value="Enabled" if vote_state else "Disabled")
    pass

async def change_vote_state(guild_id: int, state: bool):
    async with SESSION_FACTORY() as session:
        sql_guild = await utils.get_guild(session,guild_id)
        sql_guild.vote_permissions["state"] = state
        await session.commit()
        pass
    pass

async def on_interaction(self, element: discord.ui.Item, interaction: discord.Interaction):
    if isinstance(element,discord.ui.Button):
        if element.label == "Enable":
            await change_vote_state(self.ctx.guild.id,True)
            await send_ephemeral(interaction,"Voting is now enabled!")
            pass
        elif element.label == "Disable":
            await change_vote_state(self.ctx.guild.id,False)
            await send_ephemeral(interaction,"Voting is now enabled!")
            pass
        pass
    pass

Voting = element_factory(
    "Voting",
    short_description="Enable or disable creation of votes",
    long_description="Here you can enable or disable voting. This will only stop users from creating new votes, not stop the existing ones. To override this setting for roles or channels, go to your server's integration settings and deny usage of /vote according to the overrides you want to create.",
    colour=discord.Colour.purple(),
    update_callback=update,
    view_interact_callback=on_interaction,
    options = [
        ConfigButton(ButtonStyle.green,"Enable"),
        ConfigButton(ButtonStyle.red,"Disable")
    ]
)

# These are redundant because Discord's Slash Command system allows servers to just disable /votes for roles and channels
# #

# def set_override_embeds(guild: discord.Guild,embed: discord.Embed, overrides: dict[str,bool], field_name: str, getter: str):
#     with_objs: list[tuple[discord.Role,bool]] = []
#     for obj_str, state in overrides.items():
#         obj = getattr(guild,getter)(int(obj_str))
#         if obj is None: continue

#         with_objs.append((obj,state))
#         pass
#     with_objs.sort(key=lambda item: item[0].position,reverse=True) # Sort after order in guild

#     str_roles = []
#     str_states = []
#     for obj, state in with_objs:
#         str_roles.append(obj.mention)
#         str_states.append("Enabled" if state else "Disabled")
#         pass
    
#     embed.clear_fields()
#     embed.add_field(name=field_name,value="\n".join(str_roles) if len(str_roles) > 0 else "None")
#     embed.add_field(name="Override",value="\n".join(str_states) if len(str_roles) > 0 else "None")
#     pass

# async def update_vote_override_embed(self: ConfigElement, override: Literal["role_overrides","channel_overrides"], field_name: str, getter: str):
#     async with SESSION_FACTORY() as session:
#         sql_guild = await utils.get_guild(session,self.ctx.guild.id)
#         overrides = sql_guild.vote_permissions[override]
#         pass

#     set_override_embeds(self.ctx.guild,self.embed,overrides,field_name,getter)
#     pass

# async def add_override(guild_id: int, override: str, obj, state: bool):
#     async with SESSION_FACTORY() as session:
#         sql_guild = await utils.get_guild(session,guild_id)
#         override = sql_guild.vote_permissions[override]
#         override[str(obj.id)] = state
#         await session.commit()
#         pass
#     pass

# async def override_gui(bot: commands.Bot, ctx: commands.Context, waiter, error_msg: str, override: str, state: bool):
#     obj = await waiter(bot,ctx,error_msg)
#     await add_override(ctx.guild.id,override,obj,state)
#     return obj
#     pass

# async def override_role(bot: commands.Bot, ctx: commands.Context, state: bool) -> discord.Role:
#     return await override_gui(bot,ctx,utils.wait_for_role,"The message you sent could not be interpreted as a role.","role_overrides",state)
#     pass

# async def override_rem(guild_id: int, override: str, obj):
#     async with SESSION_FACTORY() as session:
#         sql_guild = await utils.get_guild(session,guild_id)
#         sql_guild.vote_permissions[override].pop(str(obj.id))
#         await session.commit()
#         pass
#     pass

# async def override_rem_gui(bot: commands.Bot, ctx: commands.Context, waiter, interaction: discord.Interaction, override: str, error_msg: str, not_exist_error: str):
#     obj = await waiter(bot,ctx,error_msg)
#     try:
#         await override_rem(ctx.guild.id,override,obj)
#     except KeyError:
#         await send_ephemeral(interaction,not_exist_error)
#         obj = None # Return None as indicator for calling function
        
#     return obj
#     pass

# async def update(self: ConfigElement):
#     await update_vote_override_embed(self,"role_overrides","Role","get_role")
#     pass

# async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
#     if not isinstance(element,discord.ui.Button): return
#     if element.label == "Add deny override":
#         await send_ephemeral(interaction,"Please send a message mentioning the role you want to add a deny override for.")
#         role = await override_role(BOT,self.ctx,False)
#         await send_ephemeral(interaction,f"Denying all users with role {role.mention} to create votes (should no prioritised role allow it)")
#         pass
#     elif element.label == "Add allow override":
#         await send_ephemeral(interaction,"Please send a message mentioning the role you want to add an allow override for.")
#         role = await override_role(BOT,self.ctx,True)
#         await send_ephemeral(interaction,f"Allowing all users with role {role.mention} to create votes (should no prioritised role deny it)")
#         pass
#     elif element.label == "Remove override":
#         await send_ephemeral(interaction,"Please send a message mentioning the role you want to remove the override for.")
#         role = await override_rem_gui(BOT,self.ctx,utils.wait_for_role,interaction,"role_overrides","The message you sent could not be interpreted as a role.","The role you mentioned does not have an override. Exiting the action...")
#         if role is not None: await send_ephemeral(interaction,f"Removed override for role {role.mention}.")
#         pass
#     pass

# Voting_Role_Overrides = element_factory(
#     "Role Overrides",
#     short_description="Override the default setting based on a user's roles",
#     long_description="Role overrides allow you to allow or disallow users the creation of votes depending on their roles. Below you can see the current overrides. Use one of the buttons to add or remove overrides.",
#     colour=discord.Colour.purple(),
#     update_callback=update,
#     view_interact_callback=on_interaction,
#     options = [
#         ConfigButton(ButtonStyle.red,"Add deny override"), ConfigButton(ButtonStyle.green,"Add allow override"),
#         ConfigButton(ButtonStyle.primary,"Remove override",row=1)
#     ]
# )

# #

# async def override_channel(bot: commands.Bot, ctx: commands.Context, state: bool):
#     return await override_gui(bot,ctx,utils.wait_for_text_channel,"The message you sent could not be interpreted as a text channel.","channel_overrides",state)
#     pass

# async def update(self: ConfigElement):
#     await update_vote_override_embed(self,"channel_overrides","Channel","get_channel")
#     pass

# async def on_interaction(self: ConfigElement, element: discord.ui.Item, interaction: discord.Interaction):
#     if not isinstance(element,discord.ui.Button): return
#     if element.label == "Add deny override":
#         await send_ephemeral(interaction,f"Please send a message mentioning the channel you wish to set a deny override for.")
#         channel = await override_channel(BOT,self.ctx,False)
#         await send_ephemeral(interaction,f"A deny override was added for {channel.mention}. If no role override exists for the executing user, they cannot create a vote in this channel.")
#         pass
#     elif element.label == "Add allow override":
#         await send_ephemeral(interaction,f"Please send a message mentioning the channel you wish to set an allow override for.")
#         channel = await override_channel(BOT,self.ctx,True)
#         await send_ephemeral(interaction,f"An allow override was added for {channel.mention}. If no role override exists denying the executing user creation of votes, they can now create votes in this channel.",ephemeral=True)
#         pass
#     elif element.label == "Remove override":
#         await send_ephemeral(interaction,f"Please send a message mentioning the channel you wish to remove the override for.")
#         channel = await override_rem_gui(BOT,self.ctx,utils.wait_for_text_channel,interaction,"channel_overrides","The message you sent could not be interpreted as a text channel.","The channel you mentioned does not have an override. Exiting the action...")
#         if channel is not None: await send_ephemeral(interaction,f"Removed override for role {channel.mention}.")
#         pass
#     pass

# Voting_Channel_Overrides = element_factory(
#     "Channel Overrides",
#     short_description="Override the default setting based on the channel the vote can be created",
#     long_description="Channel overrides allow you to enable/disable votes from a specific channel. Note that role overrides will have a higher priority.",
#     colour=discord.Colour.purple(),
#     update_callback=update,
#     view_interact_callback=on_interaction,
#     options = [
#         ConfigButton(ButtonStyle.red,"Add deny override"), ConfigButton(ButtonStyle.green,"Add allow override"),
#         ConfigButton(ButtonStyle.primary,"Remove override",row=1)
#     ]
# )

#

# Voting = branch_factory(
#     "Voting",
#     short_description="With voting users may... vote on topics. Here you can customise the permissions",
#     long_description="""Voting allows you to ask your community anything you want. From favourite pizza toppings to favourite mod team members to votes on server deletion (I do not recommend this, please make up your own mind. It's your server, don't simply delete it because someone told you to).
#     This system works similar to the cloning restrictions. You may disable or enable creation of votes by default and set overrides that allow/deny creation of votes only in some channels or for users with some roles.
#     For ease of use, the overrides and the default state are seperated into two sections of which you may select one with the select menu.""",
#     colour=discord.Colour.purple(),
#     children = [
#         Voting_State,
#         Voting_Role_Overrides,
#         Voting_Channel_Overrides
#     ]
# )
# Voting_State.PARENT = Voting_Role_Overrides.PARENT = Voting_Channel_Overrides.PARENT = Voting

####

Main = branch_factory(
    "Configuration",
    short_description="Main Menu",
    long_description="Welcome to the configuration menu! Use the menu below to select a branch to go down into.\nThe \"Back\" button will transport you to the last menu.\nThe \"Back to top\" button will transport you to this menu.",
    children=[
        Moderation,
        Leveling,
        Clones,
        Voting,
        Announcement_Channel
    ]
    )

Moderation.PARENT = Leveling.PARENT = Clones.PARENT = Announcement_Channel.PARENT = Voting.PARENT = Main

######################################################
# Command

@app_commands.command(name="config",description="A command providing all configuration possibilites of Typhoon in a neat UI")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def config_cmd(interaction: discord.Interaction):
    ctx = await commands.Context.from_interaction(interaction)
    embed = discord.Embed(title="Config",colour=discord.Colour.dark_gray())
    message = await ctx.send(embed=embed,ephemeral=True)

    config = Main(embed, message, ctx)
    await config.activate()
    pass

# Setup & Teardown
async def setup(bot: commands.Bot):
    global CONFIG
    global BOT, WEBHOOK_POOL
    global ENGINE, SESSION_FACTORY
    global CONFIG_TIMEOUT
    # Set constants
    CONFIG          = bot.CONFIG
    
    BOT             = bot
    WEBHOOK_POOL    = bot.WEBHOOK_POOL

    ENGINE          = bot.ENGINE
    SESSION_FACTORY = bot.SESSION_FACTORY

    CONFIG_TIMEOUT = CONFIG.EDIT_TIMEOUT
    bot.tree.add_command(config_cmd)
    pass

async def teardown(bot: commands.Bot):
    bot.tree.remove_command("config")
    pass
