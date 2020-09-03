import logging
import argparse
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from genie.conf.base import Testbed, Device, Interface, Link
from pyats.async_ import pcall
from pyats.log import TaskLogHandler
from pyats.log import ScreenHandler

log = logging.getLogger(__name__)

class TestbedManager(object):
    '''Class designed to handle device interactions for connecting devices
       and cdp and lldp
    '''
    def __init__(self, testbed, supported_os, config=False, ssh_only=False, alias_dict={},
                 timeout=10, logfile = '', disable_config=False):

        self.config = config
        self.ssh_only = ssh_only
        self.testbed = testbed
        self.alias_dict = alias_dict
        self.timeout = int(timeout)
        self.cdp_configured = set()
        self.lldp_configured = set()
        self.visited_devices = set()
        self.supported_os = supported_os
        self.logfile = logfile
        if disable_config:
            self.disable_config = []
        else:
            self.disable_config = None

    def connect_all_devices(self, limit):
        '''Creates a ThreadPoolExecutor designed to connect to each device in parallel
        after it takes the connection results of the objects and sorts them into three
        sets for logging purposes

        Args:
            limit ('int'): max number of threads to spawn
            
        Returns:
            three sets for devices that were connected, failed to connect to, and skipped
        '''
        
        results = {}
        success = set()
        fail = set()
        skip = set()
        
        # Set up a thread pool executor to connect to all devices at the same time
        with ThreadPoolExecutor(max_workers = limit) as executor:
            for device_name, device_obj in self.testbed.devices.items():
                # If already connected or device has already been visited skip
                if device_obj.connected or device_name in self.visited_devices:
                    continue
                if device_obj.os not in self.supported_os:
                    log.debug('     Device {} does not have valid os, skipping'.format(device_name))
                    skip.add(device_name)
                    continue
                log.debug('     Attempting to connect to {device}'.format(device=device_name))
                results[device_name] = executor.submit(self._connect_one_device,
                                                       device_name)
        
        for name, exe in results.items():
            if exe.result():
                success.add(name)
            else:
                fail.add(name)

        return success, fail, skip
        
        
    def _connect_one_device(self, device):
        '''Connect to the given device in the testbed using the given
        connections and after that enable cdp and lldp if allowed

        Args:
            device ('str'): name of device being connected
        '''
        # when -v is used root logger effective level will be set to debug so
        # script will set st_out for devices to true so device data will be sent ton
        # console
        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            to_stdout = True
        else:
            to_stdout = False
            
        # if there is a preferred alias for the device, attempt to connect with device
        # using that alias, if the attempt fails or the alias doesn't exist, it will
        # attempt to connect with the default
        if device in self.alias_dict:
            if self.alias_dict[device] in self.testbed.devices[device].connections:
                log.debug('     Attempting to connect to {} with alias {}'.format(device, self.alias_dict[device]))
                try:
                    self.testbed.devices[device].connect(via = str(self.alias_dict[device]),
                                                         connection_timeout=self.timeout,
                                                         log_stdout=to_stdout,
                                                         logfile = self.logfile,
                                                         learn_os = True,
                                                         init_config_commands = self.disable_config)
                    log.debug('     Connected to device {}'.format(device))
                except Exception as e:
                    log.debug('     Failed to connect to {} with alias {}'.format(device, self.alias_dict[device]))
                    self.testbed.devices[device].destroy(str(self.alias_dict[device]))
                else:
                    
                    # No exception raised - get out
                    return self.testbed.devices[device].connected
            else:
                log.debug('     Device {} does not have a connection with alias {}'.format(device, self.alias_dict[device]))

        # Use default - Go through all connection on the device
        for one_connect in self.testbed.devices[device].connections:
            # if ssh_only is not enabled try to connect through all connections
            if one_connect == 'defaults':
                continue
            if not self.ssh_only:
                try:
                    self.testbed.devices[device].connect(via = str(one_connect),
                                                         connection_timeout=self.timeout,
                                                         log_stdout=to_stdout,
                                                         logfile = self.logfile,
                                                         learn_os = True,
                                                         init_config_commands = self.disable_config)
                    log.debug('     Connected to device {}'.format(device))
                    break
                except Exception as e:
                    log.debug('     Failed to connect to {name} using connection {conn}'.format(name = device, conn = one_connect))                   
                    # if connection fails, erase the connection from connection mgr
                    self.testbed.devices[device].destroy(str(one_connect))
                continue

            # if ssh only is enabled, check if the connection protocol is ssh before trying to connect
            if self.testbed.devices[device].connections[one_connect].get('protocol', '') == 'ssh':
                try:
                    self.testbed.devices[device].connect(via=str(one_connect),
                                                         connection_timeout=self.timeout,
                                                         log_stdout=to_stdout,
                                                         logfile = self.logfile,
                                                         learn_os = True,
                                                         init_config_commands = self.disable_config)
                    log.debug('     Connected to device {}'.format(device))
                    break
                except Exception as e:
                    # if connection fails, erase the connection from connection mgr
                    log.debug('     Failed to connect to {name} using connection {conn}'.format(name = device, conn = one_connect))
                    self.testbed.devices[device].destroy(str(one_connect))
        
        if not self.testbed.devices[device]:
            log.debug('     Failed to connect to {}'.format(device))
        return self.testbed.devices[device].connected
                

    def configure_testbed_cdp_protocol(self):
        ''' Method checks if cdp configuration is necessary for all devices in
        the testbed and if needed calls the cdp configuration method for the
        target devices in parallel
        '''

        # Check which device to configure CDP on
        device_to_configure=[]
        for device_name, device_obj in self.testbed.devices.items():
            if device_name in self.visited_devices or device_name in self.cdp_configured or not device_obj.connected or device_obj.os not in self.supported_os:
                continue
            device_to_configure.append(device_obj)

        # No device to configure
        if not device_to_configure:
            return

        # Configure cdp on these device
        res = pcall(self.configure_device_cdp_protocol,
                    device=device_to_configure)
        for result in res:
            if result[1]:
                self.cdp_configured.add(result[0])        
        

    def configure_device_cdp_protocol(self, device):
        '''If allowed to edit device configuration enable cdp on the device
        Once done - Then add it to the cdp_configured list

        Args:
            device ('device'): the device having cdp enabled
        '''

        # Check if it is already enabled 
        if device.api.verify_cdp_in_state(max_time=self.timeout, check_interval=5):
            # Already configured - Get out
            return(device.name, False)
        
        log.debug('    Configuring cdp protocol for {}'.format(device.name))
        # Configure it
        try:
            device.api.configure_cdp()
        except Exception:
            log.error("     Exception configuring cdp "
                      "for {device}".format(device=device.name),
                                              exc_info=True)
            return(device.name, False)
        else:
            return(device.name, True)

    def configure_testbed_lldp_protocol(self):
        ''' Method checks if lldp configuration is necessary for all devices in
        the testbed and if needed calls the cdp configuration method for the
        target devices in parallel
        '''

        # Check which device to configure lldp on
        device_to_configure = []
        for device_name, device_obj in self.testbed.devices.items():
            if device_name in self.visited_devices or device_name in self.lldp_configured or not device_obj.connected or device_obj.os not in self.supported_os:
                continue
            device_to_configure.append(device_obj)

        # No device to configure    
        if not device_to_configure:
            return

        # Configure lldp on these device    
        res = pcall(self.configure_device_lldp_protocol,
                    device= device_to_configure)
        for result in res:
            if result[1]:
                self.lldp_configured.add(result[0])
        

    def configure_device_lldp_protocol(self, device):
        '''If allowed to edit device configuration enable lldp on the device
        if it is disabled and and then marks that configuration was done

        Args:
            device ('device'): the device having lldp enabled
        '''

        # Check if it is already enabled 
        if device.api.verify_lldp_in_state(max_time= self.timeout, check_interval=5):
            # Already configured - Get out
            return(device.name, False)
        
        log.debug('     Configuring lldp protocol for {}'.format(device.name))
        # Configure it
        try:
            device.api.configure_lldp()
        except Exception:
            log.error("     Exception configuring lldp "
                      "for {device}".format(device=device.name),
                      exc_info=True)
            return(device.name, False)
        else:
            return(device.name, True)

    def get_neigbor_data(self):
        '''Takes a testbed and processes the cdp and lldp data of every
        device on the testbed that has not yet been visited

        Returns:
            [{device:{'cdp':DATA, 'lldp':data}, device2:{'cdp':data,'lldp':data}}]
        '''
        dev_to_test = []
        dev_to_test_names = set()
        # if the device has not been visited add it to the list of devices to test
        # and then add it to list of devices that have been visited
        for device_name, device_obj in self.testbed.devices.items():
            if device_name in self.visited_devices:
                continue
            self.visited_devices.add(device_name)
            if device_obj.os in self.supported_os and device_obj.connected: 
                dev_to_test.append(self.testbed.devices[device_name])
                dev_to_test_names.add(device_name)
            
        # use pcall to get cdp and lldp information for all devices in to test list
        if dev_to_test:
            result = pcall(self.get_neighbor_info, device = dev_to_test)
            return result
        else:
            return []

    def get_neighbor_info(self, device):
        '''Method designed to be used with pcall, gets the devices cdp and lldp
        neighbor data and then returns it in a dictionary format

        Args:
            device ('device'): target to device to call cdp and lldp commands on
        '''
        cdp = {}
        lldp = {}
        if device.os not in self.supported_os or not device.connected:
            return {device.name: {'cdp':cdp, 'lldp':lldp}}

        log.debug('     Getting cdp and lldp neighbor info for {}'.format(device.name))
        
        # get the devices cdp neighbor information
        try:
            cdp = device.api.get_cdp_neighbors_info()
        except Exception as e:
            log.error("     Exception occurred getting cdp info for {}".format(device.name))
            log.debug(e)
        if cdp is None:
            log.debug("     No CDP information found on {}".format(device.name))

        # get the devices lldp neighbor information
        try:
            lldp = device.api.get_lldp_neighbors_info()
        except Exception as e:
            log.error("     Exception occurred getting lldp info for {}".format(device.name))
            log.debug(e)
        if lldp is None:
            log.debug("     No LLDP information found on {}".format(device.name))
        log.debug('     Got cdp and lldp neighbor info for {}'.format(device.name))
        return {device.name: {'cdp':cdp, 'lldp':lldp}}

    def unconfigure_neighbor_discovery_protocols(self, device):
        '''Unconfigures neighbor discovery protocols on device if they
        were enabled by the script earlier

        Args:
            device ('device'): device to unconfigure protocols on
        '''
        log.debug('   Unconfiguring neighbor discovery protocol for {}'.format(device.name))
        # if the device had cdp configured by the script, disable cdp on the device
        if device.name in self.cdp_configured:
            try:
                device.api.unconfigure_cdp()
            except Exception as e:
                log.error('     Error unconfiguring cdp on device {}: {}'.format(device.name, e))

        # if the device had lldp configured by the script, disable lldp on the device
        if device.name in self.lldp_configured:
            try:
                device.api.unconfigure_lldp()
            except Exception as e:
                log.error('     Error unconfiguring lldp on device {}: {}'.format(device.name, e))

    def get_interfaces_ipV4_address(self, device):
        '''Get the ip address for all of the generated interfaces on the give device

        Args:
            device ('device'): device to get interface ip addresses for
        '''
        
        log.debug('   Getting interface ipv4 addresses for {}'.format(device.name))
        # if the device isn't connected or the device doesn't have any interfaces to get ip address for
        if not device.connected or device.os not in self.supported_os or len(device.interfaces) < 1:
            return
        for interface in device.interfaces.values():
            if interface.ipv4 is None:
                try:
                    ip = device.api.get_interface_ipv4_address(interface.name )
                except Exception:
                    ip = None
                if ip:
                    ip = ipaddress.IPv4Interface(ip)
                    interface.ipv4 = ip

    def get_credentials_and_proxies(self, yaml):
        '''Takes a copy of the current credentials in the testbed for use in
        connecting to other devices

        Args:
            yaml ('dict'): testbed to collect credentials and proxies for

        Returns:
            dict of credentials used in connections
            list of proxies used by testbed devices
        '''
        credential_dict = {}
        proxy_list = []
        for device in yaml['devices'].values():
            
            # get all connections used in the testbed
            if 'credentials' in device:
                for cred in device['credentials']:
                    if cred not in credential_dict :
                        credential_dict[cred] = dict(device['credentials'][cred])
                    elif device['credentials'][cred] not in credential_dict.values():
                        credential_dict[cred + str(len(credential_dict))] = dict(device['credentials'][cred])

            # get list of proxies used in connections
            for connect in device['connections'].values():
                if 'proxy' in connect:
                    if connect['proxy'] not in proxy_list:
                        proxy_list.append(connect['proxy'])

        return credential_dict, proxy_list
