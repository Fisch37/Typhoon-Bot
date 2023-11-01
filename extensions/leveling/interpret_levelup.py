"""Lib-code for interpreting a level-up template"""
from typing import TYPE_CHECKING
from string import Template
from json import load as load_json_file
from pathlib import Path
import discord
if TYPE_CHECKING:
    from ...leveling import LevelStats

with Path(Path(__file__).parent,"level_up_message_variables.json").open(encoding="utf-8") as file:
    LEVEL_UP_MSG_VARS = tuple(load_json_file(file).items())

def format_msg(
        template: str,
        member: discord.Member,
        leaderboard: "LevelStats",
        lvl_up_channel: discord.TextChannel,
        msg_channel: discord.TextChannel
    ) -> str:
    """Replaces all variables inside a level-up message 
    template-string with the relevant information."""
    guild = member.guild
    return Template(template).safe_substitute({
        "user_name" : member.name,
        "user_nick" : member.display_name,
        "user_mention" : member.mention,
        "server_name" : guild.name,
        "server_members" : guild.member_count,
        "level" : leaderboard.level(member.id),
        "xp" : leaderboard.xp(member.id),
        "rank" : leaderboard.rank(member.id),
        "channel" : lvl_up_channel.mention,
        "send_channel" : msg_channel.mention
    })
