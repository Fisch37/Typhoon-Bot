from libs import config, utils
from ormclasses import *
from typing import Sequence, Any

import discord
from discord.ext import commands

# Declare constants
CONFIG : config.Config = ...

BOT : commands.Bot = ...
WEBHOOK_POOL : utils.WebhookPool = ...

ENGINE : asql.AsyncEngine = ...
SESSION_FACTORY : orm.sessionmaker = ...


def run_sequence(dictionary : dict, sequence : Sequence) -> Any:
    for key in sequence:
        dictionary = dictionary[key]
        pass

    return dictionary
    pass

class BaseView(discord.ui.View):
    MENU = None
    def __init__(self, parent):
        self.message    : discord.Message   = ...
        self.embed      : discord.Embed     = ...
        self.parent     : type              = parent

        super().__init__(timeout=CONFIG.EDIT_TIMEOUT)
        utils.getButtonByLabel(self,"Back").disabled = self.parent is None
        pass

    def set_info(self, message : discord.Message, embed : discord.Embed):
        self.message, self.embed = message, embed
        pass

    async def on_timeout(self) -> None:
        await self.message.edit(content="```\nThis interaction timed out```",view=None)
        await super().on_timeout()
        pass

    async def update_message(self,info_message : str = None):
        await self.message.edit(content=info_message,embed=self.embed,view=self)
        pass


    @discord.ui.button(label="Back",style=discord.ButtonStyle.gray)
    async def go_to_parent(self, button : discord.ui.Button, interaction : discord.Interaction):
        new_view : BaseView = self.parent(PARENT_DICTIONARY[self.parent],CONFIG.EDIT_TIMEOUT)
        new_view.set_info(self.message,self.embed)
        await new_view.update_message()

        self.stop()
        await interaction.response.defer()
        pass
    pass

class TreeSelectView(BaseView):
    MENU : tuple[str] = ...
    def __init__(self):
        super().__init__(PARENT_DICTIONARY[self.__class__])
        if isinstance(self.MENU,ellipsis): raise RuntimeError(f"{self.__class__} has an undefined MENU constant. This value has to be set")

        select_menu = discord.ui.Select(placeholder="Please select a value",options=[discord.SelectOption(label=k,value=k,description=v[0]) for k, v in run_sequence(SUBMENUS,self.MENU).items()])
        select_menu.callback = self.select_callback
        pass

    async def select_callback(self, select : discord.ui.Select, interaction : discord.Interaction) -> None:
        raise NotImplementedError("You have to define a callback function for the select menu")
        pass
    pass

class TreeView(TreeSelectView):
    def __init__(self,menu : tuple[str]):
        self.MENU = menu
        super().__init__()
        pass

    async def select_callback(self, select: discord.ui.Select, interaction: discord.Interaction) -> None:
        selected_value : str = interaction.data["values"][0]

        menu_equiv_data = MENU_EQUIVS[selected_value]
        menu_equiv_data[0](*menu_equiv_data[1])
        pass
    pass

PARENT_DICTIONARY = {
    
}

SUBMENUS = {
    "Main" : {
        "Moderation"
    },
}

MENU_EQUIVS = {
    "Main" : (
        TreeView,
        (tuple(),)
    )
}

@commands.command(name="config",brief="Configure the bot",description="A command for configuring anything with one command")
async def conf_cmd(ctx : commands.Context):
    embed = discord.Embed(colour=discord.Colour.blue(),title="Config")
    view = StartView()
    
    message = await ctx.send(embed=embed,view=view)
    view.set_info(message,embed)
    pass

def setup(bot : commands.Bot):
    global CONFIG, WEBHOOK_POOL
    global BOT
    global SESSION_FACTORY, ENGINE

    CONFIG, WEBHOOK_POOL = bot.CONFIG, bot.WEBHOOK_POOL
    BOT = bot
    SESSION_FACTORY, ENGINE = bot.SESSION_FACTORY, bot.ENGINE


    @BOT.command(name="config",brief="Configure the bot",description="A command for configuring anything with one command")
    async def conf_cmd(ctx : commands.Context):
        embed = discord.Embed(colour=discord.Colour.blue(),title="Config")
        view = StartView(CONFIG.EDIT_TIMEOUT)
        
        message = await ctx.send(embed=embed,view=view)
        view.set_info(message,embed)
        pass
    pass

def teardown(bot : commands.Bot):
    pass