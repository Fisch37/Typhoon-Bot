class LoggingSettings:
    # Some events have been removed for various reasons (mostly for rate limiting) (and my sanity)
    __slots__ = (
        "moderation",
        "channels",
        "server_update",
        "invites",
        #"integrations",
        "member_changes",
        "messages",
        # "reactions",
        "reactions_mod",
        "roles",
        # "threads",
        "threads_mod"
    )

    def __init__(self, 
        moderation    : bool=False, 
        channels      : bool=False, 
        server_update : bool=False,
        invites       : bool=False,
        #integrations   : bool=False,
        member_changes: bool=False,
        messages      : bool=False,
        # reactions     : bool=False,
        reactions_mod : bool=False,
        roles         : bool=False,
        # threads       : bool=False,
        threads_mod   : bool=False
        ):
        self.moderation = self.channels = self.server_update = self.invites = self.member_changes = self.messages = self.reactions_mod = self.roles = self.threads_mod = False
        self.update(moderation,channels,server_update, invites, member_changes, messages, reactions_mod, roles, threads_mod)
        pass

    @classmethod
    def from_value(cls, value: int):
        return cls(*[bool(value & 2**n) for n in range(3,len(cls.__slots__)+3)])
        pass

    def update(self,moderation: bool, channels: bool, server_update: bool, invites: bool, member_changes: bool, messages: bool, reactions_mod: bool, roles: bool, threads_mod: bool):
        if moderation is not None: 
            self.moderation = bool(moderation)
        if channels is not None: 
            self.channels = bool(channels)
        if server_update is not None: 
            self.server_update = bool(server_update)
        if invites is not None: 
            self.invites = bool(invites)
        # self.integrations = bool(integrations)
        if member_changes is not None: 
            self.member_changes = bool(member_changes)
        if messages is not None: 
            self.messages = bool(messages)
        # self.reactions = bool(reactions)
        if reactions_mod is not None: 
            self.reactions_mod = bool(reactions_mod)
        if roles is not None: 
            self.roles = bool(roles)
        # self.threads = bool(threads)
        if threads_mod is not None: 
            self.threads_mod = bool(threads_mod)
        pass

    def to_value(self) -> int:
        value = 0
        for i, slot in enumerate(self.__slots__):
            value += int(getattr(self,slot)) * 2**(i+3)
            pass

        return value
        pass
    pass

translation_table = {
            "moderation":"Moderation",
            "channels":"Channels",
            "server_update":"Server Update",
            "invites":"Invites",
            "member_changes":"Member Changes",
            "messages":"Messages",
            "reactions_mod":"Reactions Moderation",
            "roles":"Roles",
            "threads_mod":"Threads Moderation"
        }