from unittest import TestCase, main
from pyats.contrib.creators.netbox import Netbox
from pyats.topology import Testbed

class TestNetbox(TestCase):
    def test_missing_arguments(self):
        with self.assertRaises(Exception):
            NetBox()
        with self.assertRaises(Exception):
            NetBox(user_token="abc")
        with self.assertRaises(Exception):
            Netbox(netbox_url="abc")

if __name__ == '__main__':
    main()
