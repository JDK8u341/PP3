from src.pp3 import *
builder = IRBuilder(op_map={'print':Print,'-':SubSelf,'+':AddSelf,'input':Input})
code = """
&-3 ^2 &0 ^2 &1 ^3
&-1 ^2 &0 ^2 @input @+ ^3
&-2 ^2 &0 ^2 @input ^3
&-2 ~1
[
  &-3 ^3 &0 ^2 &-1 ~1 ^3
  &-1 ^3 &0 ^2 &-3 ~1 @+ ^3
  &-3 ^3 &0 ^2 &-2 ~1 ^3
  &-2 ^3 &0 ^2 &-3 ~1 @- ^3
]
&-1 ~1 @- @print
"""
ir = builder.build(code)
rt = Runtime(can_direct_addressing=False)
rt.run(ir)
print(rt.memory)