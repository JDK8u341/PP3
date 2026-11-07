// PP3 原生图执行器：整数值是地址，缓存的是可失效的出边而不是整条路径。
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstddef>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {
struct PythonError {};

PyObject* checked(PyObject* value) {
    if (!value) throw PythonError();
    return value;
}

class Ref {
    PyObject* object_;
public:
    explicit Ref(PyObject* object = nullptr) : object_(object) {}
    ~Ref() { Py_XDECREF(object_); }
    Ref(const Ref&) = delete;
    Ref& operator=(const Ref&) = delete;
    PyObject* get() const { return object_; }
};

// 超过 int64 的整数保留 PyLong；每次运算后重新规范化，能回到小整数快路径。
struct Number {
    int64_t small = 0;
    PyObject* big = nullptr;

    Number() = default;
    explicit Number(int64_t value) : small(value) {}
    explicit Number(PyObject* object) {
        if (!PyLong_CheckExact(object)) {
            PyErr_SetString(PyExc_TypeError, "native values must be exact integers");
            throw PythonError();
        }
        int overflow = 0;
        small = PyLong_AsLongLongAndOverflow(object, &overflow);
        if (PyErr_Occurred()) throw PythonError();
        if (overflow) { big = object; Py_INCREF(big); }
    }
    Number(const Number& other) : small(other.small), big(other.big) { Py_XINCREF(big); }
    Number(Number&& other) noexcept : small(other.small), big(other.big) { other.big = nullptr; }
    ~Number() { Py_XDECREF(big); }
    Number& operator=(Number other) noexcept {
        std::swap(small, other.small);
        std::swap(big, other.big);
        return *this;
    }
    bool zero() const { return !big && small == 0; }
    bool equal(const Number& other) const {
        if (!big && !other.big) return small == other.small;
        if (!big || !other.big) return false;
        int result = PyObject_RichCompareBool(big, other.big, Py_EQ);
        if (result < 0) throw PythonError();
        return result != 0;
    }
    PyObject* box() const {
        if (big) { Py_INCREF(big); return big; }
        return checked(PyLong_FromLongLong(small));
    }
    void add(int64_t delta) {
        if (!big && !((delta > 0 && small > INT64_MAX - delta)
                      || (delta < 0 && small < INT64_MIN - delta))) {
            small += delta;
            return;
        }
        Ref left(box()), right(checked(PyLong_FromLongLong(delta)));
        Ref result(checked(PyNumber_Add(left.get(), right.get())));
        *this = Number(result.get());
    }
    bool reaches_zero(int64_t delta) const {
        if (zero()) return true;
        if (!delta) return false;
        if (!big) {
            // 先判符号，避免 INT64_MIN % -1 在 C++ 中溢出。
            return ((small > 0 && delta < 0) || (small < 0 && delta > 0))
                   && small % delta == 0;
        }
        Ref zero_value(checked(PyLong_FromLong(0)));
        int negative = PyObject_RichCompareBool(big, zero_value.get(), Py_LT);
        if (negative < 0) throw PythonError();
        if ((negative && delta < 0) || (!negative && delta > 0)) return false;
        Ref divisor(checked(PyLong_FromLongLong(delta)));
        Ref remainder(checked(PyNumber_Remainder(big, divisor.get())));
        return Number(remainder.get()).zero();
    }
};
static_assert(offsetof(Number, small) == 0 && offsetof(Number, big) == 8,
              "LLVM JIT requires the documented Number layout");

constexpr size_t absent = std::numeric_limits<size_t>::max();

struct Cell {
    Number key;
    Number value;
    size_t successor = absent;
    bool dirty;
    Cell(const Number& address, Number data, bool changed)
        : key(address), value(std::move(data)), dirty(changed) {}
};

class Graph {
    PyObject* memory_;
    std::unordered_map<int64_t, size_t> small_index_;
    Ref big_index_;
    std::vector<Cell> cells_;
public:
    explicit Graph(PyObject* memory) : memory_(memory), big_index_(checked(PyDict_New())) {
        cells_.reserve(64);
        small_index_.reserve(64);
    }
    size_t locate(const Number& address) {
        if (!address.big) {
            auto found = small_index_.find(address.small);
            if (found != small_index_.end()) return found->second;
        } else {
            PyObject* found = PyDict_GetItemWithError(big_index_.get(), address.big);
            if (found) {
                size_t index = PyLong_AsSize_t(found);
                if (PyErr_Occurred()) throw PythonError();
                return index;
            }
            if (PyErr_Occurred()) throw PythonError();
        }
        Ref key(address.box());
        PyObject* value = PyDict_GetItemWithError(memory_, key.get());
        if (!value && PyErr_Occurred()) throw PythonError();
        size_t index = cells_.size();
        cells_.emplace_back(address, value ? Number(value) : Number(), !value);
        if (!address.big) small_index_.emplace(address.small, index);
        else {
            Ref boxed_index(checked(PyLong_FromSize_t(index)));
            if (PyDict_SetItem(big_index_.get(), address.big, boxed_index.get()) < 0)
                throw PythonError();
        }
        return index;
    }
    size_t next(size_t index) {
        size_t result = cells_[index].successor;
        if (result == absent) {
            // locate 可能扩容，不能把 vector 中元素的引用跨越这次调用。
            Number address = cells_[index].value;
            result = locate(address);
            cells_[index].successor = result;
        }
        return result;
    }
    Number read(size_t index) const { return cells_[index].value; }
    void write(size_t index, const Number& value) {
        bool same = cells_[index].value.equal(value);
        cells_[index].value = value;
        if (!same) cells_[index].successor = absent;
        cells_[index].dirty = true;
    }
    void flush() {
        // 首次触达顺序等于缺失键的插入顺序；已有键的赋值不会移动字典位置。
        for (auto& cell : cells_) {
            if (!cell.dirty) continue;
            Ref key(cell.key.box()), value(cell.value.box());
            if (PyDict_SetItem(memory_, key.get(), value.get()) < 0) throw PythonError();
            cell.dirty = false;
        }
    }
    void reset() {
        cells_.clear();
        small_index_.clear();
        PyDict_Clear(big_index_.get());
    }
};

enum Opcode { DATA, ADD, GET, SET, SWAP, DGET, DSET, DSWAP,
              CGET, CSET, CSWAP, JZ, JNZ, SOLVE, HOST,
              INPUT, PRINT, INPUT_CHAR, PRINT_CHAR };

struct Instruction {
    Opcode opcode;
    Number argument;
    uint64_t depth;
    size_t jump;
};
using Program = std::vector<Instruction>;
constexpr const char* capsule_name = "pp3.native.program.v1";

class Frame {
    PyObject* runtime_;
    Ref memory_;
    std::vector<size_t> constants_;
    unsigned ticks_ = 0;
    unsigned yields_ = 0;
    bool direct_;
    PyObject* hosts_;
    PyObject* guard_;
    PyObject* io_types_;
public:
    Number view;
    Graph graph;
    bool synchronized = false;

    Frame(PyObject* runtime, PyObject* memory, PyObject* initial, bool direct, size_t count,
          PyObject* hosts, PyObject* guard, PyObject* io_types)
        : runtime_(runtime), memory_(Py_NewRef(memory)), constants_(count, absent),
          direct_(direct), hosts_(hosts), guard_(guard), io_types_(io_types), view(initial), graph(memory) {}

    void poll() {
        if (++ticks_ == 4096) {
            ticks_ = 0;
            if (++yields_ == 64) {
                yields_ = 0;
                // 让宿主线程能够请求中断；活动 Runtime/IR 的并发写入仍须调用者同步。
                PyThreadState* state = PyEval_SaveThread();
#ifndef _WIN32
                // POSIX 上立即重新获取 GIL 可能饿死等待中的中断线程。
                std::this_thread::sleep_for(std::chrono::microseconds(1));
#endif
                PyEval_RestoreThread(state);
            }
            // 调用方已排除自定义信号处理器；KeyboardInterrupt 在 catch 中回写状态。
            if (PyErr_CheckSignals() < 0) throw PythonError();
        }
    }
    void flush() {
        if (synchronized) return;
        Ref result(view.box());
        if (PyObject_SetAttrString(runtime_, "view", result.get()) < 0) throw PythonError();
        graph.flush();
    }
    bool fast_io(const Instruction& instruction, PyObject* operation) {
        if (!io_types_) return false;
        if (instruction.opcode == INPUT_CHAR) {
            Ref fields(checked(PyObject_GenericGetDict(operation, nullptr)));
            PyObject* buffer = PyDict_GetItemString(fields.get(), "buffer");
            if (!buffer || reinterpret_cast<PyObject*>(Py_TYPE(buffer)) != PyTuple_GET_ITEM(io_types_, 1)) return false;
            Py_ssize_t count = PySequence_Size(buffer);
            if (count < 0) throw PythonError();
            if (!count) return false;
            Ref first(checked(PySequence_GetItem(buffer, 0)));
            if (!PyUnicode_CheckExact(first.get()) || PyUnicode_GET_LENGTH(first.get()) != 1) return false;
            Ref consumed(checked(PyObject_CallMethod(buffer, "popleft", nullptr)));
            view = Number(static_cast<int64_t>(PyUnicode_ReadChar(consumed.get(), 0)));
            return true;
        }
        if (instruction.opcode != PRINT && instruction.opcode != PRINT_CHAR) return false;
        PyObject* output = PySys_GetObject("stdout");
        if (!output || reinterpret_cast<PyObject*>(Py_TYPE(output)) != PyTuple_GET_ITEM(io_types_, 0)) return false;
        Ref fields(checked(PyObject_GenericGetDict(output, nullptr)));
        if (PyDict_Size(fields.get()) != 0) return false;
        PyObject* print = PyDict_GetItemString(PyEval_GetBuiltins(), "print");
        Ref value(view.box());
        if (instruction.opcode == PRINT) {
            Ref ignored(checked(PyObject_CallOneArg(print, value.get())));
        } else {
            Ref modulus(checked(PyLong_FromLong(256)));
            Ref remainder(checked(PyNumber_Remainder(value.get(), modulus.get())));
            long number = PyLong_AsLong(remainder.get());
            if (PyErr_Occurred()) throw PythonError();
            Ref character(checked(PyUnicode_FromOrdinal(static_cast<int>(number))));
            Ref args(checked(PyTuple_Pack(1, character.get())));
            Ref keywords(checked(Py_BuildValue("{s:s,s:O}", "end", "", "flush", Py_True)));
            Ref ignored(checked(PyObject_Call(print, args.get(), keywords.get())));
        }
        return true;
    }
    bool host(const Instruction& instruction) {
        if (!hosts_ || instruction.argument.big || instruction.argument.small < 0
            || instruction.argument.small >= PyTuple_GET_SIZE(hosts_)) {
            PyErr_SetString(PyExc_ValueError, "invalid native host index");
            throw PythonError();
        }
        PyObject* operation = PyTuple_GET_ITEM(hosts_, instruction.argument.small);
        if (fast_io(instruction, operation)) return true;
        flush();
        synchronized = true;
        bool custom_buffer = false;
        if (instruction.opcode == INPUT_CHAR) {
            Ref fields(checked(PyObject_GenericGetDict(operation, nullptr)));
            PyObject* buffer = PyDict_GetItemString(fields.get(), "buffer");
            custom_buffer = !io_types_ || !buffer
                || reinterpret_cast<PyObject*>(Py_TYPE(buffer)) != PyTuple_GET_ITEM(io_types_, 1);
        }
        // 宿主边界前已物化；回调抛错或改写状态时不得再用旧图覆盖它。
        if (instruction.opcode == HOST || custom_buffer) {
            Ref ignored(checked(PyObject_CallMethod(operation, "handle", "O", runtime_)));
        } else if (instruction.opcode == INPUT) {
            PyObject* input = PyDict_GetItemString(PyEval_GetBuiltins(), "input");
            Ref text(checked(PyObject_CallNoArgs(input)));
            Ref value(checked(PyObject_CallOneArg(reinterpret_cast<PyObject*>(&PyLong_Type), text.get())));
            if (PyObject_SetAttrString(runtime_, "view", value.get()) < 0) throw PythonError();
        } else if (instruction.opcode == PRINT || instruction.opcode == PRINT_CHAR) {
            PyObject* print = PyDict_GetItemString(PyEval_GetBuiltins(), "print");
            Ref value(checked(PyObject_GetAttrString(runtime_, "view")));
            if (instruction.opcode == PRINT) {
                Ref ignored(checked(PyObject_CallOneArg(print, value.get())));
            } else {
                Ref modulus(checked(PyLong_FromLong(256)));
                Ref remainder(checked(PyNumber_Remainder(value.get(), modulus.get())));
                long number = PyLong_AsLong(remainder.get());
                if (PyErr_Occurred()) throw PythonError();
                Ref character(checked(PyUnicode_FromOrdinal(static_cast<int>(number))));
                Ref args(checked(PyTuple_Pack(1, character.get())));
                Ref keywords(checked(Py_BuildValue("{s:s,s:O}", "end", "", "flush", Py_True)));
                Ref ignored(checked(PyObject_Call(print, args.get(), keywords.get())));
            }
        } else {
            Ref buffer(checked(PyObject_GetAttrString(operation, "buffer")));
            int nonempty = PyObject_IsTrue(buffer.get());
            if (nonempty < 0) throw PythonError();
            if (!nonempty) {
                Ref extend(checked(PyObject_GetAttrString(buffer.get(), "extend")));
                PyObject* input = PyDict_GetItemString(PyEval_GetBuiltins(), "input");
                Ref line(checked(PyObject_CallNoArgs(input)));
                Ref ignored(checked(PyObject_CallOneArg(extend.get(), line.get())));
                Ref current(checked(PyObject_GetAttrString(operation, "buffer")));
                Ref appended(checked(PyObject_CallMethod(current.get(), "append", "s", "\n")));
            }
            Ref ordinal(Py_NewRef(checked(PyDict_GetItemString(PyEval_GetBuiltins(), "ord"))));
            Ref current(checked(PyObject_GetAttrString(operation, "buffer")));
            Ref character(checked(PyObject_CallMethod(current.get(), "popleft", nullptr)));
            Ref value(checked(PyObject_CallOneArg(ordinal.get(), character.get())));
            if (PyObject_SetAttrString(runtime_, "view", value.get()) < 0) throw PythonError();
        }
        if (!guard_) return false;
        Ref valid(checked(PyObject_CallNoArgs(guard_)));
        int okay = PyObject_IsTrue(valid.get());
        if (okay < 0) throw PythonError();
        if (!okay) return false;
        Ref current(checked(PyObject_GetAttrString(runtime_, "view")));
        view = Number(current.get());
        graph.reset();
        std::fill(constants_.begin(), constants_.end(), absent);
        synchronized = false;
        return true;
    }
    void access(const Instruction& instruction, size_t pc) {
        bool direct = instruction.opcode >= DGET && instruction.opcode <= DSWAP;
        bool constant = instruction.opcode >= CGET && instruction.opcode <= CSWAP;
        if (direct && !direct_) {
            PyErr_SetString(PyExc_ValueError, "Your Config Not Allow Direct Addressing!");
            throw PythonError();
        }
        if (constant) view = instruction.argument;
        size_t place;
        if (direct || constant) {
            place = constants_[pc];
            if (place == absent) constants_[pc] = place = graph.locate(instruction.argument);
        } else place = graph.locate(view);
        uint64_t depth = direct ? 1 : instruction.depth;
        uint64_t remaining = depth - 1;
        if (remaining > 64) {
            std::unordered_map<size_t, uint64_t> visited;
            uint64_t step = 0;
            while (step < remaining) {
                auto found = visited.find(place);
                if (found != visited.end()) {
                    uint64_t cycle = step - found->second;
                    uint64_t skip = (remaining - step) % cycle;
                    while (skip--) { poll(); place = graph.next(place); }
                    break;
                }
                visited.emplace(place, step);
                poll();
                place = graph.next(place);
                ++step;
            }
        } else {
            for (uint64_t step = 0; step < remaining; ++step) {
                poll();
                place = graph.next(place);
            }
        }
        int action = (instruction.opcode - GET) % 3;
        if (action == 0) view = graph.read(place);
        else if (action == 1) graph.write(place, view);
        else {
            Number old = view;
            view = graph.read(place);
            graph.write(place, old);
        }
    }
    size_t execute(const Program& program) {
        size_t pc = 0;
        while (pc < program.size()) {
            poll();
            const Instruction& instruction = program[pc];
            switch (instruction.opcode) {
            case DATA: view = instruction.argument; ++pc; break;
            case ADD: view.add(instruction.argument.small); ++pc; break;
            case JZ: pc = view.zero() ? instruction.jump : pc + 1; break;
            case JNZ: pc = view.zero() ? pc + 1 : instruction.jump; break;
            case SOLVE:
                if (view.reaches_zero(instruction.argument.small)) {
                    view = Number();
                    pc = instruction.jump;
                } else ++pc;
                break;
            case HOST: case INPUT: case PRINT: case INPUT_CHAR: case PRINT_CHAR:
                if (!host(instruction)) return pc + 1;
                ++pc;
                break;
            default: {
                access(instruction, pc);
                ++pc;
                break;
            }
            }
        }
        return pc;
    }
};

#ifdef PP3_AOT_BODY
#include PP3_AOT_BODY
#endif

#include "_native_guard.hpp"
#include "_native_jit.hpp"

void destroy_program(PyObject* capsule) {
    auto* program = static_cast<Program*>(PyCapsule_GetPointer(capsule, capsule_name));
    if (program) delete program;
    else PyErr_Clear();
}

PyObject* compile_program(PyObject*, PyObject* code) {
    try {
        if (!PyTuple_CheckExact(code) || PyTuple_GET_SIZE(code) > 20000) {
            PyErr_SetString(PyExc_TypeError, "native code must be a bounded tuple");
            throw PythonError();
        }
        auto program = std::make_unique<Program>();
        size_t size = static_cast<size_t>(PyTuple_GET_SIZE(code));
        program->reserve(size);
        for (size_t index = 0; index < size; ++index) {
            PyObject* row = PyTuple_GET_ITEM(code, static_cast<Py_ssize_t>(index));
            if (!PyTuple_CheckExact(row) || PyTuple_GET_SIZE(row) != 4) {
                PyErr_SetString(PyExc_TypeError, "native instruction requires four integers");
                throw PythonError();
            }
            for (int field = 0; field < 4; ++field) {
                if (!PyLong_CheckExact(PyTuple_GET_ITEM(row, field))) {
                    PyErr_SetString(PyExc_TypeError, "native operands must be exact integers");
                    throw PythonError();
                }
            }
            long opcode = PyLong_AsLong(PyTuple_GET_ITEM(row, 0));
            Number argument(PyTuple_GET_ITEM(row, 1));
            uint64_t depth = PyLong_AsUnsignedLongLong(PyTuple_GET_ITEM(row, 2));
            size_t jump = PyLong_AsSize_t(PyTuple_GET_ITEM(row, 3));
            if (PyErr_Occurred()) throw PythonError();
            if (opcode < DATA || opcode > PRINT_CHAR || depth == 0 || jump > size
                || ((opcode == ADD || opcode == SOLVE) && argument.big)) {
                PyErr_SetString(PyExc_ValueError, "invalid native instruction");
                throw PythonError();
            }
            program->push_back({static_cast<Opcode>(opcode), std::move(argument), depth, jump});
        }
        PyObject* capsule = checked(PyCapsule_New(program.get(), capsule_name, destroy_program));
        program.release();
        return capsule;
    } catch (const PythonError&) { return nullptr; }
    catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
    catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); return nullptr; }
}

PyObject* run_program(PyObject*, PyObject* args) {
    PyObject *capsule, *runtime, *hosts = nullptr, *guard = nullptr, *io_types = nullptr, *jit_capsule = nullptr;
    if (!PyArg_ParseTuple(args, "OO|O!OO!O", &capsule, &runtime, &PyTuple_Type, &hosts, &guard,
                         &PyTuple_Type, &io_types, &jit_capsule)) return nullptr;
    if (io_types && PyTuple_GET_SIZE(io_types) != 2) {
        PyErr_SetString(PyExc_ValueError, "native IO types require two entries");
        return nullptr;
    }
    auto* program = static_cast<Program*>(PyCapsule_GetPointer(capsule, capsule_name));
    if (!program) return nullptr;
    JitEntry* jit = nullptr;
    if (jit_capsule) {
        jit = static_cast<JitEntry*>(PyCapsule_GetPointer(jit_capsule, jit_name));
        if (!jit) return nullptr;
        if (jit->program != program) {
            PyErr_SetString(PyExc_ValueError, "bytecode does not match this JIT module");
            return nullptr;
        }
    }
#ifdef PP3_AOT_BODY
    if (!validate_aot(*program)) {
        PyErr_SetString(PyExc_ValueError, "bytecode does not match this AOT module");
        return nullptr;
    }
#endif
    std::unique_ptr<Frame> frame;
    try {
        Ref memory(checked(PyObject_GetAttrString(runtime, "memory")));
        Ref view(checked(PyObject_GetAttrString(runtime, "view")));
        Ref direct(checked(PyObject_GetAttrString(runtime, "can_direct_addressing")));
        if (!PyDict_Check(memory.get()) || !PyBool_Check(direct.get())) {
            PyErr_SetString(PyExc_TypeError, "invalid native runtime state");
            throw PythonError();
        }
        frame = std::make_unique<Frame>(runtime, memory.get(), view.get(), direct.get() == Py_True,
                                        program->size(), hosts, guard, io_types);
#ifdef PP3_AOT_BODY
        size_t next = execute_aot(*frame, *program);
#else
        size_t next = jit ? jit->function(frame.get(), program, &frame->view) : frame->execute(*program);
        if (next == absent) throw PythonError();
#endif
        frame->flush();
        if (frame->synchronized) return PyLong_FromSize_t(next);
        Py_RETURN_NONE;
    } catch (const std::bad_alloc&) { PyErr_NoMemory(); }
    catch (const PythonError&) {}
    catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); }
    // 退出只回写一次；不能因异常而从循环入口重跑已完成的指令。
    PyObject *type, *value, *traceback;
    PyErr_Fetch(&type, &value, &traceback);
    try { if (frame) frame->flush(); }
    catch (const std::bad_alloc&) { PyErr_NoMemory(); }
    catch (const PythonError&) {}
    catch (const std::exception& error) { PyErr_SetString(PyExc_RuntimeError, error.what()); }
    if (PyErr_Occurred()) {
        Py_XDECREF(type); Py_XDECREF(value); Py_XDECREF(traceback);
    } else PyErr_Restore(type, value, traceback);
    return nullptr;
}

PyMethodDef methods[] = {
    {"compile", compile_program, METH_O, "Compile validated PP3 bytecode."},
    {"run", run_program, METH_VARARGS, "Execute a pure PP3 region."},
    {"snapshot", capture_snapshot, METH_VARARGS, "Capture host boundary guards."},
    {"unchanged", check_snapshot, METH_O, "Validate host boundary guards."},
    {"jit_symbols", jit_symbols, METH_NOARGS, "Addresses of the guarded native JIT ABI."},
    {"bind_jit", bind_jit, METH_VARARGS, "Bind machine code lifetime to bytecode."},
    {nullptr, nullptr, 0, nullptr}
};
#ifndef PP3_MODULE_NAME
#define PP3_MODULE_NAME "_native"
#define PP3_MODULE_INIT PyInit__native
#endif
PyModuleDef module = {PyModuleDef_HEAD_INIT, PP3_MODULE_NAME, nullptr, -1, methods};
}

PyMODINIT_FUNC PP3_MODULE_INIT() {
    PyObject* result = PyModule_Create(&module);
    if (!result) return nullptr;
#ifdef __clang__
    if (PyModule_AddStringConstant(result, "compiler", "Clang " __clang_version__) < 0) {
        Py_DECREF(result);
        return nullptr;
    }
#endif
    return result;
}
