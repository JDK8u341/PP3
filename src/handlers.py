"""运行器和独立扩展模块共同使用的指令类型与操作基类。"""

from abc import ABC, abstractmethod
from enum import Enum, auto


class HandlerType(Enum):
    # 运行时支持的几类指令节点
    Mem = auto()
    InPlaceMem = auto()
    InPlace = auto()
    Loop = auto()


class InPlaceHandler(ABC):
    # 操作直接修改 runtime；运行器忽略返回值
    TYPE = HandlerType.InPlace

    def __init__(self):
        pass

    @abstractmethod
    def handle(self, runtime):
        raise NotImplementedError("必须实现 handle 方法")
