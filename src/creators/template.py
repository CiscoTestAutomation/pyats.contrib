import xlrd
import xlwt
import xlsxwriter
import csv
import os
import logging

from .creator import TestbedCreator

logger = logging.getLogger(__name__)

class Template(TestbedCreator):
    def _init_arguments(self):
        return {
            'optional': { 'add_keys': None }
        }

    def to_testbed_file(self, output):
        self._output = output 
        self._generate()
        return True

    def to_testbed_object(self):
        return None

    def _generate(self):
        """ generate the template excel/csv file

        Returns
            None
        """

        # if supplied additional keys, add to self.keys
        if self._add_keys:
            self._keys.extend(list(map(lambda x: x.lower(), self._add_keys)))
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

        logger.info('Template file generated: {f}'.format(f=self._output))
        exit()

    # write keys to xls csv
    def _write_csv(self, output):
        with open(output, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(self._keys)

    # write keys to xls with xlwt
    def _write_xls(self, output):
        wb = xlwt.Workbook()
        ws = wb.add_sheet('testbed')
        for i, k in enumerate(self._keys):
            ws.write(0, i, k)
        wb.save(output)

    # write keys to xlsx with xlsxwriter
    def _write_xlsx(self, output):
        wb = xlsxwriter.Workbook(output)
        ws = wb.add_worksheet('testbed')
        ws.write_row('A1', self._keys)
        wb.close()
