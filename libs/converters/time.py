from discord.ext.commands import Converter, Context
from discord.ext.commands.errors import BadArgument
from datetime import datetime, date, time

ALLOWED_SEPERATORS = "-./: "

def dayDecideSep(argument : str) -> str:
    for char in ALLOWED_SEPERATORS: # Loop through every possible seperator
        if argument.count(char) == 2: # If it finds the right amount of seperators (like in 2021-02-31)
            return char
            pass
        pass
    return "" # Return no seperator option if the previous ones didn't match
    pass

def extractYYMMDDx(argument : str) -> tuple[int,int,int]:
    seperator = dayDecideSep(argument) # Determine seperator for YYMMDDx format
    if seperator != "": # If found a not-none seperator, split on that one
        yearstr, monstr, daystr = argument.split(seperator,3)
        pass
    else: # Implement (YY)YYMMDDx
        daystr = argument[-2:]
        monstr = argument[-4:-2]
        yearstr= argument[:-4]
        pass

    return int(yearstr),int(monstr),int(daystr)
    pass

def convert_day(day_arg : str) -> date:
    year, month, day = extractYYMMDDx(day_arg)
    
    return date(year,month,day) # Assemble a date object
    pass

def extract_time(time_arg : str) -> tuple[int,int,int,int]:
    time_split = time_arg.split(":",3)
    time_split.extend(["0"]*(3-len(time_split)))

    hstr, mstr, smsstr = time_split
    if "." in smsstr:
        sstr, msstr = smsstr.split(".")
        pass
    else:
        sstr = smsstr
        msstr = "0"
        pass

    return int(hstr), int(mstr), int(sstr), int(msstr) * (10**(3-len(msstr))) # Convert strings into integers (also parse milliseconds correctly so that ".15973" is 159.73ms)
    pass

def convert_time(time_arg : str) -> time:
    hour, minute, second, millisecond = extract_time(time_arg)

    return time(hour,minute,second,millisecond)
    pass

class TimeConverter(Converter):
    async def convert(self, ctx: Context, argument: str, tz = None) -> datetime:
        argsplit = argument.split(";",2)
        date_arg = argsplit[0]
        if len(argsplit) == 2: time_arg = argsplit[1]
        else:                  time_arg = None

        try: thisdate = await ctx._state.loop.run_in_executor(None,convert_day,date_arg)
        except ValueError: 
            raise BadArgument("Date part is invalid")

        if time_arg is not None:
            try: thistime = await ctx._state.loop.run_in_executor(None,convert_time,time_arg)
            except ValueError: 
                raise BadArgument("Time part is invalid")
            return datetime.combine(thisdate,thistime,tz)
            pass
        else:
            return datetime.combine(thisdate,time(),tz)
            pass
        pass
    pass

class PastTime(TimeConverter):
    async def convert(self, ctx : Context, argument : str) -> datetime:
        obj = await super().convert(ctx,argument)


        if obj.timestamp() >= datetime.utcnow().timestamp():
            raise BadArgument("Time passed is in the future which is not allowed")
            pass

        return obj
        pass
    pass

class FutureTime(TimeConverter):
    async def convert(self, ctx : Context, argument : str) -> datetime:
        obj = await super().convert(ctx,argument)


        if obj.timestamp() <= datetime.utcnow().timestamp():
            raise BadArgument("Time passed is in the past which is not allowed")
            pass

        return obj
        pass
    pass