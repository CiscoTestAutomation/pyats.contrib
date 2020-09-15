import json
import logging
import os
import socket

import requests

from pyats import configuration as cfg
from pyats.easypy.plugins.bases import BasePlugin

logger = logging.getLogger(__name__)

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
        # Get WebEx info from arguments or configuration
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

        # Format message with info from job run
        msg = MESSAGE_TEMPLATE.format(job=job)
        
        # internal Cisco pyATS log upload link
        # (does not exist for external release)
        try:
            # Attempt to get path for TRADe logs
            if not self.runtime.runinfo.no_upload:
                msg += '\n\nView pyATS logs at: %s'\
                       % self.runtime.runinfo.log_url
        except AttributeError:
            pass

        try:
            host = job.runtime.env['host']['name']
            # Determine if liveview is running
            if self.runtime.args.liveview and\
                    self.runtime.args.liveview_keepalive:
                # Liveview will set this to the assigned port if not specified
                port = self.runtime.args.liveview_port
                try:
                    # Attempt to add a link using the host domain name
                    addr = socket.getfqdn()
                    socket.gethostbyname(addr)
                    msg += '\n\nLogs can be viewed with the pyATS Log Viewer '\
                           'at: http://%s:%s' % (addr, port)
                except OSError:
                    msg += '\n\nLogs can be viewed in your browser by '\
                           'connecting to %s with port %s' % (host, port)
            else:
                # Show command to run liveview
                archive = self.runtime.runinfo.archive_file
                if archive:
                    msg += '\n\nRun the following command on %s to view logs '\
                           'from this job: `pyats logs view %s --host 0.0.0.0`'\
                           % (host, archive)

        except AttributeError:
            pass

        # Build payload
        payload = {'markdown': msg}
        if space:
            payload['roomId'] = space
        elif email:
            payload['toPersonEmail'] = email

        logger.info('Sending WebEx Teams notification')

        try:
            # Attempt POST
            r = requests.post(MESSAGE_URL,
                              data=json.dumps(payload),
                              headers=headers)
            logger.debug('notification status: %s' % r.status_code)
            logger.debug(r.text)
        except Exception:
            logger.exception('Failed to send WebEx Teams notification:')


# entrypoint
webex_plugin = {
    'plugins': {
        'WebExTeamsNotifyPlugin': {
            'class': WebExTeamsNotifyPlugin,
            'enabled': True,
            'kwargs': {},
            'module': 'pyats.contrib.plugins.webex_plugin.webex',
            'name': 'WebExTeamsNotifyPlugin'
        }
    }
}
