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
   - Parses the testbed to extract devices, links, and layout/annotation metadata
   - Resolves node coordinates using explicit `(x, y)`, hierarchical tiers, or circular layout
   - Creates a CML2 lab with nodes positioned according to the resolved layout
   - Synthesizes and applies visual annotations (group bounding boxes, node callouts, link subnets)
   - Starts the lab and waits for convergence
   - Retrieves the pyATS testbed from CML2
   - Updates `runtime.testbed` with the new testbed

2. **post_job**:
   - If `--cml2-keep-lab` is not set, stops and deletes the lab

## Hybrid `custom.cml2` Layout & Annotation Engine

The plugin includes an advanced layout and diagramming engine driven declaratively by `custom.cml2` sections in your testbed YAML. It supports:
- **Hierarchical & Circular Layouts**: Automatic coordinate calculation based on device tiers or fallback circular distribution.
- **Explicit Coordinate Overrides**: Pixel-precise positioning via per-device `(x, y)` definitions.
- **Group Bounding Boxes**: Automatic envelope calculation around grouped nodes with configurable padding, border radius, background colors, and embedded titles.
- **Node Callouts**: Automatic extraction and positioning of Loopback IP and role metadata positioned to clear router icons.
- **Link Subnet Annotations**: Subnet labels placed at link midpoints with normal vector offsets or explicit offsets.
- **In-Place Updates**: Non-disruptively update layout and annotations on an existing/running lab without redeploying nodes.

### Schema Reference

#### 1. Testbed Level (`testbed.custom.cml2`)

```yaml
testbed:
  name: bgp_lab
  custom:
    cml2:
      layout:
        engine: hierarchical         # Canonical engine: "hierarchical", "circular", "explicit" ("style" accepted as alias)
        tier_spacing: 180            # Vertical pixel distance between tiers
        node_spacing: 360            # Horizontal pixel distance between nodes in a tier
        center_x: 0                  # Center X coordinate (default: 0)
        center_y: 20                 # Center Y coordinate (default: 20)
      groups:
        as65000:
          title: "AS 65000 - Transit Core"
          members: [R1, R2, R3]      # Canonical member list ("devices" and "nodes" accepted as aliases)
          color: "#EBF3FB40"         # RGBA fill color (default: #EBF3FB40)
          border_color: "#1B5E20A0"  # RGBA border color (default: #1B5E20A0)
          border_radius: 30          # Corner rounding in pixels (default: 30)
          padding: 60                # Padding in pixels around nodes (default: 60)
          z_index: 0                 # Background z-index (default: 0)
          title_size: 14             # Canonical title font size in pt ("title_font_size" accepted as alias)
          title_color: "#0D47A1FF"   # Title text color (default: #0D47A1FF)
      auto_annotations:
        enabled: true                # Master toggle for automatic annotations
        group_boxes: true            # Generate bounding boxes around logical groups
        group_titles: true           # Generate title labels inside group bounding boxes
        node_callouts: true          # Generate Lo0 and role callouts adjacent to nodes
        link_labels: true            # Canonical link labels toggle ("subnets" accepted as alias)
        default_padding: 60          # Default bounding box padding around nodes (px)
        subnets_font_size: 9         # Font size for subnets (default: 9)
        subnets_color: "#555555"     # Font color for subnets (default: #555555)
        normal_offset: 22.0          # Perpendicular pixel offset from link midpoint (default: 22.0)
        z_index: 5                   # Subnet z-index (default: 5)
      links:                         # Canonical link label overrides ("link_overrides" accepted as alias)
        "R1:GigabitEthernet0/0/0/0--R2:GigabitEthernet0/0/0/0": # Interface pair or link alias
          label: "10.0.12.0/24"      # Canonical label content ("subnet" accepted as alias)
          offset_x: 0                # Fine-tuning offset in X
          offset_y: -15               # Fine-tuning offset in Y
      annotations:                   # Explicit user annotations
        - type: rectangle
          x1: -400
          y1: -250
          x2: 800                    # Note: x2 represents width in CML2
          y2: 50                     # Note: y2 represents height in CML2
          color: "#E8F5E940"
          border_color: "#2E7D32"
          z_index: 0
        - type: text
          x1: -380
          y1: -220
          text_content: "Enterprise Edge Topology"  # Canonical text content ("text" accepted as alias)
          text_size: 16              # Canonical text font size in pt ("font_size" accepted as alias)
          color: "#1B5E20"
          z_index: 2
```

#### 2. Device Level (`devices.<device>.custom.cml2`)

```yaml
devices:
  R1:
    os: iosxr
    platform: iosxrv9000
    custom:
      cml2:
        # Tier supports numeric integers (1-4) or semantic string names:
        #   1 / "isp", "external", "wan"     -> External transit tier
        #   2 / "border", "edge", "spine"    -> Enterprise border / edge tier
        #   3 / "core", "rr", "reflector"    -> Core / Route Reflector tier
        #   4 / "client", "leaf", "access"   -> Internal client / access tier
        tier: "border"               # String name (case-insensitive) or integer (1-4)
        x: -180                      # Explicit X coordinate (overrides tier calculation)
        y: -100                      # Explicit Y coordinate (overrides tier calculation)
        role: "Primary ASBR / Core"  # Device role displayed in callout
        group: as65000               # Group membership referencing testbed.custom.cml2.groups
        # Callout supports string shortcut or structured dictionary with independent offsets:
        callout:
          text: "Lo0: 10.255.0.1/32\nPolicy: LP=200, MED=50"
          position: left             # Relative alignment: "left" or "right"
          offset_x: -200             # Independent X offset override (px)
          offset_y: -15              # Independent Y offset override (px)
```

### Coordinate & Annotation Semantics

> **Critical CML2 Coordinate Rule**:
> - For **rectangle annotations**: `x1` and `y1` represent the top-left origin coordinates. `x2` and `y2` represent **width** and **height** in pixels, **not** bottom-right coordinates!
> - For **text annotations**: `x1` and `y1` represent origin coordinates. Text annotations do **not** accept `x2` or `y2`.

#### Z-Index Layering Hierarchy

To avoid visual clipping and ordering conflicts, the layout engine strictly follows a 4-tier $z$-index convention:
- **`z_index: 0`**: Bounding box rectangles and background area highlights.
- **`z_index: 2`**: Group headers and area title labels.
- **`z_index: 5`**: Device callouts (Loopback IP / role) and link subnet annotations.
- **`z_index: 10`**: High-priority notices, topology banners, and prominent markers.

#### Callout Positioning & Icon Clearance

CML2 router icons have an approximate visual footprint radius of $R \approx 30\text{px}$. The callout engine dynamically anchors callouts to prevent link line and icon interference:
- **Left-side nodes** ($x < -50$): Anchored at $x_{\text{node}} - 200, y_{\text{node}} - 15$.
- **Right-side nodes** ($x > 50$): Anchored at $x_{\text{node}} + 40, y_{\text{node}} - 15$.
- **Center nodes** ($-50 \le x \le 50$): Anchored at $x_{\text{node}} + 45, y_{\text{node}} - 15$.

### Complete 5-Router BGP Testbed Reference Example

```yaml
testbed:
  name: bgp_5node_topology
  custom:
    cml2:
      layout:
        engine: hierarchical         # Canonical engine ("style" accepted as alias)
        tier_spacing: 180
        node_spacing: 360
        center_x: 0
        center_y: 20
      groups:
        as65000:
          title: "AS 65000 - Transit Core"
          members: [R1, R2, R3]      # Canonical members ("devices" accepted as alias)
          color: "#EBF3FB40"
          border_color: "#1B5E20A0"
          border_radius: 30
          padding: 60
          z_index: 0
          title_size: 14             # Canonical title size ("title_font_size" accepted as alias)
        as65001:
          title: "AS 65001 - Customer Edge"
          members: [R4, R5]          # Canonical members ("devices" accepted as alias)
          color: "#FFF3E040"
          border_color: "#E65100A0"
          border_radius: 30
          padding: 60
          z_index: 0
          title_size: 14
      auto_annotations:
        enabled: true
        group_boxes: true
        group_titles: true
        node_callouts: true
        link_labels: true            # Canonical link labels ("subnets" accepted as alias)
        default_padding: 60
        subnets_font_size: 9
        subnets_color: "#555555"
        normal_offset: 22.0
      links:                         # Canonical links ("link_overrides" accepted as alias)
        link_r1_r2:
          label: "10.0.12.0/24\niBGP Core"   # Canonical label ("subnet" accepted as alias)
          offset_x: 0
          offset_y: -15
      annotations:
        - type: text
          x1: -150
          y1: -220
          text_content: "BGP Dual-Homed Transit Topology"
          text_size: 16
          color: "#0D47A1"
          z_index: 2

devices:
  R1:
    os: iosxr
    platform: iosxrv9000
    custom:
      cml2:
        tier: "border"               # String tier: "border" -> mapped to Tier 2
        role: "Primary ASBR"
        group: as65000
    interfaces:
      Loopback0:
        ipv4: 10.255.0.1/32
      GigabitEthernet0/0/0/0:
        link: link_r1_r2
        ipv4: 10.0.12.1/24
      GigabitEthernet0/0/0/1:
        link: link_r1_r4
        ipv4: 10.0.14.1/24

  R2:
    os: iosxr
    platform: iosxrv9000
    custom:
      cml2:
        tier: "border"               # String tier: "border" -> mapped to Tier 2
        role: "Secondary ASBR"
        group: as65000
    interfaces:
      Loopback0:
        ipv4: 10.255.0.2/32
      GigabitEthernet0/0/0/0:
        link: link_r1_r2
        ipv4: 10.0.12.2/24
      GigabitEthernet0/0/0/1:
        link: link_r2_r5
        ipv4: 10.0.25.2/24

  R3:
    os: iosxr
    platform: iosxrv9000
    custom:
      cml2:
        tier: "rr"                   # String tier: "rr" -> mapped to Tier 3
        role: "Route Reflector"
        group: as65000
    interfaces:
      Loopback0:
        ipv4: 10.255.0.3/32

  R4:
    os: ios
    platform: iosv
    custom:
      cml2:
        tier: "client"               # String tier: "client" -> mapped to Tier 4
        role: "Branch-1 CE"
        group: as65001
    interfaces:
      Loopback0:
        ipv4: 10.255.0.4/32
      GigabitEthernet0/0:
        link: link_r1_r4
        ipv4: 10.0.14.4/24

  R5:
    os: ios
    platform: iosv
    custom:
      cml2:
        tier: "client"               # String tier: "client" -> mapped to Tier 4
        role: "Branch-2 CE"
        group: as65001
    interfaces:
      Loopback0:
        ipv4: 10.255.0.5/32
      GigabitEthernet0/0:
        link: link_r2_r5
        ipv4: 10.0.25.5/24

topology:
  R1:
    interfaces:
      GigabitEthernet0/0/0/0:
        link: link_r1_r2
      GigabitEthernet0/0/0/1:
        link: link_r1_r4
  R2:
    interfaces:
      GigabitEthernet0/0/0/0:
        link: link_r1_r2
      GigabitEthernet0/0/0/1:
        link: link_r2_r5
  R4:
    interfaces:
      GigabitEthernet0/0:
        link: link_r1_r4
  R5:
    interfaces:
      GigabitEthernet0/0:
        link: link_r2_r5
```

### In-Place Layout and Annotation Updates

You can programmatically refresh node positions and visual annotations on an active CML2 lab without disrupting running nodes or tearing down sessions:

```python
from virl2_client import ClientLibrary
from pyats.topology import loader
from pyats.contrib.plugins.cml2_plugin.cml2 import update_lab_layout_and_annotations_in_place

client = ClientLibrary("https://cml2.example.com", "admin", "password", ssl_verify=False)
testbed = loader.load("testbed.yaml")

# Updates node coordinates in place, clears stale annotations, and reapplies new ones
result = update_lab_layout_and_annotations_in_place(
    lab_or_client=client,
    testbed_or_lab_id="my_running_lab_id",
    testbed=testbed,
    clear_existing_annotations=True,
)

print(
    f"Updated {result['nodes_updated']} nodes and created "
    f"{len(result['annotations_created'])} annotations."
)
```

`update_lab_layout_and_annotations_in_place()` returns a dictionary with the following keys:
- `nodes_updated` (`int`): Count of node coordinates successfully repositioned in the running lab.
- `annotations_created` (`list`): List of created annotation objects on the CML2 canvas.
```

## Notes

- The plugin automatically creates a `terminal_server` device for console access
- Device credentials from the original testbed are preserved
- Interface names (e.g., `Ethernet0/0`) are mapped to CML2 slot numbers

