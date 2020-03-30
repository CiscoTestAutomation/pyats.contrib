import os
import yaml
import re
import logging
import sys
import argparse

from pyats.topology import Testbed, Device, Interface
from pyats.utils.secret_strings import SecretString
from pyats.topology.loader.base import BaseTestbedLoader

logger = logging.getLogger(__name__)

class TestbedCreator(BaseTestbedLoader):
    """
    Abstract base class for testbed conversion actions.

    """
    _result = {'success': {}, 'errored':{}, 'warning':{}}
    _keys = ['hostname','ip','username', 'password', 'protocol', 'os']

    def __init__(self, **kwargs):
        """
        Instantiates the testbed action with appropriate arguments.
        
        """
        kwargs.update(self._parse_cli())

        arguments = self._init_arguments()

        if "required" in arguments:
            for arg in arguments["required"]:
                if arg in kwargs:
                    self.__dict__.setdefault('_' + arg, kwargs[arg])
                else:
                    raise Exception(
                        "Missing required argument: '%s'" % arg
                    )

        if "optional" in arguments:
            for arg in arguments["optional"]:
                self.__dict__.setdefault('_' + arg, kwargs[arg] 
                            if arg in kwargs else arguments["optional"][arg])

    def _parse_cli(self):
        """
        Parses arguments from CLI if any.
        
        """
        parser = argparse.ArgumentParser()
        parser.add_argument('args', nargs=argparse.REMAINDER)
        args = parser.parse_args(sys.argv)
        kwargs = {}

        if args.args and len(args.args) > 0:
            args.args = args.args[1:]
            i = 0
            while i < len(args.args):
                arg = args.args[i]
                i += 1

                # If the recurse option is passed in, convert to argument
                if arg == '-r':
                    kwargs.setdefault('recurse', True)
                    continue

                # If argument expects a list, search and return list
                if arg == '--add-keys' or arg == '--add-custom-keys':
                    j = i
                    
                    # Collect parameters
                    while j < len(args.args) and not '--' in args.args[j] and \
                        not '-r' in args.args[j]: j += 1
                    kwargs.setdefault(arg.replace('--', '').replace('-', '_'), 
                                                                args.args[i:j])

                    # Incrememt index
                    i = j
                    continue

                parts = arg.split('=', 1)
                key = None
                value = None

                # Assume flag value if no assignment is provided
                if len(parts) < 2:
                    value = True
                    key = parts[0]
                else:
                    key, value = parts
                
                # Convert key to variable name
                key = key.replace('--', '')
                key = key.replace('-', '_')
                kwargs.setdefault(key, value)

        return kwargs

    def _init_arguments(self):
        """
        Defines argument names that should be added to the class instance.
        Should be overridden in derived classes if they require arguments.

        Return type must be a dict of maximum two keys: "required" and 
        "optional". Required key must pair with an array of
        argument names which will be added to the class instance with a
        underscore in front. Optional key must pair with a dictionary of
        argument names and their default value if not specified.

        For example:
        {
            "required": ["file_name"],
            "optional": {
                "encode_password": True
            }
        }
        This will add self._file_name property and also self._encode_password 
        (which has a default value of True).

        """
        return {}

    def _generate(self):
        """
        Defines the generate method that the derived class must implement. 
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.

        """
        raise NotImplementedError(
            "Derived class must implement `_generate` method."
        )

    def to_testbed_file(self, output_location):
        """
        Retrieves the testbed information and saves it as a YAML file.
        
        Args:
            output_location ('str'): Path of where to save the testbed file.
        
        Returns:
            bool: Indication if the operation is successful or not.

        """
        if os.path.isdir(output_location):
            raise Exception('Output "{o}" is a directory'
                                                    .format(o=output_location))

        try:
            testbed = self._generate()
            encode_password = False
            
            if hasattr(self, '_encode_password'):
                encode_password = self._encode_password

            self._write_yaml(output_location, testbed, encode_password)
            
            return True
        except:
            self._result['errored']['>'] = 'An error has occurred.'
            return False

    def to_testbed_dictionary(self):
        config = self._generate()

        if isinstance(config, list):
            config = config[0]
        if isinstance(config, tuple):
            config = config[1]

        return config

    def load(self):
        return self.to_testbed_object()

    def to_testbed_object(self):
        """
        Retrieves the testbed information and returns it as a testbed object.
        
        Returns:
            Testbed: The testbed object.

        """
        data = self._generate()

        if data is None:
            return None

        return self._create_testbed(data)

    def _create_testbed(self, data):
        testbed = Testbed('testbed')
        topology = {}

        if 'topology' in data:
            # Build the interface data if it exists
            for device_name, interfaces in data['topology']:
                items = topology.setdefault(device_name, [])

                for interface_name, interface_data in interfaces:
                    interface_object = None

                    # Set IPV4 or IPV6 appropriately while instantiating
                    # interface objects
                    if 'ipv4' in interface_data:
                        interface_object = Interface(interface_name, \
                            type=interface_data['type'], \
                                alias=interface_data['alias'], \
                                    ipv4=interface_data['ipv4'])
                    elif 'ipv6' in interface_data:
                        interface_object = Interface(interface_name, \
                            type=interface_data['type'], \
                                alias=interface_data['alias'], \
                                    ipv6=interface_data['ipv6'])

                    # If interface exists and is valid, add it to interface list
                    # for the device so it will be added to device later
                    if interface_object is not None:
                        items.append(interface_object)

        for device_name, device_info in data['devices'].items():
            device = Device(device_name, connections=device_info['connections'])

            # Instantiate device object and attach properties
            device.alias = device_name
            device.type = device_info['type']

            if device_name in topology:
                # If device has interfaces, add all of them to the device
                for interface in topology[device_name]:
                    device.add_interface(interface)

            for credential_name, credential_info \
                in device_info['credentials'].items():
                # Add any connection credentials to the device
                device.credentials[credential_name] = credential_info

            testbed.add_device(device)

        return testbed

    def _encode_all_password(self, devices):
        """ encode the password of all the devices
        Args:
            devices(`list`): list of devices

        Returns:
            None
        """
        # ask password on connect if not provided, otherwise encode the password
        stack = [devices]
        while len(stack) > 0:
            current = stack.pop()
            for key, value in current.items():
                if key == "password" and value != '%ASK{}':
                    value = self._encode_secret(value)
                    current[key] = value
                elif isinstance(value, dict):
                    stack.append(value)

    def _encode_secret(self, plain_text):
        encoded = SecretString.from_plaintext(plain_text)
        return '%ENC{' + encoded.data + '}'

    def _write_yaml(self, output, devices, encode_password, input_file=None):
        """Write device data to yaml file
        Args:
            output (`str`): output file path
            devices (`list`): list of dicts containing device dat
            encode_password (`bool`): flag for encoding password
            input_file (`str`): input file name
        Returns:
            None
        """
        # if empty dict, do nothing
        if not devices:
            return
        # Make sure output file can be created
        try:
            os.makedirs(os.path.dirname(output), exist_ok=True)
        except FileNotFoundError:
            # If a file which does not contains a directory name
            pass

        if encode_password:
            self._encode_all_password(devices)

        with open(output, 'w') as f:
            try:
                yaml.dump(devices, f, default_flow_style=False)
            except Exception as e:
                self._result['errored'][
                    input_file.lstrip('./')
                ] = 'has an error: {e}'.format(e=str(e))
                return
        if input_file:
            name = input_file.lstrip('./')
            self._result['success'].setdefault(name, "")
            self._result['success'][name] += '-> {f}\n'.format(f=output)
        else:
            self._result['success'][output] = ''

    def _construct_yaml(self, devices):
        """ construct list of dicts containing device data into nest yaml 
        structure

        Args:
            devices(`list`): list of dict containing device attributes

        Returns:
             nested dict that's ready to be dumped into yaml
        """
        yaml_dict = {
            'devices': {}
        }
        seen_hostnames = set()
        for row in devices:
            try:
                name = row.pop('hostname')
            except KeyError:
                raise KeyError('Every device must have a hostname')

            if name in seen_hostnames:
                raise Exception('Duplicate hostname "{n}" detected'
                                                                .format(n=name))
            else:
                seen_hostnames.add(name)

            try:
                # get port from ip
                address = re.split(':| +', row['ip'].strip())
                row['ip'] = address[0]
                port = row.pop('port', address[1] if len(address) > 1 else None)
                os = row.pop('os')

                # build the connection dict
                connections = {
                    'cli': {
                        'ip': row.pop('ip'),
                        'protocol': row.pop('protocol')}}

                if port:
                    connections['cli'].update({'port': int(port)})

                # build the credentials dict
                password = row.pop('password', '%ASK{}')
                if 'enable_password' in self._keys:
                    enable_password = row.pop('enable_password', '%ASK{}')
                else:
                    enable_password = row.pop('enable_password', password)
                credentials = {
                    'default': {
                        'username': row.pop('username'),
                        'password': password},
                    'enable': {
                        'password':  enable_password
                    }}

            except KeyError as e:
                raise KeyError('Missing required key {k} for device {d}'
                                                    .format(k=str(e), d=name))
            dev = yaml_dict['devices'].setdefault(name, {})
            dev['os'] = os
            dev['connections'] = connections
            dev['credentials'] = credentials
            type = row.get('type')
            dev['type'] = type if type else os
            if row and len(row) > 0:
                for key, value in row.items():
                    if 'custom:' in key:
                        dev.setdefault('custom', {}).setdefault(
                            key.replace('custom:', ''), value)
                    else:
                        dev.setdefault(key, value)

        return yaml_dict

    def print_result(self):
        # print testbeds create successfully
        if not self._result['success'] and not self._result['errored'] \
            and not self._result['warning']:
            logger.warning('No file found.')
            return

        if self._result['success']:
            logger.info('Testbed file generated: ')
            for k, v in self._result['success'].items():
                logger.info('{k} {v}'.format(k=k,v=v))

        # print the ones that are errored
        if self._result['errored']:
            logger.info('')
            logger.error('Errors:')
            for k, v in self._result['errored'].items():
                logger.error('{k} {v}'.format(k=k,v=v))

        # print warnings
        if self._result['warning']:
            logger.info('')
            logger.warning('Warnings:')
            for k, v in self._result['warning'].items():
                logger.warning('{k} {v}'.format(k=k,v=v))
