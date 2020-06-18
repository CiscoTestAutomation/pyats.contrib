import os
import re
import sys
import time
import pprint
import logging
import argparse
import ipaddress
import subprocess
from itertools import product
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from yaml import (ScalarEvent, MappingEndEvent, MappingStartEvent, AliasEvent,
                  SequenceEndEvent, SequenceStartEvent, DocumentEndEvent,
                  DocumentStartEvent, StreamEndEvent, StreamStartEvent, emit,
                  resolver, Dumper, dump, YAMLError, safe_load)

from genie.conf import Genie
from genie.testbed import load
from pyats.async_ import pcall
from .creator import TestbedCreator
from genie.conf.base import Testbed, Device, Interface, Link
from genie.metaparser.util.exceptions import SchemaEmptyParserError

log = logging.getLogger(__name__)
    
supported_os = ['nxos', 'iosxr', 'iosxe', 'ios']



class Topology(TestbedCreator):
    
    """ Topology class (TestbedCreator)

        Takes a yaml file given by argument testbed_name and attempts to connect
        to each device in the testbed and discover the devices connection using
        cdp and lldp and writes it to a new  yaml file
        Args:
            testbed-name: Mandatory argument of initial testbed file
            config: if enabled the script will enable cdp and lldp on devices
                    and disable it afterwards
            all-interfaces: if enabled, script will add all interfaces to 
                    topology section of yaml file instead of just interfaces
                    with active connections
            exclude_network: list networks that won't be recorded by creator
                    if found as part of a connection
            exclude_interfaces:list interfaces that won't be recorded by creator
                    if found as part of a connection
            topo-only: if true script will only find connections between devices
                    in the testbed and will not discover new devices
    """
        
    def _init_arguments(self):
        """ Specifies the arguments for the creator.
        Returns:
            dict: Arguments for the creator.
        """
        # create 3 sets to track what devices have cdp and lldp configured
        # and what devices have be visited by the script
        self.cdp_configured = set()
        self.lldp_configured = set()
        self.visited_devices = set()
        return {
            'required': ['testbed_name'],
            'optional': {
                'config': False,
                'all_interfaces': False,
                'exclude_network': '',
                'exclude_interfaces':'',
                'topo_only': False,
                'timeout': 10
            }
        }
    
    def connect_one_device(self, testbed, device):
        '''
            connect to the given device in the testbed using the given
            connections and after that enable cdp and lldp if allowed
        '''
        # if the device has a supported os try to connect through each of 
        # the connections it has. If the device is not connected just return
        # that cdp and lldp were not configured
        if testbed.devices[device].os not in supported_os:
            return [False, False]          
        for one_connect in testbed.devices[device].connections:                         
            try:
                testbed.devices[device].connect(via = str(one_connect),
                                                connection_timeout = 10,
                                                learn_hostname = True)
                break
            except Exception:
                testbed.devices[device].destroy()

        return self.configure_device_cdp_and_lldp(testbed.devices[device])
        
    def configure_device_cdp_and_lldp(self, dev):
        '''
            If allowed to edit device configuration
            enable cdp and lldp on the device if it is disabled and return
            whether cdp and lldp where configured for the device
        '''
        cdp = False
        lldp = False

        if not dev.is_connected():
            log.info('Device {} is not connected skipping' 
                     ' cdp/lldp configuration'.format(dev.name))

        if dev.is_connected() and self._config:

            if not dev.api.verify_cdp_status(max_time= self._timeout, check_interval=5):
                try:
                    dev.api.configure_cdp()
                    cdp = True
                except Exception:
                    log.error("Exception configuring cdp " 
                              "for {device}".format(device = dev.name), 
                                                    exc_info = True)

            if not dev.api.verify_lldp_status(max_time= self._timeout, check_interval=5):
                try:
                    dev.api.configure_lldp()
                    lldp = True
                except Exception:
                    log.error("Exception configuring cdp" 
                              " for {device}".format(device = dev.name), 
                                                     exc_info = True)    
        return [cdp, lldp]


    def connect_all_devices(self, testbed, limit):
        '''
            Creates a ThreadPoolExecutor designed to connect to each device in 
            testbed
            Args:
                testbed = testbed whose devices you want to connect
                limit = max number of threads to spawn
                
            Returns:
                Dictionary of devices containing their connection status
        '''
        results = {}

        # Set up a thread pool executor to connect to all devices at the same time    
        with ThreadPoolExecutor(max_workers = limit) as executor:
            for entry in testbed.devices:
                log.info('attempting to connect to {entry}'.format(entry = entry))
                results[entry] = executor.submit(self.connect_one_device,
                                                testbed,
                                                entry)
        # read the configuration results for each device and if the cdp or lldp configured
        # add the device name to the respective set
        for entry in results:
            if results[entry].result()[0]:
                self.cdp_configured.add(entry)
            if results[entry].result()[1]:
                self.lldp_configured.add(entry)
        log.info('Devices that had cdp configured: {}, '
                 'Devices that had lldp configured: {}'.format(self.cdp_configured, self.lldp_configured))

    def unconfigure_neighbor_discovery_protocols(self, device):
        '''
            Unconfigures cdp and lldp on device if they were enabled by the
            script earlier
        '''

        # for each device in the list that had cdp configured by script,
        # disable cdp
        if device.name in self.cdp_configured:
            try:
                device.api.unconfigure_cdp()
            except Exception as e:
                log.error('Error unconfiguring cdp on device {}: {}'.format(device.name, e))

        # for each device in the list that had lldp configured by script,
        # disable lldp
        if device.name in self.lldp_configured:
            try:
                device.api.unconfigure_lldp()
            except Exception as e:
                log.error('Error unconfiguring lldp on device {}: {}'.format(device.name, e))

    def get_neighbor_info(self, device):
        '''
        Method designed to be used with pcall, gets the devices cdp and lldp
        neighbor data and then returns it in a dictionary format
        '''
        cdp = []
        lldp = []
        if device.os not in supported_os and not device.is_connected():
            return {device.name: {'cdp':cdp, 'lldp':lldp}}
        try:
            cdp = device.api.get_cdp_neighbors_info()
        except Exception:
            log.error("Exception occurred getting cdp info", exc_info = True)
        try:
            lldp = device.api.get_lldp_neighbors_info()
        except Exception:
            log.error("Exception occurred getting lldp info", exc_info = True)
        return {device.name: {'cdp':cdp, 'lldp':lldp}}

    def process_neigbor_data(self, testbed, device_list, ip_net):
        '''
            Takes a testbed and processes the cdp and lldp data of every 
            device on the testbed that has not yet been visited 
        '''
        dev_to_test = []
        # Filter designed to get interface type from interface name
        # Ex: Ethernet0/2 becomes Ethernet
        interface_filter = re.compile(r'.+?(?=\d)')

        # if the device has not been visited add it to the list of devices
        # to get data from and add it to set of devices that have been examined
        for device in testbed.devices:
            if device not in self.visited_devices:
                self.visited_devices.add(device)
                dev_to_test.append(testbed.devices[device])
        
        # use pcall to get cdp and lldp information for all accessible devices
        result = pcall(self.get_neighbor_info,
                       device = dev_to_test)
        conn_dict = {}

        # process the connection data retrieved from getting cdp and lldp neighbors 
        # and write it into a dictionary
        for entry in result:
            for device in entry:
                conn_dict[device] = self.get_device_connections(entry[device], 
                                                                device, 
                                                                device_list, 
                                                                ip_net, 
                                                                testbed)

            # if device being visited doesn't have a given interface, 
            # add the interface
            for interface in conn_dict[device]:
                if interface not in testbed.devices[device].interfaces:
                    type_name = interface_filter.match(interface)
                    interface_a = Interface(interface,
                                            type = type_name[0].lower())
                    interface_a.device = testbed.devices[device]
        return conn_dict

    def _process_cdp_information(self, result, entry, device_list, ip_net, testbed, connection_dict):
        '''
            Process the cdp parser information and enters it into the 
            connection_dict and the device_list
        '''
        # filter to strip out the domain name from the system name
        domain_filter = re.compile(r'^.*?(?P<hostname>[-\w]+)\s?')

        for index in result['index']:

            # get the relevant information
            connection = result['index'][index]
            dest_host = connection.get('system_name')
            if not dest_host:
                dest_host = connection.get('device_id')
            m = domain_filter.match(dest_host)
            if m:
                dest_host = m.groupdict()['hostname']
            if self._topo_only and dest_host not in testbed.devices:
                log.info('Device {} does not exists in {}, skipping'.format(dest_host, testbed.name))
                continue

            dest_port = connection['port_id']
            interface = connection['local_interface']

            # if either the local or neigboring interface is in ignore list
            # do not log the connection on move on to the next one
            log.info('interface = {interface},'
                        'dest = {dest}'.format(interface = interface, 
                                            dest = dest_port))
            if interface in self._exclude_interfaces or dest_port in self._exclude_interfaces:
                log.info('connection or dest interface is found in' 
                        'ignore interface list, skipping connection')
                continue
            ip_set = set()

            # get the ip addresses for the neighboring device
            mgmt_address = connection.get('management_addresses')
            if mgmt_address is not None:
                ip_set.union({ip for ip in mgmt_address})
            
            ent_address = connection.get('entry_addresses')
            if ent_address is not None:
                ip_set.union({ip for ip in ent_address})

            # if the ip addresses for the connection are in the range given
            # by the cli, do not log the connection and move on
            for ip, net in product(ip_set, ip_net):
                if ipaddress.IPv4Address(ip) in net:
                    log.info('Ip {ip} found in' 
                            'ignored network {net}'.format(ip = ip, 
                                                           net = net))
                    break
            else:
                continue
            os = self.get_os(connection['software_version'], 
                                connection['platform'])

            # add the discovered information to 
            # both the connection_dict and the device_list
            self.add_to_device_list( device_list, 
                                dest_host, 
                                dest_port, 
                                ip_set, 
                                os, 
                                entry)
            self.add_to_connection_dict(connection_dict, 
                                    dest_host, 
                                    dest_port, 
                                    ip_set, 
                                    interface,
                                    entry)

    def _process_lldp_information(self, result, entry, device_list, ip_net, testbed, connection_dict):
        '''
            Process the lldp parser information and enters it into the 
            connection_dict and the device_list
        '''
        # filter to strip out the domain name from the system name
        domain_filter = re.compile(r'^.*?(?P<hostname>[-\w]+)\s?')

        for interface, connection in result['interfaces'].items():
            port_list = connection['port_id']
            for dest_port in port_list:
                dest_host = list(port_list[dest_port]['neighbors'].keys())[0]
                if self._topo_only and dest_host not in testbed.devices:
                    log.info('{} is not in initial testbed, skipping connection'.format(dest_host))
                    continue
                neighbor = port_list[dest_port]['neighbors'][dest_host]

                # if either the local or neigboring interface is in ignore list
                # do not log the connection on move on to the next one
                log.info('interface = {interface}, '
                            'dest = {dest}'.format(interface = interface, 
                                                dest = dest_port))
                if interface in self._exclude_interfaces:
                    log.info('connection interface {} is found in ' 
                            'ignore interface list, skipping connection'.format(interface))
                    continue
                if dest_port in self._exclude_interfaces:
                    log.info('destination interface {} is found in ' 
                            'ignore interface list, skipping connection'.format(dest_port))
                    continue

                # if the ip addresses for the connection are in the range given
                # by the cli, do not log the connection and move on
                ip_address = neighbor.get('management_address')
                if ip_address is None:
                    ip_address = neighbor.get('management_address_v4')
                if ip_address is not None and ip_net:
                    for net in ip_net:
                        if ipaddress.IPv4Address(ip_address) in net:
                            log.info('Ip {ip} found in ignored '
                                        'network {net}'.format(ip = ip_address, 
                                                            net = net))
                            break
                    else:
                        continue

                os = self.get_os(neighbor['system_description'], '')
                m = domain_filter.match(dest_host)
                if m:
                    dest_host = m.groupdict()['hostname']
                    
                # add the discovered information to both 
                # the connection_dict and the device_list    
                self.add_to_device_list(device_list, 
                                dest_host, 
                                dest_port, 
                                {ip_address}, 
                                os, 
                                entry)
                self.add_to_connection_dict(connection_dict, 
                                        dest_host, 
                                        dest_port, 
                                        ip_address, 
                                        interface,
                                        entry)

    def get_device_connections(self, data, entry, device_list, ip_net, testbed):
        '''
        Take a device from a testbed and find all the adjacent devices
        '''
        connection_dict = {}
        

        # get and parse cdp information
        result = data.get('cdp', []) 
        log.info('cdp neighbor information: {}'.format(result))
        if result:
            self._process_cdp_information(result, entry, device_list, ip_net, testbed, connection_dict)

        # get and parse lldp information
        result = data.get('lldp', []) 
        log.info('lldp neighbor information: {}'.format(result))
        if result and result['total_entries'] != 0:
            self._process_lldp_information(result, entry, device_list, ip_net, testbed, connection_dict)
            
        return connection_dict

    def add_to_device_list(self, device_list, dest_host, 
                           dest_port, ip_address, os, discover_name):
        '''
            Add the information needed to create the device in the 
            testbed later to the specified list
        '''
        if dest_host not in device_list:
            device_list[dest_host] = {'ports': {dest_port}, 
                                    'ip':ip_address, 
                                    'os': os,
                                    'finder': {discover_name}}
        else:
            if device_list[dest_host]['os'] is None:
                device_list[dest_host]['os'] = os
            device_list[dest_host]['ports'].add(dest_port)
            device_list[dest_host]['ip'] = device_list[dest_host]['ip'].union(ip_address)
            device_list[dest_host]['finder'].add(discover_name)

    def add_to_connection_dict(self, connection_dict, 
                               dest_host, dest_port, 
                               ip_address,interface, dev):
        '''
            Adds the information about a connection to be added to the topology
            recording what device interface combo is connected to the given
            interface and ip address involved in the connection
        '''
        new_entry = {'dest_host': dest_host, 
                    'dest_port': dest_port, 
                    'ip_address': ip_address}
        if interface not in connection_dict:
            connection_dict[interface] = [new_entry]
        else:
            for entry in connection_dict[interface]:

                # check that the connection being added is unique
                if (entry['dest_host'] == dest_host 
                        and entry['dest_port'] == dest_port):
                    break
            else:
                log.info('Connection device {} interface {} to' 
                         ' device {} interface {} found'.format(dev, 
                                                                interface, 
                                                                dest_host, 
                                                                dest_port))
                connection_dict[interface].append(new_entry)
                
    def get_credentials_and_proxies(self, testbed):
        '''
        Takes a copy of the current credentials in the testbed 
        for use in connecting to other devices
        '''
        credential_dict = {}
        proxy_list = set()
        for device in testbed['devices'].values():

            # get all connections used in the testbed
            if 'credentials' not in device:
                continue
            for cred in device['credentials']:
                if cred not in credential_dict :
                    credential_dict[cred] = dict(device['credentials'][cred])
                elif device['credentials'][cred] not in credential_dict.values():
                    credential_dict[cred + str(len(credential_dict))] = dict(device['credentials'][cred])

            # get list of proxies used in connections
            for connect in device['connections'].values():
                if 'proxy' in connect:
                    proxy_list.add(connect['proxy'])

        return credential_dict, proxy_list

    def get_os(self, system_string, platform_name):
        ''' 
        get the os from the system_description output from the show
        cdp and show lldp neighbor parsers
        '''
        if 'IOS' in system_string or 'IOS' in platform_name:
            if 'XE' in system_string or 'XE' in platform_name:
                return 'iosxe'
            elif 'XR' in system_string or 'XR' in platform_name:
                return 'iosxr'
            else:
                return 'ios'
        if 'NX-OS' in system_string or 'NX-OS' in platform_name:
            return 'nxos'

    def get_interfaces_ip_address(self, device):
        '''
        get the ip address for all of the generated interfaces
        on the give device
        '''
        if not device.is_connected() or device.os not in supported_os or len(device.interfaces) < 1:
            return
        for interface in device.interfaces.values():
            if interface.ipv4 is None or interface.ipv6 is None:
                ip = device.api.get_interface_ipv4_address(interface.name)
                if ip:
                    ip = ipaddress.IPv4Interface(ip)
                    interface.ipv4 = ip
        
    def create_yaml_dict(self, testbed, f1):
        '''
        Take the information laid out in the testbed and then format it into a
        dictionary to be integrated with the existing
        '''
        log.info('Creating dictionary based on testbed')
        yaml_dict = {'devices':{}, 'topology': {}}
        credential_dict, _ = self.get_credentials_and_proxies(f1)

        # write new devices into dict
        for device in testbed.devices.values():
            log.info('Adding device info for {}'.format(device.name))
            if device.name not in f1['devices']:
                yaml_dict['devices'][device.name] = {'type': device.type,
                                                    'os': device.os,
                                                    'credentials': credential_dict,
                                                    'connections': {}
                                                    }
                c = yaml_dict['devices'][device.name]['connections']
                for connect in device.connections:
                    try:
                        c[connect] = {'protocol':device.connections[connect]['protocol'],
                                      'ip': device.connections[connect]['ip'],
                                    }
                    except Exception:
                        continue

            # write in the interfaces and link from devices into testbed
            interface_dict = {'interfaces': {}}
            log.info('Adding interface infor for {}'.format(device.name))        
            for interface in device.interfaces.values():
                interface_dict['interfaces'][interface.name] = {'type': interface.type}
                if interface.link is not None:
                    interface_dict['interfaces'][interface.name]['link'] = interface.link.name
                if interface.ipv4 is not None:
                    interface_dict['interfaces'][interface.name]['ipv4'] = str(interface.ipv4)
            # add interface information into the topology part of yaml_dict
            yaml_dict['topology'][device.name] = interface_dict
        log.info('topology discovered is: {}'.format(yaml_dict['topology']))

        # combine and add the new information to existing info
        log.info('combining existing testbed with new topology')
        for device in yaml_dict['devices']:
            if device not in f1['devices']:
                f1['devices'][device] = yaml_dict['devices'][device]
        if f1.get('topology') is None:
            f1['topology'] = yaml_dict['topology']
        else:
            for device in yaml_dict['topology']:
                if device not in f1['topology']:
                    f1['topology'][device] = yaml_dict['topology'][device]
                else:
                    f1['topology'][device]['interfaces'].update(yaml_dict['topology'][device]['interfaces'])

    def _write_devices_into_testbed(self, device_list, proxy_set, credential_dict, testbed):
        '''
            Writes any new devices found in the device list into the testbed
            and adds any missing interfaces into devices that are missing it
        '''
        # filter to strip out the numbers from an interface to create a type name
        # example: ethernet0/3 becomes ethernet
        interface_filter = re.compile(r'.+?(?=\d)')
        new_devices = {}

        for new_dev in device_list:
            if new_dev not in testbed.devices:
                log.info('New device {} found and'
                        ' being added to testbed'.format(new_dev))
                connections = {}

                # create connections for the ip addresses in the device list
                for count, ip in enumerate(device_list[new_dev]['ip']):
                    if count == 0:
                        count = 'default'
                    for proxy in proxy_set:

                        # create connection using possible proxies
                        connections[str(count) + proxy] = {
                            'protocol': 'ssh',
                            'ip': ip,
                            'proxy': proxy
                            }

                    # create connection to device with given ip using a device that found it
                    connections[str(count) + 'finder_proxy'] = {
                            'protocol': 'telnet',
                            'ip': ip,
                            'proxy': device_list[new_dev]['finder']
                            }

                # create the new device
                dev = Device(new_dev,
                            os = device_list[new_dev]['os'],
                            credentials = credential_dict,
                            type = 'device',
                            connections = connections,
                            custom = {'abstraction':
                                        {'order':['os'],
                                        'os': device_list[new_dev]['os']}
                                    })

                # create and add the interfaces for the new device
                for interface in device_list[new_dev]['ports']:
                    type_name = interface_filter.match(interface)
                    interface_a = Interface(interface,
                                            type = type_name[0].lower())
                    interface_a.device = dev
                new_devices[dev.name] = dev

            # if the device is already in the testbed, check if the interface exists or not
            else:
                if not self._all_interfaces:
                    for interface in device_list[new_dev]['ports']:
                        if interface not in testbed.devices[new_dev].interfaces:
                            type_name = interface_filter.match(interface)
                            interface_a = Interface(interface,
                                                    type = type_name[0].lower())
                            interface_a.device = testbed.devices[new_dev]
                else:
                    try:
                        interface_list = testbed.devices[new_dev].parse('show interfaces description')
                    except Exception:
                        interface_list = testbed.devices[new_dev].parse('show interface description')
                    for interface in interface_list['interfaces']:
                        if interface not in testbed.devices[new_dev].interfaces:
                            type_name = interface_filter.match(interface)
                            interface_a = Interface(interface,
                                                    type = type_name[0].lower())
                            interface_a.device = testbed.devices[new_dev]
        return new_devices

    def _write_connections_to_testbed(self, result, testbed):
        '''
            Writes the connections found in the results into the testbed
        '''
        for device in result:
            for interface_name in result[device]:
                # get the interface found in the connection on the device searched
                interface = testbed.devices[device].interfaces[interface_name]

                # if the interface is not already part of a link get a list of 
                # all interfaces involved in the link and create a new link 
                # object with the associated interfaces
                if interface.link is None:
                    int_list = [interface]
                    name_set = {device}
                    for entry in result[device][interface_name]:
                        dev = entry['dest_host']
                        name_set.add(dev)
                        dest_int = entry['dest_port']
                        if testbed.devices[dev].interfaces[dest_int] not in int_list:
                            int_list.append(testbed.devices[dev].interfaces[dest_int])
                    link = Link('Link_{num}'.format(num = len(testbed.links)),
                                interfaces = int_list)

                # if the interface is already part of the link go over the 
                # other interfaces found in the result and add them to the link
                # if they are not there already
                else:
                    link = interface.link
                    for entry in result[device][interface_name]:
                        dev = entry['dest_host']
                        dest_int = entry['dest_port']
                        if testbed.devices[dev].interfaces[dest_int] not in link.interfaces:
                            link.connect_interface(testbed.devices[dev].interfaces[dest_int])

    def _generate(self):
        """ Takes testbed information and writes the topology information into
            a yaml file
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.
    
        """
        testbed = load(self._testbed_name)
        with open(self._testbed_name, 'r') as stream:
            try:
                f1 = safe_load(stream)
            except YAMLError as exc:
                log.error('error opening yaml file: {}'.format(exc))
        ip_net = []
        if self._exclude_network:
            ips = self._exclude_network.strip(',')
            for ip in ips:
                try:
                    ip_net.append(ipaddress.ip_network(ip))
                except Exception:
                    log.error('Ip range given {ip} is not valid'.format(ip=ip))
        # get the credentials and proxies that are used so that they can be used 
        # when attempting to other devices on the testbed
        credential_dict, proxy_set = self.get_credentials_and_proxies(f1)
        device_list = {}

        while len(testbed.devices) > len(self.visited_devices):
            self.connect_all_devices(testbed, 
                                    len(testbed.devices))
            new_devices = {}
            #get a dictionary of all currently accessable devices connections
            result = self.process_neigbor_data(testbed, device_list, ip_net)
            log.info('Connections found in current set of devices: {}'.format(result))

            # add any new devices found to test bed
            self._write_devices_into_testbed(device_list, proxy_set, credential_dict, testbed)

            # add new devices to testbed
            for device in new_devices.values():
                device.testbed = testbed
            
            # add the connections that were found to the topology
            self._write_connections_to_testbed(result, testbed)
            
            if self._topo_only:
                break

        # get Ip address for interfaces
        for device in testbed.devices.values():
            self.get_interfaces_ip_address(device)

        # unconfigure devices that had settings changed
        pcall(self.unconfigure_neighbor_discovery_protocols,
              device= testbed.devices.values()
        )
        self.create_yaml_dict(testbed, f1)
        
        return f1