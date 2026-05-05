from src.pp3 import *
builder = IRBuilder(op_map={'print':Print,'-':SubSelf,'+':AddSelf,'input':Input})
code = "&5 ^2 &6 ^3"
ir = builder.build(code)
rt = Runtime(can_direct_addressing=False)
rt.run(ir)
print(rt.memory)

# 有一个技巧：所以地址的默认值是0，所以在未初始化的情况下，任意访问深度>2的情况都指向地址0
# 这个可以利用好
# 也就是说,VIEW 只要指向的不是你已经初始化的内存，那任意depth = 2都指向0
# 所以
# &5 ^2 &6 ^3可以将内存地址为5的位置设置值为6
# 具体：
# &5  VIEW = 5
# ^2 VIEW = 5 ,MEM[5]未初始化 = 0，所以SET MEM[0] = 5
# &6 VIEW = 6
# ^3 VIEW = 6,MEM[6] = 0,MEM[0] = 5,最后 SET MEM[5] = 6
# 完美！