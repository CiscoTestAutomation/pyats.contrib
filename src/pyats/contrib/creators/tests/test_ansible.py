import unittest
from unittest import TestCase, main
from pyats.topology import Testbed
from pyats.datastructures import Configuration
from pyats.utils import secret_strings

def check_ansible_installed():
    try:
        global Ansible
        from pyats.contrib.creators.ansible import Ansible
    except ImportError:
        return True
    return False  

@unittest.skipIf(check_ansible_installed(), 'ansible package is not installed')
class TestAnsible(TestCase):

    maxDiff = None
    # set default pyats configuration
    secret_strings.cfg = Configuration()

    def setUp(self):
        self.inventory = """[all:vars]
ansible_connection=network_cli

[iosxe]
R1_xe ansible_host=172.16.1.228
R2_xr ansible_host=172.16.1.229
R3_nx ansible_host=172.16.1.230

[iosxe:vars]
ansible_become=yes
ansible_become_method=enable
ansible_network_os=ios
ansible_user=admin
ansible_ssh_pass=Cisc0123
ansible_become_pass=Cisc0123
"""
        self.inventory_file = "/tmp/inventory.ini"
        self.output = "/tmp/output"
        with open(self.inventory_file, "w") as file:
            file.write(self.inventory)

    def test_no_arguments(self):
        with self.assertRaises(Exception):
            Ansible()
        with self.assertRaises(Exception):
            Ansible(encode_password=True)

    def test_ansible(self):
        expected = """devices:
  R1_xe:
    alias: R1_xe
    connections:
      cli:
        ip: 172.16.1.228
        protocol: ssh
      enable:
        password: Cisc0123
    credentials:
      default:
        password: Cisc0123
        username: admin
    os: ios
    platform: ios
    type: iosxe
  R2_xr:
    alias: R2_xr
    connections:
      cli:
        ip: 172.16.1.229
        protocol: ssh
      enable:
        password: Cisc0123
    credentials:
      default:
        password: Cisc0123
        username: admin
    os: ios
    platform: ios
    type: iosxe
  R3_nx:
    alias: R3_nx
    connections:
      cli:
        ip: 172.16.1.230
        protocol: ssh
      enable:
        password: Cisc0123
    credentials:
      default:
        password: Cisc0123
        username: admin
    os: ios
    platform: ios
    type: iosxe
"""
        creator = Ansible(inventory_name=self.inventory_file)
        creator.to_testbed_file(self.output)
        with open(self.output) as file:
            self.assertEqual(file.read(), expected)
        testbed = creator.to_testbed_object()
        self.assertTrue(isinstance(testbed, Testbed))
        self.assertIn('R1_xe', testbed.devices)
        self.assertIn('R2_xr', testbed.devices)
        self.assertIn('R3_nx', testbed.devices)
        self.assertEqual(testbed.devices['R1_xe'].os, 'ios')
        self.assertEqual(testbed.devices['R1_xe'].type, 'iosxe')
        self.assertEqual(testbed.devices['R1_xe'].platform, 'ios')
        self.assertEqual(testbed.devices['R2_xr'].os, 'ios')
        self.assertEqual(testbed.devices['R2_xr'].type, 'iosxe')
        self.assertEqual(testbed.devices['R2_xr'].platform, 'ios')
        self.assertEqual(testbed.devices['R3_nx'].os, 'ios')
        self.assertEqual(testbed.devices['R3_nx'].type, 'iosxe')
        self.assertEqual(testbed.devices['R3_nx'].platform, 'ios')
        self.assertIn('cli', testbed.devices['R1_xe'].connections)
        self.assertIn('cli', testbed.devices['R2_xr'].connections)
        self.assertIn('cli', testbed.devices['R3_nx'].connections)
        self.assertEqual('172.16.1.228',
                                    testbed.devices['R1_xe'].connections.cli.ip)
        self.assertEqual('172.16.1.229',
                                    testbed.devices['R2_xr'].connections.cli.ip)
        self.assertEqual('172.16.1.230',
                                    testbed.devices['R3_nx'].connections.cli.ip)
        self.assertEqual('ssh', 
                            testbed.devices['R1_xe'].connections.cli.protocol)
        self.assertEqual('ssh', 
                            testbed.devices['R2_xr'].connections.cli.protocol)
        self.assertEqual('ssh', 
                            testbed.devices['R3_nx'].connections.cli.protocol)
        self.assertIn('default', testbed.devices['R1_xe'].credentials)
        self.assertEqual('admin', 
                        testbed.devices['R1_xe'].credentials.default.username)
        self.assertIn('default', testbed.devices['R2_xr'].credentials)
        self.assertEqual('admin', 
                        testbed.devices['R2_xr'].credentials.default.username)
        self.assertIn('default', testbed.devices['R3_nx'].credentials)
        self.assertEqual('admin', 
                        testbed.devices['R3_nx'].credentials.default.username)

    def test_encode_password(self):
        expected = """devices:
  R1_xe:
    alias: R1_xe
    connections:
      cli:
        ip: 172.16.1.228
        protocol: ssh
      enable:
        password: '%ENC{wrPDosOUw5fCo8KQwpbCmA==}'
    credentials:
      default:
        password: '%ENC{wrPDosOUw5fCo8KQwpbCmA==}'
        username: admin
    os: ios
    platform: ios
    type: iosxe
  R2_xr:
    alias: R2_xr
    connections:
      cli:
        ip: 172.16.1.229
        protocol: ssh
      enable:
        password: '%ENC{wrPDosOUw5fCo8KQwpbCmA==}'
    credentials:
      default:
        password: '%ENC{wrPDosOUw5fCo8KQwpbCmA==}'
        username: admin
    os: ios
    platform: ios
    type: iosxe
  R3_nx:
    alias: R3_nx
    connections:
      cli:
        ip: 172.16.1.230
        protocol: ssh
      enable:
        password: '%ENC{wrPDosOUw5fCo8KQwpbCmA==}'
    credentials:
      default:
        password: '%ENC{wrPDosOUw5fCo8KQwpbCmA==}'
        username: admin
    os: ios
    platform: ios
    type: iosxe
""" 
        creator = Ansible(inventory_name=self.inventory_file, 
                                                        encode_password=True)
        creator.to_testbed_file(self.output)
        with open(self.output) as file:
            self.assertEqual(file.read(), expected)

if __name__ == '__main__':
    main()
