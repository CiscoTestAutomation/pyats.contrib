import os
import xlrd
import csv
import pathlib

from pyats.topology import loader
from .creator import TestbedCreator

class File(TestbedCreator):
    """ File class (TestbedCreator)

    Creator for the 'file' source. Takes in a CSV or Excel file and outputs the
    corresponding testbed object or file. Alternatively, it can take in a folder
    as path and converts all the CSV and Excel files inside.

    Args:
        path ('str'): The path of the input CSV/Excel file or a folder.
        recurse ('bool') default=False: If a folder is passed in, whether or not 
            traversal should include subdirectories.
        encode_password ('bool') default=False: Should generated testbed encode 
            its passwords.

    CLI Argument        |  Class Argument
    ---------------------------------------------
    --path=value        |  path=value
    --encode-password   |  encode_password=True
    -r                  |  recurse=True

    pyATS Examples:
        pyats create testbed file --path=test.csv --output=testbed.yaml
        pyats create testbed file --path=folder --output=testbeds -r

    Examples:
        # Create testbed from test.csv with encoded password
        creator = File(path="test.csv", encode_password=True)
        creator.to_testbed_file("testbed.yaml")
        creator.to_testbed_object()

    """

    def _init_arguments(self):
        """ Specifies the arguments for the creator.

        Returns:
            dict: Arguments for the creator.

        """
        self._cli_replacements.setdefault('-r', ('recurse', True))
        
        return {
            'required': ['path'],
            'optional': {
                'recurse': False,
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

        if isinstance(testbed, list):
            for base, item in testbed:
                self._write_yaml(os.path.join(output_location, base), 
                            item, self._encode_password, input_file=self._path)
        else:
            self._write_yaml(output_location, testbed, self._encode_password,
                                                        input_file=self._path)

        return True

    def to_testbed_object(self):
        """ Creates testbed object from the source data.
        
        Returns:
            Testbed: The created testbed.
        
        """
        testbed = self._generate()
        
        if isinstance(testbed, list):
            return [self._create_testbed(data) for _, data in testbed]
        else:
            return self._create_testbed(testbed)

    def _generate(self):
        """ Core implementation of how the testbed data is created.

        Returns: 
            dict: The intermediate testbed dictionary.

        """
        if not os.path.exists(self._path):
            raise FileNotFoundError('File or directory does not exist: %s' 
                                                                % self._path)
        
        # if is a dir then walk through it
        if os.path.isdir(self._path):
            result = []

            for root, _, files in os.walk(self._path):
                for file in files:
                    input_file = os.path.join(root, file)
                    relative = os.path.relpath(input_file, self._path)
                    devices = self._read_device_data(input_file)

                    # The testbed filename should be same as the file
                    output = os.path.splitext(relative)[0] + '.yaml'

                    result.append((output, self._construct_yaml(devices)))
            
                # if recursive option is not set, then stop after first level
                if not self._recurse:
                    break
        else:
            devices = self._read_device_data(self._path)
            return self._construct_yaml(devices)
        
        return result

    def _read_device_data(self, file):
        """ Read device data based on file type.

        Args:
            file ('str'): Path of the file.
        
        Returns:
            list: List of dictionaries containing device data.

        """
        _, extension = os.path.splitext(file)
        
        # Check if file is csv or xls
        devices = {}

        if extension == '.csv':
            devices = self._read_csv(file)
        elif extension in {'.xls', '.xlsx'}:
            devices = self._read_excel(file)
        else:
            raise Exception("Given path is not a folder or a CSV/Excel file.")

        return devices

    def _read_csv(self, file_name):
        """ Reads CSV file containing device data.

        Args:
            file_name ('str'): Name of the CSV file.

        Returns:
            list: List of dictionaries containing the device attributes from 
                each row of the file.

        """
        row_lst = []
        with open(file_name, 'r') as f:
            reader = csv.reader(f)
            self._keys = next(reader)
            for row in reader:
                # Only take key which has value
                row_lst.append({k: v for k, v in dict(
                                            zip(self._keys, row)).items() if v})
        return row_lst

    def _read_excel(self, file_name):
        """ Read Excel file containing device data.

        Args:
            file_name ('str'): name of the excel file

        Returns:
            list: List of dictionaries containing device attributes from each
                row of the file.

        """
        row_lst = []
        ws = xlrd.open_workbook(file_name).sheet_by_index(0)
        self._keys = ws.row_values(0)
        for i in range(1, ws.nrows):
            # Only take key which has value
            row_lst.append({k: v for k, v in dict(
                            zip(self._keys, ws.row_values(i))).items() if v})
        return row_lst
