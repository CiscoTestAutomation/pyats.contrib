import os
import shutil
import xlwt

from pyats.contrib.creators.file import File
from unittest import TestCase, main
from pyats.topology import Testbed
from pyats.datastructures import Configuration
from pyats.utils import secret_strings

class TestFile(TestCase):

    # set default pyats configuration
    secret_strings.cfg = Configuration()

    def setUp(self):
        self.csv_file = ("hostname,ip,username,password,protocol,os,"
        "custom:opt1,custom:opt2\nnx-osv-1,172.25.192.90,admin,admin,"
        "telnet,nxos,ss1,ss2")
        self.expected = """devices:
  nx-osv-1:
    connections:
      cli:
        ip: 172.25.192.90
        protocol: telnet
    credentials:
      default:
        password: admin
        username: admin
      enable:
        password: admin
    custom:
      opt1: ss1
      opt2: ss2
    os: nxos
    type: nxos
"""
        self.expected_encoded = """devices:
  nx-osv-1:
    connections:
      cli:
        ip: 172.25.192.90
        protocol: telnet
    credentials:
      default:
        password: '%ENC{w5HDncOOw53DoQ==}'
        username: admin
      enable:
        password: '%ENC{w5HDncOOw53DoQ==}'
    custom:
      opt1: ss1
      opt2: ss2
    os: nxos
    type: nxos
"""
        self.test_csv = "/tmp/test.csv"
        self.test_excel = "/tmp/test.xls"
        self.output = "/tmp/testbed.yaml"
        with open(self.test_csv, "w") as csv:
            csv.write(self.csv_file)
        
    def test_no_arguments(self):
        with self.assertRaises(Exception): 
            File()

    def test_csv_file(self):
        creator = File(path=self.test_csv)
        creator.to_testbed_file(self.output)
        testbed = creator.to_testbed_object()
        self.assertTrue(os.path.isfile(self.output))
        with open(self.output) as file: 
            self.assertEqual(file.read(), self.expected)
        self.assertTrue(isinstance(testbed, Testbed))
        self.assertIn('nx-osv-1', testbed.devices)
        self.assertEqual('ss1', testbed.devices['nx-osv-1'].custom.get('opt1'))
        self.assertEqual('ss2', testbed.devices['nx-osv-1'].custom.get('opt2'))
        self.assertEqual(testbed.devices['nx-osv-1'].os, 'nxos')
        self.assertEqual(testbed.devices['nx-osv-1'].type, 'nxos')
        self.assertIn('cli', testbed.devices['nx-osv-1'].connections)
        self.assertEqual('172.25.192.90', 
                        testbed.devices['nx-osv-1'].connections.cli.ip)
        self.assertEqual('telnet', 
                        testbed.devices['nx-osv-1'].connections.cli.protocol)
        self.assertIn('default', testbed.devices['nx-osv-1'].credentials)
        self.assertIn('enable', testbed.devices['nx-osv-1'].credentials)
        self.assertEqual('admin', 
                    testbed.devices['nx-osv-1'].credentials.default.username)

    def test_encode_password(self):
        File(path=self.test_csv, encode_password=True).to_testbed_file(
                                                                    self.output)
        with open(self.output) as file: 
            self.assertEqual(file.read(), self.expected_encoded)

    def test_directory(self):
        directory = '/tmp/sources'
        subdir = '/tmp/sources/subdir'
        outdir = '/tmp/testbeds'
        outsubdir = '/tmp/testbeds/subdir'
        if os.path.isdir(directory):
            shutil.rmtree(directory)
        if os.path.isdir(outdir):
            shutil.rmtree(outdir)
        os.mkdir(directory)
        os.mkdir(subdir)
        for i in range(2):
            with open('{}/{}.csv'.format(directory, i), 'w') as file:
                file.write(self.csv_file)
            with open('{}/{}.csv'.format(subdir, i), 'w') as file:
                file.write(self.csv_file)
        creator = File(path=directory)
        creator.to_testbed_file(outdir)
        self.assertEqual(len(creator.to_testbed_object()), 2)
        self.assertTrue(os.path.isfile('{}/0.yaml'.format(outdir)))
        self.assertTrue(os.path.isfile('{}/1.yaml'.format(outdir)))
        with open('{}/0.yaml'.format(outdir)) as file: 
            self.assertEqual(file.read(), self.expected)
        with open('{}/1.yaml'.format(outdir)) as file: 
            self.assertEqual(file.read(), self.expected)
        shutil.rmtree(outdir)
        creator = File(path=directory, recurse=True)
        creator.to_testbed_file(outdir)
        self.assertEqual(len(creator.to_testbed_object()), 4)
        self.assertTrue(os.path.isfile('{}/0.yaml'.format(outsubdir)))
        self.assertTrue(os.path.isfile('{}/1.yaml'.format(outsubdir)))
        with open('{}/0.yaml'.format(outsubdir)) as file: 
            self.assertEqual(file.read(), self.expected)
        with open('{}/1.yaml'.format(outsubdir)) as file: 
            self.assertEqual(file.read(), self.expected)

    def test_excel_load(self):
        wb = xlwt.Workbook()
        ws = wb.add_sheet('testbed')
        for i, k in enumerate([
            'hostname', 'ip', 'username', 'password', 'protocol', 'os',
            'custom:opt1', 'custom:opt2'
        ]):
            ws.write(0, i, k)
        for i, k in enumerate([
            'nx-osv-1', '172.25.192.90', 'admin', 'admin', 'telnet', 'nxos',
            'ss1', 'ss2'
        ]):
            ws.write(1, i, k)
        wb.save(self.test_excel)
        File(path=self.test_excel, encode_password=True).to_testbed_file(
                                                                    self.output)
        with open(self.output) as file: 
            self.assertEqual(file.read(), self.expected_encoded)

if __name__ == '__main__':
    main()
