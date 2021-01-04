
import os
import sys

from pyats.contrib.creators.creator import TestbedCreator
from unittest import TestCase, main
from pyats.topology import Testbed
from pyats.topology.loader.base import BaseTestbedLoader

class TestCreator(TestCase):
    def test_arguments(self):
        class Test(TestbedCreator):
            def _init_arguments(self):
                return {
                    "required": ["a"],
                    "optional": {
                        "b" : 12,
                        "c": [1, 2, 4]
                    }
                }
        with self.assertRaises(Exception):
            Test()
        with self.assertRaises(Exception):
            Test(b=2, c=4)
        test = Test(a=5)
        self.assertTrue(hasattr(test, '_a'))
        self.assertTrue(hasattr(test, '_b'))
        self.assertTrue(hasattr(test, '_c'))
        self.assertEqual(test._a, 5)
        self.assertEqual(test._b, 12)
        self.assertEqual(test._c, [1, 2, 4])
        test = Test(a=1, b=2, c=3)
        self.assertEqual(test._a, 1)
        self.assertEqual(test._b, 2)
        self.assertEqual(test._c, 3)

    def test_generate(self):
        with self.assertRaises(NotImplementedError):
            TestbedCreator()._generate()
        class Test(TestbedCreator):
            pass
        with self.assertRaises(NotImplementedError):
            Test().to_testbed_file('/tmp/test')
        with self.assertRaises(NotImplementedError):
            Test().to_testbed_object()
        
    def test_output_to_folder(self):
        folder = '/tmp/testfolder'
        if not os.path.isdir(folder):
            os.mkdir(folder)
        with self.assertRaises(Exception):
            TestbedCreator().to_testbed_file(folder)

    def test_cli_arguments(self):
        class Test(TestbedCreator):
            def _init_arguments(self):
                return {
                    "required": ["my_arg", "password"],
                    "optional": {
                        "b" : 'bc',
                        "time": 'on'
                    }
                }
        sys.argv = ["creator"]
        with self.assertRaises(Exception):
            Test()
        sys.argv = ["creator", "--my-arg=abc"]
        with self.assertRaises(Exception):
            Test()
        sys.argv = ["creator", "--my-arg=abc", "--password=admin"]
        test = Test()
        self.assertEqual(test._my_arg, 'abc')
        self.assertEqual(test._password, 'admin')
        self.assertEqual(test._b, 'bc')
        self.assertEqual(test._time, 'on')
        sys.argv = ["creator", "--my-arg", "--password"]
        test = Test()
        self.assertTrue(test._my_arg)
        self.assertTrue(test._password)
        sys.argv = ["creator", "--my-arg", "123", "--password", "abc"]
        test = Test()
        self.assertEqual(test._my_arg, '123')
        self.assertEqual(test._password, 'abc')
        sys.argv = ["creator", "--my-arg=a", "--password", "b"]
        test = Test()
        self.assertEqual(test._my_arg, 'a')
        self.assertTrue(test._password, 'b')
        sys.argv = ["creator", "--my-arg=a", "--password=b",
                                                        "--b=hi", "--time=55"]
        test = Test()
        self.assertEqual(test._my_arg, 'a')
        self.assertEqual(test._password, 'b')
        self.assertEqual(test._b, 'hi')
        self.assertEqual(test._time, '55')

    def test_mixed_arguments(self):
        class Test(TestbedCreator):
            def _init_arguments(self):
                return {
                    "required": ["my_arg", "password"]
                }
        sys.argv = ["creator", "--my-arg=abc"]
        test = Test(password="123")
        self.assertEqual(test._password, "123")
        self.assertEqual(test._my_arg, "abc")

    def test_cli_list(self):
        class Test(TestbedCreator):
            def _init_arguments(self):
                self._cli_list_arguments.append('--items')
                return {
                    "required": ["items", "a", "b"]
                }
        sys.argv = ["creator", "--items", "1", "2", "3", "--a=1", "--b=1"]
        test = Test()
        self.assertEqual(test._items, ['1', '2', '3'])
        self.assertEqual(test._a, '1')
        self.assertEqual(test._b, '1')
        sys.argv = ["creator", "--a=1", "--items", "1", "2", "--b=1"]
        test = Test()
        self.assertEqual(test._items, ['1', '2'])
        self.assertEqual(test._a, '1')
        self.assertEqual(test._b, '1')
        sys.argv = ["creator", "--a=1", "--b=1", "--items", "aa", "bc", "cc"]
        test = Test()
        self.assertEqual(test._items, ['aa', 'bc', 'cc'])
        self.assertEqual(test._a, '1')
        self.assertEqual(test._b, '1')
        sys.argv = ["creator", "--a", "1", "--b", "1", "--items", "aa", "bc", "cc"]
        test = Test()
        self.assertEqual(test._items, ['aa', 'bc', 'cc'])
        self.assertEqual(test._a, '1')
        self.assertEqual(test._b, '1')
        sys.argv = ["creator", "--a=1", "--items", "--b=1"]
        test = Test()
        self.assertEqual(test._items, [])
        self.assertEqual(test._a, '1')
        self.assertEqual(test._b, '1')

    def test_cli_replacements(self):
        class Test(TestbedCreator):
            def _init_arguments(self):
                self._cli_replacements.setdefault('-r', ('recurse', True))
                self._cli_replacements.setdefault('--hello', ('h', 'w'))
                return {
                    "required": ["recurse"],
                    "optional": {
                        "h": "abc"
                    }
                }
        sys.argv = ["creator", "-r"]
        test = Test()
        self.assertTrue(test._recurse)
        self.assertEqual(test._h, "abc")
        sys.argv = ["creator", "-r", "--hello"]
        test = Test()
        self.assertEqual(test._h, 'w')

    def test_inheritance(self):
        self.assertTrue(issubclass(TestbedCreator, BaseTestbedLoader))

    def test_to_testbed_file_none(self):
        output = '/tmp/test'
        class Test(TestbedCreator):
            def _generate(self):
                return None
        if os.path.isfile(output):
            os.remove(output)
        Test().to_testbed_file(output)
        self.assertFalse(os.path.isfile(output))

    def test_to_testbed_object(self):
        class Test(TestbedCreator):
            def _generate(self):
                return None
        self.assertIsNone(Test().to_testbed_object())
        class Test(TestbedCreator):
            def _generate(self):
                return {}
        self.assertTrue(isinstance(Test().to_testbed_object(), Testbed))

    def test_load(self):
        class Test(TestbedCreator):
            def _generate(self):
                return {}
        self.assertTrue(isinstance(Test().to_testbed_object(), Testbed))

if __name__ == '__main__':
    main()        
