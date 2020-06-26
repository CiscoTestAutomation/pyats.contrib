import logging
import os
import json
import requests
from pyats.easypy.plugins.bases import BasePlugin
from pyats import configuration as cfg

logger = logging.getLogger("pyats.contrib.webexnotify")

MESSAGE_URL = 'https://api.ciscospark.com/v1/messages'

MESSAGE_TEMPLATE = """
## JOB RESULT REPORT
```
Job ID        : {job.uid}
Host          : {job.runtime.env[host][name]}
Archive       : {job.runtime.runinfo.archive_file}
Total Tasks   : {job.runtime.tasks.count}
Total Runtime : {job.elapsedtime}s

Results Summary
---------------
Passed        : {job.results[passed]}
Passx         : {job.results[passx]}
Failed        : {job.results[failed]}
Aborted       : {job.results[aborted]}
Blocked       : {job.results[blocked]}
Skipped       : {job.results[skipped]}
Errored       : {job.results[errored]}
```
"""

class WebExTeamsNotifyPlugin(BasePlugin):
    '''
    Runs after job, sends notification with results to a specified WebEx Teams
    space, or a specific person.
    '''

    @classmethod
    def configure_parser(cls, parser, legacy_cli = True):
        grp = parser.add_argument_group('WebEx')

        if legacy_cli:
            space = ['-webex_space']
            email = ['-webex_email']
            token = ['-webex_token']
        else:
            space = ['--webex-space']
            email = ['--webex-email']
            token = ['--webex-token']

        grp.add_argument(*token,
                         dest='webex_token',
                         action="store",
                         type=str,
                         metavar='',
                         default = None,
                         help='Webex Bot AUTH Token')

        grp.add_argument(*space,
                         dest='webex_space',
                         action="store",
                         type=str,
                         metavar='',
                         default = None,
                         help='Webex Space ID to send notification to')

        grp.add_argument(*email,
                         dest='webex_email',
                         action="store",
                         type=str,
                         metavar='',
                         default = None,
                         help='Email of specific user to send WebEx '
                              'notification to')
        return grp


    def post_job(self, job):
        token = self.runtime.args.webex_token or cfg.get('webex.token')
        space = self.runtime.args.webex_space or cfg.get('webex.space')
        email = self.runtime.args.webex_email or cfg.get('webex.email')

        if not token:
            logger.info('WebEx Token not given as argument or in config. No '
                        'WebEx notification will be sent')
            return

        headers = {'Authorization': 'Bearer {}'.format(token),
                   'Content-Type': 'application/json'}

        if not space and not email:
            logger.info('No Space ID or email specified, No WebEx Teams '
                        'notification will be sent')
            return

        payload = {'markdown': MESSAGE_TEMPLATE.format(job=job)}
        if space:
            payload['roomId'] = space
        elif email:
            payload['toPersonEmail'] = email

        logger.info('Sending WebEx Teams notification')

        try:
            r = requests.post(MESSAGE_URL,
                              data=json.dumps(payload),
                              headers=headers)
            logger.debug('notification status: %s' % r.status_code)
            logger.debug(r.text)
        except Exception:
            logger.exception('Failed to send WebEx Teams notification:')


webex_plugin = {
    'plugins': {
        'WebExTeamsNotifyPlugin': {
            'class': WebExTeamsNotifyPlugin,
            'enabled': True,
            'kwargs': {},
            'module': 'pyats.contrib.plugins.webex',
            'name': 'WebExTeamsNotifyPlugin'
        }
    }
}