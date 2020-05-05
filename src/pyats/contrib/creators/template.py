import xlrd
import xlwt
import xlsxwriter
import csv
import os
import logging

from pyats.topology import Testbed
from .creator import TestbedCreator

class Template(TestbedCreator):
    """ Template class (TestbedCreator)

    Creator for the 'template' source. Generates a CSV or Excel template with 
    the nesscary fields to create a testbed. The template can then be populated
    with device data, and converted to testbeds via the 'file' creator.

    Args:
        add_keys ('list') default=None: Any additional keys that should be added
            to the generated template.
        add_custom_keys ('list') default=None: Any additional custom keys that 
            should be added to the generated template.

    CLI Argument                |  Class Argument
    -----------------------------------------------------------------
    --add-keys k1 k2 ...        |  add_keys=['k1', 'k2', ...]
    --add-custom-keys k1 k2 ... |  add_custom_keys=['k1', 'k2', ...]

    pyATS Examples:
        pyats create testbed template --output=testbed.yaml

    Examples:
        # Create a CSV file template
        creator = Template()
        creator.to_testbed_file("template.csv")

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        self._cli_list_arguments.append('--add-keys')
        self._cli_list_arguments.append('--add-custom-keys')

        return {
            'optional': { 
                'add_keys': None,
                'add_custom_keys': None
            }
        }

    def to_testbed_file(self, output_location):
        """ Saves the template file.

        Args:
            output_location ('str'): Where to save the file.
        
        Returns:
            bool: Indication that the operation is successful or not.
        
        """
        self._output = output_location 
        self._generate()
        return True

    def to_testbed_object(self):
        """ Creates testbed object from the source data.
        
        Returns:
            Testbed: The created testbed.
        
        """
        return Testbed(name="testbed")

    def _generate(self):
        """ Core implementation of how the template is created.

        """
        # If supplied additional keys, add to self.keys
        if self._add_keys:
            self._keys.extend(key.lower() for key in self._add_keys)

        # If supplied custom keys, add converted custom keys
        if self._add_custom_keys:
            self._keys.extend("custom:{}".format(key.lower())
                                            for key in self._add_custom_keys)

        # get file extension
        extension = os.path.splitext(self._output)[-1]
        if extension == '.csv':
            self._write_csv(self._output)
        elif extension == '.xls':
            self._write_xls(self._output)
        elif extension == '.xlsx':
            self._write_xlsx(self._output)
        else:
            raise Exception('File type is not csv or excel')

        # return success result with template filename
        if os.path.isfile(self._output):
            self._result['success'].setdefault('template', self._output)

    def _write_csv(self, output):
        """ Helper for writing keys to CSV.
        
        """
        with open(output, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(self._keys)

    def _write_xls(self, output):
        """ Helper for writing keys to XLS.
        
        """
        wb = xlwt.Workbook()
        ws = wb.add_sheet('testbed')
        for i, k in enumerate(self._keys):
            ws.write(0, i, k)
        wb.save(output)

    def _write_xlsx(self, output):
        """ Helper for writing keys to XLSX.
        
        """
        wb = xlsxwriter.Workbook(output)
        ws = wb.add_worksheet('testbed')
        ws.write_row('A1', self._keys)
        wb.close()
