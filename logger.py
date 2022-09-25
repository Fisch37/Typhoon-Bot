import discord, logging, asyncio
from typing import Literal, Union, Optional
from datetime import datetime

GuildId = int
Channel = Union[discord.TextChannel,discord.VoiceChannel,discord.StageChannel,discord.CategoryChannel]

class Significance:
    LOW = discord.Colour.green()
    MID = discord.Colour.yellow()
    HIGH = discord.Colour.red()

class Event:
    Mute    = dict[Literal["manual","member","reason","until","actor"],Union[bool,discord.Member,str,int]]
    Unmute  = dict[Literal["member","reason","actor"],Union[discord.Member,str]]
    Automod = dict[Literal["member","message"],Union[discord.Member,discord.Message]]
    GuildChannel_Create = dict[Literal["channel"],Channel]
    GuildChannel_Delete = dict[Literal["channel"],Channel]
    GuildChannel_Update = dict[Literal["before"],Literal["after"]]
    GuildSettings = dict[Literal["before","after"],discord.Guild]
    EmojiUpdate = dict[Literal["guild","before","after"],Union[discord.Guild,list[discord.Emoji]]]
    EmojiUpdate = dict[Literal["guild","before","after"],Union[discord.Guild,list[discord.Sticker]]]
    Invite = dict[Literal["invite"],discord.Invite]
    Member_JL = dict[Literal["member"],discord.Member]
    Member_Update = dict[Literal["before","after"],discord.Member]
    Message_Edit = dict[Literal["payload"],discord.RawMessageUpdateEvent]
    Message_Delete = dict[Literal["payload"],discord.RawMessageDeleteEvent]
    Reaction_Clear = dict[Literal["message","reactions"],Union[discord.Message,list[Union[discord.Emoji,discord.PartialEmoji]]]]
    Role = dict[Literal["role"],discord.Role]
    Role_Update = dict[Literal["before","after"],discord.Role]
    Thread_Update = dict[Literal["before","after"],discord.Thread]
    Thread_Delete = dict[Literal["thread"],discord.Thread]

    # See now: _Big_ Numbers! (I think I spend 30 minutes just writing these numbers)
    # I'm taking a break now...
    # In hindsight some of them are actually not doing anything anymore... I've removed some
    ########################################___
    GUILD_CHANNEL_CREATE    = 0b000000000010000
    GUILD_CHANNEL_DELETE    = 0b000000000010001
    GUILD_CHANNEL_UPDATE    = 0b000000000010010
    GUILD_CHANNEL_MASK      = 0b000000000010000

    GUILD_SETTINGS_UPDATE   = 0b000000000100000
    GUILD_EMOJI_UPDATE      = 0b000000000100001
    GUILD_STICKER_UPDATE    = 0b000000000100010
    GUILD_MASK              = 0b000000000100000

    INVITE_CREATE           = 0b000000001000000
    INVITE_DELETE           = 0b000000001000001
    INVITE_MASK             = 0b000000001000000

    MEMBER_JOIN             = 0b000000010000000
    MEMBER_LEAVE            = 0b000000010000001
    MEMBER_UPDATE           = 0b000000010000010
    MEMBER_MASK             = 0b000000010000000

    MESSAGE_EDIT            = 0b000000100000000
    MESSAGE_DELETE          = 0b000000100000001
    MESSAGE_BULK_DELETE     = 0b000000100000010
    MESSAGE_MASK            = 0b000000100000000

    REACTION_ADD            = 0b000001000000000
    REACTION_REMOVE         = 0b000001000000001
    REACTION_MASK           = 0b000001000000000

    REACTION_CLEAR_ALL      = 0b000010000000000
    REACTION_CLEAR_SINGLE   = 0b000010000000001
    REACTION_MOD_MASK       = 0b000010000000000

    ROLE_CREATE             = 0b000100000000000
    ROLE_DELETE             = 0b000100000000001
    ROLE_UPDATE             = 0b000100000000010
    ROLE_MASK               = 0b000100000000000

    THREADS_UPDATE          = 0b001000000000000
    THREADS_DELETE          = 0b001000000000001
    THREADS_MASK            = 0b000100000000000

    MUTE_EVENT              = 0b010000000000000
    UNMUTE_EVENT            = 0b010000000000001
    MUTE_MASK               = 0b010000000000000

    AUTOMOD_SPAM            = 0b000000000001000
    AUTOMOD_CAPS            = 0b000000000001001
    AUTOMOD_EMOTE           = 0b000000000001010
    AUTOMOD_MASK            = 0b000000000001000

    MOD_KICK                = 0b100000000000000
    MOD_BAN                 = 0b100000000000001
    MOD_MASK                = 0b100000000000000

    __slots__ = ("type","data", "guild")
    def __init__(self, type: int, guild: discord.Guild, data):
        self.type = type
        self.data = data
        self.guild = guild
        pass
    pass

LOGGING_EVENTS: list[Event] = []
LOGGING_CHANNEL: dict[GuildId,Optional[int]] = []


def gen_permission_override_string(perm_overrides: dict[Union[discord.Role,discord.Member],discord.PermissionOverwrite]) -> str:
    def state_to_str(state: Optional[bool]) -> str:
        if state is None: return ":heavy_minus_sign:"
        elif state is False: return ":x:"
        else: return ":white_check_mark:"
        pass
    # This line seems unreasonably long... Debugging this will be fun! Hehe...
    return "\n\n".join("".join((target.mention,"\n\t".join((perm+": "+state_to_str(state) for perm, state in override))) for target, override in perm_overrides.items()))
    pass

def channel_extra_description(event_type: int,channel: Channel) -> str:
    if isinstance(channel  ,discord.TextChannel ): channel_type = "Text"
    elif isinstance(channel,discord.VoiceChannel): channel_type = "Voice"
    elif isinstance(channel,discord.StageChannel): channel_type = "Stage"
    elif isinstance(channel,discord.CategoryChannel): channel_type = "Category"

    lines = []
    lines.append(f"Type: {channel_type}")
    lines.append(f"Name: {channel.name}")
    lines.append(f"Category: {channel.category}")
    
    if event_type == Event.GUILD_CHANNEL_CREATE:
        if isinstance(channel,discord.TextChannel):
            lines.append(f"Slowmode: {channel.slowmode_delay}s")
            pass
        elif isinstance(channel,discord.VoiceChannel):
            lines.append(f"Bitrate: {channel.bitrate}")
            lines.append(f"User Limit: {channel.user_limit}")
            lines.append(f"Video Quality: {channel.video_quality_mode.name}")
            lines.append(f"Region Override: {channel.rtc_region}")
            pass
        elif isinstance(channel,discord.StageChannel):
            lines.append("\n\t".join(channel.moderators))
            lines.append(f"Region Override: {channel.rtc_region}")
            pass

        lines.append(gen_permission_override_string(channel.overwrites))

    return "\n".join(lines)
    pass

def add_logging_event(event: Event):
    LOGGING_EVENTS.append(event)
    pass

def assemble_logging_embed(type: str, significance: discord.Colour, member: discord.Member, actor: discord.Member, message: discord.Message = None, reason: str = None, extra_description: str = None) -> discord.Embed:
    embed = discord.Embed(colour=significance,title=type,description="",timestamp=datetime.now())
    embed.set_footer(text=f"Issued by {actor.mention}",icon_url=actor.avatar.url)
    embed.set_author(name=member.name,icon_url=member.avatar.url)

    if message is not None:
        embed.description = "".join((embed.description,f"Regarding message on <t:{int(message.created_at.timestamp())}>:\n{message.clean_content}\n\n"))
        pass
    embed.description = "".join((embed.description,f"Reason: {reason}"))
    if extra_description is not None:
        embed.description = "".join((embed.description,extra_description))
        pass

    return embed
    pass

async def handle_event(event: Event):
    
    log_channel_id: int = LOGGING_CHANNEL.get(event.guild.id)
    if log_channel_id is None: return # This shouldn't happen, but safety!

    if event.type & Event.AUTOMOD_MASK:
        event_data: Event.Automod = event.data
        if   event.type == Event.AUTOMOD_CAPS: type_str = "Capslock"
        elif event.type == Event.AUTOMOD_SPAM: type_str = "Spam"
        elif event.type == Event.AUTOMOD_EMOTE:type_str = "Emotespam"

        embed = assemble_logging_embed(type_str,Significance.HIGH,event_data["member"],event_data["member"].guild.me,event_data["message"],"Automod Detection")
        pass
    elif event.type & Event.GUILD_CHANNEL_MASK:
        if event.type == Event.GUILD_CHANNEL_CREATE: type_str = "Channel Created"
        elif event.type == Event.GUILD_CHANNEL_DELETE: type_str = "Channel Deleted"
        elif event.type == Event.GUILD_CHANNEL_UPDATE: type_str = "Channel Updated"
        
        if event.type in (Event.GUILD_CHANNEL_CREATE,Event.GUILD_CHANNEL_DELETE):
            channel: Channel = event.data["channel"]
            extra_description = channel_extra_description(event.type,channel)
            pass


        embed = assemble_logging_embed(type_str,Significance.LOW if event.type == Event.GUILD_CHANNEL_CREATE else Significance.MID, None, None, None, "Unknown", extra_description)
        pass
    else:
        if event.type == Event.UNMUTE_EVENT:
            event_data: Event.Unmute = event.data
            embed = assemble_logging_embed("Unmute",Significance.HIGH,event_data["member"],event_data["actor"],None,event_data["reason"])
            pass
        elif event.type == Event.MUTE_EVENT:
            event_data: Event.Mute = event.data
            embed = assemble_logging_embed("Mute",Significance.HIGH,event_data["member"],event_data["actor"],None,event_data["reason"],f"Muted until <t:{event_data['until']}>")
            pass
        pass

    log_channel = await event.guild.fetch_channel(log_channel_id)
    await log_channel.send(embed=embed)
    pass

async def logger_task():
    while True:
        if len(LOGGING_EVENTS) > 0:
            event = LOGGING_EVENTS.pop(0)
            asyncio.create_task(handle_event(event)) # Schedule as task because... efficiency? Honestly, there's not much async stuff happening in there, but I hope for a small speed improvement (especially at larger scales)
            pass
        await asyncio.sleep(0)
        pass
    pass