from unittest import TestCase, main
import responses
from pyats.contrib.creators.netbox import Netbox
from pyats.topology import Testbed
from pyats.contrib.tests.creators.netbox_mock_data.constants import NETBOX_DEVICES_API_CALL, \
    NETBOX_DEVICES_API_RESPONSE, NETBOX_VMS_API_CALL, NETBOX_VMS_API_RESPONSE, NETBOX_GENERATED_TESTBED


class TestNetbox(TestCase):
    def test_missing_arguments(self):
        with self.assertRaises(Exception):
            NetBox()
        with self.assertRaises(Exception):
            NetBox(user_token="abc")
        with self.assertRaises(Exception):
            Netbox(netbox_url="abc")

    @responses.activate
    def test_generate_method(self):
        responses.add(responses.GET, "http://mocked_url.com" + NETBOX_DEVICES_API_CALL,
                      json=NETBOX_DEVICES_API_RESPONSE, status=200)
        responses.add(responses.GET, "http://mocked_url.com" + NETBOX_VMS_API_CALL,
                      json=NETBOX_VMS_API_RESPONSE, status=200)

        netbox_creator = Netbox(user_token="0123456789abcdef0123456789abcdef01234567",
                                netbox_url="http://mocked_url.com", custom_data_source=None, def_user="test", def_pass="test")

        testbed = netbox_creator._generate()

        self.assertDictEqual(testbed, NETBOX_GENERATED_TESTBED)

if __name__ == '__main__':
    main()
