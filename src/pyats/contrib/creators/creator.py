import os
import yaml
import re
import logging
import sys
import argparse

from pyats.utils.secret_strings import SecretString
from pyats.topology.loader.base import BaseTestbedLoader

logger = logging.getLogger(__name__)

class TestbedCreator(BaseTestbedLoader):
    """ TestbedCreator class (BaseTestbedLoader)

    The base testbed creator class. All testbed creators must inherit this class
    in order to properly integrate with pyATS CLI.

    You must override the '_generate' method in the derived class to specify the
    appropriate behaviour for your source. To add arguments to your derived
    class, simply override '_init_arguments' to return a dictionary of required
    or optional arguments. See the function for more information.

    Examples:
        # Example demonstrating the creation of a MySQL loader
        class Mysql(TestbedCreator):
            def _init_arguments(self):
                return {
                    "required": ["sql_username", "sql_password"]
                    "optional": {
                        "sql_table": "devices"
                    }
                }

            def _generate(self):
                # <Parsing Logic and Code>
                return testbed_data

        # Instantiation and usage
        creator = Mysql(sql_username='root', sql_password='admin')
        creator.to_testbed_file('tesbed.yaml')
        creator.to_testbed_object()
    
    """

    def __init__(self, **kwargs):
        """ Instantiates the testbed creator with appropriate arguments.
        
        """
        self._result = {'success': {}, 'errored':{}, 'warning':{}}
        self._keys = ['hostname','ip','username', 'password', 'protocol', 'os']
        self._cli_list_arguments = []
        self._cli_replacements = {}

        arguments = self._init_arguments()
        kwargs.update(self._parse_cli())

        if "required" in arguments:
            for arg in arguments["required"]:
                if arg in kwargs:
                    self.__dict__.setdefault('_' + arg, kwargs[arg])
                else:
                    required = '\n'.join(arguments["required"])
                    raise Exception(
                        "This following arguments are required for this source:"
                        "\n" + required + "\n\nSource Help:\n" + self.__doc__
                    )

        if "optional" in arguments:
            for arg in arguments["optional"]:
                self.__dict__.setdefault('_' + arg, kwargs[arg] 
                            if arg in kwargs else arguments["optional"][arg])

    def _parse_cli(self):
        """ Parses arguments from CLI if any. Removes the first two dashes and
            converts any left over dashes to underscores.

        Returns:
            dict: The parsed arguments in dictionary format.

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

                # If argument name is in replacement dictionary, 
                # replace it with correspoding name and value
                if arg in self._cli_replacements:
                    name, value = self._cli_replacements[arg]
                    kwargs.setdefault(name, value)
                    continue

                # If argument expects a list, search and return list
                if arg in self._cli_list_arguments:
                    j = i
                    
                    # Collect parameters
                    while j < len(args.args) and not args.args[j].startswith('--') and \
                        not '-r' in args.args[j]: j += 1

                    kwargs.setdefault(arg.replace('--', '').replace('-', '_'), 
                                                                args.args[i:j])

                    # Incrememt index
                    i = j
                    continue

                parts = arg.split('=', 1)
                key = None
                value = None

                if len(parts) < 2:
                    value = None

                    if i < len(args.args) and not args.args[i].startswith('-'):
                        # Handle spaces
                        value = args.args[i]
                        i += 1
                    else: 
                        # Assume flag value if no assignment is provided
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
        """ Defines argument that should be added to the class instance. Should 
            be overridden in derived classes if they require arguments. This 
            will ensure correct arguments are passed through either the derived 
            constructor or the CLI.

            Return type must be a dict of maximum two keys: "required" and 
            "optional". Required key must pair with an array of argument names 
            which will be added to the class instance with a underscore in 
            front. Optional key must pair with a dictionary of argument names 
            and their default value. The following demonstrates an example:

                return {
                    "required": ["file_name"],
                    "optional": {
                        "encode_password": True
                    }
                }
        
            This will add 'self._file_name' and 'self._encode_password' property
            which the derived class can access.

            Adding to the 'self._cli_list_arguments' will signify the parser 
            that the argument expects a list. For example, to have '--key' to be
            parsed as a list in '--key a b c', you will need:
        
                self._cli_list_arguments.append('--key')

            Adding to the 'self._cli_replacements' will replace any occurrences 
            of the key with the corresponding variable name and value. For 
            example, to map '-s' argument to 'silent=True' variable, 
            you will need:

                self._cli_replacements.setdefault('-s', ('silent', True))

        Returns:
            dict: The arguments for the creator.

        """
        return {}

    def _generate(self):
        """ Defines the generate method that the derived class must implement. 
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.

        """
        raise NotImplementedError(
            "Derived class must implement `_generate` method."
        )

    def to_testbed_file(self, output_location):
        """ Retrieves the testbed information and saves it as a YAML file.
        
        Args:
            output_location ('str'): Path of where to save the testbed file.
        
        Returns:
            bool: Indication if the operation is successful or not.

        """
        if os.path.isdir(output_location):
            raise Exception('Output "{o}" is a directory'
                                                    .format(o=output_location))
        testbed = self._generate()
        encode_password = False
        
        if hasattr(self, '_encode_password'):
            encode_password = self._encode_password

        try:
            self._write_yaml(output_location, testbed, encode_password)
            
            return True
        except:
            self._result['errored']['>'] = 'An error has occurred.'
            return False

    def load(self):
        """ Overrides the base testbed loader class to return a testbed object.

        Returns:
            Testbed: The testbed object.

        """
        return self.to_testbed_object()

    def to_testbed_object(self):
        """ Retrieves the testbed information and returns it as a testbed object.
        
        Returns:
            Testbed: The testbed object.

        """
        data = self._generate()

        if data is None:
            return None

        return self._create_testbed(data)

    def _create_testbed(self, data):
        """ Helper for creating testbed object from intermediate testbed
            dictionaries.

        Args:
            data ('dict'): The testbed data.

        Returns:
            Testbed: The converted testbed object.
        
        """
        return BaseTestbedLoader.create_testbed({
            'testbed': {
                'name': 'testbed'
            },
            'devices': data.get('devices', {}),
            'topology': data.get('topology', {})
        })

    def _encode_all_password(self, devices):
        """ Encode the password of all the devices.
        
        Args:
            devices ('dict'): The intermediate testbed dictionary.

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
        """ Performs password encoding.

        Args:
            plain_text ('str'): the plain text password.

        Returns:
            str: The encoded password.

        """
        encoded = SecretString.from_plaintext(plain_text)
        return '%ENC{' + encoded.data + '}'

    def _write_yaml(self, output, devices, encode_password, input_file=None):
        """ Write device data to yaml file.
        
        Args:
            output ('str'): The output file path.
            devices ('list'): Dictionary containing device data.
            encode_password ('bool'): Flag for encoding passwords or not.
            input_file ('str'): The input file name, if any.
        
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
        """ Construct list of dicts containing device data into nested yaml 
            structure.

        Args:
            devices ('list'): List of dict containing device attributes.

        Returns:
             dict: Testbed dictionary that's ready to be dumped into yaml.
    
        """
        yaml_dict = {
            'devices': {}
        }
        seen_hostnames = set()
        for row in devices:
            try:
                name = row.pop('hostname')
            except KeyError:
                raise KeyError('Empty line found in given CSV/Excel file.')

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
                
                if 'proxy' in row:
                    connections['cli'].update({'proxy': row.pop('proxy')})

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
        """ Prints the result of testbed creating process.

        """
        # print testbeds create unsuccessfully
        if not self._result['success'] and not self._result['errored'] \
            and not self._result['warning']:
            logger.warning('No file found.')
            return

        if self._result['success']:
            if 'template' in self._result['success']:
                # print template create successfully
                logger.info('Template file generated: {file}'.format(file=self._result['success']['template']))
            else:
                # print testbeds create successfully
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
