from inspect import getmembers
from typing import Callable, Coroutine, Optional, Any
import discord
from discord import ui
from abc import ABCMeta, abstractmethod
from datetime import datetime
from .utils import generate_snowflake

class EditorItem(metaclass=ABCMeta):
    __slots__ = ("_item", "_owner")

    _item_cls: type[ui.Item]= ...
    
    def __init_subclass__(cls, item_cls: type[ui.Item]):
        cls._item_cls= item_cls
        pass

    def __init__(self, 
        *args,
        **kwargs
        ):
        self._item= self._item_cls(*args,**kwargs)
        self._item.callback= self._item_callback
        pass

    async def _item_callback(self, interaction: discord.Interaction):
        await self(interaction)
        pass
    pass

def _wrap_button(ref: "Editor", callback):
    class EditorButton(EditorItem, item_cls=ui.Button):
        async def __call__(self, interaction: discord.Interaction):
            if interaction.user != ref._editor_author: return
            await callback(ref,interaction,self)
            await ref.update()
            pass
        pass
    
    return EditorButton(**callback.__editor_info__)
    pass

def _wrap_select(ref, callback):
    class EditorSelect(EditorItem, item_cls=ui.Select):
        async def __call__(self, interaction: discord.Interaction):
            if interaction.user != ref._editor_author: return
            await callback(ref,interaction,self,self._item.values)
            pass
        pass
    
    return EditorSelect(**callback.__editor_info__)
    pass

def button(
    label: str,
    style: discord.ButtonStyle,
    emoji: discord.PartialEmoji|discord.Emoji|str= None,
    disabled: bool= False,
    row: int|None= None
    ):
    def decorator(func: Callable[[Editor,EditorItem,discord.Interaction],Coroutine[Any,Any,None]]):
        func.__item_class__ = ui.Button
        func.__editor_info__ = {
            "label": label,
            "style": style,
            "emoji": emoji,
            "disabled": disabled,
            "row": row
        }

        return func
        pass

    return decorator
    pass

def select(
    options: list[discord.SelectOption],
    placeholder: str|None= None,
    min_values: int= 1,
    max_values: int= 1,
    disabled: bool= False,
    row: int|None= None
    ):
    def decorator(func: Callable[[Editor,EditorItem,list[str],discord.Interaction],Coroutine[Any,Any,None]]):
        func.__item_class__ = ui.Select
        func.__editor_info__ = {
            "options": options,
            "placeholder": placeholder,
            "min_values": min_values,
            "max_values": max_values,
            "disabled": disabled,
            "row": row
        }

        return func
        pass

    return decorator
    pass

class Editor(metaclass=ABCMeta):
    def _setup_view(self):
        for name, value in filter(
            lambda item: 
                hasattr(item[1],"__editor_info__") \
                and hasattr(item[1],"__item_class__"),
            getmembers(type(self))
            ):
            if value.__item_class__ == ui.Button:
                value = _wrap_button(self,value)
                pass
            else:
                value = _wrap_select(self,value)
                pass
            setattr(self,name,value)

            self._view.add_item(value._item)
            self._children[name]= value
            pass
        pass

    def __init__(self, author: discord.Member,*, timeout: Optional[float]= 180, snowflake_generator: Callable[[],str]=generate_snowflake):
        self._editor_author = author

        self._view = ui.View(timeout=timeout)
        self._children = {}
        self._snowflake_gen = snowflake_generator
        self._message = ...

        self.content = None
        self.embed = None

        self._setup_view()
        pass

    def set_message(self, message: discord.Message):
        self._message = message
        
        self.content = message.content
        self.embed = message.embeds[0] if len(message.embeds) > 0 else None
        pass

    async def update(self):
        if self._message is Ellipsis:
            raise RuntimeError("No message reference available. Editor was updated before call of Editor.set_message")
            pass

        await self._message.edit(content=self.content,embed=self.embed,view=self._view)
        pass
    pass

class SendCloseEditor(Editor):
    def __init__(self, author: discord.Member, *, timeout: Optional[float] = 180, snowflake_generator: Callable[[], str] = generate_snowflake):
        super().__init__(author, timeout=timeout, snowflake_generator=snowflake_generator)

        async def on_timeout():
            await self.close(self._message.channel,True)
            pass
        self._view.on_timeout = on_timeout
        pass

    @abstractmethod
    async def on_send(self, channel: discord.TextChannel): ...

    async def on_close(self,timed_out: bool): ...

    async def send_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def close(self, channel: discord.TextChannel|discord.Thread|discord.ForumChannel, timed_out: bool=False):
        self._view.clear_items()
        self._view.stop()

        await self.on_close(timed_out)
        pass

    @button("Send",discord.ButtonStyle.green,row=4)
    async def _send_trigger(self, interaction: discord.Interaction, button: EditorItem):
        await interaction.response.defer()

        if not await self.send_check(interaction): 
            return
            pass

        await self.on_send(interaction.channel)

        await self.close(interaction.channel)
        pass

    @button("Close",discord.ButtonStyle.red,row=4)
    async def _close_trigger(self, interaction: discord.Interaction, button: EditorItem):
        await self.close(interaction.channel)

        await interaction.response.defer()
        pass
    pass

class CloseEditor(Editor):
    def __init__(self, author: discord.Member, *, timeout: Optional[float] = 180, snowflake_generator: Callable[[], str] = generate_snowflake):
        super().__init__(author,timeout=timeout, snowflake_generator=snowflake_generator)

        async def on_timeout():
            await self.close(self._message.channel,True)
            pass
        self._view.on_timeout = on_timeout
        pass

    async def on_close(self,timed_out: bool): ...

    async def close(self, channel: discord.TextChannel|discord.Thread|discord.ForumChannel, timed_out: bool=False):
        self._view.clear_items()
        self._view.stop()

        await self.update()

        await self.on_close(timed_out)
        pass

    @button("Close",discord.ButtonStyle.red,row=4)
    async def _close_trigger(self, interaction: discord.Interaction, button: EditorItem):
        await self.close(interaction.channel)

        await interaction.response.defer()
        pass
    pass