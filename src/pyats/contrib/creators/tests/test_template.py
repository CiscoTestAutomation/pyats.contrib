import xlrd

from unittest import TestCase, main
from pyats.topology import Testbed
from pyats.contrib.creators.template import Template


class TestTemplate(TestCase):
    test_csv = '/tmp/test.csv'
    test_excel = '/tmp/test.xls'

    def test_csv_template(self):
        expected = "hostname,ip,username,password,protocol,os\n"
        Template().to_testbed_file(self.test_csv)
        with open(self.test_csv) as file:
            self.assertEqual(file.read(), expected)

    def test_excel_template(self):
        Template().to_testbed_file(self.test_excel)
        expected = ['hostname', 'ip', 'username', 'password', 'protocol', 'os']
        ws = xlrd.open_workbook(self.test_excel).sheet_by_index(0)
        keys = ws.row_values(0)
        self.assertEqual(expected, keys)
        
    def test_to_testbed_object(self):
        self.assertTrue(isinstance(Template().to_testbed_object(), Testbed))

    def test_add_keys(self):
        Template(add_keys=['a', 'b' ,'c']).to_testbed_file(self.test_csv)
        expected = "hostname,ip,username,password,protocol,os,a,b,c\n"
        with open(self.test_csv) as file:
            self.assertEqual(file.read(), expected)
        Template(add_custom_keys=['a', 'b' ,'c']).to_testbed_file(self.test_csv)
        expected = ("hostname,ip,username,password,protocol,os,custom:a,"
                    "custom:b,custom:c\n")
        with open(self.test_csv) as file:
            self.assertEqual(file.read(), expected)

if __name__ == '__main__':
    main()
