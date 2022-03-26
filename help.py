from discord.ext import commands
import discord, asyncio
from libs import utils

BOT : commands.Bot = ...

def split_help(content : str) -> tuple[str]:
    messages = [""]

    lines = content.split("\n")
    for line in lines:
        new_message_bit = "".join((messages[-1],line))
        if len(new_message_bit) > 2000:
            messages[-1] = "".join((messages[-1],"```"))
            messages.append("".join(("```md\n", line, "\n")))
            pass
        else:
            messages[-1] = "".join((new_message_bit,"\n"))
        pass

    return tuple(messages)
    pass

def help_command_call_struct(command : commands.Command) -> str:
    params = command.clean_params # Command parameters
    paramstring = ""
    for name, parameter in params.items():
        onestring = "".join(("<",name,">"))
        if parameter.default is not parameter.empty:
            onestring = "".join(("[",onestring,"]"))
            pass

        paramstring = "".join((paramstring," ",onestring))
        pass

    resp = "".join((command.name," ",paramstring))
    return resp
    pass

def help_from_cog(cog : commands.Cog) -> str:
    resp = "```md\n"
    for command in cog.get_commands():
        if isinstance(command,commands.Group):
            lines = help_from_group(command).splitlines(True)
            indented = "\t" + "\t".join(lines[1:])
            resp = "".join((resp,"\n+ ",lines[0],indented))
            pass
        else:
            resp = "".join((resp,"\n+ ",help_command_call_struct(command),"\n\t- ",str(command.brief)))
            pass
        pass

    return "".join((resp,"```"))
    pass

def help_from_group(command_group : commands.Group) -> str:
    resp = f"{command_group.name}: {command_group.brief}\n"
    for command in command_group.commands:
        if isinstance(command,commands.Group):
            command : commands.Group
            command_help = help_from_group(command)

            indented = "\t".join(command_help.splitlines(True))
            resp = "".join((resp,"+ ",indented,"\n"))
            pass
        else:
            resp = "".join((resp,"+ ",help_command_call_struct(command),"\n\t- ",command.brief,"\n"))
            pass
        pass

    return resp[:-1]
    pass

def whole_help() -> str:
    cog_commands = set()

    all_cogs_resp = ""
    for name, cog in BOT.cogs.items():
        cog_resp = f"\n# {name}\n{cog.description}\n"
        for command in cog.get_commands():
            if isinstance(command,commands.Group):
                lines = help_from_group(command).splitlines(True)
                indented = "\t" + "\t".join(lines[1:])
                cog_resp = "".join((cog_resp,"\n+ ",lines[0],indented))
                pass
            else:
                cog_resp = "".join((cog_resp,f"\n+ {help_command_call_struct(command)}\n\t- {command.brief}"))
                pass

            cog_commands.add(command) # Add command to set of commands with a cog
            pass

        all_cogs_resp = "\n".join((all_cogs_resp,cog_resp))
        pass

    no_cog_commands = BOT.commands.difference(cog_commands)
    no_cogs_resp = "# No category\n"
    for command in no_cog_commands:
        if isinstance(command,commands.Group):
            no_cogs_resp = "".join((cog_resp,help_from_group(command)))
            pass
        else:
            no_cogs_resp = "".join((no_cogs_resp,f"+ {help_command_call_struct(command)}\n\t- {command.brief}"))
            pass
        pass

    return "".join(("```md\n",no_cogs_resp,"\n",all_cogs_resp,"```"))
    pass

def searchCommands(matcher : str) -> set[commands.Command]:
    return set(filter(lambda command: utils.stringFilter(command.name,matcher),BOT.commands))
    pass

async def help(ctx : commands.Context, command_or_category : str = ""):
    message : discord.WebhookMessage = ...

    class HelpView(discord.ui.View):
        @discord.ui.select(
            placeholder="Select a category to see the help for",
            options=[discord.SelectOption(label=name,description=cog.description,value=name,default=(command_or_category.strip().lower()==name.lower())) for name, cog in BOT.cogs.items()] + [discord.SelectOption(label="All",value="__everything__",description="List help for every category (Note: This will send new messages)")],
            row=0
        )
        async def cog_select(self : discord.ui.View,select : discord.ui.Select, interaction : discord.Interaction):
            selected_cog = interaction.data.get("values")[0] # Get name of selected cog from interaction

            for option in select.options: option.default = False # Reset all defaults, in order to select a new one
            option = utils.selectOptionByValue(select,selected_cog) # Get selected option
            option.default = True # Set the (already selected) option as default so that it will appear in the menu
            if selected_cog == "__everything__":
                await message.edit("New messages should pop up any second now...",view=self)
                for content in split_help(whole_help()): await ctx.send(content,ephemeral=True)

                #await message.edit(whole_help(),view=self) # Edit help message to show the help for every cog
                pass
            else:
                cog = BOT.get_cog(selected_cog)
                await message.edit(help_from_cog(cog),view=self) # Edit the help message to apply to the new selected cog
                pass
            pass

        @discord.ui.button(label="Search for command",style=discord.ButtonStyle.primary,row=1)
        async def search_for_command(self : discord.ui.View, button : discord.ui.Button, interaction : discord.Interaction):
            select : discord.ui.Select = self.children[0] # Get select menu from message components
            button.disabled = True # Disable button
            select.disabled = True # Disable select menu

            await message.edit("```\nPlease type in a command search (send a message)\nUse ? as a one character wildcard\nand * as a multi character wildcard```",view=self)
            await interaction.response.defer()

            searchMsg : discord.Message = await BOT.wait_for("message",check=lambda msg: msg.author == ctx.author and msg.channel == ctx.channel) # Wait for a reply from the user
            await searchMsg.delete() # Delete the reply to prevent the help command from getting thrown to high up

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, searchCommands,searchMsg.content) # Search for all commands that match the filter given by the user

            searchResp = "```md\n" # Set up result
            for command in results:
                if isinstance(command,commands.Group):
                    searchResp = "".join((searchResp,help_from_group(command),"\n"))
                    pass
                else:
                    searchResp = "".join((searchResp,f"+ {help_command_call_struct(command)}\n\t- {command.description if command.description != '' else command.brief}\n"))
                    pass
                pass
            searchResp = "".join((searchResp,"```"))

            button.disabled = False # Reenable search option
            select.disabled = False # Reenable cog selection
            await message.edit(searchResp,view=self)
            pass
        pass

    view = HelpView()
    if command_or_category != "":
        msg_content = "```md\n"

        cog = BOT.get_cog(command_or_category)
        if cog is None: # If there is no cog with that name, search for command instead
            command = BOT.get_command(command_or_category)
            if command is not None:
                if isinstance(command, commands.Group):
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

    message : discord.WebhookMessage = await ctx.send(msg_content,view=view,ephemeral=True)
    pass


def setup(bot):
    global BOT

    BOT = bot

    BOT.add_command(commands.Command(help,brief="Shows infos for this bot's commands"))
    pass

def teardown():
    BOT.remove_command("help")
    pass