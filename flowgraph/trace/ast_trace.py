# Copyright 2018 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Abstract syntax tree (AST) transformer to trace function calls.
"""
from __future__ import absolute_import

import ast
from collections import OrderedDict
import inspect
import sys
import types
try:
    # Python 3.3+
    from inspect import signature
except ImportError:
    # Python 2.7 to 3.2
    from funcsigs import signature

from .ast_transform import to_attribute, to_call, to_name

# Does `ast.Starred` exist?
ast_has_starred = sys.version_info.major >= 3 and sys.version_info.minor >= 5


def bind_arguments(fun, *args, **kwargs):
    """ Bind arguments to function or method.

    Returns an ordered dictionary mapping argument names to values. Unlike
    `inspect.signature`, the `self` parameter of bound instance methods is
    included as an argument.
    """
    if inspect.ismethod(fun) and not inspect.isclass(fun.__self__):
        # Case 1: Bound instance method, implemented in Python.
        # Reduce to Case 2 below because `Signature.bind()`` excludes `self`
        # argument in bound methods.
        args = (fun.__self__,) + args
        fun = fun.__func__
    
    try:
        # Case 2: Callable implemented in Python.
        sig = signature(fun)
    except ValueError:
        # `inspect.signature()` doesn't work on builtins.
        # https://stackoverflow.com/q/42134927
        pass
    else:
        # Case 2, cont.: If we got a signature, use it and exit.
        bound = sig.bind(*args, **kwargs)
        return bound.arguments
    
    fun_self = getattr(fun, '__self__', None)
    if fun_self is not None and not isinstance(fun_self, types.ModuleType):
        # Case 3: Method implemented in C ("builtin method").
        # Reduce to Case 4 below.
        args = (fun_self,) + args

    # Case 4: Callable implemented in C ("builtin")
    arguments = OrderedDict()
    for i, value in enumerate(args):
        arguments[str(i)] = value
    for key, value in kwargs.items():
        arguments[key] = value
    return arguments


class TraceFunctionCalls(ast.NodeTransformer):
    """ Rewrite AST to trace function and method calls.

    Replaces function and method calls, e.g.

        f(x,y,z=1)
    
    with wrapped calls, e.g.

        trace_return(trace_function(f)(
            trace_argument(x), trace_argument(y), z=trace_argument(1)))
    """

    def __init__(self, tracer):
        super(TraceFunctionCalls, self).__init__()
        self.tracer = to_name(tracer)
    
    def trace_method(self, method):
        return to_attribute(self.tracer, method)
    
    def trace_function(self, func, nargs):
        return to_call(self.trace_method('trace_function'), [
            func, ast.Num(nargs)
        ])
    
    def trace_argument(self, arg_value, arg_name=None, nstars=0):
        # Unpack starred expression in Python 3.5+.
        starred = ast_has_starred and isinstance(arg_value, ast.Starred)
        if starred:
            arg_value = arg_value.value
            nstars = 1
        
        # Create new call.
        args = [ arg_value ]
        if arg_name:
            args += [ ast.Str(arg_name) ]
        keywords = []
        if nstars:
            keywords += [ ast.keyword('nstars', ast.Num(nstars)) ]
        call = to_call(self.trace_method('trace_argument'), args, keywords)

        # Repack starred expression in Python 3.5+.
        if starred:
            call = ast.Starred(call, ast.Load())
        return call
    
    def trace_return(self, return_value):
        return to_call(self.trace_method('trace_return'), [return_value])
    
    def visit_Call(self, call):
        """ Rewrite AST Call node.
        """
        self.generic_visit(call)
        args = [ self.trace_argument(arg) for arg in call.args ]
        keywords = [ ast.keyword(kw.arg, self.trace_argument(
                        kw.value, kw.arg, 2 if kw.arg is None else 0
                     )) for kw in call.keywords ]
        nargs = len(args) + len(keywords)

        # Handle *args and **kwargs in Python 3.4 and lower.
        starargs, kwargs = None, None
        if not ast_has_starred:
            if call.starargs is not None:
                starargs = self.trace_argument(call.starargs, nstars=1)
                nargs += 1
            if call.kwargs is not None:
                kwargs = self.trace_argument(call.kwargs, nstars=2)
                nargs += 1

        return self.trace_return(
            to_call(self.trace_function(call.func, nargs),
                    args, keywords, starargs, kwargs)
        )
