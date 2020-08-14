# Device Discovery

![Device Discovery Diagram](./img/DDdiagram.png)

*pyATS create testbed topology* takes a testbed yaml file provided by the user that contains at least one device that can be connected to and then the creator will discover all the devices and device connections using CDP and LLDP  and then return the information in a new  testbed yaml file. The script also contains a mode that avoids discovering new devices and just reports connections between the devices already in the testbed. 

**Note**: Topology creator can be allowed to change configuration of devices CDP and LLDP protocols if it is important that those configurations remain unchanged make sure to not enable config-discovery

The topology creator also has a variety of options as listed below
- config-discovery: Option to allow creator to configure a devices CDP and LLDP

- add-unconnected-interfaces: Normal behavior for script is to only add interfaces with active connections to topology, this will add all of a devices' interfaces regardless of connection status

- exclude-networks: List ip ranges in form of #.#.#.#/# . Any connection that has an ip address falling in that range will not be added to the topology

- exclude-interfaces: List interface names that if found in a connection, the creator will skip that connection and not add it to the topology

- only-links: If this is flagged the creator will only discover links between devices on the testbed, it won't do any device discovery

- alias: Takes argument in format device:alias device2:alias2  and indicates which alias should be used to connect to the device first, default behavior has no prefered alias

- ssh-only: If True the script will only attempt to use ssh connections to connect to devices, default behavior is to use all connections

- timeout: How long before connection and verification attempts time out. Default value is 10 seconds

- universal-login: give a set of credentials in format 'username' 'password' that will be used to connect to any new devices

- cred-prompt: If flagged, the creator will prompt you to add the username and password for any device that's discovered

- debug-log: Name of debug log to be generated, the log generated will contain more info than just what is sent to the console

- disable-config: If true, the script will not run config commands on devices that it connects to

## Examples
### Discovering only Links Between Existing Devices
By staring with a testbed file and running the following command:

    pyats create testbed topology --testbed-file <testbed-name>.yaml --output result.yaml --only-links
    .......
    2020-08-13T14:56:06: %CONTRIB-INFO: Testbed file generated:
    2020-08-13T14:56:06: %CONTRIB-INFO: result.yaml
This will take the initial testbed yaml file and generate a new yaml file called result.yaml with the originals information with the topology information added on
![Device Discovery Diagram](./img/DDonlylinks.png)

### Device Discovery:
By default the topology creator will search for new devices and add them to the  testbed

    pyats create testbed topology --testbed-file <testbed-name>.yaml --output result.yaml
    .......
    2020-08-13T14:56:06: %CONTRIB-INFO: Testbed file generated:
    2020-08-13T14:56:06: %CONTRIB-INFO: result.yaml
This will generate a new testbed with the newly discovered devices added in
![Device Discovery Diagram](./img/DDdiscovery.png)

### Device Discovery with user input options:
With these flages enabled it will allow the system to enable CDP and LLDP on devices to make sure the creator finds all connections on the devices. Also enabled is manual credential entry and creation of a debug log

    pyats create testbed topology --testbed-file <testbed-name>.yaml --output result.yaml --config-discovery --cred-prompt --debug-log debug.log
    
    Running creator with config-discovery will reset cdp and lldp configuration to basic configuration is this acceptable (y/n) y
    .......
    Enter username to connect to device N93_1_R3: admin
    Enter password to connect to device N93_1_R3:
    Enter username to connect to device N93_2_R4: admin
    Enter password to connect to device N93_2_R4:
    .......
    Enter username to connect to device N93_4_R6: admin
    Enter password to connect to device N93_4_R6:
    Enter username to connect to device N93_3_R5: admin
    Enter password to connect to device N93_3_R5:
    .......
    2020-08-13T14:56:06: %CONTRIB-INFO: Debug log generated: debug.log
    2020-08-13T14:56:06: %CONTRIB-INFO: Testbed file generated:
    2020-08-13T14:56:06: %CONTRIB-INFO: result.yaml
![asdasd](./img/DDconfigcred.png)