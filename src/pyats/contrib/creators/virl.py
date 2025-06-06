import re
import sys
import requests
import logging
from xml.etree import ElementTree

from .creator import TestbedCreator

logger = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)


class Virl(TestbedCreator):
    """ Virl class (TestbedCreator)

    Creator for the 'virl' source. Creates a testbed from a running VIRL simulation.

    Args:
        host ('str'): Hostname or IP address of Virl server
        username ('str'): Username to connect to Virl
        password ('str'): Password to connect to Virl
        simulation ('str'): Simulation name

    CLI Argument        |  Class Argument
    ---------------------------------------------
    --host=value        |  path=value
    --username          |  username=username
    --password          |  password=password
    --simulation        |  simulation=sim_name

    pyATS Examples:
        pyats create testbed virl --host=192.168.1.1 --username=test --password=test --simulation=sim_name

    Examples:
        # Create testbed from Virl simulation
        creator = Virl(host="192.168.1.1", username=test, password=test, simulation=test)
        creator.to_testbed_file("testbed.yaml")
        creator.to_testbed_object()

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        return {
            'required': [
                'host',
                'username',
                'password',
                'simulation'
            ],
            'optional': {
                'encode_password': False
            }
        }

    def to_testbed_file(self, output_location):
        """ Saves the source data as a testbed file.

        Args:
            output_location ('str'): Where to save the file.

        Returns:
            bool: Indication that the operation is successful or not.

        """
        testbed = self._generate()

        self._write_yaml(output_location, testbed, self._encode_password)

        return True

    def to_testbed_object(self):
        """ Creates testbed object from the source data.

        Returns:
            Testbed: The created testbed.

        """
        testbed = self._generate()

        return self._create_testbed(testbed)

    def _generate(self):
        """ Read virl data and generate testbed dictionary

        Returns:
            dict: Testbed dictionary

        """
        host = self._host

        os_type_map = {
            'IOSv': 'iosxe'
        }

        response = requests.get(
            'http://{}:19399/simengine/rest/list'.format(host),
            auth=(self._username, self._password))

        response.raise_for_status()

        sim_data = response.json()
        simulations = sim_data.get('simulations', {})
        if self._simulation not in simulations:
            logger.error('Simulation {} not found in {}'.format(
                self._simulation,
                simulations.keys()
            ))
            return {}

        if simulations.get(self._simulation, {}).get('status') != 'ACTIVE':
            logger.error('Simulation not active')
            return {}

        response = requests.get(
            "http://{}:19399/simengine/rest/export/{}?updated=1".format(
                self._host,
                self._simulation),
            auth=(self._username, self._password))
        topology = response.text

        response = requests.get(
            "http://{}:19399/simengine/rest/serial_port/{}?mode=telnet".format(
                self._host,
                self._simulation),
            auth=(self._username, self._password))
        ports = response.json()

        # Use undocumented API to get ~mgmt-lxc port info
        # since this info does not seem to be available via STD API
        response = requests.get(
            "http://{}/rest/user/{}/simulation/{}/nodes".format(
                self._host,
                self._username,
                self._simulation),
            auth=(self._username, self._password))
        node_details = response.json()

        for node in node_details:
            if node.get('node_id') == '~mgmt-lxc':
                mgmt_port = node.get('port')

        root = ElementTree.fromstring(topology)
        ElementTree.register_namespace("virl", "http://www.cisco.com/VIRL")
        namespace = "{http://www.cisco.com/VIRL}"
        nodes = root.findall("{}node".format(namespace))

        devices = {}

        devices.setdefault('mgmt', {})['os'] = 'linux'
        devices.setdefault('mgmt', {}).setdefault(
            'credentials', {}).setdefault('default', {})['username'] = self._username
        devices.setdefault('mgmt', {}).setdefault(
            'connections', {}).setdefault('mgmt', {})['protocol'] = 'ssh'
        devices.setdefault('mgmt', {}).setdefault(
            'connections', {}).setdefault('mgmt', {})['ip'] = self._host
        devices.setdefault('mgmt', {}).setdefault(
            'connections', {}).setdefault('mgmt', {})['port'] = int(mgmt_port)

        for node in nodes:
            hostname = node.get("name")
            node_type = node.get("type", None)
            node_subtype = node.get("subtype", None)
            if node_type != "SIMPLE":
                continue
            mgmt_ip = node.find("{0}extensions/{0}entry[@key='AutoNetkit.mgmt_ip']".format(namespace)).text
            devices.setdefault(hostname, {})['os'] = os_type_map.get(node_subtype)
            devices.setdefault(hostname, {}).setdefault(
                'credentials', {}).setdefault('default', {})['username'] = 'cisco'
            devices.setdefault(hostname, {}).setdefault(
                'credentials', {}).setdefault('default', {})['password'] = 'cisco'
            devices.setdefault(hostname, {}).setdefault(
                'connections', {}).setdefault('mgmt', {})['protocol'] = 'telnet'
            devices.setdefault(hostname, {}).setdefault(
                'connections', {}).setdefault('mgmt', {})['ip'] = mgmt_ip
            devices.setdefault(hostname, {}).setdefault(
                'connections', {}).setdefault('mgmt', {})['proxy'] = 'mgmt'

        for hostname in ports.keys():
            # check if the dictionary entry in not empty and has a host:port field associated
            if ports[hostname]:
                host, port = re.split(r'[/:]', ports[hostname])
                devices.setdefault(hostname, {}).setdefault(
                    'connections', {}).setdefault('a', {})['protocol'] = 'telnet'
                devices.setdefault(hostname, {}).setdefault(
                    'connections', {}).setdefault('a', {})['ip'] = host
                devices.setdefault(hostname, {}).setdefault(
                    'connections', {}).setdefault('a', {})['port'] = int(port)

        testbed = {
            'devices': devices
        }

        return testbed
