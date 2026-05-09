import src.cup as cup
import src.pp3 as pp3

reg = {**pp3.std_register,**cup.register}
code = """
@init_cup 
&5 @push 
&6 @push 
&7 @push 
@debug 
@add 
@debug 
@print
"""
builder = pp3.IRBuilder(reg)
ir = builder.build(code)
rt = pp3.Runtime()
rt.run(ir)
print(rt.memory)
