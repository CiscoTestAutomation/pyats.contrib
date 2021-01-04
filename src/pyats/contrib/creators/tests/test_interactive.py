from unittest import TestCase, main, mock
from pyats.contrib.creators.interactive import Interactive
from pyats.topology import Testbed
from pyats.datastructures import Configuration
from pyats.utils import secret_strings

class TestInteractive(TestCase):

    maxDiff = None
    # set default pyats configuration
    secret_strings.cfg = Configuration()

    @mock.patch('builtins.input')
    @mock.patch('getpass.getpass')
    def test_interactive(self, getpass, input_function):
        input_value = [
            "y", "admin", "y", "super", "y", "hostname",
            "123.123.123.123", "ssh", "ios", "n"
        ]
        value = input_value.copy()
        expected = """devices:
  hostname:
    connections:
      cli:
        ip: 123.123.123.123
        protocol: ssh
    credentials:
      default:
        password: super
        username: admin
      enable:
        password: super
    os: ios
    type: ios
"""
        def mock_input(text):
            return value.pop(0)
        input_function.side_effect = mock_input
        getpass.return_value = "super"
        output_file = '/tmp/test.yaml'
        Interactive().to_testbed_file(output_file)
        with open(output_file) as file:
            self.assertEqual(file.read(), expected)
        value = input_value.copy()
        testbed = Interactive().to_testbed_object()
        self.assertTrue(isinstance(testbed, Testbed))
        self.assertIn('hostname', testbed.devices)
        self.assertEqual(testbed.devices['hostname'].os, 'ios')
        self.assertEqual(testbed.devices['hostname'].type, 'ios')
        self.assertIn('cli', testbed.devices['hostname'].connections)
        self.assertEqual('123.123.123.123', 
                        testbed.devices['hostname'].connections.cli.ip)
        self.assertEqual('ssh', 
                        testbed.devices['hostname'].connections.cli.protocol)
        self.assertIn('default', testbed.devices['hostname'].credentials)
        self.assertIn('enable', testbed.devices['hostname'].credentials)
        self.assertEqual('admin', 
                    testbed.devices['hostname'].credentials.default.username)

    @mock.patch('builtins.input')
    @mock.patch('getpass.getpass')
    def test_encode_password(self, getpass, input_function):
        input_value = [
            "y", "admin", "y", "super", "y", "hostname",
            "123.123.123.123", "ssh", "ios", "n"
        ]
        expected = """devices:
  hostname:
    connections:
      cli:
        ip: 123.123.123.123
        protocol: ssh
    credentials:
      default:
        password: '%ENC{w6PDrsORw5nDpQ==}'
        username: admin
      enable:
        password: '%ENC{w6PDrsORw5nDpQ==}'
    os: ios
    type: ios
"""
        def mock_input(text):
            return input_value.pop(0)
        input_function.side_effect = mock_input
        getpass.return_value = "super"
        output_file = '/tmp/test.yaml'
        Interactive(encode_password=True).to_testbed_file(output_file)
        with open(output_file) as file:
            self.assertEqual(file.read(), expected)

    @mock.patch('builtins.input')
    @mock.patch('getpass.getpass')
    def test_add_keys(self, getpass, input_function):
        input_value = [
            "y", "admin", "y", "super", "y", "hostname",
            "123.123.123.123", "ssh", "ios", "opt1", "opt2", "opt3", "n"
        ]
        value = input_value.copy()
        expected = """devices:
  hostname:
    a: opt1
    b: opt2
    c: opt3
    connections:
      cli:
        ip: 123.123.123.123
        protocol: ssh
    credentials:
      default:
        password: super
        username: admin
      enable:
        password: super
    os: ios
    type: ios
"""
        def mock_input(text):
            return value.pop(0)
        input_function.side_effect = mock_input
        getpass.return_value = "super"
        output_file = '/tmp/test.yaml'
        Interactive(add_keys=['a', 'b', 'c']).to_testbed_file(output_file)
        with open(output_file) as file:
            self.assertEqual(file.read(), expected)
        expected = """devices:
  hostname:
    connections:
      cli:
        ip: 123.123.123.123
        protocol: ssh
    credentials:
      default:
        password: super
        username: admin
      enable:
        password: super
    custom:
      w: opt1
      ww: opt2
      www: opt3
    os: ios
    type: ios
"""
        value = input_value.copy()
        Interactive(add_custom_keys=['w', 'ww', 'www']).to_testbed_file(
                                                                    output_file)
        with open(output_file) as file:
            self.assertEqual(file.read(), expected)

    @mock.patch('builtins.input')
    @mock.patch('getpass.getpass')
    def test_two_devices(self, getpass, input_function):
        input_value = [
            "n", "n", "n", "dev1", "123.123.123.123", "superuser", 
            "telnet", "linux", "y", "dev2", "123.123.123.123", "superuser", 
            "telnet", "linux", "n"
        ]
        expected = """devices:
  dev1:
    connections:
      cli:
        ip: 123.123.123.123
        protocol: telnet
    credentials:
      default:
        password: super
        username: superuser
      enable:
        password: super
    os: linux
    type: linux
  dev2:
    connections:
      cli:
        ip: 123.123.123.123
        protocol: telnet
    credentials:
      default:
        password: super
        username: superuser
      enable:
        password: super
    os: linux
    type: linux
"""
        def mock_input(text):
            return input_value.pop(0)
        input_function.side_effect = mock_input
        getpass.return_value = "super"
        output_file = '/tmp/.yaml'
        Interactive().to_testbed_file(output_file)
        with open(output_file) as file:
            self.assertEqual(file.read(), expected)

if __name__ == '__main__':
    main()
