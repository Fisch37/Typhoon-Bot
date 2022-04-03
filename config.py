"""
Configuration! That's all
"""
from libs import utils, config
from config_base import branch_factory, element_factory, ConfigElement, ConfigButton, ConfigSelect, CONFIG_TIMEOUT
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

Main = branch_factory(
    "Configuration",
    short_description="Main Menu",
    long_description="Welcome to the configuration menu! Use the menu below to select a branch to go down into.\nThe \"Back\" button will transport you to the last menu.\nThe \"Back to top\" button will transport you to this menu.",
    children=[
        Moderation,
    ]
    )

Moderation.PARENT = Main

######################################################
# Command

@commands.command(name="config",brief="A UI command to configure Typhoon",description="A command providing all configuration possibilites of Typhoon in a neat UI")
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