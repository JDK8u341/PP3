"""扁平字节码候选：只用于比较普通标准 IR，不作为兼容公共执行器。"""

from src.pp3 import AddSelf, Data, HandlerType, MemHandlerType, SubSelf


class FlatBytecode:
    def __init__(self, handles):
        code = []

        def emit(nodes):
            for node in nodes:
                if node.TYPE == HandlerType.Loop:
                    start = len(code)
                    code.append((0, 0, 0))
                    emit(node.body)
                    code.append((1, start, 0))
                    code[start] = (0, len(code), 0)
                elif type(node) is Data:
                    code.append((2, node.data, 0))
                elif type(node) is AddSelf:
                    code.append((3, 0, 0))
                elif type(node) is SubSelf:
                    code.append((4, 0, 0))
                elif node.TYPE in (HandlerType.Mem, HandlerType.InPlaceMem):
                    direct = node.TYPE == HandlerType.Mem
                    action = {MemHandlerType.Get: 0, MemHandlerType.Set: 1, MemHandlerType.Swap: 2}[node.h_type]
                    code.append((5 + action + 3 * direct, node.place if direct else node.depth, 0))
                else:
                    code.append((11, node, 0))

        emit(handles)
        self.code = code

    def run(self, runtime):
        code = self.code
        pc = 0
        memory = runtime.memory
        view = runtime.view
        try:
            while pc < len(code):
                op, arg, unused = code[pc]
                if op == 0:
                    if view == 0:
                        pc = arg
                        continue
                elif op == 1:
                    pc = arg
                    continue
                elif op == 2:
                    view = arg
                elif op == 3:
                    view += 1
                elif op == 4:
                    view -= 1
                elif op == 11:
                    runtime.view = view
                    runtime._std_handlers.get(type(arg), arg).handle(runtime)
                    memory, view = runtime.memory, runtime.view
                else:
                    if op >= 8:
                        if not runtime.can_direct_addressing:
                            raise ValueError("Your Config Not Allow Direct Addressing!")
                        place, action = arg, op - 8
                    else:
                        place, action = view, op - 5
                        for _ in range(arg - 1):
                            place = memory[place]
                    if action == 0:
                        view = memory[place]
                    elif action == 1:
                        memory[place] = view
                    else:
                        view, memory[place] = memory[place], view
                pc += 1
        finally:
            runtime.view = view
