from src.pp3 import *
from collections import deque
from operator import add, sub, mul


def _binary_operation(runtime, operation):
    # 先验证并计算，再消费操作数，确保失败时栈和 view 都保持原样
    stack = runtime.memory["_cup"]
    if len(stack) < 2:
        raise IndexError("cup 二元运算至少需要两个操作数")
    result = operation(stack[-2], stack[-1])
    stack.pop()
    stack.pop()
    runtime.view = result


def _integer_divide(left, right):
    # 用绝对值整除后恢复符号，实现 C++ 式向零截断，避免浮点精度损失
    quotient = abs(left) // abs(right)
    return -quotient if (left < 0) != (right < 0) else quotient

class InitCup(InPlaceHandler):
    def handle(self, runtime):
        runtime.memory["_cup"] =  deque()

class Push(InPlaceHandler):
    def handle(self, runtime):
        runtime.memory["_cup"].append(runtime.view)

class Pop(InPlaceHandler):
    def handle(self, runtime):
        runtime.view = runtime.memory["_cup"].pop()

class Popleft(InPlaceHandler):
    def handle(self, runtime):
        runtime.view = runtime.memory["_cup"].popleft()

class PushLeft(InPlaceHandler):
    def handle(self, runtime):
        runtime.memory["_cup"].appendleft(runtime.view)

class Add(InPlaceHandler):
    def handle(self, runtime):
        _binary_operation(runtime, add)


class Sub(InPlaceHandler):
    def handle(self, runtime):
        _binary_operation(runtime, sub)

class Mul(InPlaceHandler):
    def handle(self, runtime):
        _binary_operation(runtime, mul)

class Div(InPlaceHandler):
    def handle(self, runtime):
        _binary_operation(runtime, _integer_divide)

register = {'add': Add, 'sub': Sub, 'mul': Mul, 'div': Div,'init_cup':InitCup,
            'push':Push, 'pop':Pop, 'pop_left':Popleft, 'push_left':PushLeft,}
