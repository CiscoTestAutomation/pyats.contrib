import requests 
import copy
import logging

from .creator import TestbedCreator

logger = logging.getLogger(__name__)

class Netbox(TestbedCreator):
    """ Netbox class (TestbedCreator)

    Creator for the 'netbox' source. Retrieves device data from a hosted Netbox
    instance via REST API and converts them to either a testbed file or testbed
    object. Will prompt user for device credentials.

    Args:
        netbox_url ('str'): The URL to the Netbox instance.
        user_token ('str'): The REST API access token. Can be found under your 
            profile and in the API Tokens tab.
        encode_password (bool) default=False: Should generated testbed encode 
            its passwords.
        topology (bool) default=False: Do not generate topology data by default, 
        verify (bool) default=True: Should requests library validate SSL cert for netbox
        url_filter ('str') default=None: Netbox URL filter string, example: 'status=active&site=test_site'
        def_user ('str') default=None: Set the username for all devices
        def_pass ('str') default=None: Set the password for all devices
        host_upper (bool) default=False: Store hostname in upper case (to match the prompt)

    CLI Argument        |  Class Argument
    ---------------------------------------------
    --netbox-url=value  |  netbox_url=value
    --user-token=value  |  user_token=value
    --encode-password   |  encode_password=True
    --topology          |  topology=True
    --verify=False      |  verify=False
    --host_upper=True   |  host_upper=True
    --url_filter=value  |  url_filter=value
    --def_user=value    |  def_user=value
    --def_pass=value    |  def_pass=value
    --tag_telnet=value  |  tag_telnet=value

    pyATS Examples:
        pyats create testbed netbox --output=out --netbox-url=https://netbox.com
        --user-token=72830d67beff4ae178b94d8f781842408df8069d

    Examples:
        # Create testbed from Netbox source
        creator = Netbox(user_token="72830d67", netbox_url="https://netbox.com")
        creator.to_testbed_file("testbed.yaml")
        creator.to_testbed_object()

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        return {
            'required': ['netbox_url', 'user_token'],
            'optional': {
                'encode_password': False,
                'topology': False,
                'verify': True,
                'host_upper': False,
                'url_filter': None,
                'def_user': None,
                'def_pass': None,
                'tag_telnet': None
            }
        }

    def _parse_response(self, response, return_property):
        """ Helper to parse JSON response from HTTP requests.

        Args:
            response ('response'): The response object obtained after 
                HTTP request.
            return_property ('str'): Any filtering that will be applied after 
                parsing the response.

        Returns:
            dict: The response JSON in dictionary form or none if response 
                is invalid.

        """
        response = None if not response else response.json()

        if response and return_property:
            return response[return_property]

        return response

    def _get_request(self, url, headers=None, return_property=None):
        """ Helper to send GET request and returns the response JSON in 
            dictionary form.

        Args:
            url ('str'): URL of where to send the GET request to.
            headers ('dict'): The headers used in the HTTP request.
            return_property ('str'): Any filtering applied to the dictionary
                after parsing the JSON.

        Returns:
            dict: The response JSON in dictionary form.
    
        """
        try:
            response = None

            if not headers:
                response = requests.get(url, verify=self._verify)
            else:
                response = requests.get(url, headers=headers, verify=self._verify)
            
            results = self._parse_response(response, return_property)

            while "next" in response.json().keys() and response.json()["next"]:
                next_url = response.json()["next"]
                if not headers:
                    response = requests.get(next_url, verify=self._verify)
                else:
                    response = requests.get(next_url, headers=headers, verify=self._verify)
                
                results += self._parse_response(response, return_property)

            return results
        except:
            return None

    def _format_url(self, base, route):
        """ Helper to join the base URL and its route.

        Args:
            base ('str'): The base of the URL.
            route ('dict'): The URL route.

        Returns:
            str: The joined URL.
        
        """
        return "{}{}{}".format(base, "" if base[-1] == "/" else "/", route)

    def _set_value_if_exists(self, container, key, entry):
        """ Helper to set value in dictionary if given entry
            is not none.

        Args:
            container ('dict'): Where to insert the new key value pair. 
            key ('str'): The key that the entry corresponds to.
            entry ('str'): The value to be added.

        Returns:
            bool: Whether or not the entry is inserted.
        
        """
        if not entry is None:
            container.setdefault(key, entry)

            return True
        
        return False

    def _parse_os(self, os):
        """ Helper to parse the OS type.

        Args:
            os ('str'): The input os type.

        Returns:
            str: The OS type if it exists or None if it cannot
                be found in list of valid OS.
    
        """
        valid_os = ["com", "asa", "dnac", "ios-xe", "ios-xr",
            "iosxe", "iosxr", "ios", "junos", "linux", "nxos", "nx-os", "yang", 
            "ftd"]

        for valid in valid_os:
            if os and valid in os.lower():
                #ftd is a deprecated platform in pyats, change to fxos
                if valid == "ftd":
                   return "fxos"
                return valid.replace("-", "")
        
        return None

    def _format_type(self, interface_name, interface_type): 
        """ Helper to parse the interface type.

        Args:
            interface_type ('str'): The input interface type.
            interface_name ('str'): The input interface name from Netbox.
            interface_type ('str'): The input interface type from Netbox.

        Returns:
            str: The interface type if it exists or none if it 
            cannot be found in list of valid types.
    
        """
        # for reference: available at /api/dcim/_choices/interface:type
        netbox_interface_types = [
            {
                "value": 0,
                "label": "Virtual"
            },
            {
                "value": 200,
                "label": "Link Aggregation Group (LAG)"
            },
            {
                "value": 800,
                "label": "100BASE-TX (10/100ME)"
            },
            {
                "value": 1000,
                "label": "1000BASE-T (1GE)"
            },
            {
                "value": 1120,
                "label": "2.5GBASE-T (2.5GE)"
            },
            {
                "value": 1130,
                "label": "5GBASE-T (5GE)"
            },
            {
                "value": 1150,
                "label": "10GBASE-T (10GE)"
            },
            {
                "value": 1170,
                "label": "10GBASE-CX4 (10GE)"
            },
            {
                "value": 1050,
                "label": "GBIC (1GE)"
            },
            {
                "value": 1100,
                "label": "SFP (1GE)"
            },
            {
                "value": 1200,
                "label": "SFP+ (10GE)"
            },
            {
                "value": 1300,
                "label": "XFP (10GE)"
            },
            {
                "value": 1310,
                "label": "XENPAK (10GE)"
            },
            {
                "value": 1320,
                "label": "X2 (10GE)"
            },
            {
                "value": 1350,
                "label": "SFP28 (25GE)"
            },
            {
                "value": 1400,
                "label": "QSFP+ (40GE)"
            },
            {
                "value": 1420,
                "label": "QSFP28 (50GE)"
            },
            {
                "value": 1500,
                "label": "CFP (100GE)"
            },
            {
                "value": 1510,
                "label": "CFP2 (100GE)"
            },
            {
                "value": 1650,
                "label": "CFP2 (200GE)"
            },
            {
                "value": 1520,
                "label": "CFP4 (100GE)"
            },
            {
                "value": 1550,
                "label": "Cisco CPAK (100GE)"
            },
            {
                "value": 1600,
                "label": "QSFP28 (100GE)"
            },
            {
                "value": 1700,
                "label": "QSFP56 (200GE)"
            },
            {
                "value": 1750,
                "label": "QSFP-DD (400GE)"
            },
            {
                "value": 2600,
                "label": "IEEE 802.11a"
            },
            {
                "value": 2610,
                "label": "IEEE 802.11b/g"
            },
            {
                "value": 2620,
                "label": "IEEE 802.11n"
            },
            {
                "value": 2630,
                "label": "IEEE 802.11ac"
            },
            {
                "value": 2640,
                "label": "IEEE 802.11ad"
            },
            {
                "value": 2810,
                "label": "GSM"
            },
            {
                "value": 2820,
                "label": "CDMA"
            },
            {
                "value": 2830,
                "label": "LTE"
            },
            {
                "value": 6100,
                "label": "OC-3/STM-1"
            },
            {
                "value": 6200,
                "label": "OC-12/STM-4"
            },
            {
                "value": 6300,
                "label": "OC-48/STM-16"
            },
            {
                "value": 6400,
                "label": "OC-192/STM-64"
            },
            {
                "value": 6500,
                "label": "OC-768/STM-256"
            },
            {
                "value": 6600,
                "label": "OC-1920/STM-640"
            },
            {
                "value": 6700,
                "label": "OC-3840/STM-1234"
            },
            {
                "value": 3010,
                "label": "SFP (1GFC)"
            },
            {
                "value": 3020,
                "label": "SFP (2GFC)"
            },
            {
                "value": 3040,
                "label": "SFP (4GFC)"
            },
            {
                "value": 3080,
                "label": "SFP+ (8GFC)"
            },
            {
                "value": 3160,
                "label": "SFP+ (16GFC)"
            },
            {
                "value": 3320,
                "label": "SFP28 (32GFC)"
            },
            {
                "value": 3400,
                "label": "QSFP28 (128GFC)"
            },
            {
                "value": 4000,
                "label": "T1 (1.544 Mbps)"
            },
            {
                "value": 4010,
                "label": "E1 (2.048 Mbps)"
            },
            {
                "value": 4040,
                "label": "T3 (45 Mbps)"
            },
            {
                "value": 4050,
                "label": "E3 (34 Mbps)"
            },
            {
                "value": 5000,
                "label": "Cisco StackWise"
            },
            {
                "value": 5050,
                "label": "Cisco StackWise Plus"
            },
            {
                "value": 5100,
                "label": "Cisco FlexStack"
            },
            {
                "value": 5150,
                "label": "Cisco FlexStack Plus"
            },
            {
                "value": 5200,
                "label": "Juniper VCP"
            },
            {
                "value": 5300,
                "label": "Extreme SummitStack"
            },
            {
                "value": 5310,
                "label": "Extreme SummitStack-128"
            },
            {
                "value": 5320,
                "label": "Extreme SummitStack-256"
            },
            {
                "value": 5330,
                "label": "Extreme SummitStack-512"
            },
            {
                "value": 32767,
                "label": "Other"
            }
        ]

        # map the values of interface type from Netbox to a pyATS/Genie valid type 
        valid_types_lookup = {
            "ethernet": [800, 1000, 1120, 1130, 1150, 1170, 1050, 1100, 1200, 1300, 
                1310, 1320, 1350, 1400, 1420, 1500, 1510, 1650, 1520, 1550, 1600, 1700, 
                1750,], 
            # "loopback": [], 
            "vlan": [0], 
            "port-channel": [200], 
            "wireless": [2600, 2610, 2620, 2630, 2640,], 
            "cellular": [2810, 2820, 2830], 
            "SONET": [6100, 6200, 6300, 6400, 6500, 6600, 6700], 
            "fibrechannel": [3010, 3020, 3040, 3080, 3160, 3320, 3400], 
            "serial": [4000, 4010, 4040, 4050], 
            "stacking": [5000, 5050, 5100, 5150, 5200, 5300, 5310, 5320, 5330], 
            "other": [32767]
            }

        # TODO: iosxr interface-types require UPPER case names - need to update to support 
        valid_types = ["ethernet", "loopback", "vlan", "port-channel", "pseudowire", "tunnel", "mgmt", "nve", ]

        # 2 phase type lookup, first try with interface name, then use Netbox interface type
        for valid in valid_types:
            if interface_name and valid in interface_name:
                return valid

        for valid, netbox_type_values in valid_types_lookup.items(): 
            if interface_type["value"] in netbox_type_values: 
                return valid
        
        # TODO: ASAv Management0/0 interfaces don't match interface name based types, and are "Virtual" interfaces in NetBox

        return None

    def _get_info(self, data, keys, transformation=None):
        """ Helper for getting data from nested dictionary. 

        Args:
            data ('dict'): The dictionary where you want to 
                retrieve info from.
            keys ('list'): An ordered list of keys depicting 
                the nested structure.
            transformation ('callable'): Any transformation 
                to apply to the result data.
        
        Returns:
            str: The retrieved data or None if keys does not
                exist in dictionary.
    
        """
        current = data

        for key in keys:    
            if not current or key not in current.keys():
                return None
            
            current = current[key]

        if transformation and current:
            current = transformation(current)

        return current

    def _generate(self):
        """ Transforms NetBox data into testbed format.
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.
    
        """
        logger.info("Begin retrieving data from netbox...")
        token = "Token {}".format(self._user_token)
        headers = { "Authorization": token }
        testbed = {}
        data = {}
        topology = {}

        # Configure Testbed wide details
        if self._def_user and self._def_pass:
            logger.info("Configuring testbed default credentials.")
            testbed["credentials"] = {
                "default": {
                    "username": self._def_user, 
                    "password": self._def_pass
                }
            }

        response = [] 
        netbox_endpoints = ["dcim/devices", "virtualization/virtual-machines"]
        for endpoint in netbox_endpoints: 
            if self._url_filter is None:
                url="api/{endpoint}/?format=json".format(endpoint=endpoint)
            else:
                url="api/{endpoint}/?format=json&{url_filter}".format(endpoint=endpoint, url_filter=self._url_filter)

            devices_url = self._format_url(self._netbox_url, url)
            response += self._get_request(devices_url, headers, "results")

        # If no response is received for retrieving a list of devices, stop
        if not response: 
            logger.error("\nnetbox instance gave no response")
            return None

        for device in response:
            is_valid = True

            if self._host_upper is True:
                device_name = device["name"].upper()
            else:
                device_name = device["name"]

            logger.info("Retrieving associated data for {}..."
                                                        .format(device_name))
            device_id = device["id"]
            device_data = data.setdefault(device_name, {})

            # Construct device platform data
            device_platform = self._parse_os(self._get_info(device, 
                            ["platform", "slug"], lambda slug: slug.lower()))

            # OS value is required and must exist
            is_valid &= self._set_value_if_exists(device_data, "os",
                                                             device_platform)

            # Set other testbed values if they exists
            self._set_value_if_exists(device_data, "alias", device_name)
            self._set_value_if_exists(device_data, "platform", device_platform)
            self._set_value_if_exists(device_data, "type", 
                            self._get_info(device, ["device_type", "model"]))

            # NetBox Virtual Machines don't have a "device_type" attribute, but pyATS requires
            # one. If missing, construct a type from Platform + Role
            if "type" not in device_data.keys(): 
                role_name = self._get_info(device, ["role", "name"])
                platform_name = self._get_info(device, ["platform", "name"])
                device_data["type"] = "{platform} - {role}".format(platform = platform_name, role = role_name)
            
            # Initialize connection data
            connections = device_data.setdefault("connections", {})
            cli = connections.setdefault("cli", {})
            mask_filter = lambda ip: ip.split("/")[0]
            ipv6 = self._get_info(device, [
                "primary_ip6", "address"
            ], mask_filter)
            found_ip = False

            if self._tag_telnet is not None and self._tag_telnet in device['tags']:
                protocol='telnet'
            else:
                protocol='ssh'

            cli.setdefault("protocol", protocol)
            # Attempt to set connection protocol to primary IP, if found
            found_ip |= self._set_value_if_exists(cli, "ip", self._get_info(
                            device, ["primary_ip4", "address"], mask_filter))
            found_ip |= self._set_value_if_exists(cli, "ip",
                self._get_info(device, ["primary_ip", "address"], mask_filter))
            found_ip |= self._set_value_if_exists(cli, "ip", ipv6)

            # If we did not find a valid OS type for device, we skip it
            if not is_valid:
                logger.warning(
                    "OS type is not valid for {}. ".format(device_name) +
                    "Skipping..."
                )
                
                # Delete the device from testbed
                del data[device_name]
                continue
            
            # Set IP to IPV6 if IPV4 primary does not exist
            if "ip" in cli and "." in cli["ip"] and ipv6:
                connections.setdefault("ipv6", {
                    "ip": ipv6, "protocol": "ssh"
                })
            
            if self._topology is True:
                # Need to determine whether to do the lookup for interfaces against DCIM or VM
                if "rack" in device.keys():
                    # Even unracked devices have the key "rack" in the returned body
                    interface_url = self._format_url(self._netbox_url, 
                        "api/dcim/interfaces/?device_id={}&format=json".format(
                                                                            device_id))                    
                else: 
                    # Otherwise lookup as VM
                    interface_url = self._format_url(self._netbox_url, 
                        "api/virtualization/interfaces/?virtual_machine_id={}&format=json".format(
                                                                            device_id))                    

                # Send request for interfaces
                interface_response = self._get_request(interface_url, headers, 
                                                                        "results")

                # If no interface response are received, we skip the device
                if not interface_response:
                    logger.warning(
                        "No interface found for {}. ".format(device_name) +
                        "Skipping device..."
                    )

                    # Delete device data from testbed
                    del data[device_name]
                    continue
                
                # Initialize interface data
                interfaces = topology.setdefault(device_name, {
                    "interfaces": {} 
                })["interfaces"]

                for interface in interface_response:
                    interface_name = interface["name"]
                    interface_id = interface["id"]
                    current = interfaces.setdefault(interface_name, {})

                    current.setdefault("alias", "{}_{}"
                                            .format(device_name, interface_name))
                    self._set_value_if_exists(current, "type", 
                                        self._format_type(
                                            interface_name.lower(), 
                                            interface["type"]
                                        ))
                    if current.get('type') is None:
                        logger.info("{device_name} interface {interface_name} is not valid, skipping".format(device_name=device_name, interface_name=interface_name.lower()))
                        del interfaces[interface_name]
                        continue
                    
                    # Use the cable information from Netbox to configure link on interface
                    self._set_value_if_exists(
                        current, "link", 
                        self._get_info(interface, ["cable", "id"], lambda link: "cable_num_{link}".format(link=link))
                    )

                    # Attempt to retrieve IP for each interface
                    ip_url = self._format_url(self._netbox_url,
                        "api/ipam/ip-addresses/?interface_id={}&format=json"
                                                            .format(interface_id))
                    ip_response = self._get_request(ip_url, headers, "results")

                    # If no response for IP retrieval then we skip this interface
                    if not ip_response:
                        continue

                    for ip_address in ip_response:
                        # If we have not found primary IP for the device, set it to
                        # the first interface IP we see
                        if not found_ip:
                            cli.setdefault("ip", mask_filter(ip_address["address"]))

                            found_ip = True
                        
                        # Correctly set IP information on interface data
                        family = "ipv4" if "." in ip_address["address"] else "ipv6"
                        current.setdefault(family, ip_address["address"])

            # If no primary IP found for this device, then we stop and skip
            if not found_ip:
                logger.warning(
                    "Connection IP not found for {}. ".format(device_name) +
                    "Skipping device..."
                )
                
                del data[device_name]
                del topology[device_name]
                continue
                
            if self._def_user is None or self._def_pass is None:
                # Request user to manually enter their credentials for each device
                logger.info("Connection Credentials for {}:".format(device_name))

                username = input("Username: ")
                password = input("Password: ")

                # Only include device specific credentials block if default credentials were NOT provided
                device_data.setdefault("credentials", {
                    "default": { "username": username, "password": password }
                })
            else:
                username = self._def_user
                password  = self._def_pass
                device_data.setdefault("credentials", {
                    "default": { "username": username, "password": password }
                })


        # If testbed has data, return it
        if len(data.keys()) > 0:
            return { "testbed": testbed, "devices": data, "topology": topology }
        
        return None
