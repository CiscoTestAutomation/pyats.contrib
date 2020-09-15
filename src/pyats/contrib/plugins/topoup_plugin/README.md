Topology Up Plugin
------------------
The topology Up plugin intents to check all the devices connectivity before
starting the script. It is very useful in the case of virtual devices where
it can be announced that the device is up and running while the device is actually
still in the bringup phase.

Arguments:
```
TopologyUpPlugin:
  --all_devices_up                  Enabling/Disabling the plugin
  --connection_check_timeout        Timeout value for checking the device connectivity
  --connection_check_interval       Time interval to wait before the device connectivity retry
```
