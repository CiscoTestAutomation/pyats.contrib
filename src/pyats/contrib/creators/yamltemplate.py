import os
import string
import yaml

from .creator import TestbedCreator


class Yamltemplate(TestbedCreator):
    """ Yamltemplate class (TestbedCreator)

    Creator for the 'yamltemplate' source. Takes in a YAML file containing template strings
    as described in PEP 292, but using % as the delimiter (rather than $). Prompts for input
    for each identifier, substitutes the given values, and outputs the resulting YAML file.
    Can optionally take a list of values from a second YAML file, and prompt the user to
    override them if desired.

    Args:
        template_file ('str'): The path of the input YAML template file.
        value_file ('str') default=None: The path of a YAML file contains key-value pairs
            to be populated in the template.
        noprompt ('boolean') default=False: If specified, the user will not be prompted
            to override the default values from the value_file.
        delimiter ('str') default='%': If specified, uses the provided string as the
            string template delimiter.

    CLI Argument          |  Class Argument
    ---------------------------------------------
    --template-file=value |  template_file=value
    --value-file=value    |  value_file=value
    --noprompt            |  noprompt=True
    --delimiter=value     |  delimiter=True

    pyATS Examples:
        pyats create testbed yamltemplate --template-file=temp.yaml --output=testbed.yaml
        pyats create testbed yamltemplate --template-file=temp.yaml --value-file values.yaml
            --output=testbed.yaml
        pyats create testbed yamltemplate --template-file=temp.yaml --value-file values.yaml
            --output=testbed.yaml --noprompt

    Examples:
        creator = Yamltemplate(template_file="temp.yaml")
        creator.to_testbed_file("testbed.yaml")
        creator.to_testbed_object()

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        return {
            'required': ['template_file'],
            'optional': {
                'value_file': None,
                'noprompt': False,
                'delimiter': '%'
            }
        }

    def _get_info(self, msg, default=''):
        """ Prompts input from user with optional default.

        Args:
            msg ('str'): The prompt message.
            default ('str'): The default value if no input provided.

        Returns:
            str: The user's input, or the default value if no input provided.

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
        if not os.path.exists(self._template_file):
            raise FileNotFoundError(f'File does not exist: {self._template_file}')

        if self._noprompt and not self._value_file:
            raise Exception('noprompt option requires a value file to be specified')

        with open(self._template_file, 'r') as f:
            tmpl_str = f.read()

        tmpl = type('CustomTemplate', (string.Template, object), {'delimiter': self._delimiter})(tmpl_str)

        kwargs = {}
        if self._value_file:
            with open(self._value_file, 'r') as f:
                kwargs = yaml.safe_load(f)

        if not self._noprompt:
            # Find all keys from template file
            keys = [s[1] or s[2] for s in tmpl.pattern.findall(tmpl_str) if s[1] or s[2]]
            # Ignore duplicate keys
            for key in list(dict.fromkeys(keys)):
                if key in kwargs:
                    kwargs[key] = self._get_info(f'{key} ({kwargs[key]}): ', default=kwargs[key])
                else:
                    kwargs[key] = self._get_info(f'{key}: ')

        try:
            sub = tmpl.substitute(kwargs)
        except KeyError as e:
            raise Exception(f'No value found for key "{e.args[0]}"')
        clean_yaml = yaml.safe_load(sub)
        return clean_yaml
