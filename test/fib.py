from src.pp3 import *

builder = IRBuilder(op_map=std_register)
code = "@input $5 #5 @- $5 &0 $1 &1 $2 #2 @print #5 [ $4 #1 $3 #2 $0 [ #3 @+ $3 #0 @- $0 ] #3 @print #2 $1 #3 $2 #4 @- $5 ]"
ir = builder.build(code)
rt = Runtime(can_direct_addressing=True)
rt.run(ir)
print()
code2 = """
&-2 ^2 &0 ^2 &1 ^3
&-3 ^2 &0 ^2 &1 ^3
&-4 ^2 &0 ^2 &1 ^3
&-6 ^2 &0 ^2 &1 ^3
&-1 ^2 &0 ^2 @input ^3
&-1 ~1
[
  &-2 ~1 @print
  &-4 ^3 &0 ^2 &-2 ~1 ^3
  &-5 ^2 &0 ^2 &-3 ~1 ^3
  &-5 ~1
  [
    &-6 ^3 &0 ^2 &-4 ~1 ^3
    &-4 ^3 &0 ^2 &-6 ~1 @+ ^3
    &-6 ^3 &0 ^2 &-5 ~1 ^3
    &-5 ^3 &0 ^2 &-6 ~1 @- ^3
  ]
  &-2 ^3 &0 ^2 &-3 ~1 ^3
  &-3 ^3 &0 ^2 &-4 ~1 ^3
  &-6 ^3 &0 ^2 &-1 ~1 ^3
  &-1 ^3 &0 ^2 &-6 ~1 @- ^3
]
"""
ir = builder.build(code2)
rt = Runtime(can_direct_addressing=False)
rt.run(ir)
