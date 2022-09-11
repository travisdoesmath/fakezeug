import asyncio
import copy
import math
import operator
import time
from contextvars import ContextVar
from threading import Thread

import pytest

from werkzeug import local

# Since the tests are creating local instances, use global context vars
# to avoid accumulating anonymous context vars that can't be collected.
_cv_ns = ContextVar("werkzeug.tests.ns")
_cv_stack = ContextVar("werkzeug.tests.stack")
_cv_val = ContextVar("werkzeug.tests.val")


@pytest.fixture(autouse=True)
def reset_context_vars():
    ns_token = _cv_ns.set({})
    stack_token = _cv_stack.set([])
    yield
    _cv_ns.reset(ns_token)
    _cv_stack.reset(stack_token)


def test_basic_local():
    ns = local.Local(_cv_ns)
    ns.foo = 0
    values = []

    def value_setter(idx):
        time.sleep(0.01 * idx)
        ns.foo = idx
        time.sleep(0.02)
        values.append(ns.foo)

    threads = [Thread(target=value_setter, args=(x,)) for x in [1, 2, 3]]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(values) == [1, 2, 3]

    def delfoo():
        del ns.foo

    delfoo()
    pytest.raises(AttributeError, lambda: ns.foo)
    pytest.raises(AttributeError, delfoo)

    local.release_local(ns)


def test_basic_local_asyncio():
    ns = local.Local(_cv_ns)
    ns.foo = 0
    values = []

    async def value_setter(idx):
        await asyncio.sleep(0.01 * idx)
        ns.foo = idx
        await asyncio.sleep(0.02)
        values.append(ns.foo)

    async def main():
        futures = [asyncio.ensure_future(value_setter(i)) for i in [1, 2, 3]]
        await asyncio.gather(*futures)

    asyncio.run(main())
    assert sorted(values) == [1, 2, 3]

    def delfoo():
        del ns.foo

    delfoo()
    pytest.raises(AttributeError, lambda: ns.foo)
    pytest.raises(AttributeError, delfoo)

    local.release_local(ns)


def test_local_release():
    ns = local.Local(_cv_ns)
    ns.foo = 42
    local.release_local(ns)
    assert not hasattr(ns, "foo")

    ls = local.LocalStack(_cv_stack)
    ls.push(42)
    local.release_local(ls)
    assert ls.top is None


def test_local_stack():
    ls = local.LocalStack(_cv_stack)
    assert ls.top is None
    ls.push(42)
    assert ls.top == 42
    ls.push(23)
    assert ls.top == 23
    ls.pop()
    assert ls.top == 42
    ls.pop()
    assert ls.top is None
    assert ls.pop() is None
    assert ls.pop() is None

    proxy = ls()
    ls.push([1, 2])
    assert proxy == [1, 2]
    ls.push((1, 2))
    assert proxy == (1, 2)
    ls.pop()
    ls.pop()
    assert repr(proxy) == "<LocalProxy unbound>"


def test_local_stack_asyncio():
    ls = local.LocalStack(_cv_stack)
    ls.push(1)

    async def task():
        ls.push(1)
        assert len(ls._storage.get()) == 2

    async def main():
        futures = [asyncio.ensure_future(task()) for _ in range(3)]
        await asyncio.gather(*futures)

    asyncio.run(main())


def test_proxy_local():
    ns = local.Local(_cv_ns)
    ns.foo = []
    p = local.LocalProxy(ns, "foo")
    p.append(42)
    p.append(23)
    p[1:] = [1, 2, 3]
    assert p == [42, 1, 2, 3]
    assert p == ns.foo
    ns.foo += [1]
    assert list(p) == [42, 1, 2, 3, 1]
    p_from_local = ns("foo")
    p_from_local.append(2)
    assert p == p_from_local
    assert p._get_current_object() is ns.foo


def test_proxy_callable():
    value = 42
    p = local.LocalProxy(lambda: value)
    assert p == 42
    value = [23]
    p.append(42)
    assert p == [23, 42]
    assert value == [23, 42]
    assert p._get_current_object() is value


def test_proxy_wrapped():
    class SomeClassWithWrapped:
        __wrapped__ = "wrapped"

    proxy = local.LocalProxy(_cv_val)
    assert proxy.__wrapped__ is _cv_val
    _cv_val.set(42)

    with pytest.raises(AttributeError):
        proxy.__wrapped__

    ns = local.Local(_cv_ns)
    ns.foo = SomeClassWithWrapped()
    ns.bar = 42

    assert ns("foo").__wrapped__ == "wrapped"

    with pytest.raises(AttributeError):
        ns("bar").__wrapped__


def test_proxy_doc():
    def example():
        """example doc"""

    assert local.LocalProxy(lambda: example).__doc__ == "example doc"
    # The __doc__ descriptor shouldn't block the LocalProxy's class doc.
    assert local.LocalProxy.__doc__.startswith("A proxy")


def test_proxy_fallback():
    local_stack = local.LocalStack(_cv_stack)
    local_proxy = local_stack()

    assert repr(local_proxy) == "<LocalProxy unbound>"
    assert isinstance(local_proxy, local.LocalProxy)
    assert local_proxy.__class__ is local.LocalProxy
    assert "LocalProxy" in local_proxy.__doc__

    local_stack.push(42)

    assert repr(local_proxy) == "42"
    assert isinstance(local_proxy, int)
    assert local_proxy.__class__ is int
    assert "int(" in local_proxy.__doc__


def test_proxy_unbound():
    ns = local.Local(_cv_ns)
    p = ns("value")
    assert repr(p) == "<LocalProxy unbound>"
    assert not p
    assert dir(p) == []


def _make_proxy(value):
    ns = local.Local(_cv_ns)
    ns.value = value
    p = ns("value")
    return ns, p


def test_proxy_type():
    _, p = _make_proxy([])
    assert isinstance(p, list)
    assert p.__class__ is list
    assert issubclass(type(p), local.LocalProxy)
    assert type(p) is local.LocalProxy


def test_proxy_string_representations():
    class Example:
        def __repr__(self):
            return "a"

        def __bytes__(self):
            return b"b"

        def __index__(self):
            return 23

    _, p = _make_proxy(Example())
    assert str(p) == "a"
    assert repr(p) == "a"
    assert bytes(p) == b"b"
    # __index__
    assert bin(p) == "0b10111"
    assert oct(p) == "0o27"
    assert hex(p) == "0x17"


def test_proxy_hash():
    ns, p = _make_proxy("abc")
    assert hash(ns.value) == hash(p)


@pytest.mark.parametrize(
    "op",
    [
        operator.lt,
        operator.le,
        operator.eq,
        operator.ne,
        operator.gt,
        operator.ge,
        operator.add,
        operator.sub,
        operator.mul,
        operator.truediv,
        operator.floordiv,
        operator.mod,
        divmod,
        pow,
        operator.lshift,
        operator.rshift,
        operator.and_,
        operator.or_,
        operator.xor,
    ],
)
def test_proxy_binop_int(op):
    _, p = _make_proxy(2)
    assert op(p, 3) == op(2, 3)
    # r-op
    assert op(3, p) == op(3, 2)


@pytest.mark.parametrize("op", [operator.neg, operator.pos, abs, operator.invert])
def test_proxy_uop_int(op):
    _, p = _make_proxy(-2)
    assert op(p) == op(-2)


def test_proxy_numeric():
    class Example:
        def __complex__(self):
            return 1 + 2j

        def __int__(self):
            return 1

        def __float__(self):
            return 2.1

        def __round__(self, n=None):
            if n is not None:
                return 3.3

            return 3

        def __trunc__(self):
            return 4

        def __floor__(self):
            return 5

        def __ceil__(self):
            return 6

        def __index__(self):
            return 2

    _, p = _make_proxy(Example())
    assert complex(p) == 1 + 2j
    assert int(p) == 1
    assert float(p) == 2.1
    assert round(p) == 3
    assert round(p, 2) == 3.3
    assert math.trunc(p) == 4
    assert math.floor(p) == 5
    assert math.ceil(p) == 6
    assert [1, 2, 3][p] == 3  # __index__


@pytest.mark.parametrize(
    "op",
    [
        operator.iadd,
        operator.isub,
        operator.imul,
        operator.imatmul,
        operator.itruediv,
        operator.ifloordiv,
        operator.imod,
        operator.ipow,
        operator.ilshift,
        operator.irshift,
        operator.iand,
        operator.ior,
        operator.ixor,
    ],
)
def test_proxy_iop(op):
    class Example:
        value = 1

        def fake_op(self, other):
            self.value = other
            return self

        __iadd__ = fake_op
        __isub__ = fake_op
        __imul__ = fake_op
        __imatmul__ = fake_op
        __itruediv__ = fake_op
        __ifloordiv__ = fake_op
        __imod__ = fake_op
        __ipow__ = fake_op
        __ilshift__ = fake_op
        __irshift__ = fake_op
        __iand__ = fake_op
        __ior__ = fake_op
        __ixor__ = fake_op

    ns, p = _make_proxy(Example())
    p_out = op(p, 2)
    assert type(p_out) is local.LocalProxy
    assert p.value == 2
    assert ns.value.value == 2


def test_proxy_matmul():
    class Example:
        def __matmul__(self, other):
            return 2 * other

        def __rmatmul__(self, other):
            return 2 * other

    _, p = _make_proxy(Example())
    assert p @ 3 == 6
    assert 4 @ p == 8


def test_proxy_str():
    _, p = _make_proxy("{act} %s")
    assert p + " world" == "{act} %s world"
    assert "say " + p == "say {act} %s"
    assert p * 2 == "{act} %s{act} %s"
    assert 2 * p == p * 2
    assert p % ("world",) == "{act} world"
    assert p.format(act="test") == "test %s"


def test_proxy_list():
    _, p = _make_proxy([1, 2, 3])
    assert len(p) == 3
    assert p[0] == 1
    assert 3 in p
    assert 4 not in p
    assert tuple(p) == (1, 2, 3)
    assert list(reversed(p)) == [3, 2, 1]
    p[0] = 4
    assert p == [4, 2, 3]
    del p[-1]
    assert p == [4, 2]
    p += [5]
    assert p[-1] == 5
    p *= 2
    assert len(p) == 6
    p[:] = []
    assert not p
    p.append(1)
    assert p
    assert p + [2] == [1, 2]
    assert [2] + p == [2, 1]


def test_proxy_copy():
    class Foo:
        def __copy__(self):
            return self

        def __deepcopy__(self, memo):
            return self

    ns, p = _make_proxy(Foo())
    assert copy.copy(p) is ns.value
    assert copy.deepcopy(p) is ns.value

    a = []
    _, p = _make_proxy([a])
    assert copy.copy(p) == [a]
    assert copy.copy(p)[0] is a
    assert copy.deepcopy(p) == [a]
    assert copy.deepcopy(p)[0] is not a


def test_proxy_iterator():
    a = [1, 2, 3]
    _, p = _make_proxy(iter(a))
    assert next(p) == 1


def test_proxy_length_hint():
    class Example:
        def __length_hint__(self):
            return 2

    _, p = _make_proxy(Example())
    assert operator.length_hint(p) == 2


def test_proxy_context_manager():
    class Example:
        value = 2

        def __enter__(self):
            self.value += 1
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.value -= 1

    _, p = _make_proxy(Example())
    assert p.value == 2

    with p:
        assert p.value == 3

    assert p.value == 2


def test_proxy_class():
    class Meta(type):
        def __instancecheck__(cls, instance):
            return True

        def __subclasscheck__(cls, subclass):
            return True

    class Parent:
        pass

    class Example(Parent, metaclass=Meta):
        pass

    class Child(Example):
        pass

    _, p = _make_proxy(Example)
    assert type(p()) is Example
    assert isinstance(1, p)
    assert issubclass(int, p)
    assert p.__mro__ == (Example, Parent, object)
    assert p.__bases__ == (Parent,)
    assert p.__subclasses__() == [Child]


def test_proxy_attributes():
    class Example:
        def __init__(self):
            object.__setattr__(self, "values", {})

        def __getattribute__(self, name):
            if name == "ham":
                return "eggs"

            return super().__getattribute__(name)

        def __getattr__(self, name):
            return self.values.get(name)

        def __setattr__(self, name, value):
            self.values[name] = value

        def __delattr__(self, name):
            del self.values[name]

        def __dir__(self):
            return sorted(self.values.keys())

    _, p = _make_proxy(Example())
    assert p.nothing is None
    assert p.__dict__ == {"values": {}}
    assert dir(p) == []

    p.x = 1
    assert p.x == 1
    assert dir(p) == ["x"]

    del p.x
    assert dir(p) == []

    assert p.ham == "eggs"
    p.ham = "spam"
    assert p.ham == "eggs"
    assert p.values["ham"] == "spam"


def test_proxy_await():
    async def get():
        return 1

    _, p = _make_proxy(get())

    async def main():
        return await p

    out = asyncio.run(main())
    assert out == 1


def test_proxy_aiter():
    class Example:
        value = 3

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.value:
                self.value -= 1
                return self.value

            raise StopAsyncIteration

    _, p = _make_proxy(Example())

    async def main():
        out = []

        async for v in p:
            out.append(v)

        return out

    out = asyncio.run(main())
    assert out == [2, 1, 0]


def test_proxy_async_context_manager():
    class Example:
        value = 2

        async def __aenter__(self):
            self.value += 1
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.value -= 1

    _, p = _make_proxy(Example())

    async def main():
        async with p:
            assert p.value == 3

        assert p.value == 2
        return True

    assert asyncio.run(main())
