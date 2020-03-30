from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.cli.inventory import InventoryCLI
from ansible import context
from .creator import TestbedCreator

class Ansible(TestbedCreator):
    def _init_arguments(self): 
        return {
            'required': ['inventory_name'],
            'optional': {
                'encode_password': False
            }
        }

    def _generate(self):
        """ 
        Transforms Ansible data into testbed format.
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.
    
        """
        # Set Ansible arguments for export
        context.CLIARGS = {}
        context.CLIARGS['export'] = True
        context.CLIARGS['basedir'] = '.'

        # Instantiate Ansible control objects
        inventory = InventoryManager(loader=DataLoader(), \
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
                device = devices.setdefault(host.encode('ascii'), {})
                connections = device.setdefault('connections', {
                     cli_name: { 'protocol': 'ssh' }
                })
                cli = connections[cli_name]
                default = device.setdefault('credentials', {
                    'default': {}
                })['default']

                cli.setdefault('ip', host_vars[host]['ansible_host'] \
                    .encode('ascii'))
                password = None

                # Select the correct field name based on what is given
                if 'ansible_ssh_pass' in category['vars']:
                    password = 'ansible_ssh_pass'
                elif 'ansible_password' in category['vars']:
                    password = 'ansible_password'
                else:
                    # If password does not exist, skip over device
                    del devices[host.encode('ascii')]
                    continue
                
                # Set password and username
                default.setdefault('password', \
                    category['vars'][password].encode('ascii'))
                default.setdefault('username', \
                    category['vars']['ansible_user'].encode('ascii'))

                # If device has any other connection types, we also
                # set those respectively with their password
                if 'ansible_become_method' in category['vars'] and \
                    'ansible_become_pass' in category['vars']:
                    inner = connections.setdefault( \
                        category['vars']['ansible_become_method'] \
                            .encode('ascii'), {})
                    inner.setdefault('password', \
                        category['vars']['ansible_become_pass'].encode('ascii'))

                # Set other device properties
                device.setdefault('alias', host.encode('ascii'))
                device.setdefault('os', \
                    category['vars']['ansible_network_os'].encode('ascii'))
                device.setdefault('platform', \
                    category['vars']['ansible_network_os'].encode('ascii'))
                device.setdefault('type', device_type.encode('ascii'))

        return testbed if len(testbed['devices']) > 0 else None
