Topology Up Plugin
------------------
The topology Up plugin intents to check all the devices connectivity before
starting the script. It is very useful in the case of virtual devices where
it can be announced that the device is up and running while the device is actually
still in the bringup phase.

Arguments:
```
TopologyUpPlugin:
  --check-all-devices-up            Enabling/Disabling the plugin run, if argument passed set to True; devices' check will run
  --connection-check-timeout        Timeout value for checking the device connectivity, default is 120 seconds
  --connection-check-interval       Time interval to wait before the device connectivity retry, default is 10 seconds

  Legacy:
  -check_all_devices_up            Enabling/Disabling the plugin run, if argument set to True; devices' check will run
  -connection_check_timeout        Timeout value for checking the device connectivity, default is 120 seconds
  -connection_check_interval       Time interval to wait before the device connectivity retry, default is 10 seconds
```
