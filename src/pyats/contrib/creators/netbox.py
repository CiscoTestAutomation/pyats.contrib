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
        topology (bool) default=False: Do not generate topology data by default, #TODO fix links
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
            
            return self._parse_response(response, return_property)
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
            "iosxe", "iosxr", "ios", "junos", "linux", "nxos", "yang"]

        for valid in valid_os:
            if os and valid in os:
                return valid
        
        return None

    def _format_type(self, interface_type): 
        """ Helper to parse the interface type.

        Args:
            interface_type ('str'): The input interface type.

        Returns:
            str: The interface type if it exists or none if it 
            cannot be found in list of valid types.
    
        """
        valid_types = ["ethernet", "loopback", "vlan"]

        for valid in valid_types:
            if interface_type and valid in interface_type:
                return valid

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
            if not current:
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
        data = {}
        topology = {}

        if self._url_filter is None:
            url=f"api/dcim/devices/?format=json"
        else:
            url=f"api/dcim/devices/?format=json&{self._url_filter}"

        devices_url = self._format_url(self._netbox_url, url)
        response = self._get_request(devices_url, headers, "results")

        # If no response is received for retrieving a list of devices, stop
        if not response: 
            logger.error("\nnetbox instance gave no response")
            return None

        for device in response:
            is_valid = True

            if self._host_upper is True:
                device_name = device["display_name"].upper()
            else:
                device_name = device["display_name"]

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
            
            # TODO Link is required for topology, need to implement
            if self._topology is True:
                # Send request for interfaces
                interface_url = self._format_url(self._netbox_url, 
                    "api/dcim/interfaces/?device_id={}&format=json".format(
                                                                        device_id))
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
                                        self._format_type(interface_name.lower()))
                    if current.get('type') is None:
                        logger.info(f"{device_name} interface {interface_name.lower()} is not valid, skipping")
                        del interfaces[interface_name]
                        continue

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
                continue
                
            if self._def_user is None or self._def_pass is None:
                # Request user to manually enter their credentials for each device
                logger.info("Connection Credentials for {}:".format(device_name))

                username = input("Username: ")
                password = input("Password: ")
            else:
                username = self._def_user
                password  = self._def_pass

            device_data.setdefault("credentials", {
                 "default": { "username": username, "password": password }
            })

        # If testbed has data, return it
        if len(data.keys()) > 0:
            return { "devices": data, "topology": topology }
        
        return None
