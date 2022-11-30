from unittest import TestCase, main, mock
from pyats.contrib.creators.yamltemplate import Yamltemplate
from pyats.topology import Testbed
import tempfile
import os


class TestYamltemplate(TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmpl_str = """devices:
  %{device_name}:
    connections:
      cli:
        ip: %mgmt_ip
        protocol: ssh
    credentials:
      default:
        username: %username
        password: %password
    os: %os
"""

        _, cls.template_file = tempfile.mkstemp(text=True)
        with open(cls.template_file, 'w') as file:
            file.write(cls.tmpl_str)

        cls.expected = """devices:
  hostname:
    connections:
      cli:
        ip: 123.123.123.123
        protocol: ssh
    credentials:
      default:
        password: super
        username: admin
    os: iosxe
"""

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.template_file)
        except OSError:
            pass

    def setUp(self):
        _, self.output_file = tempfile.mkstemp(text=True)
        _, self.values_file = tempfile.mkstemp(text=True)

    def tearDown(self):
        try:
            os.remove(self.output_file)
            os.remove(self.values_file)
        except OSError:
            pass

    @mock.patch('builtins.input')
    def test_interactive(self, input_function):
        input_value = ["hostname", "123.123.123.123", "admin", "super", "iosxe"]
        value = input_value.copy()

        def mock_input(text):
            return value.pop(0)
        input_function.side_effect = mock_input
        Yamltemplate(template_file=self.template_file).to_testbed_file(self.output_file)
        with open(self.output_file) as file:
            self.assertEqual(file.read(), self.expected)
        os.remove(self.output_file)
        value = input_value.copy()
        testbed = Yamltemplate(template_file=self.template_file).to_testbed_object()
        self.assertTrue(isinstance(testbed, Testbed))
        self.assertIn('hostname', testbed.devices)
        self.assertEqual(testbed.devices['hostname'].os, 'iosxe')
        self.assertIn('cli', testbed.devices['hostname'].connections)
        self.assertEqual('123.123.123.123',  testbed.devices['hostname'].connections.cli.ip)
        self.assertEqual('ssh', testbed.devices['hostname'].connections.cli.protocol)
        self.assertIn('default', testbed.devices['hostname'].credentials)
        self.assertEqual('admin', testbed.devices['hostname'].credentials.default.username)

    @mock.patch('builtins.input')
    def test_interactive_with_values_file(self, input_function):
        input_value = ["", "", "admin", "super", "iosxe"]
        value = input_value.copy()

        def mock_input(text):
            return value.pop(0)
        input_function.side_effect = mock_input
        values = """device_name: hostname
mgmt_ip: 123.123.123.123
"""
        with open(self.values_file, 'w') as file:
            file.write(values)
        Yamltemplate(template_file=self.template_file, value_file=self.values_file).to_testbed_file(self.output_file)
        with open(self.output_file) as file:
            self.assertEqual(file.read(), self.expected)
        os.remove(self.output_file)
        value = input_value.copy()
        testbed = Yamltemplate(template_file=self.template_file, value_file=self.values_file).to_testbed_object()
        self.assertTrue(isinstance(testbed, Testbed))
        self.assertIn('hostname', testbed.devices)
        self.assertEqual(testbed.devices['hostname'].os, 'iosxe')
        self.assertIn('cli', testbed.devices['hostname'].connections)
        self.assertEqual('123.123.123.123',  testbed.devices['hostname'].connections.cli.ip)
        self.assertEqual('ssh', testbed.devices['hostname'].connections.cli.protocol)
        self.assertIn('default', testbed.devices['hostname'].credentials)
        self.assertEqual('admin', testbed.devices['hostname'].credentials.default.username)

    def test_values_file_noprompt(self):
        values = """device_name: hostname
mgmt_ip: 123.123.123.123
username: admin
password: super
os: iosxe
"""
        with open(self.values_file, 'w') as file:
            file.write(values)
        Yamltemplate(template_file=self.template_file,
                     value_file=self.values_file,
                     noprompt=True).to_testbed_file(self.output_file)
        with open(self.output_file) as file:
            self.assertEqual(file.read(), self.expected)
        testbed = Yamltemplate(template_file=self.template_file,
                               value_file=self.values_file,
                               noprompt=True).to_testbed_object()
        self.assertTrue(isinstance(testbed, Testbed))
        self.assertIn('hostname', testbed.devices)
        self.assertEqual(testbed.devices['hostname'].os, 'iosxe')
        self.assertIn('cli', testbed.devices['hostname'].connections)
        self.assertEqual('123.123.123.123',  testbed.devices['hostname'].connections.cli.ip)
        self.assertEqual('ssh', testbed.devices['hostname'].connections.cli.protocol)
        self.assertIn('default', testbed.devices['hostname'].credentials)
        self.assertEqual('admin', testbed.devices['hostname'].credentials.default.username)

    def test_missing_keys(self):
        values = """device_name: hostname
mgmt_ip: 123.123.123.123
username: admin
password: super
"""
        with open(self.values_file, 'w') as file:
            file.write(values)
        with self.assertRaises(Exception):
            Yamltemplate(template_file=self.template_file,
                         value_file=self.values_file,
                         noprompt=True)._generate()

    def test_no_values_file_noprompt(self):
        with self.assertRaises(Exception):
            Yamltemplate(template_file=self.template_file, noprompt=True)._generate()

    def test_delimiter(self):
        delimiter = '$'
        _, template_file = tempfile.mkstemp(text=True)
        with open(template_file, 'w') as file:
            file.write(self.tmpl_str.replace('%', delimiter))

        values = """device_name: hostname
mgmt_ip: 123.123.123.123
username: admin
password: super
os: iosxe
"""
        with open(self.values_file, 'w') as file:
            file.write(values)
        Yamltemplate(template_file=template_file,
                     value_file=self.values_file,
                     noprompt=True,
                     delimiter=delimiter).to_testbed_file(self.output_file)
        with open(self.output_file) as file:
            self.assertEqual(file.read(), self.expected)

        try:
            os.remove(template_file)
        except OSError:
            pass


if __name__ == '__main__':
    main()
