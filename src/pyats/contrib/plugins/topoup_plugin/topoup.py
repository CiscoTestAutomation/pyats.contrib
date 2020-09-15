# Python
import logging
from time import sleep, time

# pyAts
from pyats.async_ import pcall
from pyats.easypy.plugins.bases import BasePlugin

# Logger
log = logging.getLogger('ats.easypy.%s' % __name__)


class TopologyUpPlugin(BasePlugin):
    '''
    Runs before job starts, to verify virtual topology is up and running
    before executing the test script.
    '''

    @classmethod
    def configure_parser(cls, parser, legacy_cli = True):
        grp = parser.add_argument_group('TopologyUpPlugin')

        if legacy_cli:
            all_devices_up = ['-all_devices_up']
            connection_check_timeout = ['-connection_check_timeout']
            connection_check_interval = ['-connection_check_interval']
        else:
            all_devices_up = ['--all_devices_up']
            connection_check_timeout = ['--connection_check_timeout']
            connection_check_interval = ['--connection_check_interval']

        # -all_devices_up
        # --all_devices_up
        grp.add_argument(*all_devices_up,
                         dest='all_devices_up',
                         action='store_true',
                         default=False,
                         help='Enable/Disable checking for topology up pre job execution')

        # -connection_check_timeout
        # --connection_check_timeout
        grp.add_argument(*connection_check_timeout,
                         dest='connection_check_timeout',
                         action='store',
                         default=120,
                         help='Total time allowed for checking devices connectivity')

        # -connection_check_interval
        # --connection_check_interval
        grp.add_argument(*connection_check_interval,
                         dest='connection_check_interval',
                         action='store',
                         default=10,
                         help='Time to sleep between device connectivity checks')

        return grp


    def pre_job(self, task):
        '''Loop over all the topology devices and make sure they are up and running
           before executing the test script.
        '''

        # Set the timers
        start_time = time()
        timeout = self.runtime.args.connection_check_timeout
        interval = self.runtime.args.connection_check_interval

        log.info("Connectivity check timeout is '{timeout}' and "
            "connectivity check interval is '{interval}'".format(timeout=timeout, interval=interval))

        # Looping over devices and make sure they are up
        pcall_output = pcall(device_connect,
            ckwargs = {'start_time': start_time, 'timeout': timeout, 'interval': interval},
            ikwargs = [{'device':self.runtime.testbed.devices[dev]} for dev in self.runtime.testbed.devices])

        if not (pcall_output[0] and pcall_output[1]):
            # Terminate testscript
            raise Exception ("Not all the testbed devices are up and ready")

        return


def device_connect(device, start_time, timeout, interval):
    '''Try to connect to the device and if fails, sleep for interval seconds and retry
       till the timeout is reached

        Args:
            device ('obj'): device to use
            start_time ('int'): Current time to calculate the timeout, seconds
            timeout ('int'): Timeout value when reached exit even if failed, seconds
            interval ('int'): Sleep time between retries, seconds

        Returns:
            result(`bool`): Device is successfully connected

        Raises:
            None

    '''

    time_difference = time() - start_time

    while (time() - start_time) < float(timeout):

        try:
            # Connect to the device
            device.connect()
            log.info("Successfully connected to '{device}'".format(device=device))

            # Return the pcall call with True
            return True

        except:
            # Not ready sleep and retry
            log.info("Sleeping for '{interavl}' seconds and retry, remaining time {remaining_time}".format(
                interavl=interval, remaining_time=timeout-time_difference))

            # Sleep for `interval` seconds
            sleep(interval)

            # Retry connecting to the device
            device_connect(device, start_time, timeout, interval)

    return False


# entrypoint
topology_up_plugin = {
    'plugins': {
        'TopologyUpPlugin': {
            'class': TopologyUpPlugin,
            'enabled': False,
            'kwargs': {},
            'module': 'pyats.contrib.plugins.topoup_plugin.topoup',
            'name': 'TopologyUpPlugin'
        }
    }
}
