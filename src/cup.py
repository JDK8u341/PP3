from src.pp3 import *
from collections import deque

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
        p1 = runtime.memory["_cup"].pop()
        p2 = runtime.memory["_cup"].pop()
        runtime.view = p1 + p2


class Sub(InPlaceHandler):
    def handle(self, runtime):
        r = runtime.memory["_cup"].pop()
        l = runtime.memory["_cup"].pop()
        runtime.view = l - r

class Mul(InPlaceHandler):
    def handle(self, runtime):
        p1 = runtime.memory["_cup"].pop()
        p2 = runtime.memory["_cup"].pop()
        runtime.view = p1 * p2

class Div(InPlaceHandler):
    def handle(self, runtime):
        r = runtime.memory["_cup"].pop()
        l = runtime.memory["_cup"].pop()
        runtime.view = l / r

register = {'add': Add, 'sub': Sub, 'mul': Mul, 'div': Div,'init_cup':InitCup,
            'push':Push, 'pop':Pop, 'pop_left':Popleft, 'push_left':PushLeft,}