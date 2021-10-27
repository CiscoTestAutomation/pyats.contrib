import os
import string
import yaml

from pyats.topology import loader
from .creator import TestbedCreator

class Yamltemplate(TestbedCreator):
    """ Yamltemplate class (TestbedCreator)

    Creator for the 'yamltemplate' source. Takes in a YAML file with $-based identifiers
    (as described in PEP 292). Prompts for input for each identifier, substitutes the given
    values, and outputs the resulting YAML file.

    Args:
        path ('str'): The path of the input YAML template file.
        values ('str'): The path of a YAML file contains key-value pairs to be populated in the template.
        noprompt ('boolean'): If specified, the user will not be prompted to override the default values
                              from the values file.

    CLI Argument        |  Class Argument
    ---------------------------------------------
    --path=value        |  path=value
    --values=value      |  values=value
    --noprompt          |  noprompt=True

    pyATS Examples:
        pyats create testbed yamltemplate --path=temp.yaml --output=testbed.yaml

    Examples:
        # Create testbed from test.csv with encoded password
        creator = Yamltemplate(path="temp.yaml")
        creator.to_testbed_file("testbed.yaml")
        creator.to_testbed_object()

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        return {
            'required': ['path'],
            'optional': {
                'values': None,
                'noprompt': False,
            }
        }

    def _get_info(self, msg, default=''):
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
        while not response:
            response = input(msg) or default
        return response


    def _generate(self):
        """ Core implementation of how the testbed data is created.

        Returns:
            dict: The intermediate testbed dictionary.

        """
        if not os.path.exists(self._path):
            raise FileNotFoundError(f'File does not exist: {self._path}')

        with open(self._path, 'r') as f:
            tmpl = f.read()

        kwargs = {}
        if self._values:
            with open(self._values, 'r') as f:
                kwargs = yaml.safe_load(f)

        if not self._noprompt:
            keys = [ele[1] for ele in string.Formatter().parse(tmpl) if ele[1]]
            for key in list(dict.fromkeys(keys)):
                if key in kwargs:
                    kwargs[key] = self._get_info(f'{key} ({kwargs[key]}): ', default=kwargs[key])
                else:
                    kwargs[key] = self._get_info(f'{key}: ')

        sub = string.Template(tmpl).substitute(kwargs)
        clean_yaml = yaml.safe_load(sub)
        return clean_yaml
