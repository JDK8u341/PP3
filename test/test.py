from src.pp3 import *

rt = Runtime(can_direct_addressing=True)

irb = IRBuilder({'print':Print,'-':SubSelf,'+':AddSelf,'input':Input})
ir_ss = irb.build(r'&5 %0 @print #0 @print')
print(ir_ss)
rt.clear()
rt.run(ir_ss)
print()

ir_ss2 = irb.build(r'&5 *1 @print %5 @print')
print(ir_ss2)
rt.clear()
rt.run(ir_ss2)

ir_ss3 = irb.build(r'&5 *1 @print %5 @+ @print')
print(ir_ss3)
rt.clear()
rt.run(ir_ss3)

ir_ss4 = irb.build(r'@input [ @print @- ]')
print(ir_ss4)
rt.clear()
rt.run(ir_ss4)

# 假设你之前定义的所有类（Runtime, IRBuilder, MemHandler, ...）都在作用域内
# 这里直接使用你给的 IRBuilder 和 Runtime

builder = IRBuilder(op_map={'print':Print,'-':SubSelf,'+':AddSelf,'input':Input})
code = "@input $5 #5 @- $5 &0 $1 &1 $2 #2 @print #5 [ $4 #1 $3 #2 $0 [ #3 @+ $3 #0 @- $0 ] #3 @print #2 $1 #3 $2 #4 @- $5 ]"
ir = builder.build(code)
rt = Runtime(can_direct_addressing=True)
rt.run(ir)
print()
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
