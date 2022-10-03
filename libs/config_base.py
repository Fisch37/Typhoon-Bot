CONFIG_TIMEOUT = 600

from typing import Any, Iterable, Optional, Union, Callable, Coroutine

import discord, discord.ui
from discord.ext import commands
import asyncio, dataclasses, logging, time
from . import utils

async def close_confirm(interaction: discord.Interaction):
    will_close = [False] # Global-local issues again...

    close_confirm_view = discord.ui.View()
    yes_button = discord.ui.Button(style=discord.ButtonStyle.danger,label="Yes")
    no_button  = discord.ui.Button(style=discord.ButtonStyle.green,label="No")
    
    close_confirm_view.add_item(yes_button)
    close_confirm_view.add_item(no_button)
    
    async def yes_interaction(new_interaction: discord.Interaction) -> None:
        will_close[0] = True

        close_confirm_view.stop()
        await new_interaction.response.defer()
        pass
    async def no_interaction(new_interaction: discord.Interaction) -> None:
        will_close[0] = False

        close_confirm_view.stop()
        await new_interaction.response.defer()
        pass

    yes_button.callback = yes_interaction
    no_button .callback = no_interaction


    await interaction.response.send_message("Are you certain you want to close this interaction?",view=close_confirm_view,ephemeral=True)
    await close_confirm_view.wait()
    return will_close[0]
    pass

# View Options preperation
@dataclasses.dataclass()
class ConfigOption:
    type: type[discord.ui.Item]
    style: dict[str,Any]

    async def callback(self, interaction) -> None: ...
    pass

@dataclasses.dataclass(init=False)
class ConfigButton(ConfigOption):
    style: discord.ButtonStyle
    label: str
    emoji: Optional[discord.PartialEmoji]
    redirect_url: Optional[str]
    row: int = 0

    def __init__(
            self, 
            style: discord.ButtonStyle, 
            label: str, 
            emoji: Optional[discord.PartialEmoji]=None, 
            redirect_url: Optional[str]=None,
            row: int=0
        ):
        self.style, self.label, self.emoji, self.redirect_url, self.row = style, label, emoji, redirect_url, row

        super().__init__(discord.ui.Button,
            {
                "style":style,
                "label":label,
                "url":redirect_url,
                "emoji":emoji,
                "row":row
            }
        )
        pass
    pass

@dataclasses.dataclass(init=False)
class ConfigSelect(ConfigOption):
    value_range: range
    placehold_text: Optional[str]
    options: tuple[discord.SelectOption]
    row: int = 0

    def __init__(
        self,
        value_range: range,
        options: tuple[discord.SelectOption],
        placehold_text: Optional[str] = None,
        row: int = 0
        ):
        self.value_range, self.placehold_text, self.options, self.row = value_range, placehold_text, options, row

        super().__init__(discord.ui.Select,
        {
            "placeholder":placehold_text,
            "min_values":value_range.start,
            "max_values":value_range.stop - 1,
            "options":options,
            "row":row
        }
        )
        pass

    async def select_callback(self, interaction: discord.Interaction, values: list[str]) -> None: ...

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.select_callback(interaction,interaction.data["values"])
        pass
    pass


# View preperation
@dataclasses.dataclass(init=False)
class ConfigBase:
    TITLE: str = ...
    SHORT_DESCR: str = ...
    LONG_DESCR: str = ...
    COLOUR: discord.Colour = ...
    PARENT: "ConfigBase" = ...

    embed: discord.Embed
    view: discord.ui.View = ...
    message: discord.Message
    
    is_active: bool

    def __init__(self, embed: discord.Embed, message: discord.Message, ctx: commands.Context) -> None:
        self.embed, self.message, self.ctx = embed, message, ctx
        self.config_buttons = {}
        
        asyncio.create_task(self.timeout_handler())
        pass

    async def on_timeout(self):
        self.embed = discord.Embed(title="Interaction timed out",colour=discord.Colour.red(),description="This interaction timed out due to inactivity")
        self.view.stop()
        self.view = None

        # Calling the class specifically so that it doesn't call the update of any subclasses (like FactoryElement for example)
        self.embed.clear_fields()
        await ConfigBase.update(self)
        pass

    async def timeout_handler(self):
        self.last_change = time.perf_counter_ns()
        while (time.perf_counter_ns() - self.last_change) < CONFIG_TIMEOUT*(10**9):
            await asyncio.sleep(1)
            if not self.is_active: return
            pass

        await self.on_timeout()
        pass


    def add_view_items(self):
        back_button = discord.ui.Button(style=discord.ButtonStyle.primary,label="Back",row=4, disabled=self.PARENT is None)
        main_button = discord.ui.Button(style=discord.ButtonStyle.secondary,label="Back to top",row=4, disabled=self.PARENT is None)
        close_button = discord.ui.Button(style=discord.ButtonStyle.danger,label="Close",row=4)

        self.config_buttons = {
            "back": back_button,
            "main": main_button,
            "close": close_button
        }

        for item in (back_button,main_button,close_button):
            self.view.add_item(item)
            pass
        pass

    def add_callbacks(self,*, items: Optional[Iterable[discord.ui.Item]]=None):
        def create_handler(child):
            async def handle(interaction):
                utils.view_disable_all(self.view)
                await self.message.edit(view=self.view)
                # Doing this in parallel might RACE with things happening in on_view_interaction
                # E.g. in ConfigBranch

                try:
                    await self.on_view_interaction(child,interaction)
                finally:
                    if self.view is not None:
                        # The view may be none if this happens in a config branch
                        # (When switching to a different branch the view is briefly None)
                        utils.view_enable_all(self.view)
                        await self.message.edit(view=self.view)
                        pass
                    pass
                pass

            return handle
            pass

        for child in self.view.children if items is None else items:
            child.callback = create_handler(child)
            pass
        pass

    def assure_view(self):
        if self.view is Ellipsis:
            self.view = discord.ui.View(timeout=None)
            self.add_view_items()
            self.add_callbacks()
            pass
        pass

    async def update(self):
        self.last_change = time.perf_counter_ns()

        self.assure_view()

        await self.message.edit(embed=self.embed, view=self.view)
        pass

    async def on_view_interaction(self, element: discord.ui.Item, interaction: discord.Interaction):
        if element is self.config_buttons["back"]:
            await self.switch_to_parent()
            pass
        elif element is self.config_buttons["main"]:
            top_level: ConfigBase = self
            while top_level.PARENT is not None: top_level = top_level.PARENT # Always go further up when there's still a parent left

            await self.deactivate()
            await top_level(self.embed,self.message,self.ctx).activate()
            pass

        elif element is self.config_buttons["close"]:
            if await close_confirm(interaction): # Ask for confirmation before closing
                await interaction.followup.send("Closing interaction",ephemeral=True)
                await self.close()
                pass
            else:
                await interaction.followup.send("Closing cancelled",ephemeral=True)
                pass
            pass
        if element is not self.config_buttons["close"]: await interaction.response.defer()
        pass

    async def close(self):
        await self.deactivate()

        await self.message.edit(embed=discord.Embed(colour=discord.Colour.orange(),title="Interaction closed",description="This interaction was closed by the user"))
        pass

    async def wait(self):
        while self.is_active: await asyncio.sleep(0.1)
        pass

    async def activate(self):
        self.is_active = True
        
        self.embed.title = self.TITLE
        self.embed.description = self.LONG_DESCR
        self.embed.colour = self.COLOUR
        self.embed.clear_fields()
        await self.update()
        pass

    async def deactivate(self):
        self.view.stop()
        self.view = None
        
        self.is_active = False
        await self.update()
        pass

    async def switch_to_parent(self):
        await self.deactivate()
        await self.PARENT(self.embed,self.message,self.ctx).activate()
        pass
    pass

@dataclasses.dataclass(init=False)
class ConfigBranch(ConfigBase):
    CHILDREN: list[ConfigBase] = ...
    active_child: Optional[ConfigBase]
    
    def __init__(self, embed: discord.Embed, message: discord.Message, guild: discord.Guild):
        super().__init__(embed,message,guild)
        
        self.CHILDREN_DICT = {child.TITLE: child for child in self.CHILDREN}
        self.active_child = None
        pass

    def add_view_items(self):
        super().add_view_items()

        select_menu = discord.ui.Select(placeholder="Select a branch to go to",row=0,options=[
            discord.SelectOption(label=child.TITLE,value=child.TITLE,description=child.SHORT_DESCR)
            for child in self.CHILDREN
        ])

        self.view.add_item(select_menu)
        pass

    async def on_view_interaction(self, element: Union[discord.ui.Button,discord.ui.Select], interaction: discord.Interaction):
        await super().on_view_interaction(element,interaction)

        if isinstance(element,discord.ui.Select):
            child = self.CHILDREN_DICT[element.values[0]]
            await self.switch_to_child(child)
            pass
        pass

    async def switch_to_child(self, child: ConfigBase):
        await self.deactivate()

        child_obj = child(self.embed,self.message,self.ctx)
        await child_obj.activate()
        pass
    pass

@dataclasses.dataclass(init=False)
class ConfigElement(ConfigBase):
    OPTIONS: tuple[ConfigOption]

    def add_view_items(self):
        "NOTE: Callback system missing"
        super().add_view_items()

        for option in self.OPTIONS:
            item = option.type(**option.style)
            self.view.add_item(item)
            pass
        pass

    def add_callbacks(self):
        super().add_callbacks()
        pass
    pass





def branch_factory(title: str,*, short_description: str, long_description: str, children: list[ConfigBase], colour=discord.Colour.blurple(), parent: Optional[ConfigBranch]=None):
    class Factory_Branch(ConfigBranch):
        TITLE = title
        SHORT_DESCR = short_description
        LONG_DESCR = long_description
        COLOUR = colour
        PARENT = parent

        CHILDREN = children
        pass

    return Factory_Branch
    pass

def element_factory(
    title: str,*, short_description: str, long_description: str, options: list[ConfigBranch], colour=discord.Colour.blurple(), parent: Optional[ConfigBranch]=None,
    update_callback: Optional[Callable[["ConfigElement"],Coroutine[Any,Any,None]]]=None,
    view_interact_callback: Optional[Callable[["ConfigElement",discord.ui.Item,discord.Interaction],Coroutine[Any,Any,None]]]=None
    ):
    class Factory_Element(ConfigElement):
        TITLE = title
        SHORT_DESCR = short_description
        LONG_DESCR = long_description
        COLOUR = colour
        PARENT = parent

        OPTIONS = options

        async def update(self) -> None:
            self.assure_view() # Do this so on the first update a view definitely exists
            if update_callback is not None and self.is_active: await update_callback(self)
            await super().update()
            pass

        async def on_view_interaction(self, element: discord.ui.Item, interaction: discord.Interaction):
            await super().on_view_interaction(element, interaction)

            if view_interact_callback is not None and self.is_active: 
                await view_interact_callback(self,element,interaction)
                await self.update()
                pass
            pass
        pass

    return Factory_Element
    pass