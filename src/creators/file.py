import os
import pathlib
import xlrd
import csv

from pyats.topology import loader
from .creator import TestbedCreator

class File(TestbedCreator):
    def _init_arguments(self):
        return {
            'required': ['path'],
            'optional': {
                'recurse': False,
                'encode_password': False
            }
        }

    def to_testbed_file(self, output_location):
        testbed = self._generate()

        if isinstance(testbed, list):
            for base, item in self._generate():
                self._write_yaml(os.path.join(output_location, base), 
                            item, self._encode_password, input_file=self._path)
        else:
            self._write_yaml(output_location, testbed, self._encode_password,
                                                        input_file=self._path)

        return True

    def to_testbed_object(self):
        testbed = self._generate()
        
        if isinstance(testbed, list):
            return [self._create_testbed(data) for _, data in testbed]
        else:
            return self._create_testbed(testbed)

    def _generate(self):
        if not os.path.exists(self._path):
            raise FileNotFoundError('File or directory does not exist: %s' 
                                                                % self._path)
            # if is a dir then walk through it

        if os.path.isdir(self._path):
            result = []

            for root, _, files in os.walk(self._path):

                # get sub dir name relative to input dir
                p = pathlib.Path(root)

                # remove the ./ in front
                out_sub_dir = str(p.relative_to(self._path)).lstrip('./')
                for file in files:
                    # remove the ./ in front
                    input_file = os.path.join(root, file).lstrip('./')

                    devices = self._read_device_data(input_file)

                    # write to a yaml file where the filename 
                    # is the same as the excel file
                    output = os.path.join(out_sub_dir,
                                            os.path.splitext(file)[0] + '.yaml')
                
                    result.append((output, self._construct_yaml(devices)))

                # if recursive option is not set, then stop after first level
                if not self._recurse:
                    break
        # not a dir, just a file
        else:
            devices = self._read_device_data(self._path)
            return self._construct_yaml(devices)

        return result

    def _read_device_data(self, file):
        """ Read device data based on file type
        Args
            file (`str`): filename to read
        Returns:
            List of Dicts containing device data
        """
        _, extension = os.path.splitext(file)
        # check if file is csv or xls
        devices = {}
        try:
            if extension == '.csv':
                devices = self._read_csv(file)
            elif extension in {'.xls', '.xlsx'}:
                devices = self._read_excel(file)
            else:
                self._result['warning'][file] = 'is not excel or csv'
        except Exception as e:
            self._result['errored'][file] = 'has an error: {e}'.format(e=str(e))
            return
        return devices

    def _read_csv(self, file_name):
        """ read csv file containing device data

        Args:
            file_name(`str`): name of the csv file

        Returns:
             list of dict containing device attributes from each row of the file
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
        """ read excel file containing device data

        Args:
            file_name(`str`): name of the excel file

        Returns:
             list of dict containing device attributes from each row of the file
        """
        row_lst = []
        ws = xlrd.open_workbook(file_name).sheet_by_index(0)
        self._keys = ws.row_values(0)
        for i in range(1, ws.nrows):
            # Only take key which has value
            row_lst.append({k: v for k, v in dict(
                            zip(self._keys, ws.row_values(i))).items() if v})
        return row_lst
