"""PP3 专属字节码编码；宿主调用带精确续执行位置，供 VM 与机器码 AOT 共用。"""

from .pp3 import MemHandlerType


def encode(description, root=None, host_modes=None):
    code, hosts, resumes = [], [], {}
    actions = {MemHandlerType.Get: 0, MemHandlerType.Set: 1, MemHandlerType.Swap: 2}

    def emit(opcode, argument=0, depth=1, jump=0):
        code.append((opcode, argument, depth, jump))
        return len(code) - 1

    def target(index, destination):
        code[index] = (*code[index][:3], destination)

    def loop(body, sequence=None, owner=None, parents=()):
        summary = None
        if body and all(op[0] in ("add", "sub") for op in body):
            summary = emit(13, sum(1 if op[0] == "add" else -1 for op in body))
        opening = emit(11)
        block(body, sequence, owner, parents)
        emit(12, jump=opening + 1)
        target(opening, len(code))
        if summary is not None:
            target(summary, len(code))

    def block(body, sequence=None, owner=None, parents=()):
        index = 0
        while index < len(body):
            operation = body[index]
            kind = operation[0]
            if kind == "loop":
                if root is None:
                    loop(operation[1])
                else:
                    node = operation[2]
                    loop(operation[1], node.body, node, parents + ((sequence, index + 1, owner),))
            elif kind in ("add", "sub"):
                delta = 0
                while index < len(body) and body[index][0] in ("add", "sub"):
                    delta += 1 if body[index][0] == "add" else -1
                    index += 1
                emit(1, delta)
                continue
            elif kind == "data":
                if index + 1 < len(body) and body[index + 1][0] == "indirect":
                    _, action, depth = body[index + 1]
                    emit(8 + actions[action], operation[1], depth)
                    index += 1
                else:
                    emit(0, operation[1])
            elif kind == "direct":
                emit(5 + actions[operation[1]], operation[2])
            elif kind == "host":
                node = operation[1]
                position = emit(host_modes.get(id(node), 14), len(hosts))
                hosts.append(node)
                resumes[position + 1] = parents + ((sequence, index + 1, owner),)
            else:
                emit(2 + actions[operation[1]], depth=operation[2])
            index += 1

    if root is None:
        loop(description)
        return tuple(code)
    block(description, root)
    return tuple(code), tuple(hosts), resumes
