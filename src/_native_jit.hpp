// LLVM 只能跨越不抛 C++ 异常的 C ABI；错误以 -1 返回并保留 Python 异常。
template<int operation>
int jit_operation(Frame* frame, const Program* program, size_t pc) noexcept {
    try {
        if constexpr (operation == -1) frame->poll();
        else {
            const Instruction& instruction = (*program)[pc];
            if constexpr (operation == DATA) frame->view = instruction.argument;
            else if constexpr (operation == ADD) frame->view.add(instruction.argument.small);
            else if constexpr (operation == SOLVE) {
                if (frame->view.reaches_zero(instruction.argument.small)) {
                    frame->view = Number();
                    return 1;
                }
            } else if constexpr (operation >= HOST) return frame->host(instruction) ? 0 : 1;
            else frame->access(instruction, pc);
        }
        return 0;
    } catch (const PythonError&) { return -1; }
    catch (const std::bad_alloc&) { PyErr_NoMemory(); return -1; }
    catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); return -1; }
}

using JitFunction = size_t (*)(Frame*, const Program*, Number*);
struct JitEntry {
    JitFunction function;
    const Program* program;
    Ref program_owner;
    Ref code_owner;
    JitEntry(JitFunction function, Program* program, PyObject* capsule, PyObject* owner)
        : function(function), program(program), program_owner(Py_NewRef(capsule)), code_owner(Py_NewRef(owner)) {}
};
constexpr const char* jit_name = "pp3.native.jit.v1";

void destroy_jit(PyObject* capsule) {
    delete static_cast<JitEntry*>(PyCapsule_GetPointer(capsule, jit_name));
}

PyObject* bind_jit(PyObject*, PyObject* args) {
    PyObject *address, *program_capsule, *owner;
    if (!PyArg_ParseTuple(args, "OOO", &address, &program_capsule, &owner)) return nullptr;
    auto function = reinterpret_cast<JitFunction>(PyLong_AsVoidPtr(address));
    if (PyErr_Occurred()) return nullptr;
    auto* program = static_cast<Program*>(PyCapsule_GetPointer(program_capsule, capsule_name));
    if (!program) return nullptr;
    if (!function) { PyErr_SetString(PyExc_ValueError, "null JIT entry"); return nullptr; }
    try {
        auto entry = std::make_unique<JitEntry>(function, program, program_capsule, owner);
        PyObject* result = checked(PyCapsule_New(entry.get(), jit_name, destroy_jit));
        entry.release();
        return result;
    } catch (const PythonError&) { return nullptr; }
    catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
}

PyObject* jit_symbols(PyObject*, PyObject*) {
    using Function = int (*)(Frame*, const Program*, size_t) noexcept;
    Function functions[] = {
        jit_operation<DATA>, jit_operation<ADD>, jit_operation<GET>, jit_operation<SET>,
        jit_operation<SWAP>, jit_operation<DGET>, jit_operation<DSET>, jit_operation<DSWAP>,
        jit_operation<CGET>, jit_operation<CSET>, jit_operation<CSWAP>, jit_operation<-1>,
        jit_operation<-1>, jit_operation<SOLVE>, jit_operation<HOST>, jit_operation<INPUT>,
        jit_operation<PRINT>, jit_operation<INPUT_CHAR>, jit_operation<PRINT_CHAR>, jit_operation<-1>
    };
    PyObject* result = PyTuple_New(20);
    if (!result) return nullptr;
    for (int i = 0; i < 20; ++i) {
        PyObject* address = PyLong_FromVoidPtr(reinterpret_cast<void*>(functions[i]));
        if (!address) { Py_DECREF(result); return nullptr; }
        PyTuple_SET_ITEM(result, i, address);
    }
    return result;
}
