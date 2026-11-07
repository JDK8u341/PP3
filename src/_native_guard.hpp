// 快照用 Python 容器持有所有引用，让 GC 能看见 handler 与 Runtime 之间的回环。
PyObject* state_dict(PyObject* object) {
    if (PyType_Check(object)) {
#if PY_VERSION_HEX >= 0x030C0000
        return checked(PyType_GetDict(reinterpret_cast<PyTypeObject*>(object)));
#else
        return Py_NewRef(reinterpret_cast<PyTypeObject*>(object)->tp_dict);
#endif
    }
    if (PyDict_CheckExact(object)) return Py_NewRef(object);
    if (PyList_CheckExact(object)) return Py_NewRef(Py_None);
    return checked(PyObject_GenericGetDict(object, nullptr));
}

PyObject* capture_snapshot(PyObject*, PyObject* args) {
    PyObject *objects, *runtime;
    if (!PyArg_ParseTuple(args, "O!O", &PyTuple_Type, &objects, &runtime)) return nullptr;
    PyObject* result = PyTuple_New(PyTuple_GET_SIZE(objects));
    if (!result) return nullptr;
    try {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(objects); ++i) {
            PyObject* object = PyTuple_GET_ITEM(objects, i);
            Ref dictionary(state_dict(object));
            Ref state(dictionary.get() == Py_None ? checked(PyList_AsTuple(object))
                                                   : checked(PyDict_Copy(dictionary.get())));
            PyObject* mro = PyType_Check(object) ? reinterpret_cast<PyTypeObject*>(object)->tp_mro : Py_None;
            PyObject* row = checked(PyTuple_Pack(6, object, reinterpret_cast<PyObject*>(Py_TYPE(object)),
                dictionary.get(), state.get(), mro ? mro : Py_None, object == runtime ? Py_True : Py_False));
            PyTuple_SET_ITEM(result, i, row);
        }
        return result;
    } catch (const PythonError&) { Py_DECREF(result); return nullptr; }
}

PyObject* check_snapshot(PyObject*, PyObject* snapshot) {
    if (!PyTuple_CheckExact(snapshot)) { PyErr_SetString(PyExc_TypeError, "invalid snapshot"); return nullptr; }
    try {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(snapshot); ++i) {
            PyObject* row = PyTuple_GET_ITEM(snapshot, i);
            if (!PyTuple_CheckExact(row) || PyTuple_GET_SIZE(row) != 6) {
                PyErr_SetString(PyExc_TypeError, "invalid snapshot row");
                throw PythonError();
            }
            PyObject* object = PyTuple_GET_ITEM(row, 0);
            if (reinterpret_cast<PyObject*>(Py_TYPE(object)) != PyTuple_GET_ITEM(row, 1)) Py_RETURN_FALSE;
            PyObject* old_dict = PyTuple_GET_ITEM(row, 2);
            PyObject* state = PyTuple_GET_ITEM(row, 3);
            PyObject* mro = PyTuple_GET_ITEM(row, 4);
            if (mro != Py_None && (!PyType_Check(object) || reinterpret_cast<PyTypeObject*>(object)->tp_mro != mro)) Py_RETURN_FALSE;
            if (old_dict == Py_None) {
                if (!PyList_CheckExact(object) || !PyTuple_CheckExact(state)) Py_RETURN_FALSE;
                if (PyList_GET_SIZE(object) != PyTuple_GET_SIZE(state)) Py_RETURN_FALSE;
                for (Py_ssize_t index = 0; index < PyTuple_GET_SIZE(state); ++index)
                    if (PyList_GET_ITEM(object, index) != PyTuple_GET_ITEM(state, index)) Py_RETURN_FALSE;
            } else {
                if (!PyDict_CheckExact(state) || !PyDict_CheckExact(old_dict)) Py_RETURN_FALSE;
                Ref current(state_dict(object));
                if (current.get() != old_dict || PyDict_Size(current.get()) != PyDict_Size(state)) Py_RETURN_FALSE;
                Py_ssize_t a = 0, b = 0;
                PyObject *ak, *av, *bk, *bv;
                while (PyDict_Next(state, &a, &ak, &av)) {
                    if (!PyDict_Next(current.get(), &b, &bk, &bv) || ak != bk) Py_RETURN_FALSE;
                    if (PyTuple_GET_ITEM(row, 5) == Py_True && PyUnicode_CheckExact(ak)
                        && PyUnicode_CompareWithASCIIString(ak, "view") == 0) continue;
                    if (av != bv) Py_RETURN_FALSE;
                }
            }
        }
        Py_RETURN_TRUE;
    } catch (const PythonError&) { return nullptr; }
}
