# CML2 Dynamic Topology Plugin

The CML2 Plugin creates a Cisco Modeling Labs (CML2) topology from a pyATS testbed definition, starts the lab, and updates the testbed to connect to the running devices.

## Requirements

- Cisco Modeling Labs (CML) 2.7 or later
- `virl2_client` package (automatically installed with `pyats.contrib`)

## Usage

```bash
# Basic usage with CLI arguments
pyats run job my_job.py --testbed-file testbed.yaml \
    --cml2-enable \
    --cml2-url https://cml2.example.com \
    --cml2-username admin \
    --cml2-password password

# Using environment variables
export CML2_URL=https://cml2.example.com
export CML2_USERNAME=admin
export CML2_PASSWORD=password

pyats run job my_job.py --testbed-file testbed.yaml --cml2-enable

# Keep the lab after job completion
pyats run job my_job.py --testbed-file testbed.yaml \
    --cml2-enable --cml2-keep-lab
```

## Arguments

```
CML2Plugin:
  --cml2-enable              Enable CML2 dynamic topology creation
  --cml2-url                 CML2 server URL (or set CML2_URL env var)
  --cml2-username            CML2 username (or set CML2_USERNAME env var)
  --cml2-password            CML2 password (or set CML2_PASSWORD env var)
  --cml2-keep-lab            Keep the lab after job completion (default: delete)
  --cml2-ssl-verify          Verify SSL certificate (default: False)
  --cml2-lab-prefix          Prefix for lab name (default: "")
  --cml2-init-config         Apply initial config (hostname) to nodes (default: True)

Legacy CLI:
  -cml2_enable
  -cml2_url
  -cml2_username
  -cml2_password
  -cml2_keep_lab
  -cml2_ssl_verify
  -cml2_lab_prefix
  -cml2_init_config
```

## Initial Node Configuration

When `--cml2-init-config` is enabled (default), the plugin applies initial configuration
to each node before starting the lab. The default configuration includes:

- **hostname**: Set to the device alias (if defined) or device name
- **no ip domain lookup**: Disable DNS lookups
- **line con/vty settings**: Disable exec timeout and enable logging synchronous

This ensures that pyATS can properly connect to nodes with the correct hostname.

## Testbed Format

The plugin expects a testbed YAML with:

1. **devices section**: Network devices with `platform` attribute for CML2 node definition mapping
2. **topology section**: Interface definitions with `link` attributes to define connections

### Supported Platforms

| pyATS Platform | CML2 Node Definition |
|----------------|---------------------|
| `iosv`, `iol`  | `iol`               |
| `iosvl2`, `ioll2` | `ioll2`          |
| `csr1000v`     | `csr1000v`          |
| `cat8000v`     | `cat8000v`          |
| `cat9000v`     | `cat9000v`          |
| `nxosv`, `nxosv9000` | `nxosv9000`   |
| `iosxrv9000`   | `iosxrv9000`        |
| `asav`         | `asav`              |

### Example Testbed

```yaml
testbed:
  name: my_lab

devices:
  router1:
    os: ios
    type: router
    platform: iosv
    credentials:
      default:
        username: cisco
        password: cisco

  router2:
    os: ios
    type: router
    platform: iosv
    credentials:
      default:
        username: cisco
        password: cisco

topology:
  router1:
    interfaces:
      Ethernet0/0:
        link: link1
        type: ethernet
      Ethernet0/1:
        link: link2
        type: ethernet

  router2:
    interfaces:
      Ethernet0/0:
        link: link1
        type: ethernet
      Ethernet0/1:
        link: link2
        type: ethernet
```

## How It Works

1. **pre_job**: 
   - Parses the testbed to extract devices and links
   - Creates a CML2 lab with nodes and connections
   - Starts the lab and waits for convergence
   - Retrieves the pyATS testbed from CML2
   - Updates `runtime.testbed` with the new testbed

2. **post_job**:
   - If `--cml2-keep-lab` is not set, stops and deletes the lab

## Notes

- The plugin automatically creates a `terminal_server` device for console access
- Device credentials from the original testbed are preserved
- Interface names (e.g., `Ethernet0/0`) are mapped to CML2 slot numbers
