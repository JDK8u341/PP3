from abc import ABC, abstractmethod
from enum import Enum, auto
from collections import defaultdict

class HandlerType(Enum):
    # 运行时支持的几类指令节点
    Mem = auto()
    InPlaceMem = auto()
    InPlace = auto()
    Loop = auto()

class MemHandlerType(Enum):
    # 内存访问的三种基本操作
    Get = auto()
    Set = auto()
    Swap = auto()


class MemHandler:
    # 直接寻址指令：对固定地址进行读、写或交换
    TYPE = HandlerType.Mem
    def __init__(self,h_type,place):
        self.place = place
        self.h_type = h_type

class IndirectMemHandler:
    # 间接寻址指令：从当前 view 出发，按 depth 找到目标地址
    TYPE = HandlerType.InPlaceMem
    def __init__(self,h_type,depth):
        if depth <= 0:
            raise ValueError("depth must be positive")
        self.depth = depth
        self.h_type = h_type


class InPlaceHandler(ABC):
    # 原地操作指令：读取 runtime，返回新的 view
    TYPE = HandlerType.InPlace
    def __init__(self):
        pass

    @abstractmethod
    def handle(self,runtime):
        raise NotImplementedError("Must implement this method")

class LoopBlock:
    # 循环块：当 view 不为 0 时重复执行 body
    TYPE = HandlerType.Loop
    def __init__(self,block_body):
        self.body = block_body


class Runtime:

    def __init__(self,can_direct_addressing=False):
        # memory 默认值为 0，view 是当前工作值
        self.memory = defaultdict(int)
        self.view = 0
        self.mem_handler_map = {
            MemHandlerType.Get:self.get,
            MemHandlerType.Set:self.set,
            MemHandlerType.Swap:self.swap,
        }
        self.can_direct_addressing = can_direct_addressing

    def swap(self,place):
        # 交换 view 和指定内存地址中的值
        self.view,self.memory[place] = self.memory[place],self.view

    def set(self,place):
        # 把当前 view 写入指定内存地址
        self.memory[place] = self.view

    def get(self,place):
        # 从指定内存地址读取值到 view
        self.view = self.memory[place]

    def run(self,handles):
        for h in handles:
            if h.TYPE == HandlerType.Mem:
                # 直接寻址默认关闭，避免不受限制地访问固定地址
                if not self.can_direct_addressing:
                    raise ValueError("Your Config Not Allow Direct Addressing!")
                self.mem_handler_map[h.h_type](h.place)
            elif h.TYPE == HandlerType.InPlaceMem:
                # 间接寻址：沿 memory 链找到最终操作地址
                place = self.view
                for i in range(h.depth-1):
                    place = self.memory[place]
                self.mem_handler_map[h.h_type](place)
            elif h.TYPE == HandlerType.InPlace:
                h.handle(self)
            else:
                while self.view != 0:
                    self.run(h.body)


    def clear(self):
        self.view = 0
        self.memory = defaultdict(int)


def Get(place):
    # 生成直接读取指令：view = memory[place]
    return MemHandler(MemHandlerType.Get, place)

def Set(place):
    # 生成直接写入指令：memory[place] = view
    return MemHandler(MemHandlerType.Set, place)

def Swap(place):
    # 生成直接交换指令：view <-> memory[place]
    return MemHandler(MemHandlerType.Swap, place)

def IndirectGet(depth):
    # 生成间接读取指令：沿 memory 链找到地址后读取
    return IndirectMemHandler(MemHandlerType.Get, depth)

def IndirectSet(depth):
    # 生成间接写入指令：沿 memory 链找到地址后写入
    return IndirectMemHandler(MemHandlerType.Set, depth)

def IndirectSwap(depth):
    # 生成间接交换指令：沿 memory 链找到地址后交换
    return IndirectMemHandler(MemHandlerType.Swap, depth)

class Print(InPlaceHandler):
    # 打印 view，并保持 view 不变
    def handle(self, runtime):
        print(runtime.view)
        return runtime.view


class Input(InPlaceHandler):
    # 从标准输入读取整数作为新的 view
    def handle(self, runtime):
        return int(input())


class Data(InPlaceHandler):
    # 立即数指令：把固定值写入 view
    def __init__(self, data):
        super().__init__()
        self.data = data

    def handle(self, runtime):
        runtime.view = self.data


class AddSelf(InPlaceHandler):
    # view 自增 1
    def handle(self, runtime):
        runtime.view += 1


class SubSelf(InPlaceHandler):
    # view 自减 1
    def handle(self, runtime):
        runtime.view -= 1


class Debug(InPlaceHandler):
    def handle(self, runtime):
        runtime.memory["_debug_idx"] += 1
        print(f"# Debug {runtime.memory['_debug_idx']}\nView: {runtime.view}\n Memory: {runtime.memory}")

std_register = {'print': Print, '-': SubSelf, '+': AddSelf, 'input': Input, 'debug': Debug}

class IRBuilder:
    def __init__(self,op_map=None):
        # op_map 用来注册 @name 形式的自定义操作
        self.op_map = op_map if op_map is not None else {}
        self.handle_map = {'#':self.get,'$':self.set,'%':self.swap,
                           '&':self.data,'@':self.op,'~':self.indirect_get,
                           '^':self.indirect_set,'*':self.indirect_swap,}

    @staticmethod
    def match_brackets(s):
        # 预先匹配循环括号，方便 build 时切出循环体
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
        # 解析 #n
        return Get(int(code[1:]))

    @staticmethod
    def set(code):
        # 解析 $n
        return Set(int(code[1:]))

    @staticmethod
    def swap(code):
        # 解析 %n
        return Swap(int(code[1:]))

    @staticmethod
    def indirect_get(code):
        # 解析 ~n
        return IndirectGet(int(code[1:]))

    @staticmethod
    def indirect_set(code):
        # 解析 ^n
        return IndirectSet(int(code[1:]))

    @staticmethod
    def indirect_swap(code):
        # 解析 *n
        return IndirectSwap(int(code[1:]))

    @staticmethod
    def data(code):
        # 解析 &n
        return Data(int(code[1:]))

    def op(self,code):
        # 解析 @name，并从 op_map 中创建对应操作
        return self.op_map[code[1:]]()

    def loop(self,code,pairs,idx):
        # 解析 [ ... ]，递归构建循环体
        end = pairs[idx]
        body = self.build(code[idx+1:end])
        return LoopBlock(body)

    def build(self,code):
        idx = 0
        irs = []
        # 字符串代码按空格分词；也支持直接传入 token 列表
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
