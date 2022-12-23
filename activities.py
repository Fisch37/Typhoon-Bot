# This is a list of joke activity that the bot will periodically select from
import discord

# The following format keys are supported:
# {year}: The current year in local time
# {month}: The current month in local time
# {day}: The current day of the month in local time
# {hour}: The current hour of the day in local time
# {minute}: The current minute of the day in local time
# {servers}: The amount of servers this bot is in
# {uptimeH}: The hours the bot has been online for
# {uptimeM}: The minutes of the hour the bot has been online for

ACTIVITIES = (
    # discord.Activity(type=discord.ActivityType.playing,name="guess who gets the next command against MelonBot#5023\n(Please let me win :3)"),
    # Removed this activity since the bot it is referencing doesn't really exist
    discord.Activity(type=discord.ActivityType.watching,name="the cosmic microwave background radiation for alien messages"),
    discord.Activity(type=discord.ActivityType.listening,name="/help"),
    discord.Activity(type=discord.ActivityType.playing,name="your camera feed live on Twitch (:D)"),
    discord.Activity(type=discord.ActivityType.competing,name="the robot olympics of {year}"),
    discord.Activity(type=discord.ActivityType.playing,name="with nuclear codes (Nah, I'm not [or am I?])"),
    discord.Activity(type=discord.ActivityType.watching,name="Ultron's baby steps"),
    discord.Activity(type=discord.ActivityType.listening,name="{servers} servers!"),
    discord.Activity(type=discord.ActivityType.listening,name="you for {uptimeH} hours and {uptimeM} minutes")
)
