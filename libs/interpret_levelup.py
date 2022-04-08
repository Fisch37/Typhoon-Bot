from string import Template
import discord
from leveling import LevelStats # This might cause a infinite import loop...


VAR_DESCR = (
    ("user_name"         , "The username. This does not change with the nickname and does not mention the user"),
    ("user_nick"         , "The nickname of a user. This can change with the server. It does not mention the user"),
    ("user_mention"      , "Mentions the user"),
    
    ("server_name"       , "The server name"),
    ("server_members"    , "The amount of members on a server."),

    ("level"             , "The level of the user."),
    ("xp"                , "The xp of the user."),
    ("rank"              , "The rank of the user on the leaderboard."),
    ("channel"           , "The channel a user has achieved their level-up in. This needn't be the channel this message is sent in"),
    ("send_channel"      , "The channel this message will be sent in.")
)

def raw_format(template, member_name, member_nick ,member_mention, guild_name, guild_count, level, xp, rank, channel, send_channel):
    return Template(template).safe_substitute({
        "user_name"     : member_name,
        "user_nick"     : member_nick,
        "user_mentio"   : member_mention,
        "server_name"   : guild_name,
        "server_members": guild_count,
        "level"         : level,
        "xp"            : xp,
        "rank"          : rank,
        "channel"       : channel,
        "send_channel"  : send_channel
    })
    pass

def format_msg(template : str, member : discord.Member, guild : discord.Guild, leaderboard : LevelStats, lvl_up_channel : discord.TextChannel, msg_channel : discord.TextChannel) -> str:
    return raw_format(
        template,
        member.name,
        member.display_name,
        member.mention,
        guild.name,
        guild.member_count,
        leaderboard.level(member.id),
        leaderboard.xp(member.id),
        leaderboard.rank(member.id),
        lvl_up_channel.mention,
        msg_channel.mention
    )
    pass