import logging
import argparse
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from genie.conf.base import Testbed, Device, Interface, Link


log = logging.getLogger(__name__)


class TestbedManager(object):
    '''Class designed to handle device interactions for connecting devcices
       and cdp and lldp
    '''
    def __init__(self, testbed, config=False, ssh_only=False, alias_dict={},
                 timeout=10, supported_os):

        self.config = config
        self.ssh_only = ssh_only
        self.testbed = testbed
        self.alias_dict = alias_dict
        self.timeout = timeout
        self.supported_os = supported_os

        self.cdp_configured = set()
        self.lldp_configured = set()


    def _connect_all_devices(self, limit):
        '''
            Creates a ThreadPoolExecutor designed to connect to each device in
            Args:
                limit = max number of threads to spawn

            Returns:
                Dictionary of devices containing their connection status
        '''
        results = {}

        # Set up a thread pool executor to connect to all devices at the same time
        with ThreadPoolExecutor(max_workers = limit) as executor:
            for device_name, device_obj in self.testbed.devices.items():
                # If already connected skip - TODO Edmond - Already visited
                if device_obj.connected or device_obj.os not in self.supported_os:
                    continue

                log.info('Attempting to connect to {device}'.format(device=device))
                results[entry] = executor.submit(self._connect_one_device,
                                                entry)

    def connect_all_devices(self, limit):
        '''
            Creates a ThreadPoolExecutor designed to connect to each device in
            Args:
                limit = max number of threads to spawn

            Returns:
                Dictionary of devices containing their connection status
        '''
        results = {}

        # Set up a thread pool executor to connect to all devices at the same time
        with ThreadPoolExecutor(max_workers = limit) as executor:
            for entry in self.testbed.devices:
                if self.testbed.devices[entry].connected:
                    continue
                log.info('Attempting to connect to {entry}'.format(entry = entry))
                results[entry] = executor.submit(self._connect_one_device,
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

    def _connect_one_device(self, device):
        '''
            connect to the given device in the testbed using the given
            connections and after that enable cdp and lldp if allowed
            Args:
                device: name of device being connected
            Returns:
                [bool cdp_configured, bool lldp_configured]
        '''

        # if there is a prefered alias for the device, attempt to connect with device
        # using that alias, if the attmept fails or the alias doesn't exist, it will
        # attempt to connect normally
        if device in self.alias_dict:
            if self.alias_dict[device] in self.testbed.devices[device].connections:
                log.info('Attempting to connect to {} with alias {}'.format(device, self.alias_dict[device]))
                try:
                    self.testbed.devices[device].connect(via = str(self.alias_dict[device]),
                                                    connection_timeout = 10)
                except:
                    log.info('Failed to connect to {} with alias {}'.format(device, self.alias_dict[device]))
                    self.testbed.devices[device].destroy()
            else:
                log.info('Device {} does not have a connection with alias {}'.format(device, self.alias_dict[device]))

        if self.testbed.devices[device].connected:
            return self.configure_neighbor_discovery_protocols(self.testbed.devices[device])

        for one_connect in self.testbed.devices[device].connections:
            if not self.ssh_only or (self.ssh_only and one_connect.protocol == 'ssh'):
                try:
                    self.testbed.devices[device].connect(via = str(one_connect),
                                                    connection_timeout = 10)
                    break
                except Exception:
                    # if connection fails, erase the connection from connection mgr
                    self.testbed.devices[device].destroy()

        return self.configure_neighbor_discovery_protocols(self.testbed.devices[device])

    def configure_neighbor_discovery_protocols(self, dev):
        '''
            TODO: consider taking argument of list of protocols to configure
            If allowed to edit device configuration
            enable cdp and lldp on the device if it is disabled and return
            whether cdp and lldp where configured for the device

            Args:
                dev: the device having it's protocols changed
            Results:
                [bool cdp_configured, bool lldp_configured]
        '''
        cdp = False
        lldp = False

        if not dev.connected:
            log.info('Device {} is not connected skipping'
                        ' cdp/lldp configuration'.format(dev.name))

        if dev.connected and self.config:

            if not dev.api.verify_cdp_in_state(max_time= self.timeout, check_interval=5):
                try:
                    dev.api.configure_cdp()
                    cdp = True
                except Exception:
                    log.error("Exception configuring cdp "
                                "for {device}".format(device = dev.name),
                                                    exc_info = True)

            if not dev.api.verify_lldp_in_state(max_time= self.timeout, check_interval=5):
                try:
                    dev.api.configure_lldp()
                    lldp = True
                except Exception:
                    log.error("Exception configuring cdp"
                                " for {device}".format(device = dev.name),
                                                        exc_info = True)
        return [cdp, lldp]

    def unconfigure_neighbor_discovery_protocols(self, device):
        '''
            TODO: consider taking argument of list of protocols to unconfigure
            Unconfigures neighbor discovery protocols on device if they
            were enabled by the script earlier
            Args:
                device: device to unconfigure protocols on
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
        Args:
            device: target to device to call cdp and lldp commands on
        '''
        cdp = {}
        lldp = {}
        if device.os not in self.supported_os or not device.connected:
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

    def get_interfaces_ipV4_address(self, device):
        '''
        get the ip address for all of the generated interfaces on the give device
        Args:
            device: device to get interface ip addresss for
        '''
        if not device.connected or device.os not in self.supported_os or len(device.interfaces) < 1:
            return
        for interface in device.interfaces.values():
            if interface.ipv4 is None:
                ip = device.api.get_interface_ipv4_address(interface.name)
                if ip:
                    ip = ipaddress.IPv4Interface(ip)
                    interface.ipv4 = ip

    def get_credentials_and_proxies(self, yaml):
        '''
        Takes a copy of the current credentials in the testbed for use in
        connecting to other devices
        Args:
            testbed: testbed to collect credentails and proxies for
        Returns:
            dict of credentials used in connections
            list of proxies used by testbed devices
        '''
        credential_dict = {}
        proxy_list = []
        for device in yaml['devices'].values():
            # get all connections used in the testbed
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
