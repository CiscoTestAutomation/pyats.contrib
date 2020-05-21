import os
from collections import OrderedDict
import ipaddress
import argparse
import logging
import sys
import subprocess
import re
import pprint
from genie.conf.base import Testbed, Device, Interface, Link
from concurrent.futures import ThreadPoolExecutor
from yaml import (ScalarEvent, MappingEndEvent, MappingStartEvent, AliasEvent,
                  SequenceEndEvent, SequenceStartEvent, DocumentEndEvent,
                  DocumentStartEvent, StreamEndEvent, StreamStartEvent, emit,
                  resolver, Dumper, dump, YAMLError, safe_load)

from genie.conf import Genie
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
                'exclude_ip': '',
                'ignore_interfaces':''
            }
        }
    
    def connect_one_device(self, testbed, device):
        
        if not testbed.devices[device].connections:
            return {device: testbed.devices[device].is_connected()}
        if testbed.devices[device].is_connected():
            return testbed.devices[device].is_connected()             
        for one_connect in testbed.devices[device].connections:                         
            try:
                testbed.devices[device].connect(via = str(one_connect),
                                                connection_timeout = 10,
                                                learn_hostname = True)
                break
            except Exception as e:
                print(e)
                testbed.devices[device].destroy()               
        return testbed.devices[device].is_connected()

    def connect_all_devices(self, testbed, limit):
        '''
        Creates a ThreadPoolExecutor designed to connect to each device in testbed
        
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
            entries[block].append(device)
            i += 1
        
        # Set up a thread pool executor to connect to all devices at the same time    
        for block in entries:
            with ThreadPoolExecutor(max_workers = limit) as executor:
                for entry in block:
                    log.info('attempting to connect to {entry}'.format(entry = entry))
                    results[entry] = executor.submit(self.connect_one_device,
                                                    testbed,
                                                    entry)
        return results


    def configure_cdp_lldp_testbed (self, testbed, config_off):
        """
        Enables cdp and lldp for all devices in the testbed and recordes what
        was enabled so that they can be turned off later
        
        Args:
            testbed: testbed of devices to enable
            config_off: toggle that makes script skip enabling cdp/lldp on devices
        
        Returns:
            cdp_changed: set of devices where cdp was enabled
            lldp_changed: set of devices where lldp was enabled
        """
        cdp_changed = set()
        lldp_changed = set()
        if config_off:
            return cdp_changed, lldp_changed
        for device in testbed.devices.values():
            if device.os not in os_list:
                continue
            if not device.api.verify_cdp_status():
                try:
                    device.api.configure_cdp()
                except:
                    log.error("Exception configuring cdp for {device}".format(device = device), exc_info = True)
                cdp_changed.add(device.name)
            if not device.api.verify_lldp_status():
                try:
                    device.api.configure_lldp()
                except:
                    log.error("Exception configuring cdp for {device}".format(device = device), exc_info = True)
                lldp_changed.add(device.name)
        return cdp_changed, lldp_changed

    def unconfigure_cdp_lldp_testbed(self, testbed, cdp_set, lldp_set):
        '''
        unconfigures the cdp and lldp of devices that were enabled at the 
        start of the script
        Args:
            testbed: testbed of devices to unconfigure
            cdp_set: list of devices to unconfigure cdp on
            lldp_set: list of devices to unconfigure lldp on
        '''
        for device in cdp_set:
            try:
                testbed.devices[device].api.unconfigure_cdp()
            except:
                log.error("Exception unconfiguring cdp for {device}".format(device = device), exc_info = True)
        for device in lldp_set:
            try:
                testbed.devices[device].api.unconfigure_lldp()
            except:
                log.error("Exception unconfiguring lldp for {device}".format(device = device), exc_info = True)

    def get_device_connections(self, device, device_list, ip_net, int_skip):
        '''
        Take a device from a testbed and find all the adjacent devices
        '''
        log.info('{device} connection info:'.format(device = device.name))
        if not device.is_connected():
            return None
        connection_dict = {}
        # if the device isn't of an os that parsers can be run on stop
        if device.os not in os_list:
            return connection_dict
        # filter to strip out the domain name from the system name
        domain_filter = re.compile(r'^.*?(?P<hostname>[-\w]+)\s?')

        # get and parse cdp information
        result = device.api.get_cdp_neighbors_info()
        log.info(result)
        if result is not None:
            #for every cdp entry find the os, destination name, destination port, and the ip-address and then add them to the relevant lists
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
                log.info('interface = {interface}, dest = {dest}'.format(interface = interface, dest = dest_port))
                if interface in int_skip or dest_port in int_skip:
                    log.info('skiped connection')
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
                    print(ip)
                    if ip_net is not None and ipaddress.IPv4Address(ip) in ip_net:
                        skip = True
                if skip:
                    continue
                os = self.get_os(connection['software_version'], connection['platform'])
                # add the discovered information to both the connection_dict and the device_list
                self.add_to_device_list( device_list, 
                                    dest_host, 
                                    dest_port, 
                                    ip_set, 
                                    os, 
                                    device.name)
                self.add_to_connection_dict(connection_dict, 
                                        dest_host, 
                                        dest_port, 
                                        ip_set, 
                                        interface)
        # get and parse lldp information
        result = device.api.get_lldp_neighbors_info()
        log.info(result)
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
                    log.info('interface = {interface}, dest = {dest}'.format(interface = interface, dest = dest_port))
                    if interface in int_skip or dest_port in int_skip:
                        log.info('skiped connection')
                        continue
                    # if the ip addresses for the connection are in the range given
                    # by the cli, do not log the connection and move on
                    ip_address = neighbor.get('management_address')
                    if ip_address is None:
                        ip_address = neighbor.get('management_address_v4')
                    if ip_net is not None and ipaddress.IPv4Address(ip_address) in ip_net:
                        continue

                    os = self.get_os(port_list[dest_port]['neighbors'][dest_host]['system_description'], '')
                    m = domain_filter.match(dest_host)
                    if m:
                        dest_host = m.groupdict()['hostname']
                    # add the discovered information to both the connection_dict and the device_list    
                    self.add_to_device_list(device_list, 
                                    dest_host, 
                                    dest_port, 
                                    {ip_address}, 
                                    os, 
                                    device.name)
                    self.add_to_connection_dict(connection_dict, 
                                            dest_host, 
                                            dest_port, 
                                            ip_address, 
                                            interface)
        return connection_dict

    def add_to_device_list(self, device_list, dest_host, dest_port, ip_address, os, discover_name):
        '''
            Add the information needed to create the device in the testbed later to the specified
            list
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

    def add_to_connection_dict(self, connection_dict, dest_host, dest_port, ip_address,interface):
        '''
            Adds the information about a connection to be added to the topology
            recording what device interface combo is connected to the given
            interface and ip address involced in the connection
        '''
        new_entry = {'dest_host': dest_host, 
                    'dest_port': dest_port, 
                    'ip_address': ip_address}
        if interface not in connection_dict:
            connection_dict[interface] = [new_entry]
        else:
            unique = True
            for entry in connection_dict[interface]:
                if (entry['dest_host'] == dest_host and entry['dest_port'] == dest_port):
                    unique = False
                    break
            if unique:
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

    def get_interface_ip_address(self, device):
        if not device.is_connected() or device.os not in os_list:
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
        yaml_dict = {'devices':{}, 'topology': {}}
        credential_dict, _ = self.get_credentials_and_proxies(f1)
        for device in testbed.devices.values():
            if device.name not in f1['devices']:
                yaml_dict['devices'][device.name] = {'type': device.type,
                                                    'os': device.os,
                                                    'credentials': credential_dict,
                                                    'connections': {}
                                                    }
                c = yaml_dict['devices'][device.name]['connections']
                for connect in device.connections:
                    try:
                        pprint.pprint(device.connections[connect])
                        c[connect] = {'protocol': device.connections[connect]['protocol'],
                                        'ip': device.connections[connect]['ip'],
                                        }
                    except:
                        continue
            interface_dict = {'interfaces': {}}        
            for interface in device.interfaces.values():
                interface_dict['interfaces'][interface.name] = {'type': interface.type,
                                                                'link': interface.link.name}
                if interface.ipv4 is not None:
                    interface_dict['interfaces'][interface.name]['ipv4'] = str(interface.ipv4)
            yaml_dict['topology'][device.name] = interface_dict
        return yaml_dict

    def _generate(self):
        """ Takes testbed information and writes
        
        Returns:
            dict: The intermediate dictionary format of the testbed data.
    
        """
        print(self._testbed_name)
        testbed = Genie.init(self._testbed_name)
        with open(self._testbed_name, 'r') as stream:
            try:
                f1 = safe_load(stream)
            except YAMLError as exc:
                print(exc)
        ip_net = None
        if self._exclude_ip:
            try:
                ip_net = ipaddress.ip_network(self._exclude_ip)
            except:
                log.error('Ip range given is not valid')
        # get the credentials and proxies that are used so that they can be used 
        # when attempting to other devices on the testbed
        credential_dict, proxy_set = self.get_credentials_and_proxies(f1)
        pprint.pprint(credential_dict)
        # set used to track if a device has been visited or not
        visited_devices = set()

        # filter to strip out the numbers from an interface to create a type name
        # example: ethernet0/3 becomes ethernet
        interface_filter = re.compile(r'.+?(?=\d)')
        device_list = {}

        #while len(testbed.devices) > len(visited_devices):
        self.connect_all_devices(testbed, len(testbed.devices))
        cdp, lldp = self.configure_cdp_lldp_testbed(testbed, self._config_off)
        result = {}
        new_devices = {}
        for device in testbed.devices:
            # skip over device if connection to device couldn't be made or 
            # the device has been visited
            if device in visited_devices or not testbed.devices[device].is_connected() or device in proxy_set:
                visited_devices.add(device)
                continue
            result[device] = self.get_device_connections(testbed.devices[device], device_list, ip_net, self._ignore_interfaces)

            # if device being visited doesn't have a given interface, 
            # add the interface
            for interface in result[device]:
                if interface not in testbed.devices[device].interfaces:
                    type_name = interface_filter.match(interface)
                    interface_a = Interface(interface,
                                            type = type_name[0].lower())
                    interface_a.device = testbed.devices[device]

            # add device to visited list
            visited_devices.add(device)
        pprint.pprint(result)
        # add any new devices found to test bed
        for new_dev in device_list:
            if new_dev not in testbed.devices:
                connections = {}
                # create connections for the ip addresses in the device list
                # TO DO: add connect through ssh, connect through the device that discovered the new dev
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
                    # create connection to device with given ip without using a procy
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
                    print(interface_list)
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
                # if the interface is not already part of a link get a list of all interfaces involved in the link and create a new link object with the associated interfaces
                if interface.link is None:
                    int_list = [interface]
                    name_set = {device}
                    for entry in result[device][interface_name]:
                        dev = entry['dest_host']
                        name_set.add(dev)
                        dest_int = entry['dest_port']
                        int_list.append(testbed.devices[dev].interfaces[dest_int])
                    link = Link('Link_{num} '.format(num = len(testbed.links)),
                                interfaces = int_list)
                # if the interface is already part of the link go over the other interfaces found in the result and add them to the link if they are not there already
                else:
                    link = interface.link
                    for entry in result[device][interface_name]:
                        dev = entry['dest_host']
                        dest_int = entry['dest_port']
                        if testbed.devices[dev].interfaces[dest_int] not in link.interfaces:
                            link.connect_interface(testbed.devices[dev].interfaces[dest_int])

        # get Ip address for interfaces
        for device in testbed.devices.values():
            self.get_interface_ip_address(device)

        self.unconfigure_cdp_lldp_testbed(testbed, cdp, lldp)
        f2 = self.create_yaml_dict(testbed, f1)
        log.info(f2)
        # combine and add the new information to existing info
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