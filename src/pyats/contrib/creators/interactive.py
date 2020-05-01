import logging
import getpass
import os

from .creator import TestbedCreator

logger = logging.getLogger(__name__)

class Interactive(TestbedCreator):
    """ Interactive class (TestbedCreator)

    Creator for the 'interactive' source. Runs a console script to prompt step 
    by step questions and generating the corresponding testbed object or file 
    as an output.

    Args:
        add_keys ('list') default=None: Any additional keys that should be added
            to the testbed.
        encode_password ('bool') default=False: Should generated testbed encode 
            its passwords.

    CLI Argument                |  Class Argument
    -----------------------------------------------------------------
    --add-keys k1 k2 ...        |  add_keys=['k1', 'k2', ...]
    --add-custom-keys k1 k2 ... |  add_custom_keys=['k1', 'k2', ...]
    --encode-password           |  encode_password=True

    pyATS Examples:
        pyats create testbed interactive --output=testbed.yaml

    Examples:
        # Create testbed from CLI with additional keys
        creator = Interactive(encode_password=True, add_keys=['time', 'date'])
        creator.to_testbed_file("testbed.yaml")
        creator.to_testbed_object()

    """

    _VALID_ANSWER = {'yes': True, 'y': True, 'no': False, 'n': False}

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        self._cli_list_arguments.append('--add-keys')
        self._cli_list_arguments.append('--add-custom-keys')

        return {
            'optional': {
                'encode_password': False,
                'add_keys': None,
                'add_custom_keys': None
            }
        }

    def _prompt_password(self, msg):
        """ Prompts user to enter password, and set to '%ASK{}' if nothing 
            entered.

        Returns:
            str: The password that the user entered.

        """
        password = getpass.getpass(prompt=msg)
        if not password:
            return '%ASK{}'
        else:
            return password

    def _get_info(self, msg, iterable=None, invalid=False):
        """ Prompts input from user, validating the input if iterable is
            provided.

        Args:
            msg ('str'): The prompt message.
            iterable ('iterable'): Iterable object that contains the 
                valid/invalid answers.
            invalid ('bool'): Flag that tells if iterable is invalid answer.

        Returns:
            str: The user's input.

        """
        response = ''

        # if provided a list of valid answers, then check if input is valid
        if iterable:
            if invalid:
                while response in iterable:
                    response = input(msg)
            else:
                while response not in iterable:
                    response = input(msg)
        else:
            response = input(msg)
        return response

    def _generate(self):
        """ Core implementation of how the testbed data is created.

        Returns: 
            dict: The intermediate testbed dictionary.

        """
        # Make sure output isn't a directory
        logger.info('Start creating Testbed yaml file ...')
        devices = []
        more_device = True
        all_password = None
        all_username = None
        enable_all_password = None
        name_set = set()

        # (keyname, description)
        keys = [('hostname', ''),
                ('IP', '(ip, or ip:port)'),
                ('Username', ''),
                ('Password', ''),
                ('Protocol', '(ssh, telnet, ...)'),
                ('OS', '(iosxr, iosxe, ios, nxos, linux, ...)')]

        # check if all devices have same username
        user_answer = self._get_info(
            'Do all of the devices have the same username? [y/n] ',
                                                    iterable=self._VALID_ANSWER)

        # if same username, ask user
        if self._VALID_ANSWER.get(user_answer):
            all_username = self._get_info(
                            'Common Username: ', iterable={''}, invalid=True)
            logger.info('')

        # check if all devices have same password
        pass_answer = self._get_info(
            'Do all of the devices have the same default password? [y/n] ',
                                                    iterable=self._VALID_ANSWER)

        # if same password, ask user
        if self._VALID_ANSWER.get(pass_answer):
            all_password = self._prompt_password(
                "Common Default Password "
                + "(leave blank if you want to enter on demand): ")
            logger.info('')

        enable_pass_answer = self._get_info(
            'Do all of the devices have the same enable password? [y/n] ',
            iterable=self._VALID_ANSWER)

        # if same enable password, ask, if nothing is entered, 
        # set it to the same as default password
        if self._VALID_ANSWER.get(enable_pass_answer):
            enable_all_password = self._prompt_password(
                "Common Enable Password " + 
                "(leave blank if you want to enter on demand): ")
            logger.info('')

        while more_device:
            logger.info('')
            device = {}
            for key, description in keys:

                # Get Device hostname
                if key == 'hostname':
                    name = self._get_info('Device hostname: ', iterable={''}, 
                                                                invalid=True)

                    # if device name already exist, ask again
                    while name in name_set:
                        logger.info('{d} has been already entered'
                                                                .format(d=name))
                        name = self._get_info('Device hostname: ', 
                                                    iterable={''}, invalid=True)
                    device['hostname'] = name
                    name_set.add(name)
                    continue

                elif key.lower() == 'username':

                    # ask user for username
                    if all_username:
                        device['username'] = all_username
                    else:
                        device['username'] = self._get_info(
                                '   Username: ', iterable={''}, invalid=True)
                    continue

                elif key.lower() == 'password':

                    # ask user for password if not all devices has the same
                    if all_password:
                        device['password'] = all_password
                    else: 
                        device['password'] = self._prompt_password(
                        "Default Password " +
                        "(leave blank if you want to enter on demand): ")
                    # ask for enable password if not the same, 
                    # and if user entered nothing set default password to enable
                    if enable_all_password:
                        enable_pass = enable_all_password 
                    else:
                        enable_pass = self._prompt_password(
                        "Enable Password " +
                        "(leave blank if you want to enter on demand): ")

                    if enable_pass:
                        device['enable_password'] = enable_pass
                    else:
                        device['enable_password'] = ''
                    continue

                else:
                    # Any other key
                    device[key.lower()] = self._get_info('   {k} {d}: '
                    .format(k=key, d=description), iterable={''}, invalid=True)

            # ask input for custom keys if supplied
            if self._add_custom_keys:
                if not self._add_keys:
                    self._add_keys = []
                self._add_keys.extend("custom:{}".format(key.lower())
                                            for key in self._add_custom_keys)

            if self._add_keys:
                for k in self._add_keys:
                    if k not in device:
                        device[k.lower()] = self._get_info(
                            '   Value for custom key "{k}": '.format(k=k),
                            iterable={''},
                            invalid=True)

            devices.append(device)

            # ask if user want to enter more devices
            answer = self._get_info('More devices to add ? [y/n] ', 
                                            iterable=self._VALID_ANSWER).lower()
            more_device = self._VALID_ANSWER[answer]

        return self._construct_yaml(devices)
