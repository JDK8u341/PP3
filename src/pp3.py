from abc import ABC, abstractmethod
from enum import Enum, auto
from collections import defaultdict

class HandlerType(Enum):
    Mem = auto()
    InPlaceMem = auto()
    InPlace = auto()
    Loop = auto()

class MemHandlerType(Enum):
    Get = auto()
    Set = auto()
    Swap = auto()


class MemHandler:
    TYPE = HandlerType.Mem
    def __init__(self,h_type,place):
        self.place = place
        self.h_type = h_type

class InPlaceMemHandler:
    TYPE = HandlerType.InPlaceMem
    def __init__(self,h_type,depth):
        if depth <= 0:
            raise ValueError("depth must be positive")
        self.depth = depth
        self.h_type = h_type


class InPlaceHandler(ABC):
    TYPE = HandlerType.InPlace
    def __init__(self):
        pass

    @abstractmethod
    def handle(self,runtime):
        raise NotImplementedError("Must implement this method")

class LoopBlock:
    TYPE = HandlerType.Loop
    def __init__(self,block_body):
        self.body = block_body


class Runtime:

    def __init__(self,can_direct_addressing=False):
        self.memory = defaultdict(int)
        self.view = 0
        self.mem_handler_map = {
            MemHandlerType.Get:self.get,
            MemHandlerType.Set:self.set,
            MemHandlerType.Swap:self.swap,
        }
        self.can_direct_addressing = can_direct_addressing

    def swap(self,place):
        self.view,self.memory[place] = self.memory[place],self.view

    def set(self,place):
        self.memory[place] = self.view

    def get(self,place):
        self.view = self.memory[place]

    def run(self,handles):
        for h in handles:
            if h.TYPE == HandlerType.Mem:
                if not self.can_direct_addressing:
                    raise ValueError("Your Config Not Allow Direct Addressing!")
                self.mem_handler_map[h.h_type](h.place)
            elif h.TYPE == HandlerType.InPlaceMem:
                place = self.view
                for i in range(h.depth-1):
                    place = self.memory[place]
                self.mem_handler_map[h.h_type](place)
            elif h.TYPE == HandlerType.InPlace:
                self.view = h.handle(self)
            else:
                while self.view != 0:
                    self.run(h.body)


    def clear(self):
        self.view = 0
        self.memory = defaultdict(int)


def Get(place):
    return MemHandler(MemHandlerType.Get, place)

def Set(place):
    return MemHandler(MemHandlerType.Set, place)

def Swap(place):
    return MemHandler(MemHandlerType.Swap, place)

def IndirectGet(depth):
    return InPlaceMemHandler(MemHandlerType.Get,depth)

def IndirectSet(depth):
    return InPlaceMemHandler(MemHandlerType.Set,depth)

def IndirectSwap(depth):
    return InPlaceMemHandler(MemHandlerType.Swap,depth)

class Print(InPlaceHandler):
    def handle(self, runtime):
        print(runtime.view)
        return runtime.view

class Input(InPlaceHandler):
    def handle(self, runtime):
        return int(input())

class Data(InPlaceHandler):
    def __init__(self,data):
        super().__init__()
        self.data = data

    def handle(self, runtime):
        return self.data

class AddSelf(InPlaceHandler):
    def handle(self, runtime):
        return runtime.view + 1

class SubSelf(InPlaceHandler):
    def handle(self, runtime):
        return runtime.view - 1

class IRBuilder:
    def __init__(self,op_map=None):
        self.op_map = op_map if op_map is not None else {}
        self.handle_map = {'#':self.get,'$':self.set,'%':self.swap,
                           '&':self.data,'@':self.op,'~':self.indirect_get,
                           '^':self.indirect_set,'*':self.indirect_swap,}

    @staticmethod
    def match_brackets(s):
        stack = []
        pairs = {}

        for i, ch in enumerate(s):
            if ch == '[':
                stack.append(i)
            elif ch == ']':
                if not stack:
                    raise ValueError(f"Unmatched closing bracket at position {i}")
                left = stack.pop()
                pairs[left] = i

        if stack:
            raise ValueError(f"Unmatched opening bracket(s) at positions {stack}")

        return pairs

    @staticmethod
    def get(code):
        return Get(int(code[1:]))

    @staticmethod
    def set(code):
        return Set(int(code[1:]))

    @staticmethod
    def swap(code):
        return Swap(int(code[1:]))

    @staticmethod
    def indirect_get(code):
        return IndirectGet(int(code[1:]))

    @staticmethod
    def indirect_set(code):
        return IndirectSet(int(code[1:]))

    @staticmethod
    def indirect_swap(code):
        return IndirectSwap(int(code[1:]))

    @staticmethod
    def data(code):
        return Data(int(code[1:]))

    def op(self,code):
        return self.op_map[code[1:]]()

    def loop(self,code,pairs,idx):
        end = pairs[idx]
        body = self.build(code[idx+1:end])
        return LoopBlock(body)

    def build(self,code):
        idx = 0
        irs = []
        codes = code.split() if isinstance(code,str) else code
        pairs = self.match_brackets(codes)
        while idx < len(codes):
            raw = codes[idx]
            h = raw.strip()
            if h[0] != '[':
                d = self.handle_map[h[0]](h)
            else:
                d = self.loop(codes,pairs,idx)
                idx = pairs[idx]
            irs.append(d)
            idx += 1
        return irs