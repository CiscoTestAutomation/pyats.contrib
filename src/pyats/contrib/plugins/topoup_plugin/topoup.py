# Python
import logging
from time import sleep, time

# pyAts
from pyats.async_ import pcall
from pyats.log.utils import banner
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
            all_devices_up = ['-check_all_devices_up']
            connection_check_timeout = ['-connection_check_timeout']
            connection_check_interval = ['-connection_check_interval']
        else:
            all_devices_up = ['--check-all-devices-up']
            connection_check_timeout = ['--connection-check-timeout']
            connection_check_interval = ['--connection-check-interval']

        # -check_all_devices_up
        # --check-all-devices-up
        grp.add_argument(*all_devices_up,
                         dest='all_devices_up',
                         action="store_true",
                         help='Enable/Disable checking for topology up pre job execution')

        # -connection_check_timeout
        # --connection-check-timeout
        grp.add_argument(*connection_check_timeout,
                         dest='connection_check_timeout',
                         action='store',
                         default=120,
                         help='Total time allowed for checking devices connectivity')

        # -connection_check_interval
        # --connection-check-interval
        grp.add_argument(*connection_check_interval,
                         dest='connection_check_interval',
                         action='store',
                         default=10,
                         help='Time to sleep between device connectivity checks')

        return grp


    def pre_job(self, task):
        '''Try to connect to all the topology devices in parallel and make sure they
           are up and running before executing the test script.
        '''

        # Check for the argument controlling the plugin run (Checking devices)
        check_devices_up = self.runtime.args.all_devices_up

        if not check_devices_up:
            log.info("Checking all devices are up and ready is disabled, '--check-all-devices-up' "
                     "must be set to True in case of pyats runs or '-check_all_devices_up' set to "
                     "True in case of legacy easypy runs")
            return
        else:
            log.info("TopologyUp Plugin is enabled, will start the plugin checking for all "
                "the devices' connectivity!")

        # Set the timers
        start_time = time()
        timeout = self.runtime.args.connection_check_timeout
        interval = self.runtime.args.connection_check_interval

        log.info("Connectivity check timeout is '{timeout}' and "
            "connectivity check interval is '{interval}'".format(timeout=timeout, interval=interval))

        # check devices and exclude IXIA device
        devices_list = []
        for device in self.runtime.testbed.find_devices():
            if 'ixia' not in str(device.__class__):
                devices_list.append({'device': device})
            else:
                log.info("Device {device} is not supported and connected check is skipped.".format(device=device.name))

        # Trying to connect to all devices in parallel
        pcall_output = pcall(device_connect,
            ckwargs = {'start_time': start_time, 'timeout': timeout, 'interval': interval},
            ikwargs = devices_list)

        # Create Summary
        log.info(banner("Devices' connection trials summary"))

        failed_list = []
        succeeded_list = []

        for res, dev, count in pcall_output:
            if res is False:
                msg = "Device '{device}' connectivity check failed after '{count}' trial(s)".format(
                    device=dev, count=count)
                failed_list.append(msg)
            else:
                msg = "Device '{device}' connectivity passed after '{count}' trial(s)".format(
                    device=dev, count=count)
                succeeded_list.append(msg)

        for mes in succeeded_list:
            log.info(mes)

        for fail_mes in failed_list:
            if fail_mes == failed_list[0]:
                log.info('')
            log.warning(fail_mes)

        if failed_list:
            # Terminate testscript
            log.info(banner("TopologyUp Plugin end!"))
            raise Exception ("Not all the testbed devices are up and ready")
        else:
            log.info("All devices are up and ready, Connected succesfully!")
            log.info(banner("TopologyUp Plugin end!"))

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
            device.name(`str`): Device's name'
            count(`int`): Device's connectivity trials count

        Raises:
            None

    '''

    count = 0

    while (time() - start_time) < float(timeout):

        time_difference = time() - start_time

        count = count+1

        try:
            # Connect to the device
            device.connect()

        except:
            # Not ready sleep and retry
            log.info("Connecting to device '{device}' failed. Sleeping for '{interval}' seconds "\
                "and retry, remaining time {remaining_time}".format(
                device=device, interval=str(interval), remaining_time=str(float(timeout)-float(time_difference))))

            # Sleep for `interval` seconds
            sleep(int(interval))

            continue

        else:
            log.info("Successfully connected to '{device}'".format(device=device))

            # Return the pcall call with True
            return (True, device.name, count)

    return (False, device.name, count)


# entrypoint
topology_up_plugin = {
    'plugins': {
        'TopologyUpPlugin': {
            'class': TopologyUpPlugin,
            'enabled': True,
            'kwargs': {},
            'module': 'pyats.contrib.plugins.topoup_plugin.topoup',
            'name': 'TopologyUpPlugin'
        }
    }
}
