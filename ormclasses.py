from sqlalchemy.ext.mutable import MutableDict, MutableList
import sqlalchemy.orm as orm
import sqlalchemy as sql
from sqlalchemy.dialects import mysql
from sqlalchemy_json import NestedMutable, NestedMutableJson, NestedMutableList, mutable_json_type
import sqlalchemy_json
from sqlalchemy.engine.cursor import CursorResult
import sqlalchemy as sql, sqlalchemy.ext.asyncio as asql

Base = orm.declarative_base()

MutableListType = MutableList.as_mutable(sql.JSON)
NestedMutableListType = NestedMutableList.as_mutable(sql.JSON)

class Guild(Base):
    __tablename__="guilds"

    id                      = sql.Column(sql.String(20),                   primary_key=True, nullable=False,autoincrement=False)
    module_settings         = sql.Column(sql.SmallInteger,                                   nullable=False,default=0)

    automod_state           = sql.Column(mysql.BIT(3),                                       nullable=False,default=0)
    anarchies               = sql.Column(MutableListType,                                    nullable=False,default=[])
    god_roles               = sql.Column(MutableListType,                                    nullable=False,default=[])
    logging_state           = sql.Column(sql.Boolean,                                        nullable=False,default=False)
    logging_channel         = sql.Column(sql.String(20),                                     nullable=True )
    logging_settings        = sql.Column(sql.Integer,                                        nullable=False,default=0)
    warn_settings           = sql.Column(sql.Integer,                                        nullable=False,default=0)
    automod_settings        = sql.Column(mutable_json_type(sql.JSON,True),                   nullable=True)

    clone_filter            = sql.Column(mutable_json_type(sql.JSON),                        nullable=False,default=sqlalchemy_json.MutableDict())
    clone_enabled           = sql.Column(sql.Boolean,                                        nullable=False,default=True)

    timezone                = sql.Column(mysql.TINYTEXT,                                     nullable=True )
    
    reaction_roles          = sql.Column(MutableListType,                                    nullable=False,default=[])
    vote_permissions        = sql.Column(mutable_json_type(sql.JSON,True),                   nullable=False,default=sqlalchemy_json.NestedMutableDict())
    integrations            = sql.Column(mutable_json_type(sql.JSON,True),                   nullable=False,default={})
    announcement_override   = sql.Column(sql.String(20),                                     nullable=True )
    mute_role_id            = sql.Column(sql.String(20),                                     nullable=True )

    lower_xp_gain           = sql.Column(mysql.TINYINT(unsigned=True),                       nullable=False,default=15)
    upper_xp_gain           = sql.Column(mysql.TINYINT(unsigned=True),                       nullable=False,default=25)
    xp_timeout              = sql.Column(mysql.SMALLINT(unsigned=True),                      nullable=False,default=60)
    level_state             = sql.Column(sql.Boolean,                                        nullable=False,default=False)
    pass

class ReactionRoles(Base):
    __tablename__="reaction_roles"

    message_id            = sql.Column(sql.String(20),                   primary_key=True, nullable=False)
    react_roles           = sql.Column(mutable_json_type(sql.JSON,True),                   nullable=False)
    pass

class GuildWarning(Base):
    __tablename__="warnings"

    guild_id              = sql.Column(sql.String(20),                   primary_key=True, nullable=True )
    warns                 = sql.Column(NestedMutableListType,                              nullable=True )
    pass

class GuildMutes(Base):
    __tablename__="mutes"

    guild_id              = sql.Column(sql.String(20),                   primary_key=True, nullable=True )
    mutes                 = sql.Column(mutable_json_type(sql.JSON,True),                   nullable=True )
    """
    {
        member_id : [end_time, reason]
    }
    """
    pass

class GuildLevels(Base):
    __tablename__="levels"

    guild_id              = sql.Column(sql.String(20),                   primary_key=True, nullable=False)
    rewards               = sql.Column(mutable_json_type(sql.JSON,True),                   nullable=False, default={})
    levels                = sql.Column(mutable_json_type(sql.JSON),                        nullable=False, default={})
    pass

class ScheduledMessages(Base):
    __tablename__="msg_schedules"

    guild_id              = sql.Column(sql.String(20),                   primary_key=True, nullable=False)
    schedules             = sql.Column(MutableListType                                   , nullable=False)
    pass