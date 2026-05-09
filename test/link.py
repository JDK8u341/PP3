from src.pp3 import *


code = """
&-1 ^2 @debug @input [ ^3 ^2 @debug @input ]
&-1 ~1 @debug [ @print ~1 @debug ]
"""

builder = IRBuilder(op_map=std_register)

ir = builder.build(code)
rt = Runtime(can_direct_addressing=False)
rt.run(ir)
print()
print(rt.memory)