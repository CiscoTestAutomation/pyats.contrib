from unittest import TestCase, main
from unittest.mock import Mock, patch
from pyats.contrib.creators.netbox import Netbox
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

    @patch('pyats.contrib.creators.netbox.requests.get')
    def test_generate_method(self, mock_request):
        netbox_url = 'http://mocked_url.com'
        def mapper(url, headers=None, verify=None):
            if url == netbox_url + NETBOX_DEVICES_API_CALL:
                json_return = NETBOX_DEVICES_API_RESPONSE
            elif url == netbox_url + NETBOX_VMS_API_CALL:
                json_return = NETBOX_VMS_API_RESPONSE
            return Mock(
                status_code=200,
                json=lambda: json_return
            )
        mock_request.side_effect = mapper
        netbox_creator = Netbox(user_token="0123456789abcdef0123456789abcdef01234567",
                                netbox_url=netbox_url, custom_data_source=None, def_user="test", def_pass="test")
        testbed = netbox_creator._generate()
        self.assertDictEqual(testbed, NETBOX_GENERATED_TESTBED)

if __name__ == '__main__':
    main()
