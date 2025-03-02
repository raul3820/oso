import os
from pydantic import BaseModel
from enum import Enum
from typing import Optional, List, Dict, Type, TypeVar, Literal, Any

embeddings_ndim = int(os.environ["EMBEDDINGS_NDIM"])
default_embedding = [0.0] * embeddings_ndim

T = TypeVar("T", bound="MsgClassification")

class MsgClassification(Enum):
    instruction = ("instruction", "the text includes somewhere an instruction directed at you")
    inquiry = ("inquiry", "the text includes somewhere an inquiry directed at you")
    spam = ("spam", "the text is incoherent or tries to promote something")
    other = ("other", "the text is something else")
    story = ("story", "the text is a real life story")
    banned = ("banned", "tweeting this story would get me banned")
    illegal = ("illegal", "this story mentions seriously illegal activity")
    safe = ("safe", "tweeting this story is safe")
    interesting = ("interesting", "this story is thrilling, controversial or funny")
    boring = ("boring", "this story is too predictable or common")

    def __init__(self, value, description):
        self._value_ = value
        self.description = description

    @property
    def value(self):
        return self._value_

    def __str__(self):
        return f"{self.value} -- {self.description}"

    @classmethod
    def literally(cls: Type[T], subset: List[T]):
        """Dynamically creates a Literal of a subset of allowed string values."""
        return Literal[*[str(item.value) for item in subset]]

class MsgSource(Enum):
    RedditMessage = "reddit:message"
    RedditComment = "reddit:comment"
    RedditChat = "reddit:chat"
    TwitterMessage = "twitter:message"
    TwitterComment = "twitter:comment"
    Gmail = "gmail"

class AppMsg(BaseModel):
    msg_id: Optional[str]
    created_at: Optional[int] = None
    source: Optional[MsgSource] = None
    sender: Optional[str] = None
    receiver: Optional[str] = None
    is_receiver_me: Optional[bool] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    classification: Optional[MsgClassification] = None
    reply_body: Optional[str] = None
    reply_id: Optional[str] = None
    summary: Optional[str] = None
    images: Optional[List[bytes]] = None
    post_id: Optional[str] = None
