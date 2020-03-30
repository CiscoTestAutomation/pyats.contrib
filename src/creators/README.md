testbed-creator
---

Introduction
---
The testbed-creator package is created to streamline the process of 
parsing and converting some form of device data into testbed format, 
whether it maybe a YAML file output or a pyATS testbed object.

Currently, it supports creating testbed from NetBox, Ansible, CSV, Excel, and
CLI. For specific usage, please refer to the examples folder demonstrating the 
utilities. These actions are integrated with pyATS create testbed command, and
it will load actions automatically should the user choose to create new ones.

Creating Actions
---
To create a new action, you need to inherit the `TestbedCreator` base class and
implement the `_generate` function. The `_generate` function should not take in 
any arguments and should return a testbed dictionary in the structure of an
actual testbed file.

The following code snippet demonstrates how to create an example action called 
`Mysql`, which aims to retrieve device data from a MySQL database. The file name
containing the class must match the class name, but in all lower case. Put your
newly made file inside the `actions` folder and it will automatically integrate
with pyATS commands. Please note that only one class can be in an action file.

```
# /actions/mysql.py

class Mysql(TestbedCreator):
    def _init_arguments(self):
      return {
        "required": ["sql_username", "sql_password"]
        "optional": {
          "sql_table": "devices"
        }
      }

    def _generate(self):
        <Parsing Logic and Code>
        return testbed_data
```

To use the action manually, you must instantiate a `Mysql` with the proper
parameters, and then you will have access to `to_testbed_file` and 
`to_testbed_object` which will create a testbed file or object respectively.

```
action = MySql(sql_username="root", sql_password="123456")
action.to_testbed_file("testbed.yaml")
testbed_object = action.to_testbed_object()
```

Calling your action can also be done through pyATS prompt. Simply specify
the name of your action as source and pass in the correct arguments for the 
constructor. Note that all dashes in command line are interpreted as underscores.

```
pyats create testbed mysql --output=testbed.yaml --sql-username=root --sql-password=123456
```

Sample Output
---
Below is a sample testbed output in YAML format. It is expected that the 
generate function also return this format but in a Python dictionary data 
structure. For a detailed explanation on the testbed structure please refer to the
[pyATS documentation.](https://pubhub.devnetcloud.com/media/pyats/docs/topology/schema.html#)

```
devices:
  ios01:
    alias: ios01
    connections:
      cli:
        ip: 192.168.105.1
        protocol: ssh
    credentials:
      default:
        password: iospass
        username: iosuser
    os: ios
    platform: ios
    type: ios
  junos01:
    alias: junos01
    connections:
      netconf:
        ip: 192.168.105.2
        protocol: ssh
    credentials:
      default:
        password: junospass
        username: junosuser
    os: junos
    platform: junos
    type: junos
```