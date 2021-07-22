try:
    from ansible.parsing.dataloader import DataLoader
    from ansible.inventory.manager import InventoryManager
    from ansible.cli.inventory import InventoryCLI
    from ansible import context
except Exception:
    raise ImportError("'ansible' package is not installed. Please install by running: pip install ansible")
from .creator import TestbedCreator

class Ansible(TestbedCreator):
    """ Ansible class (TestbedCreator)

    Creator for the 'ansible' source. Reads the given inventory in Ansible and 
    converts the data to a structured testbed file or object.

    Args:
        inventory_name ('str'): The name of the Ansible inventory.
        encode_password ('bool') default=False: Should generated testbed encode 
            its passwords.

    CLI Argument           |  Class Argument
    ------------------------------------------------
    --inventory-name=value |  inventory_name=value
    --encode-password      |  encode_password=True

    pyATS Examples:
        pyats create testbed ansible --output=out --inventory-name=inventory.ini

    Examples:
        # Create testbed from Ansible source
        creator = Ansible(inventory_name="inventory.ini")
        creator.to_testbed_file("template.csv")
        creator.to_testbed_object()

    """
    
    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        return {
            'required': ['inventory_name'],
            'optional': {
                'encode_password': False
            }
        }

    def _generate(self):
        """ Transforms Ansible data into testbed format.
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.
    
        """
        # Set Ansible arguments for export
        context.CLIARGS = {}
        context.CLIARGS['export'] = True
        context.CLIARGS['basedir'] = '.'

        # Instantiate Ansible control objects
        inventory = InventoryManager(loader=DataLoader(), 
                                                sources=self._inventory_name)
        test = InventoryCLI(args=[''])
        group = inventory.groups.get('all')
        test.inventory = inventory

        # Fetch all the data associated with particular inventory
        result = test.json_inventory(top=group)
        testbed = {}
        devices = testbed.setdefault('devices', {})
        host_vars = result['_meta']['hostvars']

        # Remove items that are not device type in result
        del result['all']
        del result['_meta']

        for device_type, category in result.items():
            # If category does not contain vars or hosts, we skip
            if not 'vars' in category or not 'hosts' in category:
                continue

            for host in category['hosts']:
                cli_name = 'cli'

                # If netconf is defined as connection type, use that instead
                # of default CLI type
                if 'ansible_connection' in category['vars']:
                    if 'netconf' in category['vars']['ansible_connection']:
                        cli_name = 'netconf'

                # Construct connection fields and credentials
                device = devices.setdefault(host, {})
                connections = device.setdefault('connections', {
                     cli_name: {'protocol': 'ssh'}
                })
                cli = connections[cli_name]
                default = device.setdefault('credentials', {'default': {}})
                default = default['default']

                # set connection ip
                if host in host_vars and 'ansible_host' in host_vars[host]:
                    cli.setdefault('ip', host_vars[host]['ansible_host'])
                else:
                    cli.setdefault('ip', host)

                # set connection port
                if 'ansible_ssh_port' in category['vars']:
                    cli.setdefault('port', category['vars']['ansible_ssh_port'])

                password = None
                # Select the correct field name based on what is given
                if 'ansible_ssh_pass' in category['vars']:
                    password = 'ansible_ssh_pass'
                elif 'ansible_password' in category['vars']:
                    password = 'ansible_password'
                else:
                    # If password does not exist, skip over device
                    del devices[host]
                    continue
                
                # Set password and username
                default.setdefault('password', category['vars'][password])
                default.setdefault('username', category['vars']['ansible_user'])

                # If device has any other connection types, we also
                # set those respectively with their password
                if 'ansible_become_method' in category['vars'] and \
                    'ansible_become_pass' in category['vars']:
                    inner = connections.setdefault(
                        category['vars']['ansible_become_method'], {})
                    inner.setdefault('password',
                        category['vars']['ansible_become_pass'])

                # Set other device properties
                device.setdefault('alias', host)

                if 'ansible_network_os' not in category['vars']:
                    raise Exception("Missing key word 'ansible_network_os' for %s" % host)

                device.setdefault('os', category['vars']['ansible_network_os'])
                device.setdefault('platform',
                                        category['vars']['ansible_network_os'])
                device.setdefault('type', device_type)

        return testbed if len(testbed['devices']) > 0 else None
