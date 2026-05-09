from src.pp3 import *

rt = Runtime(can_direct_addressing=True)

irb = IRBuilder(std_register)
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