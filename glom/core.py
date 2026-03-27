"""*glom gets results.*

The ``glom`` package has one central entrypoint,
:func:`glom.glom`. Everything else in the package revolves around that
one function. Sometimes, big things come in small packages.

A couple of conventional terms you'll see repeated many times below:

* **target** - glom is built to work on any data, so we simply
  refer to the object being accessed as the *"target"*
* **spec** - *(aka "glomspec", short for specification)* The
  accompanying template used to specify the structure of the return
  value.

Now that you know the terms, let's take a look around glom's powerful
semantics.

"""


import os
import sys
import pdb
import copy
import warnings
import weakref
import operator
from abc import ABCMeta
from pprint import pprint
import string
from collections import OrderedDict
import traceback

from face.helpers import get_wrap_width
from boltons.typeutils import make_sentinel
from boltons.iterutils import is_iterable
#from boltons.funcutils import format_invocation

basestring = str
_AbstractIterableBase = ABCMeta('_AbstractIterableBase', (object,), {})
from collections import ChainMap
from reprlib import Repr, recursive_repr

GLOM_DEBUG = os.getenv('GLOM_DEBUG', '').strip().lower()
GLOM_DEBUG = False if (GLOM_DEBUG in ('', '0', 'false')) else True

TRACE_WIDTH = max(get_wrap_width(max_width=110), 50)   # min width

PATH_STAR = True
# should * and ** be interpreted as parallel traversal in Path.from_text()?
# Changed to True in 23.1, this option to disable will go away soon

_type_type = type

_MISSING = make_sentinel('_MISSING')
SKIP =  make_sentinel('SKIP')
SKIP.__doc__ = """
The ``SKIP`` singleton can be returned from a function or included
via a :class:`~glom.Val` to cancel assignment into the output
object.

>>> target = {'a': 'b'}
>>> spec = {'a': lambda t: t['a'] if t['a'] == 'a' else SKIP}
>>> glom(target, spec)
{}
>>> target = {'a': 'a'}
>>> glom(target, spec)
{'a': 'a'}

Mostly used to drop keys from dicts (as above) or filter objects from
lists.

.. note::

   SKIP was known as OMIT in versions 18.3.1 and prior. Versions 19+
   will remove the OMIT alias entirely.
"""
OMIT = SKIP  # backwards compat, remove in 19+

STOP = make_sentinel('STOP')
STOP.__doc__ = """
The ``STOP`` singleton can be used to halt iteration of a list or
execution of a tuple of subspecs.

>>> target = range(10)
>>> spec = [lambda x: x if x < 5 else STOP]
>>> glom(target, spec)
[0, 1, 2, 3, 4]
"""

LAST_CHILD_SCOPE = make_sentinel('LAST_CHILD_SCOPE')
LAST_CHILD_SCOPE.__doc__ = """
Marker that can be used by parents to keep track of the last child
scope executed.  Useful for "lifting" results out of child scopes
for scopes that want to chain the scopes of their children together
similar to tuple.
"""

NO_PYFRAME = make_sentinel('NO_PYFRAME')
NO_PYFRAME.__doc__ = """
Used internally to mark scopes which are no longer wrapped
in a recursive glom() call, so that they can be cleaned up correctly
in case of exceptions
"""

MODE =  make_sentinel('MODE')

MIN_MODE =  make_sentinel('MIN_MODE')

CHILD_ERRORS = make_sentinel('CHILD_ERRORS')
CHILD_ERRORS.__doc__ = """
``CHILD_ERRORS`` is used by glom internals to keep track of
failed child branches of the current scope.
"""

CUR_ERROR = make_sentinel('CUR_ERROR')
CUR_ERROR.__doc__ = """
``CUR_ERROR`` is used by glom internals to keep track of
thrown exceptions.
"""

_PKG_DIR_PATH = os.path.dirname(os.path.abspath(__file__))

class GlomError(Exception):
    """The base exception for all the errors that might be raised from
    :func:`glom` processing logic.

    By default, exceptions raised from within functions passed to glom
    (e.g., ``len``, ``sum``, any ``lambda``) will not be wrapped in a
    GlomError.
    """



    def __str__(self):
        if getattr(self, '_finalized_str', None):
            return self._finalized_str
        elif getattr(self, '_scope', None) is not None:
            self._target_spec_trace = format_target_spec_trace(self._scope, self.__wrapped)
            parts = ["error raised while processing, details below.",
                     " Target-spec trace (most recent last):",
                     self._target_spec_trace]
            parts.extend(self._tb_lines)
            self._finalized_str = "\n".join(parts)
            return self._finalized_str

        # else, not finalized
        try:
            exc_get_message = self.get_message
        except AttributeError:
            exc_get_message = super().__str__
        return exc_get_message()


def _unpack_stack(scope, only_errors=True):
    """
    convert scope to [[scope, spec, target, error, [children]]]

    this is a convenience method for printing stacks

    only_errors=True means ignore branches which may still be hanging around
    which were not involved in the stack trace of the error

    only_errors=False could be useful for debugger / introspection (similar
    to traceback.print_stack())
    """
    pass




def format_target_spec_trace(scope, root_error, width=TRACE_WIDTH, depth=0, prev_target=_MISSING, last_branch=True):
    """
    unpack a scope into a multi-line but short summary
    """
    pass


# TODO: not used (yet)
def format_oneline_trace(scope):
    """
    unpack a scope into a single line summary
    (shortest summary possible)
    """
    pass


class PathAccessError(GlomError, AttributeError, KeyError, IndexError):
    """This :exc:`GlomError` subtype represents a failure to access an
    attribute as dictated by the spec. The most commonly-seen error
    when using glom, it maintains a copy of the original exception and
    produces a readable error message for easy debugging.

    If you see this error, you may want to:

       * Check the target data is accurate using :class:`~glom.Inspect`
       * Catch the exception and return a semantically meaningful error message
       * Use :class:`glom.Coalesce` to specify a default
       * Use the top-level ``default`` kwarg on :func:`~glom.glom()`

    In any case, be glad you got this error and not the one it was
    wrapping!

    Args:
       exc (Exception): The error that arose when we tried to access
          *path*. Typically an instance of KeyError, AttributeError,
          IndexError, or TypeError, and sometimes others.
       path (Path): The full Path glom was in the middle of accessing
          when the error occurred.
       part_idx (int): The index of the part of the *path* that caused
          the error.

    >>> target = {'a': {'b': None}}
    >>> glom(target, 'a.b.c')
    Traceback (most recent call last):
    ...
    PathAccessError: could not access 'c', part 2 of Path('a', 'b', 'c'), got error: ...

    """
    def __init__(self, exc, path, part_idx):
        self.exc = exc
        self.path = path
        self.part_idx = part_idx


    def __repr__(self):
        cn = self.__class__.__name__
        return f'{cn}({self.exc!r}, {self.path!r}, {self.part_idx!r})'


class PathAssignError(GlomError):
    """This :exc:`GlomError` subtype is raised when an assignment fails,
    stemming from an :func:`~glom.assign` call or other
    :class:`~glom.Assign` usage.

    One example would be assigning to an out-of-range position in a list::

      >>> assign(["short", "list"], Path(5), 'too far')  # doctest: +SKIP
      Traceback (most recent call last):
      ...
      PathAssignError: could not assign 5 on object at Path(), got error: IndexError(...

    Other assignment failures could be due to assigning to an
    ``@property`` or exception being raised inside a ``__setattr__()``.

    """
    def __init__(self, exc, path, dest_name):
        self.exc = exc
        self.path = path
        self.dest_name = dest_name


    def __repr__(self):
        cn = self.__class__.__name__
        return f'{cn}({self.exc!r}, {self.path!r}, {self.dest_name!r})'


class CoalesceError(GlomError):
    """This :exc:`GlomError` subtype is raised from within a
    :class:`Coalesce` spec's processing, when none of the subspecs
    match and no default is provided.

    The exception object itself keeps track of several values which
    may be useful for processing:

    Args:
       coal_obj (Coalesce): The original failing spec, see
          :class:`Coalesce`'s docs for details.
       skipped (list): A list of ignored values and exceptions, in the
          order that their respective subspecs appear in the original
          *coal_obj*.
       path: Like many GlomErrors, this exception knows the path at
          which it occurred.

    >>> target = {}
    >>> glom(target, Coalesce('a', 'b'))
    Traceback (most recent call last):
    ...
    CoalesceError: no valid values found. Tried ('a', 'b') and got (PathAccessError, PathAccessError) ...

    .. note::

       Coalesce is a *branching* specifier type, so as of v20.7.0, its
       exception messages feature an error tree. See
       :ref:`branched-exceptions` for details on how to interpret these
       exceptions.

    """
    def __init__(self, coal_obj, skipped, path):
        self.coal_obj = coal_obj
        self.skipped = skipped
        self.path = path

    def __repr__(self):
        cn = self.__class__.__name__
        return f'{cn}({self.coal_obj!r}, {self.skipped!r}, {self.path!r})'



class BadSpec(GlomError, TypeError):
    """Raised when a spec structure is malformed, e.g., when a specifier
    type is invalid for the current mode."""


class UnregisteredTarget(GlomError):
    """This :class:`GlomError` subtype is raised when a spec calls for an
    unsupported action on a target type. For instance, trying to
    iterate on an non-iterable target:

    >>> glom(object(), ['a.b.c'])
    Traceback (most recent call last):
    ...
    UnregisteredTarget: target type 'object' not registered for 'iterate', expected one of registered types: (...)

    It should be noted that this is a pretty uncommon occurrence in
    production glom usage. See the :ref:`setup-and-registration`
    section for details on how to avoid this error.

    An UnregisteredTarget takes and tracks a few values:

    Args:
       op (str): The name of the operation being performed ('get' or 'iterate')
       target_type (type): The type of the target being processed.
       type_map (dict): A mapping of target types that do support this operation
       path: The path at which the error occurred.

    """
    def __init__(self, op, target_type, type_map, path):
        self.op = op
        self.target_type = target_type
        self.type_map = type_map
        self.path = path
        super().__init__(op, target_type, type_map, path)

    def __repr__(self):
        cn = self.__class__.__name__
        # <type %r> is because Python 3 inexplicably changed the type
        # repr from <type *> to <class *>
        return ('%s(%r, <type %r>, %r, %r)'
                % (cn, self.op, self.target_type.__name__, self.type_map, self.path))



if getattr(__builtins__, '__dict__', None) is not None:
    # pypy's __builtins__ is a module, as is CPython's REPL, but at
    # normal execution time it's a dict?
    __builtins__ = __builtins__.__dict__


_BUILTIN_ID_NAME_MAP = {id(v): k
                             for k, v in __builtins__.items()}


class _BBRepr(Repr):
    """A better repr for builtins, when the built-in repr isn't
    roundtrippable.
    """
    def __init__(self):
        super().__init__()
        # turn up all the length limits very high
        for name in self.__dict__:
            if not isinstance(getattr(self, name), int):
                continue
            setattr(self, name, 1024)



bbrepr = recursive_repr()(_BBRepr().repr)


class _BBReprFormatter(string.Formatter):
    """
    allow format strings to be evaluated where {!r} will use bbrepr
    instead of repr
    """


bbformat = _BBReprFormatter().format


# TODO: push this back up to boltons with repr kwarg
def format_invocation(name='', args=(), kwargs=None, **kw):
    """Given a name, positional arguments, and keyword arguments, format
    a basic Python-style function call.

    >>> print(format_invocation('func', args=(1, 2), kwargs={'c': 3}))
    func(1, 2, c=3)
    >>> print(format_invocation('a_func', args=(1,)))
    a_func(1)
    >>> print(format_invocation('kw_func', kwargs=[('a', 1), ('b', 2)]))
    kw_func(a=1, b=2)

    """
    pass


class Path:
    """Path objects specify explicit paths when the default
    ``'a.b.c'``-style general access syntax won't work or isn't
    desirable. Use this to wrap ints, datetimes, and other valid
    keys, as well as strings with dots that shouldn't be expanded.

    >>> target = {'a': {'b': 'c', 'd.e': 'f', 2: 3}}
    >>> glom(target, Path('a', 2))
    3
    >>> glom(target, Path('a', 'd.e'))
    'f'

    Paths can be used to join together other Path objects, as
    well as :data:`~glom.T` objects:

    >>> Path(T['a'], T['b'])
    T['a']['b']
    >>> Path(Path('a', 'b'), Path('c', 'd'))
    Path('a', 'b', 'c', 'd')

    Paths also support indexing and slicing, with each access
    returning a new Path object:

    >>> path = Path('a', 'b', 1, 2)
    >>> path[0]
    Path('a')
    >>> path[-2:]
    Path(1, 2)

    To build a Path object from a string, use :meth:`Path.from_text()`. 
    This is the default behavior when the top-level :func:`~glom.glom` 
    function gets a string spec.
    """
    def __init__(self, *path_parts):
        if not path_parts:
            self.path_t = T
            return
        if isinstance(path_parts[0], TType):
            path_t = path_parts[0]
            offset = 1
        else:
            path_t = T
            offset = 0
        for part in path_parts[offset:]:
            if isinstance(part, Path):
                part = part.path_t
            if isinstance(part, TType):
                sub_parts = part.__ops__
                if sub_parts[0] is not T:
                    raise ValueError('path segment must be path from T, not %r'
                                     % sub_parts[0])
                i = 1
                while i < len(sub_parts):
                    path_t = _t_child(path_t, sub_parts[i], sub_parts[i + 1])
                    i += 2
            else:
                path_t = _t_child(path_t, 'P', part)
        self.path_t = path_t

    _CACHE = {True: {}, False: {}}
    _MAX_CACHE = 10000
    _STAR_WARNED = False

    @classmethod
    def from_text(cls, text):
        """Make a Path from .-delimited text:

        >>> Path.from_text('a.b.c')
        Path('a', 'b', 'c')

        This is the default behavior when :func:`~glom.glom` gets a string spec.
        """
        pass


    def __len__(self):
        return (len(self.path_t.__ops__) - 1) // 2

    def __eq__(self, other):
        if type(other) is Path:
            return self.path_t.__ops__ == other.path_t.__ops__
        elif type(other) is TType:
            return self.path_t.__ops__ == other.__ops__
        return False

    def __ne__(self, other):
        return not self == other

    def values(self):
        """
        Returns a tuple of values referenced in this path.

        >>> Path(T.a.b, 'c', T['d']).values()
        ('a', 'b', 'c', 'd')
        """
        cur_t_path = self.path_t.__ops__
        return cur_t_path[2::2]

    def items(self):
        """
        Returns a tuple of (operation, value) pairs.

        >>> Path(T.a.b, 'c', T['d']).items()
        (('.', 'a'), ('.', 'b'), ('P', 'c'), ('[', 'd'))

        """
        cur_t_path = self.path_t.__ops__
        return tuple(zip(cur_t_path[1::2], cur_t_path[2::2]))


    def from_t(self):
        '''return the same path but starting from T'''
        pass

    def __getitem__(self, i):
        cur_t_path = self.path_t.__ops__
        try:
            step = i.step
            start = i.start if i.start is not None else 0
            stop = i.stop

            start = (start * 2) + 1 if start >= 0 else (start * 2) + len(cur_t_path)
            if stop is not None:
                stop = (stop * 2) + 1 if stop >= 0 else (stop * 2) + len(cur_t_path)
        except AttributeError:
            step = 1
            start = (i * 2) + 1 if i >= 0 else (i * 2) + len(cur_t_path)
            if start < 0 or start > len(cur_t_path):
                raise IndexError('Path index out of range')
            stop = ((i + 1) * 2) + 1 if i >= 0 else ((i + 1) * 2) + len(cur_t_path)

        new_t = TType()
        new_path = cur_t_path[start:stop]
        if step is not None and step != 1:
            new_path = tuple(zip(new_path[::2], new_path[1::2]))[::step]
            new_path = sum(new_path, ())
        new_t.__ops__ = (cur_t_path[0],) + new_path
        return Path(new_t)

    def __repr__(self):
        return _format_path(self.path_t.__ops__[1:])




class Spec:
    """Spec objects serve three purposes, here they are, roughly ordered
    by utility:

      1. As a form of compiled or "curried" glom call, similar to
         Python's built-in :func:`re.compile`.
      2. A marker as an object as representing a spec rather than a
         literal value in certain cases where that might be ambiguous.
      3. A way to update the scope within another Spec.

    In the second usage, Spec objects are the complement to
    :class:`~glom.Val`, wrapping a value and marking that it
    should be interpreted as a glom spec, rather than a literal value.
    This is useful in places where it would be interpreted as a value
    by default. (Such as T[key], Call(func) where key and func are
    assumed to be literal values and not specs.)

    Args:
        spec: The glom spec.
        scope (dict): additional values to add to the scope when
          evaluating this Spec

    """
    def __init__(self, spec, scope=None):
        self.spec = spec
        self.scope = scope or {}



    def __repr__(self):
        cn = self.__class__.__name__
        if self.scope:
            return f'{cn}({bbrepr(self.spec)}, scope={self.scope!r})'
        return f'{cn}({bbrepr(self.spec)})'


class Coalesce:
    """Coalesce objects specify fallback behavior for a list of
    subspecs.

    Subspecs are passed as positional arguments, and keyword arguments
    control defaults. Each subspec is evaluated in turn, and if none
    match, a :exc:`CoalesceError` is raised, or a default is returned,
    depending on the options used.

    .. note::

      This operation may seem very familar if you have experience with
      `SQL`_ or even `C# and others`_.


    In practice, this fallback behavior's simplicity is only surpassed
    by its utility:

    >>> target = {'c': 'd'}
    >>> glom(target, Coalesce('a', 'b', 'c'))
    'd'

    glom tries to get ``'a'`` from ``target``, but gets a
    KeyError. Rather than raise a :exc:`~glom.PathAccessError` as usual,
    glom *coalesces* into the next subspec, ``'b'``. The process
    repeats until it gets to ``'c'``, which returns our value,
    ``'d'``. If our value weren't present, we'd see:

    >>> target = {}
    >>> glom(target, Coalesce('a', 'b'))
    Traceback (most recent call last):
    ...
    CoalesceError: no valid values found. Tried ('a', 'b') and got (PathAccessError, PathAccessError) ...

    Same process, but because ``target`` is empty, we get a
    :exc:`CoalesceError`.

    .. note::

       Coalesce is a *branching* specifier type, so as of v20.7.0, its
       exception messages feature an error tree. See
       :ref:`branched-exceptions` for details on how to interpret these
       exceptions.


    If we want to avoid an exception, and we know which value we want
    by default, we can set *default*:

    >>> target = {}
    >>> glom(target, Coalesce('a', 'b', 'c'), default='d-fault')
    'd-fault'

    ``'a'``, ``'b'``, and ``'c'`` weren't present so we got ``'d-fault'``.

    Args:

       subspecs: One or more glommable subspecs
       default: A value to return if no subspec results in a valid value
       default_factory: A callable whose result will be returned as a default
       skip: A value, tuple of values, or predicate function
         representing values to ignore
       skip_exc: An exception or tuple of exception types to catch and
         move on to the next subspec. Defaults to :exc:`GlomError`, the
         parent type of all glom runtime exceptions.

    If all subspecs produce skipped values or exceptions, a
    :exc:`CoalesceError` will be raised. For more examples, check out
    the :doc:`tutorial`, which makes extensive use of Coalesce.

    .. _SQL: https://en.wikipedia.org/w/index.php?title=Null_(SQL)&oldid=833093792#COALESCE
    .. _C# and others: https://en.wikipedia.org/w/index.php?title=Null_coalescing_operator&oldid=839493322#C#

    """
    def __init__(self, *subspecs, **kwargs):
        self.subspecs = subspecs
        self._orig_kwargs = dict(kwargs)
        self.default = kwargs.pop('default', _MISSING)
        self.default_factory = kwargs.pop('default_factory', _MISSING)
        if self.default and self.default_factory:
            raise ValueError('expected one of "default" or "default_factory", not both')
        self.skip = kwargs.pop('skip', _MISSING)
        if self.skip is _MISSING:
            self.skip_func = lambda v: False
        elif callable(self.skip):
            self.skip_func = self.skip
        elif isinstance(self.skip, tuple):
            self.skip_func = lambda v: v in self.skip
        else:
            self.skip_func = lambda v: v == self.skip
        self.skip_exc = kwargs.pop('skip_exc', GlomError)
        if kwargs:
            raise TypeError(f'unexpected keyword args: {sorted(kwargs.keys())!r}')


    def __repr__(self):
        cn = self.__class__.__name__
        return format_invocation(cn, self.subspecs, self._orig_kwargs, repr=bbrepr)


class Inspect:
    """The :class:`~glom.Inspect` specifier type provides a way to get
    visibility into glom's evaluation of a specification, enabling
    debugging of those tricky problems that may arise with unexpected
    data.

    :class:`~glom.Inspect` can be inserted into an existing spec in one of two
    ways. First, as a wrapper around the spec in question, or second,
    as an argument-less placeholder wherever a spec could be.

    :class:`~glom.Inspect` supports several modes, controlled by
    keyword arguments. Its default, no-argument mode, simply echos the
    state of the glom at the point where it appears:

      >>> target = {'a': {'b': {}}}
      >>> val = glom(target, Inspect('a.b'))  # wrapping a spec
      ---
      path:   ['a.b']
      target: {'a': {'b': {}}}
      output: {}
      ---

    Debugging behavior aside, :class:`~glom.Inspect` has no effect on
    values in the target, spec, or result.

    Args:
       echo (bool): Whether to print the path, target, and output of
         each inspected glom. Defaults to True.
       recursive (bool): Whether or not the Inspect should be applied
         at every level, at or below the spec that it wraps. Defaults
         to False.
       breakpoint (bool): This flag controls whether a debugging prompt
         should appear before evaluating each inspected spec. Can also
         take a callable. Defaults to False.
       post_mortem (bool): This flag controls whether exceptions
         should be caught and interactively debugged with :mod:`pdb` on
         inspected specs.

    All arguments above are keyword-only to avoid overlap with a
    wrapped spec.

    .. note::

       Just like ``pdb.set_trace()``, be careful about leaving stray
       ``Inspect()`` instances in production glom specs.

    """
    def __init__(self, *a, **kw):
        self.wrapped = a[0] if a else Path()
        self.recursive = kw.pop('recursive', False)
        self.echo = kw.pop('echo', True)
        breakpoint = kw.pop('breakpoint', False)
        if breakpoint is True:
            breakpoint = pdb.set_trace
        if breakpoint and not callable(breakpoint):
            raise TypeError('breakpoint expected bool or callable, not: %r' % breakpoint)
        self.breakpoint = breakpoint
        post_mortem = kw.pop('post_mortem', False)
        if post_mortem is True:
            post_mortem = pdb.post_mortem
        if post_mortem and not callable(post_mortem):
            raise TypeError('post_mortem expected bool or callable, not: %r' % post_mortem)
        self.post_mortem = post_mortem

    def __repr__(self):
        return '<INSPECT>'




class Call:
    """:class:`Call` specifies when a target should be passed to a function,
    *func*.

    :class:`Call` is similar to :func:`~functools.partial` in that
    it is no more powerful than ``lambda`` or other functions, but
    it is designed to be more readable, with a better ``repr``.

    Args:
       func (callable): a function or other callable to be called with
          the target

    :class:`Call` combines well with :attr:`~glom.T` to construct objects. For
    instance, to generate a dict and then pass it to a constructor:

    >>> class ExampleClass(object):
    ...    def __init__(self, attr):
    ...        self.attr = attr
    ...
    >>> target = {'attr': 3.14}
    >>> glom(target, Call(ExampleClass, kwargs=T)).attr
    3.14

    This does the same as ``glom(target, lambda target:
    ExampleClass(**target))``, but it's easy to see which one reads
    better.

    .. note::

       ``Call`` is mostly for functions. Use a :attr:`~glom.T` object
       if you need to call a method.

    .. warning::

       :class:`Call` has a successor with a fuller-featured API, new
       in 19.10.0: the :class:`Invoke` specifier type.
    """
    def __init__(self, func=None, args=None, kwargs=None):
        if func is None:
            func = T
        if not (callable(func) or isinstance(func, (Spec, TType))):
            raise TypeError('expected func to be a callable or T'
                            ' expression, not: %r' % (func,))
        if args is None:
            args = ()
        if kwargs is None:
            kwargs = {}
        self.func, self.args, self.kwargs = func, args, kwargs

    def glomit(self, target, scope):
        'run against the current target'
        pass

    def __repr__(self):
        cn = self.__class__.__name__
        return f'{cn}({bbrepr(self.func)}, args={self.args!r}, kwargs={self.kwargs!r})'




class Invoke:
    """Specifier type designed for easy invocation of callables from glom.

    Args:
      func (callable): A function or other callable object.

    ``Invoke`` is similar to :func:`functools.partial`, but with the
    ability to set up a "templated" call which interleaves constants and
    glom specs.

    For example, the following creates a spec which can be used to
    check if targets are integers:

    >>> is_int = Invoke(isinstance).specs(T).constants(int)
    >>> glom(5, is_int)
    True

    And this composes like any other glom spec:

    >>> target = [7, object(), 9]
    >>> glom(target, [is_int])
    [True, False, True]

    Another example, mixing positional and keyword arguments:

    >>> spec = Invoke(sorted).specs(T).constants(key=int, reverse=True)
    >>> target = ['10', '5', '20', '1']
    >>> glom(target, spec)
    ['20', '10', '5', '1']

    Invoke also helps with evaluating zero-argument functions:

    >>> glom(target={}, spec=Invoke(int))
    0

    (A trivial example, but from timestamps to UUIDs, zero-arg calls do come up!)

    .. note::

       ``Invoke`` is mostly for functions, object construction, and callable
       objects. For calling methods, consider the :attr:`~glom.T` object.

    """
    def __init__(self, func):
        if not callable(func) and not _is_spec(func, strict=True):
            raise TypeError('expected func to be a callable or Spec instance,'
                            ' not: %r' % (func,))
        self.func = func
        self._args = ()
        # a registry of every known kwarg to its freshest value as set
        # by the methods below. the **kw dict is used as a unique marker.
        self._cur_kwargs = {}

    @classmethod
    def specfunc(cls, spec):
        """Creates an :class:`Invoke` instance where the function is
        indicated by a spec.

        >>> spec = Invoke.specfunc('func').constants(5)
        >>> glom({'func': range}, (spec, list))
        [0, 1, 2, 3, 4]

        """
        pass

    def constants(self, *a, **kw):
        """Returns a new :class:`Invoke` spec, with the provided positional
        and keyword argument values stored for passing to the
        underlying function.

        >>> spec = Invoke(T).constants(5)
        >>> glom(range, (spec, list))
        [0, 1, 2, 3, 4]

        Subsequent positional arguments are appended:

        >>> spec = Invoke(T).constants(2).constants(10, 2)
        >>> glom(range, (spec, list))
        [2, 4, 6, 8]

        Keyword arguments also work as one might expect:

        >>> round_2 = Invoke(round).constants(ndigits=2).specs(T)
        >>> glom(3.14159, round_2)
        3.14

        :meth:`~Invoke.constants()` and other :class:`Invoke`
        methods may be called multiple times, just remember that every
        call returns a new spec.
        """
        pass

    def specs(self, *a, **kw):
        """Returns a new :class:`Invoke` spec, with the provided positional
        and keyword arguments stored to be interpreted as specs, with
        the results passed to the underlying function.

        >>> spec = Invoke(range).specs('value')
        >>> glom({'value': 5}, (spec, list))
        [0, 1, 2, 3, 4]

        Subsequent positional arguments are appended:

        >>> spec = Invoke(range).specs('start').specs('end', 'step')
        >>> target = {'start': 2, 'end': 10, 'step': 2}
        >>> glom(target, (spec, list))
        [2, 4, 6, 8]

        Keyword arguments also work as one might expect:

        >>> multiply = lambda x, y: x * y
        >>> times_3 = Invoke(multiply).constants(y=3).specs(x='value')
        >>> glom({'value': 5}, times_3)
        15

        :meth:`~Invoke.specs()` and other :class:`Invoke`
        methods may be called multiple times, just remember that every
        call returns a new spec.

        """
        pass

    def star(self, args=None, kwargs=None):
        """Returns a new :class:`Invoke` spec, with *args* and/or *kwargs*
        specs set to be "starred" or "star-starred" (respectively)

        >>> spec = Invoke(zip).star(args='lists')
        >>> target = {'lists': [[1, 2], [3, 4], [5, 6]]}
        >>> list(glom(target, spec))
        [(1, 3, 5), (2, 4, 6)]

        Args:
           args (spec): A spec to be evaluated and "starred" into the
              underlying function.
           kwargs (spec): A spec to be evaluated and "star-starred" into
              the underlying function.

        One or both of the above arguments should be set.

        The :meth:`~Invoke.star()`, like other :class:`Invoke`
        methods, may be called multiple times. The *args* and *kwargs*
        will be stacked in the order in which they are provided.
        """
        pass

    def __repr__(self):
        base_fname = self.__class__.__name__
        fname_map = {'C': 'constants', 'S': 'specs', '*': 'star'}
        if type(self.func) is Spec:
            base_fname += '.specfunc'
            args = (self.func.spec,)
        else:
            args = (self.func,)
        chunks = [format_invocation(base_fname, args, repr=bbrepr)]

        for i in range(len(self._args) // 3):
            op, args, _kwargs = self._args[i * 3: i * 3 + 3]
            fname = fname_map[op]
            if op in ('C', 'S'):
                kwargs = [(k, v) for k, v in _kwargs.items()
                          if self._cur_kwargs[k] is _kwargs]
            else:
                kwargs = {}
                if args:
                    kwargs['args'] = args
                if _kwargs:
                    kwargs['kwargs'] = _kwargs
                args = ()

            chunks.append('.' + format_invocation(fname, args, kwargs, repr=bbrepr))

        return ''.join(chunks)



class Ref:
    """Name a part of a spec and refer to it elsewhere in the same spec,
    useful for trees and other self-similar data structures.

    Args:
       name (str): The name of the spec to reference.
       subspec: Pass a spec to name it *name*, or leave unset to refer
          to an already-named spec.
    """
    def __init__(self, name, subspec=_MISSING):
        self.name, self.subspec = name, subspec


    def __repr__(self):
        if self.subspec is _MISSING:
            args = bbrepr(self.name)
        else:
            args = bbrepr((self.name, self.subspec))[1:-1]
        return "Ref(" + args + ")"


class TType:
    """``T``, short for "target". A singleton object that enables
    object-oriented expression of a glom specification.

    .. note::

       ``T`` is a singleton, and does not need to be constructed.

    Basically, think of ``T`` as your data's stunt double. Everything
    that you do to ``T`` will be recorded and executed during the
    :func:`glom` call. Take this example:

    >>> spec = T['a']['b']['c']
    >>> target = {'a': {'b': {'c': 'd'}}}
    >>> glom(target, spec)
    'd'

    So far, we've relied on the ``'a.b.c'``-style shorthand for
    access, or used the :class:`~glom.Path` objects, but if you want
    to explicitly do attribute and key lookups, look no further than
    ``T``.

    But T doesn't stop with unambiguous access. You can also call
    methods and perform almost any action you would with a normal
    object:

    >>> spec = ('a', (T['b'].items(), list))  # reviewed below
    >>> glom(target, spec)
    [('c', 'd')]

    A ``T`` object can go anywhere in the spec. As seen in the example
    above, we access ``'a'``, use a ``T`` to get ``'b'`` and iterate
    over its ``items``, turning them into a ``list``.

    You can even use ``T`` with :class:`~glom.Call` to construct objects:

    >>> class ExampleClass(object):
    ...    def __init__(self, attr):
    ...        self.attr = attr
    ...
    >>> target = {'attr': 3.14}
    >>> glom(target, Call(ExampleClass, kwargs=T)).attr
    3.14

    On a further note, while ``lambda`` works great in glom specs, and
    can be very handy at times, ``T`` and :class:`~glom.Call`
    eliminate the need for the vast majority of ``lambda`` usage with
    glom.

    Unlike ``lambda`` and other functions, ``T`` roundtrips
    beautifully and transparently:

    >>> T['a'].b['c']('success')
    T['a'].b['c']('success')

    ``T``-related access errors raise a :exc:`~glom.PathAccessError`
    during the :func:`~glom.glom` call.

    .. note::

       While ``T`` is clearly useful, powerful, and here to stay, its
       semantics are still being refined. Currently, operations beyond
       method calls and attribute/item access are considered
       experimental and should not be relied upon.

    .. note::

       ``T`` attributes starting with __ are reserved to avoid
       colliding with many built-in Python behaviors, current and
       future.  The ``T.__()`` method is available for cases where
       they are needed.  For example, ``T.__('class__')`` is
       equivalent to accessing the ``__class__`` attribute.

    """
    __slots__ = ('__ops__',)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError('T instances reserve dunder attributes.'
                                 ' To access the "{name}" attribute, use'
                                 ' T.__("{d_name}")'.format(name=name, d_name=name[2:]))
        return _t_child(self, '.', name)

    def __getitem__(self, item):
        return _t_child(self, '[', item)

    def __call__(self, *args, **kwargs):
        if self is S:
            if args:
                raise TypeError(f'S() takes no positional arguments, got: {args!r}')
            if not kwargs:
                raise TypeError('S() expected at least one kwarg, got none')
            # TODO: typecheck kwarg vals?
        return _t_child(self, '(', (args, kwargs))

    def __star__(self):
        return _t_child(self, 'x', None)

    def __starstar__(self):
        return _t_child(self, 'X', None)

    def __stars__(self):
        """how many times the result will be wrapped in extra lists"""
        t_ops = self.__ops__[1::2]
        return t_ops.count('x') + t_ops.count('X')

    def __add__(self, arg):
        return _t_child(self, '+', arg)

    def __sub__(self, arg):
        return _t_child(self, '-', arg)

    def __mul__(self, arg):
        return _t_child(self, '*', arg)

    def __floordiv__(self, arg):
        return _t_child(self, '#', arg)

    def __truediv__(self, arg):
        return _t_child(self, '/', arg)

    __div__ = __truediv__

    def __mod__(self, arg):
        return _t_child(self, '%', arg)

    def __pow__(self, arg):
        return _t_child(self, ':', arg)

    def __and__(self, arg):
        return _t_child(self, '&', arg)

    def __or__(self, arg):
        return _t_child(self, '|', arg)

    def __xor__(self, arg):
        return _t_child(self, '^', arg)

    def __invert__(self):
        return _t_child(self, '~', None)

    def __neg__(self):
        return _t_child(self, '_', None)

    def __(self, name):
        return _t_child(self, '.', '__' + name)

    def __repr__(self):
        t_path = self.__ops__
        return _format_t(t_path[1:], t_path[0])

    def __getstate__(self):
        t_path = self.__ops__
        return tuple(({T: 'T', S: 'S', A: 'A'}[t_path[0]],) + t_path[1:])

    def __setstate__(self, state):
        self.__ops__ = ({'T': T, 'S': S, 'A': A}[state[0]],) + state[1:]




def _s_first_magic(scope, key, _t):
    """
    enable S.a to do S['a'] or S['a'].val as a special
    case for accessing user defined string variables
    """
    pass




def _assign_op(dest, op, arg, val, path, scope):
    """helper method for doing the assignment on a T operation"""
    pass




T = TType()  # target aka Mr. T aka "this"
S = TType()  # like T, but means grab stuff from Scope, not Target
A = TType()  # like S, but shorthand to assign target to scope

T.__ops__ = (T,)
S.__ops__ = (S,)
A.__ops__ = (A,)

_T_STAR = T.__star__()  # helper constant for Path.from_text
_T_STARSTAR = T.__starstar__()  # helper constant for Path.from_text

UP = make_sentinel('UP')
ROOT = make_sentinel('ROOT')






class Val:
    """Val objects are specs which evaluate to the wrapped *value*.

    >>> target = {'a': {'b': 'c'}}
    >>> spec = {'a': 'a.b', 'readability': Val('counts')}
    >>> pprint(glom(target, spec))
    {'a': 'c', 'readability': 'counts'}

    Instead of accessing ``'counts'`` as a key like it did with
    ``'a.b'``, :func:`~glom.glom` just unwrapped the Val and
    included the value.

    :class:`~glom.Val` takes one argument, the value to be returned.

    .. note::

       :class:`Val` was named ``Literal`` in versions of glom before
       20.7.0. An alias has been preserved for backwards
       compatibility, but reprs have changed.

    """
    def __init__(self, value):
        self.value = value


    def __repr__(self):
        cn = self.__class__.__name__
        return f'{cn}({bbrepr(self.value)})'


Literal = Val  # backwards compat for pre-20.7.0


class ScopeVars:
    """This is the runtime partner of :class:`Vars` -- this is what
    actually lives in the scope and stores runtime values.

    While not part of the importable API of glom, it's half expected
    that some folks may write sepcs to populate and export scopes, at
    which point this type makes it easy to access values by attribute
    access or by converting to a dict.

    """
    def __init__(self, base, defaults):
        self.__dict__ = dict(base)
        self.__dict__.update(defaults)

    def __iter__(self):
        return iter(self.__dict__.items())

    def __repr__(self):
        return f"{self.__class__.__name__}({bbrepr(self.__dict__)})"


class Vars:
    """
    :class:`Vars` is a helper that can be used with **S** in order to
    store shared mutable state.

    Takes the same arguments as :class:`dict()`.

    Arguments here should be thought of the same way as default arguments
    to a function.  Each time the spec is evaluated, the same arguments
    will be referenced; so, think carefully about mutable data structures.
    """
    def __init__(self, base=(), **kw):
        dict(base)  # ensure it is a dict-compatible first arg
        self.base = base
        self.defaults = kw


    def __repr__(self):
        ret = format_invocation(self.__class__.__name__,
                                args=(self.base,) if self.base else (),
                                kwargs=self.defaults,
                                repr=bbrepr)
        return ret


class Let:
    """
    Deprecated, kept for backwards compat. Use S(x='y') instead.

    >>> target = {'data': {'val': 9}}
    >>> spec = (Let(value=T['data']['val']), {'val': S['value']})
    >>> glom(target, spec)
    {'val': 9}

    """
    def __init__(self, **kw):
        if not kw:
            raise TypeError('expected at least one keyword argument')
        self._binding = kw


    def __repr__(self):
        cn = self.__class__.__name__
        return format_invocation(cn, kwargs=self._binding, repr=bbrepr)


class Auto:
    """
    Switch to Auto mode (the default)

    TODO: this seems like it should be a sub-class of class Spec() --
    if Spec() could help define the interface for new "modes" or dialects
    that would also help make match mode feel less duct-taped on
    """
    def __init__(self, spec=None):
        self.spec = spec


    def __repr__(self):
        cn = self.__class__.__name__
        rpr = '' if self.spec is None else bbrepr(self.spec)
        return f'{cn}({rpr})'


class _AbstractIterable(_AbstractIterableBase):
    __metaclass__ = ABCMeta
    @classmethod
    def __subclasshook__(cls, C):
        if C in (str, bytes):
            return False
        return callable(getattr(C, "__iter__", None))


class _ObjStyleKeysMeta(type):
    def __instancecheck__(cls, C):
        return hasattr(C, "__dict__") and hasattr(C.__dict__, "keys")


class _ObjStyleKeys(_ObjStyleKeysMeta('_AbstractKeys', (object,), {})):
    __metaclass__ = _ObjStyleKeysMeta





# handlers are 3-arg callables, with args (spec, target, scope)
# spec is the first argument for convenience in the case
# that the handler is a method of the spec type






class Pipe:
    """Evaluate specs one after the other, passing the result of
    the previous evaluation in as the target of the next spec:

      >>> glom({'a': {'b': -5}}, Pipe('a', 'b', abs))
      5

    Same behavior as ``Auto(tuple(steps))``, but useful for explicit
    usage in other modes.
    """
    def __init__(self, *steps):
        self.steps = steps


    def __repr__(self):
        return self.__class__.__name__ + bbrepr(self.steps)


class TargetRegistry:
    '''
    responsible for registration of target types for iteration
    and attribute walking
    '''
    def __init__(self, register_default_types=True):
        self._op_type_map = {}
        self._op_type_tree = {}  # see _register_fuzzy_type for details
        self._type_cache = {}

        self._op_auto_map = OrderedDict()  # op name to function that returns handler function

        self._register_builtin_ops()

        if register_default_types:
            self._register_default_types()
        return

    def get_handler(self, op, obj, path=None, raise_exc=True):
        """for an operation and object **instance**, obj, return the
        closest-matching handler function, raising UnregisteredTarget
        if no handler can be found for *obj* (or False if
        raise_exc=False)

        """
        pass




    def _register_fuzzy_type(self, op, new_type, _type_tree=None):
        """Build a "type tree", an OrderedDict mapping registered types to
        their subtypes

        The type tree's invariant is that a key in the mapping is a
        valid parent type of all its children.

        Order is preserved such that non-overlapping parts of the
        subtree take precedence by which was most recently added.
        """
        pass


    def register_op(self, op_name, auto_func=None, exact=False):
        """add operations beyond the builtins ('get' and 'iterate' at the time
        of writing).

        auto_func is a function that when passed a type, returns a
        handler associated with op_name if it's supported, or False if
        it's not.

        See glom.core.register_op() for the global version used by
        extensions.
        """
        if not isinstance(op_name, basestring):
            raise TypeError(f'expected op_name to be a text name, not: {op_name!r}')
        if auto_func is None:
            auto_func = lambda t: False
        elif not callable(auto_func):
            raise TypeError(f'expected auto_func to be callable, not: {auto_func!r}')

        # determine support for any previously known types
        known_types = set(sum([list(m.keys()) for m
                               in self._op_type_map.values()], []))
        type_map = self._op_type_map.get(op_name, OrderedDict())
        type_tree = self._op_type_tree.get(op_name, OrderedDict())
        for t in sorted(known_types, key=lambda t: t.__name__):
            if t in type_map:
                continue
            try:
                handler = auto_func(t)
            except Exception as e:
                raise TypeError('error while determining support for operation'
                                ' "%s" on target type: %s (got %r)'
                                % (op_name, t.__name__, e))
            if handler is not False and not callable(handler):
                raise TypeError('expected handler for op "%s" to be'
                                ' callable or False, not: %r' % (op_name, handler))
            type_map[t] = handler

        if not exact:
            for t in known_types:
                self._register_fuzzy_type(op_name, t, _type_tree=type_tree)

        self._op_type_map[op_name] = type_map
        self._op_type_tree[op_name] = type_tree
        self._op_auto_map[op_name] = auto_func



_DEFAULT_SCOPE = ChainMap({})


def glom(target, spec, **kwargs):
    """Access or construct a value from a given *target* based on the
    specification declared by *spec*.

    Accessing nested data, aka deep-get:

    >>> target = {'a': {'b': 'c'}}
    >>> glom(target, 'a.b')
    'c'

    Here the *spec* was just a string denoting a path,
    ``'a.b'``. As simple as it should be. You can also use 
    :mod:`glob`-like wildcard selectors:

    >>> target = {'a': [{'k': 'v1'}, {'k': 'v2'}]}
    >>> glom(target, 'a.*.k')
    ['v1', 'v2']

    In addition to ``*``, you can also use ``**`` for recursive access:

    >>> target = {'a': [{'k': 'v3'}, {'k': 'v4'}], 'k': 'v0'}
    >>> glom(target, '**.k')
    ['v0', 'v3', 'v4']
    
    The next example shows how to use nested data to 
    access many fields at once, and make a new nested structure.

    Constructing, or restructuring more-complicated nested data:

    >>> target = {'a': {'b': 'c', 'd': 'e'}, 'f': 'g', 'h': [0, 1, 2]}
    >>> spec = {'a': 'a.b', 'd': 'a.d', 'h': ('h', [lambda x: x * 2])}
    >>> output = glom(target, spec)
    >>> pprint(output)
    {'a': 'c', 'd': 'e', 'h': [0, 2, 4]}

    ``glom`` also takes a keyword-argument, *default*. When set,
    if a ``glom`` operation fails with a :exc:`GlomError`, the
    *default* will be returned, very much like
    :meth:`dict.get()`:

    >>> glom(target, 'a.xx', default='nada')
    'nada'

    The *skip_exc* keyword argument controls which errors should
    be ignored.

    >>> glom({}, lambda x: 100.0 / len(x), default=0.0, skip_exc=ZeroDivisionError)
    0.0

    Args:
       target (object): the object on which the glom will operate.
       spec (object): Specification of the output object in the form
         of a dict, list, tuple, string, other glom construct, or
         any composition of these.
       default (object): An optional default to return in the case
         an exception, specified by *skip_exc*, is raised.
       skip_exc (Exception): An optional exception or tuple of
         exceptions to ignore and return *default* (None if
         omitted). If *skip_exc* and *default* are both not set,
         glom raises errors through.
       scope (dict): Additional data that can be accessed
         via S inside the glom-spec. Read more: :ref:`scope`.

    It's a small API with big functionality, and glom's power is
    only surpassed by its intuitiveness. Give it a whirl!

    """
    pass


def chain_child(scope):
    """
    used for specs like Auto(tuple), Switch(), etc
    that want to chain their child scopes together

    returns a new scope that can be passed to
    the next recursive glom call, e.g.

    scope[glom](target, spec, chain_child(scope))
    """
    pass


unbound_methods = {type(str.__len__)} #, type(Ref.glomit)])








_DEFAULT_SCOPE.update({
    glom: _glom,
    TargetRegistry: TargetRegistry(register_default_types=True),
})


def register(target_type, **kwargs):
    """Register *target_type* so :meth:`~Glommer.glom()` will
    know how to handle instances of that type as targets.

    Here's an example of adding basic iterabile support for Django's ORM:

    .. code-block:: python

        import glom
        import django.db.models

        glom.register(django.db.models.Manager, iterate=lambda m: m.all())
        glom.register(django.db.models.QuerySet, iterate=lambda qs: qs.all())



    Args:
       target_type (type): A type expected to appear in a glom()
          call target
       get (callable): A function which takes a target object and
          a name, acting as a default accessor. Defaults to
          :func:`getattr`.
       iterate (callable): A function which takes a target object
          and returns an iterator. Defaults to :func:`iter` if
          *target_type* appears to be iterable.
       exact (bool): Whether or not to match instances of subtypes
          of *target_type*.

    .. note::

       The module-level :func:`register()` function affects the
       module-level :func:`glom()` function's behavior. If this
       global effect is undesirable for your application, or
       you're implementing a library, consider instantiating a
       :class:`Glommer` instance, and using the
       :meth:`~Glommer.register()` and :meth:`Glommer.glom()`
       methods instead.

    """
    pass


def register_op(op_name, **kwargs):
    """For extension authors needing to add operations beyond the builtin
    'get', 'iterate', 'keys', 'assign', and 'delete' to the default scope. 
    See TargetRegistry for more details.
    """
    _DEFAULT_SCOPE[TargetRegistry].register_op(op_name, **kwargs)
    return


class Glommer:
    """The :class:`Glommer` type mostly serves to encapsulate type
    registration context so that advanced uses of glom don't need to
    worry about stepping on each other.

    Glommer objects are lightweight and, once instantiated, provide
    a :func:`glom()` method:

    >>> glommer = Glommer()
    >>> glommer.glom({}, 'a.b.c', default='d')
    'd'
    >>> Glommer().glom({'vals': list(range(3))}, ('vals', len))
    3

    Instances also provide :meth:`~Glommer.register()` method for
    localized control over type handling.

    Args:
       register_default_types (bool): Whether or not to enable the
          handling behaviors of the default :func:`glom()`. These
          default actions include dict access, list and iterable
          iteration, and generic object attribute access. Defaults to
          True.

    """
    def __init__(self, **kwargs):
        register_default_types = kwargs.pop('register_default_types', True)
        scope = kwargs.pop('scope', _DEFAULT_SCOPE)

        # this "freezes" the scope in at the time of construction
        self.scope = ChainMap(dict(scope))
        self.scope[TargetRegistry] = TargetRegistry(register_default_types=register_default_types)

    def register(self, target_type, **kwargs):
        """Register *target_type* so :meth:`~Glommer.glom()` will
        know how to handle instances of that type as targets.

        Args:
           target_type (type): A type expected to appear in a glom()
              call target
           get (callable): A function which takes a target object and
              a name, acting as a default accessor. Defaults to
              :func:`getattr`.
           iterate (callable): A function which takes a target object
              and returns an iterator. Defaults to :func:`iter` if
              *target_type* appears to be iterable.
           exact (bool): Whether or not to match instances of subtypes
              of *target_type*.

        .. note::

           The module-level :func:`register()` function affects the
           module-level :func:`glom()` function's behavior. If this
           global effect is undesirable for your application, or
           you're implementing a library, consider instantiating a
           :class:`Glommer` instance, and using the
           :meth:`~Glommer.register()` and :meth:`Glommer.glom()`
           methods instead.

        """
        pass



class Fill:
    """A specifier type which switches to glom into "fill-mode". For the
    spec contained within the Fill, glom will only interpret explicit
    specifier types (including T objects). Whereas the default mode
    has special interpretations for each of these builtins, fill-mode
    takes a lighter touch, making Fill great for "filling out" Python
    literals, like tuples, dicts, sets, and lists.

    >>> target = {'data': [0, 2, 4]}
    >>> spec = Fill((T['data'][2], T['data'][0]))
    >>> glom(target, spec)
    (4, 0)

    As you can see, glom's usual built-in tuple item chaining behavior
    has switched into a simple tuple constructor.

    (Sidenote for Lisp fans: Fill is like glom's quasi-quoting.)

    """
    def __init__(self, spec=None):
        self.spec = spec



    def __repr__(self):
        cn = self.__class__.__name__
        rpr = '' if self.spec is None else bbrepr(self.spec)
        return f'{cn}({rpr})'



class _ArgValuator:
    def __init__(self):
        self.cache = {}

    def mode(self, target, spec, scope):
        """
        similar to FILL, but without function calling;
        useful for default, scope assignment, call/invoke, etc
        """
        pass


def arg_val(target, arg, scope):
    """
    evaluate an argument to find its value
    (arg_val phonetically similar to "eval" -- evaluate as an arg)
    """
    pass
