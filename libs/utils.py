import logging, os, asyncio
import threading
from typing import *
from datetime import datetime

from discord.ext import commands
import discord

from ormclasses import *

def unzip(iterable: Iterable) -> zip:
    return zip(*iterable)
    pass

def first(sequence: Sequence[Any], matcher: Callable) -> Any:
    for element in sequence:
        if matcher(element): return element
        pass

    raise ValueError("No match found")
    pass

def stringFromDuration(seconds: int):
    minutes = seconds // 60
    seconds%=60
    
    hours = minutes // 60
    minutes%=60

    return f"{hours}H {minutes}M {seconds}S"
    pass

def durationFromString(text: str) -> int:
    hourPoint = text.find("H")
    minPoint  = text.find("M")
    secPoint = text.find("S")

    hours   = int(text[:hourPoint])           if hourPoint!=-1 else 0
    minutes = int(text[hourPoint+1:minPoint]) if minPoint !=-1 else 0
    seconds = int(text[minPoint+1:secPoint])  if secPoint !=-1 else 0

    return hours*3600 + minutes*60 + seconds
    pass

def setCustomLogger(level=logging.INFO):
    if not os.path.exists('logs'):
        os.mkdir("logs")

    currTime = datetime.now()
    logFileName = "logs/{0}-{1}-{2}-{3}.log".format(currTime.date(),currTime.hour,currTime.minute,currTime.second)
    formatStr = "[%(asctime)s | %(threadName)s / %(levelname)s] %(message)s"
    logging.basicConfig(filename = logFileName, level=level,format=formatStr)

    stdoutLogger = logging.StreamHandler()
    stdoutLogger.setFormatter(logging.Formatter(formatStr))
    logging.getLogger().addHandler(stdoutLogger)

def call_once(func: Callable):
    func.__was_called__ = False

    def wrapper(*args,**kwargs):
        if func.__was_called__: return None

        func.__was_called__ = True
        return func(*args,**kwargs)
        pass 

    wrapper.__name__ = func.__name__
    return wrapper
    pass

def call_once_async(func: Callable):
    func.__was_called__ = False

    async def wrapper(*args,**kwargs):
        if func.__was_called__: return None

        func.__was_called__ = True
        return await func(*args,**kwargs)
        pass 

    wrapper.__name__ = func.__name__
    return wrapper
    pass

def perm_message_check(error_msg: str="No Permission",**perms: bool):
    def decorator(func: Callable):
        func.permission_error_msg = error_msg
        return commands.has_permissions(**perms)(func)
        pass

    return decorator
    pass

async def confirmation_interact(interaction: discord.Interaction, question: str="Are you sure you want to do this?", confirm_option: str="Confirm",*,timeout: float =180) -> bool:
    class Confirmation(discord.ui.View):
        def __init__(view, *, timeout: Optional[float] = 180):
            view.response = False
            super().__init__(timeout=timeout)

        @discord.ui.button(label=confirm_option,style=discord.ButtonStyle.danger)
        async def confirm(view, vinteraction: discord.Interaction, button):
            await vinteraction.response.defer()

            view.response = True
            view.stop()
            pass

        @discord.ui.button(label="Cancel",style=discord.ButtonStyle.green)
        async def cancel(view, vinteraction: discord.Interaction, button):
            await vinteraction.response.defer()

            view.response = False
            view.stop()
            pass
        pass

    view = Confirmation(timeout=timeout)
    msg = await interaction.followup.send(question,view=view,ephemeral=True)
    
    timed_out = await view.wait()
    await msg.edit(content="Interaction completed. You can close this message now",view=None)
    return (not timed_out) and view.response
    pass

def _view_set_all_able_state(view: discord.ui.View, state: bool):
    for item in view.children:
        if type(item) in (discord.ui.Select, discord.ui.Button):
            item.disabled = state
            pass
        pass
    pass

def view_enable_all(view: discord.ui.View):
    _view_set_all_able_state(view,False)
    pass

def view_disable_all(view: discord.ui.View):
    _view_set_all_able_state(view,True)
    pass

class Singleton:
    """Inherit from this class to create a Singleton instance"""
    _instances = dict()
    def __new__(cls):
        if not cls in cls._instances.keys():
            cls._instances[cls] = object.__new__(cls)
            pass
        return cls._instances[cls]
        pass
    pass

def stringFilter(name: str, matcher: str) -> bool:
    star_wildcard = -1 # Marks the place at which a * wildcard was found
    j = 0
    for i in range(len(name)):
        if j >= len(matcher):
            return False

        if matcher[j] == "*":
            star_wildcard = j
            pass

        char = name[i]
        if star_wildcard +1 == len(matcher): return True
        if star_wildcard > -1 and not matcher[star_wildcard+1] == char: # Skip checks as long as the current character does not match the next filter-char
            continue
        elif star_wildcard > -1:
            j+=1 # Increment to next character (so that it won't find the wildcard again)
            pass
        star_wildcard = -1 # Reset wildcard index

        if char != matcher[j] and matcher[j] != "?": # ? is 1 character wildcard
            return False
            pass
        j += 1
        pass
    return j >= len(matcher)
    pass

def colourFromString(hex_string: str) -> discord.Colour:
    hex_string = hex_string.strip()
    if len(hex_string) != 6: raise ValueError()
    red   = int(hex_string[0:2],base=16)
    green = int(hex_string[2:4],base=16)
    blue  = int(hex_string[4:6],base=16)

    return discord.Colour.from_rgb(red,green,blue)
    pass

def set_component_state_recursive(view_or_row: Union[discord.ui.View,discord.ActionRow],state: bool):
    for child in view_or_row.children:
        if isinstance(child,discord.ActionRow):
            set_component_state_recursive(child)
            pass
        else:
            child: discord.Component
            child.disabled = not state
            pass
        pass
    pass

def getButtonByLabel(view: discord.ui.View,label: str) -> Optional[discord.Button]:
    for child in view.children:
        if not isinstance(child,discord.ui.Button): continue
        if child.label == label: return child
        pass
    return None
    pass

def selectOptionByValue(select: discord.ui.Select, name: str):
    for option in select.options:
        if option.value == name: return option
        pass
    pass

class WebhookPool:
    def __init__(self, bot: commands.Bot):
        self.pool: dict[int,dict[int,discord.Webhook]] = {}
        self._initialized = False
        self._bot = bot
        pass

    async def get(self, channel: discord.TextChannel,*,reason: str="New Webhook gathered from pool") -> discord.Webhook:
        if not channel.guild.id in self.pool.keys():
            self.pool[channel.guild.id] = {}
            pass

        if not channel.id in self.pool[channel.guild.id].keys():
            webhooks = [webhook for webhook in await channel.webhooks() if webhook.type == discord.WebhookType.incoming and webhook.user.id == self._bot.user.id]
            if len(webhooks) == 0:
                webhooks.append(await channel.create_webhook(name=self._bot.user.name,avatar=await self._bot.user.avatar.read(),reason=reason))
                pass
            
            self.pool[channel.guild.id][channel.id] = webhooks[0]
            pass

        return self.pool[channel.guild.id][channel.id]
        pass

    def clear(self):
        self.pool.clear()
        pass
    pass

async def get_guild(session: asql.AsyncSession, guild_id: int) -> Guild:
    result: CursorResult = await session.execute(sql.select(Guild).where(Guild.id == str(guild_id)))
    sql_guild = result.scalar_one_or_none()
    if sql_guild is None:
        sql_guild = Guild(id=str(guild_id))
        session.add(sql_guild)
        pass

    return sql_guild
    pass

def generate_snowflake(*,__inc__=[0]) -> int: # __inc__ is a list because that means it will be stored across execution
    """Generates a snowflake according to https://discord.com/developers/docs/reference#snowflakes"""
    if not isinstance(__inc__[0],int): raise TypeError("Cached increment is not an integer. You probably set it as something else. Don't")

    raw_binary = lambda n: bin(n)[2:] # Does not include 0b prefix

    # Get Unix Epoch
    utc_time = datetime.utcnow()
    unix_millis = int(utc_time.timestamp()*1000)
    
    discord_epoch = unix_millis - 1420070400000 # Discord Epoch is counting first second since 2015
    internal_process_id = 31 # Setting to 31 because it is not possible according to Discord's docs, meaning this will not occur as a snowflake from discord
    internal_worker_id  = 31 # Same as above

    snowflake = eval("0b" + raw_binary(discord_epoch) + raw_binary(internal_process_id) + raw_binary(internal_worker_id) + raw_binary(__inc__[0]))
    # This uses eval and is therefore a potential issue. But, the only possible input is __inc__[0] which can only be an integer

    __inc__[0] += 1
    __inc__[0] %= 2**12

    return snowflake
    pass

class ValueErrorConverter(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str) -> int:
        try:
            return self._CONVERTER(argument)
        except ValueError:
            raise commands.BadArgument("argument is not a valid integer")
            pass
        pass
    pass

class IntConverter(ValueErrorConverter):
    _CONVERTER = int
    pass

class FloatConverter(ValueErrorConverter):
    _CONVERTER = float
    pass

async def wait_for_convert(
    bot: commands.Bot, 
    ctx: commands.Context, 
    converter: commands.Converter, 
    error_prompt: str="Passed argument could not be converted", 
    check=lambda val: True, timeout: float=None
) -> Optional[Any]:
    while True:
        resp_msg: discord.Message = await bot.wait_for("message",check=lambda msg: msg.author == ctx.author and msg.channel == ctx.channel,timeout=timeout)
        try:
            obj = await converter.convert(ctx,resp_msg.content)
        except commands.CommandError:
            await ctx.send(error_prompt,ephemeral=True)
            pass
        else:
            if not check(obj): 
                await ctx.send(error_prompt,ephemeral=True)
                continue
            break
        finally:
            await resp_msg.delete()
            pass
        pass

    return obj
    pass

async def wait_for_role(
    bot: commands.Bot, 
    ctx: commands.Context, 
    error_prompt: str="Passed argument was not a role", 
    check=lambda msg: True,timeout: float=None
) -> Optional[discord.Role]:
    return await wait_for_convert(bot,ctx,commands.RoleConverter(),error_prompt,check,timeout)
    pass

async def wait_for_text_channel(
    bot: commands.Bot, 
    ctx: commands.Context, 
    error_prompt: str="Passed argument was not a text channel", 
    timeout: float=None, 
    check=lambda msg: True
) -> Optional[discord.TextChannel]:
    return await wait_for_convert(bot,ctx,commands.TextChannelConverter(),error_prompt,check,timeout)
    pass

def get_SingleSelectView(placeholder: str,options: list[discord.SelectOption], owner: discord.Member=None):
    class SingleSelectView(discord.ui.View):
        def __init__(self, *, timeout: Optional[float] = 180):
            self.result = None
            super().__init__(timeout=timeout)

        @discord.ui.select(
            placeholder=placeholder,
            options=options
        )
        async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
            if owner is not None and owner != interaction.user: 
                return
                
            self.result = discord.utils.find(
                lambda option: option.value == select.values[0],
                options
            )
            self.stop()

            await interaction.response.defer()
            pass
        pass

    return SingleSelectView

def get_SingleTextModal(
    label: str,
    style: discord.TextStyle=discord.TextStyle.short,
    placeholder: str|None=None,
    default: str|None=None,
    min_length: int|None=None,
    max_length: int|None=None,
    
    *,
    required: bool=True
):
    class SingleTextModal(discord.ui.Modal):
        completion_info = (None, None)

        text_input = discord.ui.TextInput(
            label=label, 
            style=style,
            placeholder=placeholder,
            default=default,
            required=required,
            min_length=min_length,
            max_length=max_length,
            row=0
        )

        async def on_submit(self, interaction: discord.Interaction) -> None:
            self.completion_info = (interaction, self.text_input.value)
            pass

        async def wait_for_results(self) -> tuple[discord.Interaction,str]|tuple[None,None]:
            await self.wait()

            return self.completion_info
            pass
        pass

    return SingleTextModal
    pass