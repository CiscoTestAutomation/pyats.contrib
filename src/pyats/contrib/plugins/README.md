Plugins
---

WebEx Teams Notification Plugin
---
The WebEx Teams Notification Plugin runs automatically after every job when the
`pyats.contrib` package is installed, and will attempt to send a notification if
the necessary information is provided. The plugin adds additional configuration
and CLI arguments for providing authorization for a WebEx Teams Bot, as well as
the location to send the notification to.

Arguments:
```
WebEx:
  --webex-token         Webex Bot AUTH Token
  --webex-space         Webex Space ID to send notification to
  --webex-email         Email of specific user to send WebEx notification to
```

Configuration options:
```cfg
[webex]
token = <WEBEX_BOT_TOKEN>
space = <WEBEX_SPACE_ID>
email = <EMAIL_OF_INDIVIDUAL>
```

A WebEx Teams Bot Token can be easily generated from the
[developer section of the WebEx website](https://developer.webex.com/docs/bots).

A Space ID can be retrieved as part of "Space Details" from the help menu option
from within the WebEx application.

A notification will only be sent to an individual user if the Space ID is not
specified.

The Notification will include the following information:
 - Job ID
 - Host name
 - Archive location
 - Total number of tasks
 - Total runtime duration
 - Results summary over all tasks