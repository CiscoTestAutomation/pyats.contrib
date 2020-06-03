import os
from collections import OrderedDict
import ipaddress
import argparse
import logging
import sys
import subprocess
import re
from yaml import (ScalarEvent, MappingEndEvent, MappingStartEvent, AliasEvent,
                  SequenceEndEvent, SequenceStartEvent, DocumentEndEvent,
                  DocumentStartEvent, StreamEndEvent, StreamStartEvent, emit,
                  resolver, Dumper, dump, YAMLError, safe_load)
from concurrent.futures import ThreadPoolExecutor
import pprint
from genie.conf.base import Testbed, Device, Interface, Link
from genie.conf import Genie
from pyats.async_ import pcall
from .creator import TestbedCreator
from genie.metaparser.util.exceptions import SchemaEmptyParserError
import time
log = logging.getLogger(__name__)
    
os_list = ['nxos', 'iosxr', 'iosxe', 'ios']

class Topology(TestbedCreator):
    
    """ Topology class (TestbedCreator)

    Creates a yaml file that

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.
        Returns:
            dict: Arguments for the creator.
        """
        return {
            'required': ['testbed_name'],
            'optional': {
                'config_off': False,
                'all_interfaces': False,
                'exclude_network': '',
                'ignore_interfaces':''
            }
        }
    
    def connect_one_device(self, testbed, device, config_off):
        
        if testbed.devices[device].os not in os_list:
            return [False, False]          
        for one_connect in testbed.devices[device].connections:                         
            try:
                testbed.devices[device].connect(via = str(one_connect),
                                                connection_timeout = 10,
                                                learn_hostname = True)
                break
            except Exception:
                testbed.devices[device].destroy()               
        cdp = False
        lldp = False
        dev = testbed.devices[device]
        if not dev.is_connected():
            log.info('Device {} is not connected skipping' 
                     ' cdp/lldp configuration'.format(dev.name))
            return [False, False]
        if dev.is_connected() and not config_off:
            if not dev.api.verify_cdp_status(max_time=10, check_interval=5):
                try:
                    dev.api.configure_cdp()
                    cdp = True
                except Exception:
                    log.error("Exception configuring cdp " 
                              "for {device}".format(device = device), 
                                                    exc_info = True)
            if not dev.api.verify_lldp_status(max_time=10, check_interval=5):
                try:
                    dev.api.configure_lldp()
                    lldp = True
                except Exception:
                    log.error("Exception configuring cdp" 
                              " for {device}".format(device = device), 
                                                     exc_info = True)    
        return [cdp, lldp]


    def connect_all_devices(self, testbed, limit, config_off):
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
        entries = []
        i = limit
        block = -1
        
        # Incase limit set by user is less than number of devices,
        # the first loop sets up commands to be run in sets of size limit,
        # then the second loop calls the apis in block sets
        for device in testbed.devices:
            if i == limit:
                entries.append([])
                i = 0
                block += 1
            if not testbed.devices[device].is_connected():
                entries[block].append(device)
            i += 1
        
        # Set up a thread pool executor to connect to all devices at the same time    
        for block in entries:
            with ThreadPoolExecutor(max_workers = limit) as executor:
                for entry in block:
                    log.info('attempting to connect to {entry}'.format(entry = entry))
                    results[entry] = executor.submit(self.connect_one_device,
                                                    testbed,
                                                    entry,
                                                    config_off)
        cdp_set = set()
        lldp_set = set()
        for entry in results:
            if results[entry].result()[0]:
                cdp_set.add(entry)
            if results[entry].result()[1]:
                lldp_set.add(entry)
        log.info('Devices that had cdp enabled:{}, '
                 'Devices that had lldp enabled: {}'.format(cdp_set, lldp_set))
        return cdp_set, lldp_set

    def unconfigure_device(self, cdp, lldp, device):
        '''
            using the sets given disable lldp and cdp if enabled by script on 
            device
        '''
        if device.name in cdp:
            device.api.unconfigure_cdp()
        if device.name in lldp:
            device.api.unconfigure_lldp()

    def process_neigbor_data(self, testbed, device_list, ip_net, int_skip, visited_devices):
        '''
            Takes a testbed and processes the cdp and lldp data of every 
            device on the testbed that has not yet been visited 
        '''
        dev_to_test = []
        interface_filter = re.compile(r'.+?(?=\d)')
        for device in testbed.devices:
            if device not in visited_devices:
                visited_devices.add(device)
                dev_to_test.append(testbed.devices[device])
        
        # use pcall to get cdp and lldp information for all accessible devices
        result = pcall(self.get_neighbor_info,
                       device = dev_to_test)
        conn_dict = {}
        # process the data retireved and write it into a dictionary
        for entry in result:
            for device in entry:
                conn_dict[device] = self.get_device_connections(entry[device], 
                                                                device, 
                                                                device_list, 
                                                                ip_net, 
                                                                int_skip)
        # if device being visited doesn't have a given interface, 
        # add the interface
            for interface in conn_dict[device]:
                if interface not in testbed.devices[device].interfaces:
                    type_name = interface_filter.match(interface)
                    interface_a = Interface(interface,
                                            type = type_name[0].lower())
                    interface_a.device = testbed.devices[device]
        return conn_dict

    def get_neighbor_info(self, device):
        '''
        Method designed to be used with pcall, gets the devices cdp and lldp
        neighbor data and then returns it in a dictionary format
        '''
        cdp = None
        lldp = None
        if device.os not in os_list:
            return {device.name: {'cdp':cdp, 'lldp':lldp}}
        try:
            cdp = device.api.get_cdp_neighbors_info()
        except:
            log.error("Exception occurred getting cdp info", exc_info = True)
        try:
            lldp = device.api.get_lldp_neighbors_info()
        except:
            log.error("Exception occurred getting lldp info", exc_info = True)
        return {device.name: {'cdp':cdp, 'lldp':lldp}}

    def get_device_connections(self, data, entry, device_list, ip_net, int_skip):
        '''
        Take a device from a testbed and find all the adjacent devices
        '''
        connection_dict = {}
        # filter to strip out the domain name from the system name
        domain_filter = re.compile(r'^.*?(?P<hostname>[-\w]+)\s?')

        # get and parse cdp information
        result = data['cdp']
        if result is not None:
            # for every cdp entry find the os, destination name, destination 
            # port, and the ip-address and then add them to the relevant lists
            for index in result['index']:
                # get the relevant information
                connection = result['index'][index]
                dest_host = connection.get('system_name')
                if not dest_host:
                    dest_host = connection.get('device_id')
                m = domain_filter.match(dest_host)
                if m:
                    dest_host = m.groupdict()['hostname']
                dest_port = connection['port_id']
                interface = connection['local_interface']
                # if either the local or neigboring interface is in ignore list
                # do not log the connection on move on to the next one
                log.info('interface = {interface},'
                         'dest = {dest}'.format(interface = interface, 
                                                dest = dest_port))
                if interface in int_skip or dest_port in int_skip:
                    log.info('connection or dest interface is found in' 
                            'ignore interface list, skipping connection')
                    continue
                ip_set = set ()
                # get the ip addresses for the neighboring device
                x = connection.get('management_addresses')
                if x is not None:
                    for address in x:
                        ip_set.add(address)
                
                x = connection.get('entry_addresses')
                if x is not None:
                    for address in x:
                        ip_set.add(address)
                skip = False
                # if the ip addresses for the connection are in the range given
                # by the cli, do not log the connection and move on
                for ip in ip_set:
                    if ip_net is not None:
                        for net in ip_net:
                            if ipaddress.IPv4Address(ip) in net:
                                log.info('Ip {ip} found in' 
                                        'ignored network {net}'.format(ip = ip, 
                                                                       net = net))
                                skip = True
                if skip:
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

        # get and parse lldp information
        result = data['lldp']
        log.info('lldp neighbor information: {}'.format(result))
        if result is not None and result['total_entries'] != 0:
            for interface in result['interfaces']:
                connection = result['interfaces'][interface]
                port_list = connection['port_id']
                for port in port_list:
                    dest_port = port
                    dest_host = list(port_list[port]['neighbors'].keys())[0]
                    neighbor = port_list[dest_port]['neighbors'][dest_host]

                    # if either the local or neigboring interface is in ignore list
                    # do not log the connection on move on to the next one
                    log.info('interface = {interface}, '
                             'dest = {dest}'.format(interface = interface, 
                                                    dest = dest_port))
                    if interface in int_skip or dest_port in int_skip:
                        log.info('connection or dest interface is found in ' 
                                 'ignore interface list, skipping connection')
                        continue

                    # if the ip addresses for the connection are in the range given
                    # by the cli, do not log the connection and move on
                    ip_address = neighbor.get('management_address')
                    if ip_address is None:
                        ip_address = neighbor.get('management_address_v4')
                    if ip_address is not None and ip_net:
                        skip = False
                        for net in ip_net:
                            if ipaddress.IPv4Address(ip) in net:
                                log.info('Ip {ip} found in ignored '
                                         'network {net}'.format(ip = ip, 
                                                                net = net))
                                skip = True
                        if skip:
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
                                    'finder': discover_name}
        else:
            if device_list[dest_host]['os'] is None:
                device_list[dest_host]['os'] = os
            device_list[dest_host]['ports'].add(dest_port)
            device_list[dest_host]['ip'] = device_list[dest_host]['ip'].union(ip_address)

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
            unique = True
            for entry in connection_dict[interface]:

                # check that the connection being added is unique
                if (entry['dest_host'] == dest_host 
                        and entry['dest_port'] == dest_port):
                    unique = False
                    break
            if unique:
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
            for cred in device['credentials']:
                if cred not in credential_dict :
                    credential_dict[cred] = dict(device['credentials'][cred])
                elif device['credentials'][cred] not in credential_dict.values():
                    credential_dict[cred + str(len(credential_dict))] = dict(device['credentials'][cred])

            #get list of proxies used in connections
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
        if (not device.is_connected() or device.os not in os_list 
            or len(device.interfaces) < 1):
            return
        for interface in device.interfaces.values():
            if interface.ipv4 is None or interface.ipv6 is None:
                ip = device.api.get_interface_ip_address(interface.name)
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
                    except:
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
        return yaml_dict

    def _generate(self):
        """ Takes testbed information and writes the topology information into
            a yaml file
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.
    
        """
        testbed = Genie.init(self._testbed_name)
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
                except:
                    log.error('Ip range given {ip} is not valid'.format(ip=ip))
        # get the credentials and proxies that are used so that they can be used 
        # when attempting to other devices on the testbed
        credential_dict, proxy_set = self.get_credentials_and_proxies(f1)
        # set used to track if a device has been visited or not
        visited_devices = set()

        # filter to strip out the numbers from an interface to create a type name
        # example: ethernet0/3 becomes ethernet
        interface_filter = re.compile(r'.+?(?=\d)')
        device_list = {}

        #while len(testbed.devices) > len(visited_devices):
        cdp, lldp = self.connect_all_devices(testbed, 
                                             len(testbed.devices),
                                             self._config_off)
        result = {}
        new_devices = {}
        
        #get a dictionary of all currently accessable devices connections
        result = self.process_neigbor_data(testbed, device_list, ip_net, 
                                           self._ignore_interfaces, 
                                           visited_devices)
        log.info('Connections found in current set of devices: {}'.format(result))
        # add any new devices found to test bed
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
                            'settings':{'ESCAPE_CHAR_CHATTY_TERM_WAIT': 0.5,
                                        'ESCAPE_CHAR_PROMPT_WAIT': 0.5},
                            'proxy': proxy
                            }
                    # create connection to device with given ip without using a proxy
                    connections[str(count) + 'no_proxy'] = {
                            'protocol': 'telnet',
                            'ip': ip,
                            'settings':{'ESCAPE_CHAR_CHATTY_TERM_WAIT': 0.5,
                                        'ESCAPE_CHAR_PROMPT_WAIT': 0.5},
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
                    except:
                        interface_list = testbed.devices[new_dev].parse('show interface description')
                    for interface in interface_list['interfaces']:
                        if interface not in testbed.devices[new_dev].interfaces:
                            type_name = interface_filter.match(interface)
                            interface_a = Interface(interface,
                                                    type = type_name[0].lower())
                            interface_a.device = testbed.devices[new_dev]
        # add new devices to testbed
        for device in new_devices.values():
            device.testbed = testbed
        

        # add the connections that were found to the topology
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

        # get Ip address for interfaces
        for device in testbed.devices.values():
            self.get_interfaces_ip_address(device)

        # unconfigure devices that had settings changed
        pcall(self.unconfigure_device,
              cargs = (cdp, lldp), 
              device= testbed.devices.values()
        )
        f2 = self.create_yaml_dict(testbed, f1)
        # combine and add the new information to existing info
        log.info('combining existing testbed with new topology')
        for device in f2['devices']:
            if device not in f1['devices']:
                f1['devices'][device] = f2['devices'][device]
        if f1.get('topology') is None:
            f1['topology'] = f2['topology']
        else:
            for device in f2['topology']:
                if device not in f1['topology']:
                    f1['topology'][device] = f2['topology'][device]
                else:
                    f1['topology'][device]['interfaces'].update(f2['topology'][device]['interfaces'])
        return f1