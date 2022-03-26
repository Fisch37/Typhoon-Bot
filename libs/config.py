"""
Neuer Dateityp für configs (.cfg)
Folgt Standard für .cfg-Dateien
Format:
    {key}={value}
Alles hinter einem # (, welches nicht mit \ escaped ist), soll ein Kommentar sein und ignoriert werden
"""
from typing import *
import os, logging, atexit

COMMENT = "#"

class Config:
    def __init__(self, **kwargs : dict[str,Any]):
        self.comments = {}
        for key, value in kwargs.items():
            setattr(self,key,value)
            pass
        pass
    @classmethod
    def from_dict(cls,dictionary : dict[str,Any], comments : dict[int,str] = {}):
        obj = Config(comments=comments)
        for key, value in dictionary.items():
            setattr(obj,key,value)
            pass
        return obj
        pass

    def __str__(self):
        lines = ["".join([str(key),"=",str(value)]) for key, value in self.__dict__.items() if key != "comments"]
        for i in range(len(lines)):
            lines[i] = "".join((lines[i],self.comments.get(i) if i in self.comments.keys() else "","\n"))
            pass
        return "".join(lines)
        pass
    def __repr__(self):
        lines = ["".join(("    ",key," = ",str(value),"\n")) for key, value in self.__dict__.items()]
        return "".join(("<Config object\n",("".join(lines)),">"))
    pass

def __checkInt__(string : str):
    intAllowed = "0123456789-"
    return all([char in intAllowed for char in string])
    pass

def __checkFloat__(string : str):
    floatAllowed = "0123456789-."
    return all([char in floatAllowed for char in string])
    pass

def __checkBool__(string : str):
    return string in ("true","false")
    pass

def __convertBool__(string : str) -> bool:
    if string == "true":
        return True
    elif string == "false":
        return False
    else:
        raise ValueError

def __findComment__(string : str, start : int = 0):
    commentIndex = start + 1
    stringIndex = start
    stringState = False
    while stringIndex < commentIndex:
        if stringState:
            stringState = False
            stringIndex = string.find('"',stringIndex+1)
            pass

        if stringIndex == -1:
            break
        commentIndex = string.find(COMMENT,stringIndex)
        newStringIndex = string.rfind('"',stringIndex+1,commentIndex) # Find first " before # that wasn't found before

        if stringIndex < newStringIndex or newStringIndex == -1:
            stringIndex = newStringIndex
            stringState = True
            pass
        pass

    return commentIndex
    pass

def __remComments__(string : str,newline : str = "\n") -> tuple[list[str],dict[int,str]]:
    lines = string.split(newline)
    comments = {}
    for i in range(len(lines)):
        line = lines[i]
        commentIndex = __findComment__(line)
        if commentIndex != -1:
            comments[i] = line[commentIndex:]
            lines[i] = line[:commentIndex]
            pass
        pass
    while "" in lines: lines.remove("")
    return lines, comments
    pass

def load(file : Union[str, os.PathLike, int], autoClose : bool = True, encoding : str = None, errors : str = None, newline : str =None, closefd : bool = True,opener = None, create_new : bool = False) -> Config:
    convertors : dict[Callable, Callable] = {
        __checkInt__   : int,
        __checkFloat__ : float,
        __checkBool__  : __convertBool__
    }
    if create_new and not os.path.exists(file): open(file,"x").close()

    dictionary : dict[str, Any] = {}
    with open(file,"r",encoding=encoding,errors=errors,newline=newline,closefd=closefd,opener=opener) as fileObj:
        content = fileObj.read()
        pass
    lines, comments = __remComments__(content,newline if newline is not None else "\n")
    for line in lines:
        if line.strip() == (newline if newline is not None else "\n"): continue
        key, value = line.split("=",1)
        key = key.strip()
        value = value.strip()

        for check, convert in convertors.items(): # Convert to data types
            if check(value):
                value = convert(value.strip())
                break
            pass

        dictionary[key] = value
        pass

    cfg = Config.from_dict(dictionary,comments=comments)
    logging.debug(f"Loaded config file from {file}")
    if autoClose: atexit.register(save,file,cfg)
    return cfg
    pass

def save(file : Union[str, os.PathLike, int], cfg : Config,exist_ok : bool = True) -> int:
    logging.debug(f"Saving config file to {file}")
    if not exist_ok and os.path.exists(file):
        raise FileExistsError
    with open(file,"w") as fileObj:
        fileObj.truncate()
        return fileObj.write(str(cfg))
        pass
    pass

def __main__():
    cfg = load("test.cfg","utf-8",create_new=True)
    print(cfg)
    cfg.changeIsComing = True
    print(str(cfg))
    print("Saved new config with", save("test.cfg",cfg),"bytes")
    pass

if __name__=="__main__":
    __main__()
    pass