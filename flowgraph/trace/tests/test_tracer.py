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

from __future__ import absolute_import

from collections import OrderedDict
from textwrap import dedent
import unittest

from flowgraph.core.tests import objects
from ..trace_event import TraceCall, TraceReturn
from ..tracer import Tracer


class TestTracer(unittest.TestCase):
    """ Test the execution tracer.
    """

    def setUp(self):
        """ Create the tracer and set a handler for trace events.
        """
        self.tracer = Tracer()        
        self.events = []
        def handler(changed):
            event = changed['new']
            if event:
                self.events.append(event)
        self.tracer.observe(handler, 'event')
    
    def trace(self, code):
        """ Trace code in environment with test objects.
        """
        env = dict(objects=objects)
        return self.tracer.trace(dedent(code), env=env)
    
    def test_basic_call(self):
        """ Are function calls traced?
        """
        env = self.trace("""
            foo = objects.Foo()
            bar = objects.bar_from_foo(foo, x=1, y=2)
        """)
        
        events = self.events
        self.assertEqual(len(events), 4)
        
        event = events[2]
        self.assertTrue(isinstance(event, TraceCall))
        self.assertTrue(event.atomic)
        self.assertEqual(event.function, objects.bar_from_foo)
        self.assertEqual(event.module_name, objects.__name__)
        self.assertEqual(event.qual_name, 'bar_from_foo')
        self.assertEqual(event.arguments,
                         OrderedDict([('foo',env['foo']), ('x',1), ('y',2)]))
        
        event = events[3]
        self.assertTrue(isinstance(event, TraceReturn))
        self.assertTrue(event.atomic)
        self.assertEqual(event.function, objects.bar_from_foo)
        self.assertEqual(event.module_name, objects.__name__)
        self.assertEqual(event.qual_name, 'bar_from_foo')
    
    def test_basic_return(self):
        """ Are function returns traced?
        """
        env = self.trace("""
            foo = objects.create_foo()
        """)
        
        events = self.events
        self.assertEqual(len(events), 2)
        
        event = events[0]
        self.assertTrue(isinstance(event, TraceCall))
        self.assertTrue(event.atomic)
        self.assertEqual(event.function, objects.create_foo)
        self.assertEqual(event.module_name, objects.__name__)
        self.assertEqual(event.qual_name, 'create_foo')
        self.assertEqual(event.arguments, OrderedDict())
        
        event = events[1]
        self.assertTrue(isinstance(event, TraceReturn))
        self.assertTrue(event.atomic)
        self.assertEqual(event.function, objects.create_foo)
        self.assertEqual(event.module_name, objects.__name__)
        self.assertEqual(event.qual_name, 'create_foo')
        self.assertEqual(event.return_value, env['foo'])
    
    def test_atomic_nested_return(self):
        """ Test that the bodies of atomic functions are not traced.
        """
        env = self.trace("""
            foo = objects.nested_create_foo()
        """)
        
        events = self.events
        self.assertEqual(len(events), 2)
        self.assertTrue(isinstance(events[0], TraceCall))
        self.assertTrue(isinstance(events[1], TraceReturn))
        self.assertTrue(events[0].atomic)
        self.assertTrue(events[1].atomic)
        self.assertEqual(events[0].qual_name, 'nested_create_foo')
        self.assertEqual(events[1].qual_name, 'nested_create_foo')
    
    def test_atomic_higher_order_call(self):
        """ Test that a user-defined function called from within an atomic
        function is not traced.
        """
        env = self.trace("""
            foo = objects.Foo()
            foo.apply(lambda x: objects.Bar(x))
            baz = objects.baz_from_foo(foo)
        """)
        
        events = self.events
        self.assertEqual(len(events), 8)
        self.assertEqual(events[0].qual_name, 'Foo.__init__')
        self.assertEqual(events[2].qual_name, 'Foo.__getattribute__')
        self.assertEqual(events[4].qual_name, 'Foo.apply')
        self.assertEqual(events[6].qual_name, 'baz_from_foo')
    
    def test_getattr(self):
        """ Are attribute getters traced?
        """
        env = self.trace("""
            container = objects.FooContainer()
            foo1 = container.foo_property
            foo2 = container.foo
        """)
        
        events = self.events
        self.assertEqual(len(events), 6)
        self.assertEqual(events[0].qual_name, 'FooContainer.__init__')
        self.assertEqual(events[2].qual_name, 'FooContainer.__getattribute__')
        self.assertEqual(events[3].return_value, foo1)
        self.assertEqual(events[4].qual_name, 'FooContainer.__getattribute__')
        self.assertEqual(events[5].return_value, foo2)
    
    def test_setattr(self):
        """ Are attribute setters traced?
        """
        env = self.trace("""
            container = objects.FooContainer()
            container.foo = objects.Foo()
        """)
        
        events = self.events
        self.assertEqual(len(events), 6)
        self.assertEqual(events[0].qual_name, 'FooContainer.__init__')
        self.assertEqual(events[2].qual_name, 'Foo.__init__')
        self.assertEqual(events[4].qual_name, 'FooContainer.__setattr__')


if __name__ == '__main__':
    unittest.main()
