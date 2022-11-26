from discord.ext import commands
from discord import app_commands
import discord, asyncio
from libs import utils

BOT: commands.Bot = ...

def split_help(content: str) -> tuple[str]:
    messages = [""]

    lines = content.split("\n")
    for line in lines:
        new_message_bit = "".join((messages[-1],line))
        if len(new_message_bit) > 2000-3:
            # subtracting three to add "```" later
            messages[-1] = "".join((messages[-1],"```"))
            messages.append("".join(("```md\n", line, "\n")))
            pass
        else:
            messages[-1] = "".join((new_message_bit,"\n"))
        pass

    return tuple(messages)
    pass

def help_for_any_command(command: app_commands.Command|app_commands.ContextMenu|app_commands.Group) -> str:
    if isinstance(command,discord.app_commands.Group):
        lines = help_from_group(command).splitlines(True)
        indented = "\t" + "\t".join(lines[1:])
        single_help = f"+ {lines[0]}{indented}"
        pass
    elif isinstance(command,app_commands.ContextMenu):
        # Cannot use app_commands.ContextMenu
        single_help = f"+ {help_from_context_menu(command)}"
        pass
    elif isinstance(command,discord.app_commands.Command):
        single_help = f"+ {help_command_call_struct(command)}\n\t+ {command.description}"
        pass
    else:
        single_help = "+ Unknown command"
    
    return f"{single_help}"
    pass

def help_command_call_struct(command: app_commands.Command) -> str:
    paramstring = ""
    for parameter in command.parameters:
        onestring = "".join(("<",parameter.display_name,">"))
        if not parameter.required:
            onestring = "".join(("[",onestring,"]"))
            pass

        paramstring = "".join((paramstring," ",onestring))
        pass

    resp = "".join((command.name," ",paramstring))
    return resp
    pass

def help_from_cog(cog: commands.Cog) -> str:
    resp = f"```md\n# {cog.__cog_name__}\n{cog.description}\n"
    for command in cog.get_app_commands():
        resp = f"{resp}\n{help_for_any_command(command)}"
        pass

    return f"{resp}```"
    pass

def help_from_group(command_group: discord.app_commands.Group) -> str:
    resp = f"{command_group.name}: {command_group.description}\n"
    for command in command_group.commands:
        command: app_commands.Group|app_commands.Command
        if isinstance(command,discord.app_commands.Group):
            command_help = help_from_group(command)

            indented = "\t".join(command_help.splitlines(True))
            resp = "".join((resp,"+ ",indented,"\n"))
            pass
        else:
            if isinstance(command,app_commands.commands.ContextMenu):
                print("Group handler!")
                pass
            resp = f"{resp}+ {help_command_call_struct(command)}\n\t+ {command.description}\n"
            pass
        pass

    return resp[:-1]
    pass

def help_from_context_menu(command: discord.app_commands.ContextMenu) -> str:
    if command.type == discord.AppCommandType.message:
        cmd_type = "Message Command"
    elif command.type == discord.AppCommandType.user:
        cmd_type = "User Command"
    else:
        cmd_type = "Unknown Context Command"
    return f"({cmd_type}): {str(command.name)}"
    pass

def whole_help() -> str:
    cog_commands = set()

    all_cogs_resp = ""
    for name, cog in BOT.cogs.items():
        cog_resp = f"\n# {name}\n{cog.description}\n"
        for command in cog.get_app_commands():
            single_help = help_for_any_command(command)

            cog_resp = f"{cog_resp}\n{single_help}"
            cog_commands.add(command) # Add command to set of commands with a cog
            pass

        all_cogs_resp = f"{all_cogs_resp}\n{cog_resp}\n"
        pass

    no_cog_commands = set(BOT.tree.get_commands()).difference(cog_commands)
    no_cogs_resp = "# No category\n"
    for command in no_cog_commands:
        no_cogs_resp = f"{no_cogs_resp}\n{help_for_any_command(command)}"
        pass

    return f"```md\n{no_cogs_resp}\n{all_cogs_resp}```"
    pass

def searchCommands(matcher: str, current_guild: discord.Guild=None) -> set[app_commands.Command]:
    all_commands = BOT.tree.get_commands()
    if current_guild is not None: 
        all_commands.extend(BOT.tree.get_commands(guild=current_guild))
    
    return set(filter(
        lambda command: utils.stringFilter(command.name,matcher),
        all_commands))
    pass

async def help(interaction: discord.Interaction, command_or_category: str=""):
    await interaction.response.defer(ephemeral=True)

    message: discord.WebhookMessage = ...

    class HelpView(discord.ui.View):
        @discord.ui.select(
            placeholder="Select a category to see the help for",
            options=[discord.SelectOption(label=name,description=cog.description,value=name,default=(command_or_category.strip().lower()==name.lower())) for name, cog in BOT.cogs.items()] + [discord.SelectOption(label="All",value="__everything__",description="List help for every category (Note: This will send new messages)")],
            row=0
        )
        async def cog_select(self: discord.ui.View,vinteraction: discord.Interaction, select: discord.ui.Select):
            await vinteraction.response.defer(ephemeral=True)
            
            selected_cog = vinteraction.data.get("values")[0] # Get name of selected cog from interaction

            for option in select.options: option.default = False # Reset all defaults, in order to select a new one
            option = utils.selectOptionByValue(select,selected_cog) # Get selected option
            option.default = True # Set the (already selected) option as default so that it will appear in the menu
            if selected_cog == "__everything__":
                await message.edit(content="New messages should pop up any second now...",view=self)
                for content in split_help(whole_help()): await vinteraction.followup.send(content,ephemeral=True)
                pass
            else:
                cog = BOT.get_cog(selected_cog)
                await message.edit(content=help_from_cog(cog),view=self) # Edit the help message to apply to the new selected cog
                pass
            pass

        @discord.ui.button(label="Search for command",style=discord.ButtonStyle.primary,row=1)
        async def search_for_command(self: discord.ui.View, vinteraction: discord.Interaction, button: discord.ui.Button):
            await vinteraction.response.send_message("This function is not yet implemented and will be so in the future using modals", ephemeral=True)
            raise NotImplementedError("This function is not yet implemented and will be so in the future using modals")
            select: discord.ui.Select = self.children[0] # Get select menu from message components
            button.disabled = True # Disable button
            select.disabled = True # Disable select menu

            await message.edit(content="```\nPlease type in a command search (send a message)\nUse ? as a one character wildcard\nand * as a multi character wildcard```",view=self)
            await vinteraction.response.defer()

            searchMsg: discord.Message = await BOT.wait_for("message",check=lambda msg: msg.author.id == interaction.user.id and msg.channel == interaction.channel) # Wait for a reply from the user
            await searchMsg.delete() # Delete the reply to prevent the help command from getting thrown to high up

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, searchCommands,searchMsg.content) # Search for all commands that match the filter given by the user
            
            if len(results) > 0:
                searchResp = "```md\n" # Set up result
                for command in results:
                    if isinstance(command,app_commands.Group):
                        searchResp = "".join((searchResp,help_from_group(command),"\n"))
                        pass
                    else:
                        searchResp = "".join((searchResp,f"+ {help_command_call_struct(command)}\n\t- {command.description}\n"))
                        pass
                    pass
                searchResp = "".join((searchResp,"```"))
            else:
                searchResp = "```\nThere's no command matching this filter```"
                pass

            button.disabled = False # Reenable search option
            select.disabled = False # Reenable cog selection
            for option in select.options: option.default = False

            await message.edit(content=searchResp,view=self)
            pass
        pass

    view = HelpView()
    if command_or_category != "":
        msg_content = "```md\n"

        cog = BOT.get_cog(command_or_category)
        if cog is None: # If there is no cog with that name, search for command instead
            command = BOT.tree.get_command(command_or_category)
            if command is not None:
                if isinstance(command, app_commands.Group):
                    msg_content = "".join((msg_content,help_from_group(command),"```"))
                    pass
                else:
                    msg_content = "".join((msg_content,help_command_call_struct(command),"\n\t- ",f"{command.description if command.description != '' else command.brief}\n","```"))
                    pass
                pass
            else:
                msg_content = "```\nNo command or category with that name exists.\nPlease select from the menu below```"
                pass
            pass
        else:
            msg_content = help_from_cog(cog)
            pass
        pass
    else:
        msg_content = "```\nPlease select from the menu below```"

    message: discord.WebhookMessage = await interaction.followup.send(msg_content,view=view,ephemeral=True)
    pass


async def setup(bot):
    global BOT

    BOT = bot

    BOT.tree.command(name="help",description="Shows infos for this bot's commands")(help)
    pass

async def teardown():
    BOT.remove_command("help")
    pass