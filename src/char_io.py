"""字符输入输出扩展；注册表在模块加载时建立，实例由各 Runtime 创建。"""

from collections import deque

from .handlers import InPlaceHandler


class InputAsChar(InPlaceHandler):
    def __init__(self):
        super().__init__()
        self.buffer = deque()

    def handle(self, runtime):
        # 一次读入整行，补回 input() 移除的换行，再逐个返回码点
        if not self.buffer:
            self.buffer.extend(input())
            self.buffer.append("\n")
        runtime.view = ord(self.buffer.popleft())

    def clear(self):
        self.buffer.clear()


class PrintAsChar(InPlaceHandler):
    def handle(self, runtime):
        # 取模只用于输出，不改变 view，也不额外追加换行
        print(chr(runtime.view % 256), end="", flush=True)


register = {"input_as_char": InputAsChar, "print_as_char": PrintAsChar}
