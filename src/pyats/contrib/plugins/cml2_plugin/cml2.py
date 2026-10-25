"""
CML2 Dynamic Topology Plugin for pyATS

This plugin creates a CML2 lab topology from a pyATS testbed definition,
starts the lab, and updates the testbed to connect to the running devices.

Requirements:
    - virl2_client package
    - CML2 server access
"""

from __future__ import annotations

import io
import ipaddress
import logging
import math
import os
import re
import yaml
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyats.easypy.plugins.bases import BasePlugin
from pyats.log.utils import banner
from pyats.topology import loader
from pyats.topology.loader import TestbedFileLoader

if TYPE_CHECKING:
    from pyats.topology import Device, Testbed
    from virl2_client import ClientLibrary
    from virl2_client.models import Lab, Node, Interface

log = logging.getLogger(__name__)


# =============================================================================
# Platform Mapping
# =============================================================================

PLATFORM_TO_NODE_DEFINITION: dict[str, str] = {
    # IOS/IOL
    "iosv": "iosv",
    "iol": "iol-xe",
    "iol-xe": "iol-xe",
    "iosvl2": "iosvl2",
    "ioll2": "ioll2-xe",
    "ioll2-xe": "ioll2-xe",
    # CSR/Cat8000v
    "csr1000v": "csr1000v",
    "cat8000v": "cat8000v",
    # Cat9000v
    "cat9000v": "cat9000v",
    # NX-OS
    "nxosv": "nxosv9000",
    "nxosv9000": "nxosv9000",
    # IOS-XR
    "iosxrv": "iosxrv9000",
    "iosxrv9000": "iosxrv9000",
    # ASA
    "asav": "asav",
    # Linux
    "linux": "ubuntu",
    "ubuntu": "ubuntu",
    "alpine": "alpine",
}

# OS to default platform mapping (used when platform is not specified)
OS_TO_DEFAULT_PLATFORM: dict[str, str] = {
    "ios": "iosv",
    "iosxe": "iol-xe",
    "iosxr": "iosxrv9000",
    "nxos": "nxosv9000",
    "asa": "asav",
    "linux": "ubuntu",
}

# Patterns to infer platform from device name
DEVICE_NAME_PATTERNS: list[tuple[str, str]] = [
    (r"csr", "csr1000v"),
    (r"cat8000", "cat8000v"),
    (r"cat9000", "cat9000v"),
    (r"n9k|nxos|nexus", "nxosv9000"),
    (r"xrv|iosxr", "iosxrv9000"),
    (r"asa", "asav"),
    (r"iol", "iol-xe"),
]

# CML2 default credentials by node definition
# Reference: https://developer.cisco.com/docs/modeling-labs/faq/
CML2_DEFAULT_CREDENTIALS: dict[str, dict[str, str]] = {
    # IOL / IOL-XE (IOS on Linux)
    "iol": {"username": "cisco", "password": "cisco"},
    "iol-xe": {"username": "cisco", "password": "cisco"},
    "ioll2": {"username": "cisco", "password": "cisco"},
    "ioll2-xe": {"username": "cisco", "password": "cisco"},
    "iosv": {"username": "cisco", "password": "cisco"},
    "iosvl2": {"username": "cisco", "password": "cisco"},
    # CSR1000v / Cat8000v / Cat9000v (IOS-XE)
    "csr1000v": {"username": "cisco", "password": "cisco"},
    "cat8000v": {"username": "cisco", "password": "cisco"},
    "cat9000v": {"username": "cisco", "password": "cisco"},
    # NX-OSv9000 (NX-OS)
    "nxosv9000": {"username": "admin", "password": "cisco"},
    # IOS-XRv9000 (IOS-XR)
    "iosxrv9000": {"username": "cisco", "password": "cisco"},
    # ASAv
    "asav": {"username": "admin", "password": "Admin123"},
    # Linux
    "ubuntu": {"username": "cisco", "password": "cisco"},
    "alpine": {"username": "alpine", "password": "alpine"},
    # External Connector (no credentials)
    "external_connector": {"username": "", "password": ""},
    # Unmanaged Switch (no credentials)
    "unmanaged_switch": {"username": "", "password": ""},
}


# =============================================================================
# Tier Mapping & Parsing
# =============================================================================

TIER_NAME_MAP: dict[str, int] = {
    # Tier 1: ISP / External Transit / WAN
    "isp": 1,
    "external": 1,
    "transit": 1,
    "wan": 1,
    # Tier 2: Edge / Border / ASBR / Leaf
    "edge": 2,
    "border": 2,
    "asbr": 2,
    "leaf": 2,
    # Tier 3: Core / Route Reflector / Spine
    "core": 3,
    "spine": 3,
    "rr": 3,
    "reflector": 3,
    "route_reflector": 3,
    # Tier 4: Client / Access / Internal / Distribution
    "client": 4,
    "access": 4,
    "internal": 4,
    "distribution": 4,
}


def parse_tier(tier_val: Any, device_name: str = "device") -> int | None:
    """
    Parses a tier specification into an integer (1-indexed architectural tier).
    Supports integers, numeric strings, and architectural role names (case-insensitive, trimmed).
    Raises ValueError for unrecognized strings or invalid types.

    Args:
        tier_val: Integer, numeric string, or architectural tier name.
        device_name: Name of device for error context.

    Returns:
        int | None: Resolved integer tier or None if tier is None.
    """
    if tier_val is None:
        return None
    if isinstance(tier_val, int):
        return tier_val
    if isinstance(tier_val, str):
        cleaned = tier_val.strip().lower()
        if cleaned.isdigit():
            return int(cleaned)
        if cleaned in TIER_NAME_MAP:
            return TIER_NAME_MAP[cleaned]
        raise ValueError(
            f"Invalid string tier '{tier_val}' for device '{device_name}'. "
            f"Expected integer or one of {sorted(TIER_NAME_MAP.keys())}."
        )
    try:
        return int(tier_val)
    except Exception:
        raise ValueError(f"Invalid tier type '{type(tier_val)}' for device '{device_name}'.")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DeviceInfo:
    """Information about a device extracted from testbed."""

    name: str
    platform: str
    os: str
    type: str
    alias: str | None = None
    credentials: dict[str, Any] = field(default_factory=dict)
    # Hybrid layout and annotation extensions:
    x: int | float | None = None
    y: int | float | None = None
    tier: int | None = None
    role: str | None = None
    group: str | None = None
    callout: dict[str, Any] = field(default_factory=dict)

    @property
    def callout_text(self) -> str | None:
        """Return custom callout text string if defined."""
        if isinstance(self.callout, dict):
            return self.callout.get("text")
        return None


@dataclass
class LinkEndpoint:
    """One endpoint of a link."""

    device: str
    interface: str
    slot: int | None = None


@dataclass
class LinkInfo:
    """Information about a link between two devices."""

    link_id: str
    endpoints: list[LinkEndpoint] = field(default_factory=list)


# =============================================================================
# Helper Functions
# =============================================================================


def get_custom_cml2(obj: Any) -> dict[str, Any]:
    """
    Safely extract the 'cml2' metadata dictionary from a pyATS Testbed, Device, or Link.

    Args:
        obj: pyATS Testbed, Device, or Link instance.

    Returns:
        dict[str, Any]: The cml2 metadata dictionary, or an empty dict if not defined.
    """
    if obj is None:
        return {}
    custom = getattr(obj, "custom", None)
    if custom is None:
        return {}
    if isinstance(custom, dict):
        cml2_meta = custom.get("cml2", {})
    else:
        cml2_meta = getattr(custom, "cml2", {})
    if isinstance(cml2_meta, dict):
        return dict(cml2_meta)
    return {}


def parse_interface_slot(interface_name: str, device_type: str | None = None) -> int | None:
    """
    Parse interface name to extract a CML2 interface index.

    For CML2, interfaces are indexed sequentially (0, 1, 2, ...).
    The calculation depends on the device type and interface naming convention.

    For IOL devices (Ethernet slot/port format):
        Interface naming: EthernetX/Y where X=slot, Y=port
        CML2 index formula: cml2_index = slot * 4 + port
        (IOL typically has 4 ports per slot)
        
        Examples:
            Ethernet0/0 -> index 0  (slot=0, port=0: 0*4 + 0 = 0)
            Ethernet0/1 -> index 1  (slot=0, port=1: 0*4 + 1 = 1)
            Ethernet1/0 -> index 4  (slot=1, port=0: 1*4 + 0 = 4)
            Ethernet2/0 -> index 8  (slot=2, port=0: 2*4 + 0 = 8)

    For other devices (GigabitEthernet, etc.):
        Use the last number as the index (original behavior)
        
        Examples:
            GigabitEthernet0/0 -> index 0
            GigabitEthernet0/1 -> index 1
            GigabitEthernet1 -> index 1

    Args:
        interface_name: Interface name string (e.g., "Ethernet1/0")
        device_type: Device type (e.g., "iol", "iosv", "csr1000v"). 
                     If None, auto-detect based on interface name.

    Returns:
        CML2 interface index or None if cannot be determined
    """
    # Skip loopback and management interfaces
    lower_name = interface_name.lower()
    if lower_name.startswith(("loopback", "loop", "lo", "mgmt", "management")):
        return None

    # Determine if this is an IOL-style interface
    # IOL uses "Ethernet" (not GigabitEthernet) with slot/port format
    is_iol = False
    if device_type and device_type.lower() == "iol":
        is_iol = True
    elif lower_name.startswith("ethernet") and not lower_name.startswith("ethernet0"):
        # If interface is like Ethernet1/0, Ethernet2/0 (non-zero slot), likely IOL
        is_iol = True
    elif lower_name.startswith("ethernet") and "/" in interface_name:
        # Ethernet with slot/port format - check device_type or assume IOL if slot > 0
        is_iol = True

    # Try to extract slot and port from common patterns
    # Pattern: Ethernet0/0, GigabitEthernet0/0, Ethernet1/0, etc.
    match = re.search(r"(\d+)[/:](\d+)(?:[/:](\d+))?(?:[/:](\d+))?$", interface_name)
    if match:
        numbers = [int(g) for g in match.groups() if g is not None]
        if len(numbers) >= 2:
            slot = numbers[0]
            port = numbers[1]
            
            if is_iol:
                # IOL: Compute CML2 index = slot * 4 + port
                cml2_index = slot * 4 + port
                log.debug(f"parse_interface_slot (IOL): {interface_name} -> slot={slot}, port={port}, cml2_index={cml2_index}")
                return cml2_index
            else:
                # Non-IOL: Use just the port number (last number)
                log.debug(f"parse_interface_slot (non-IOL): {interface_name} -> port={port}")
                return port
        return numbers[0]

    # Pattern: eth0, ens0, GigabitEthernet1, etc.
    match = re.search(r"(\d+)$", interface_name)
    if match:
        return int(match.group(1))

    return None


def calculate_node_positions(node_count: int, radius: int = 200) -> list[tuple[int, int]]:
    """
    Calculate node positions in a circular layout.

    Args:
        node_count: Number of nodes
        radius: Radius of the circle

    Returns:
        List of (x, y) coordinate tuples
    """
    if node_count == 0:
        return []

    if node_count == 1:
        return [(0, 0)]

    positions = []
    for i in range(node_count):
        angle = (2 * math.pi * i) / node_count - math.pi / 2  # Start from top
        x = int(radius * math.cos(angle))
        y = int(radius * math.sin(angle))
        positions.append((x, y))

    return positions


def calculate_hierarchical_positions(
    devices: dict[str, DeviceInfo],
    tier_spacing: int = 180,
    node_spacing: int = 360,
    center_x: int = 0,
    center_y: int = 20,
) -> dict[str, tuple[int, int]]:
    """
    Computes (x, y) coordinates for devices organized by architectural tier.

    Devices with explicit (x, y) coordinates retain their exact values.
    Devices lacking explicit coordinates are grouped by tier (defaulting to Tier 2)
    and spaced symmetrically across the center axis.

    Args:
        devices: Mapping of device names to DeviceInfo instances.
        tier_spacing: Vertical pixel distance between adjacent tiers.
        node_spacing: Horizontal pixel distance between nodes within the same tier.
        center_x: Global horizontal midpoint offset.
        center_y: Global vertical midpoint offset.

    Returns:
        dict[str, tuple[int, int]]: Mapping of device names to (x, y) coordinate tuples.
    """
    if not devices:
        return {}

    result: dict[str, tuple[int, int]] = {}
    tiers: dict[int, list[str]] = defaultdict(list)

    # Separate devices with explicit coordinates from tier-placed devices
    for name, dev in devices.items():
        dev_x = getattr(dev, "x", None)
        dev_y = getattr(dev, "y", None)
        if dev_x is not None and dev_y is not None:
            result[name] = (int(round(dev_x)), int(round(dev_y)))
        else:
            dev_tier = getattr(dev, "tier", None)
            t = dev_tier if dev_tier is not None else 2
            tiers[t].append(name)

    if not tiers:
        return result

    sorted_tiers = sorted(tiers.keys())
    total_tiers = len(sorted_tiers)
    start_y = center_y - ((total_tiers - 1) * tier_spacing) // 2

    for tier_idx, t in enumerate(sorted_tiers):
        tier_nodes = sorted(tiers[t])
        y_pos = start_y + (tier_idx * tier_spacing)
        n_nodes = len(tier_nodes)
        total_width = (n_nodes - 1) * node_spacing
        start_x = center_x - (total_width // 2)

        for i, name in enumerate(tier_nodes):
            x_pos = start_x + (i * node_spacing)
            result[name] = (int(round(x_pos)), int(round(y_pos)))

    return result


def resolve_node_positions(
    devices: dict[str, DeviceInfo],
    testbed_cml2: dict[str, Any] | None = None,
) -> dict[str, tuple[int, int]]:
    """
    Resolves node positions by checking layout configuration and device metadata.
    Guarantees 100% backward compatibility when custom.cml2 is absent.
    """
    if not devices:
        return {}

    testbed_cml2 = testbed_cml2 or {}
    layout_cfg = testbed_cml2.get("layout", {})
    engine_val = layout_cfg.get("engine") or layout_cfg.get("style", "auto")
    engine = str(engine_val).lower() if engine_val else "auto"

    has_explicit_or_tier = any(
        getattr(d, "x", None) is not None or getattr(d, "tier", None) is not None for d in devices.values()
    )

    nodes_cfg = testbed_cml2.get("nodes", {})
    has_testbed_nodes = bool(nodes_cfg)

    # Legacy circular fallback: when engine is circular OR engine is auto with NO custom layout hints
    if engine == "circular" or (engine == "auto" and not has_explicit_or_tier and not has_testbed_nodes and not layout_cfg):
        circle_pos = calculate_node_positions(len(devices), radius=layout_cfg.get("radius", 200))
        return {name: circle_pos[i] for i, name in enumerate(devices.keys())}

    # If testbed has nodes defined, update devices with missing x/y/tier
    if nodes_cfg:
        for name, dev in devices.items():
            if name in nodes_cfg:
                n_meta = nodes_cfg[name]
                if isinstance(n_meta, dict):
                    if dev.x is None and "x" in n_meta:
                        dev.x = n_meta["x"]
                    if dev.y is None and "y" in n_meta:
                        dev.y = n_meta["y"]
                    if dev.tier is None and "tier" in n_meta:
                        dev.tier = parse_tier(n_meta["tier"], device_name=name)

    tier_spacing = layout_cfg.get("tier_spacing", 180)
    node_spacing = layout_cfg.get("node_spacing", 360)
    center_x = layout_cfg.get("center_x", 0)
    center_y = layout_cfg.get("center_y", 20)

    return calculate_hierarchical_positions(
        devices,
        tier_spacing=tier_spacing,
        node_spacing=node_spacing,
        center_x=center_x,
        center_y=center_y,
    )


def generate_group_annotations(
    groups_config: dict[str, Any],
    node_positions: dict[str, tuple[int, int]],
    default_padding: int = 60,
) -> list[dict[str, Any]]:
    """
    Generates CML2 rectangle bounding boxes and embedded title text annotations
    for administrative groups and areas.

    Args:
        groups_config: Dictionary mapping group_id to group configuration dicts.
        node_positions: Mapping of device names to (x, y) coordinates.
        default_padding: Default padding in pixels around member nodes.

    Returns:
        list[dict[str, Any]]: List of annotation payload dictionaries.
    """
    annotations = []

    for group_id, grp in groups_config.items():
        if not isinstance(grp, dict):
            continue
        members = grp.get("members") or grp.get("devices") or grp.get("nodes", [])
        member_coords = [node_positions[m] for m in members if m in node_positions]
        if not member_coords:
            continue

        pad = grp.get("padding", default_padding)
        pad_x = grp.get("padding_x", pad)
        pad_y = grp.get("padding_y", pad)

        if len(member_coords) == 1:
            half_w = grp.get("half_width", 140)
            half_h = grp.get("half_height", 70)
            x1 = float(member_coords[0][0] - half_w)
            y1 = float(member_coords[0][1] - half_h)
            w = float(half_w * 2)
            h = float(half_h * 2)
        else:
            min_x = min(c[0] for c in member_coords)
            max_x = max(c[0] for c in member_coords)
            min_y = min(c[1] for c in member_coords)
            max_y = max(c[1] for c in member_coords)
            x1 = float(min_x - pad_x)
            y1 = float(min_y - (pad_y + 5))
            w = float((max_x - min_x) + (2 * pad_x))
            h = float((max_y - min_y) + (2 * pad_y + 10))

        # Allow explicit coordinate overrides from YAML
        x1 = float(grp.get("x1", x1))
        y1 = float(grp.get("y1", y1))
        w = float(grp.get("x2", w))
        h = float(grp.get("y2", h))

        z_index = int(grp.get("z_index", 0))

        # 1. Rectangle Bounding Box
        annotations.append({
            "type": "rectangle",
            "x1": x1,
            "y1": y1,
            "x2": w,   # Width in pixels
            "y2": h,   # Height in pixels
            "color": grp.get("color", "#1094DFFF"),
            "border_color": grp.get("border_color", "#808080FF"),
            "border_style": grp.get("border_style", ""),
            "border_radius": int(grp.get("border_radius", 30)),
            "thickness": int(grp.get("thickness", 1)),
            "z_index": z_index,
        })

        # 2. Embedded Title Annotation
        title = grp.get("title", group_id)
        if title:
            annotations.append({
                "type": "text",
                "x1": x1 + 15.0,
                "y1": y1 + 22.0,
                "text_content": str(title),
                "text_size": int(grp.get("title_size") or grp.get("title_font_size", 12)),
                "text_font": "monospace",
                "text_bold": bool(grp.get("title_bold", True)),
                "text_italic": False,
                "text_unit": "pt",
                "color": grp.get("title_color", "#FFFFFFFF"),
                "border_color": "#00000000",
                "thickness": 1,
                "z_index": z_index + 2,
            })

    return annotations


def generate_node_and_link_annotations(
    testbed: Any,
    node_positions: dict[str, tuple[int, int]],
    devices_info: dict[str, DeviceInfo] | None = None,
    link_overrides: dict[str, Any] | None = None,
    auto_ann_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Synthesizes per-node Loopback/role callouts and link midpoint subnet annotations.
    """
    annotations = []
    devices_info = devices_info or {}
    link_overrides = link_overrides or {}
    auto_ann = auto_ann_config or {}

    gen_callouts = auto_ann.get("node_callouts", True)
    if "link_labels" in auto_ann:
        gen_links = bool(auto_ann["link_labels"])
    elif "subnets" in auto_ann:
        gen_links = bool(auto_ann["subnets"])
    else:
        gen_links = True

    # 1. Per-Node Callouts
    if gen_callouts:
        for dev_name, (nx, ny) in node_positions.items():
            dev_obj = getattr(testbed, "devices", {}).get(dev_name)
            dev_info = devices_info.get(dev_name)
            if not dev_obj and not dev_info:
                continue

            # Query Loopback0 IP address
            lo_ip = None
            if dev_obj and hasattr(dev_obj, "topology") and hasattr(dev_obj.topology, "interfaces"):
                for intf_name, intf in dev_obj.topology.interfaces.items():
                    lower_name = intf_name.lower()
                    if "loopback" in lower_name or lower_name in ("lo0", "loopback0") or lower_name.startswith("lo"):
                        if getattr(intf, "ipv4", None):
                            lo_ip = str(intf.ipv4)
                            break

            callout_lines = []
            if lo_ip:
                callout_lines.append(f"Lo0: {lo_ip}")
            if dev_info and dev_info.role:
                callout_lines.append(dev_info.role)
            elif dev_obj and getattr(dev_obj, "role", None):
                callout_lines.append(getattr(dev_obj, "role"))

            # Check explicit callout override
            custom_callout = dev_info.callout if dev_info else {}
            if not custom_callout and dev_obj and hasattr(dev_obj, "custom"):
                custom_callout = getattr(dev_obj, "custom", {}).get("cml2", {}).get("callout", {})

            if isinstance(custom_callout, str):
                custom_callout = {"text": custom_callout}

            if custom_callout.get("text"):
                text = str(custom_callout["text"])
            elif callout_lines:
                text = "\n".join(callout_lines)
            else:
                text = None

            if text:
                if nx < 0:
                    default_ox, default_oy = -200.0, -15.0
                elif nx > 0:
                    default_ox, default_oy = 40.0, -15.0
                else:
                    default_ox, default_oy = 45.0, -12.0

                ox = float(custom_callout.get("offset_x", default_ox))
                oy = float(custom_callout.get("offset_y", default_oy))
                ax = nx + ox
                ay = ny + oy

                annotations.append({
                    "type": "text",
                    "x1": float(ax),
                    "y1": float(ay),
                    "text_content": text,
                    "text_size": int(custom_callout.get("text_size", 12)),
                    "text_font": "monospace",
                    "text_bold": bool(custom_callout.get("bold", False)),
                    "text_italic": False,
                    "text_unit": "pt",
                    "color": custom_callout.get("color", "#333333FF"),
                    "border_color": "#00000000",
                    "z_index": int(custom_callout.get("z_index", 5)),
                })

    # 2. Pairwise Link Subnet Annotations
    if gen_links and hasattr(testbed, "links") and testbed.links:
        for link in testbed.links:
            intfs = getattr(link, "interfaces", [])
            if len(intfs) != 2:
                continue

            interfaces = sorted(intfs, key=lambda i: (getattr(getattr(i, "device", None), "name", ""), getattr(i, "name", "")))
            i1, i2 = interfaces[0], interfaces[1]
            d1 = getattr(getattr(i1, "device", None), "name", None)
            d2 = getattr(getattr(i2, "device", None), "name", None)

            if not d1 or not d2 or d1 not in node_positions or d2 not in node_positions:
                continue

            p1, p2 = node_positions[d1], node_positions[d2]
            mid_x = (p1[0] + p2[0]) / 2.0
            mid_y = (p1[1] + p2[1]) / 2.0

            subnet_text = None
            if getattr(i1, "ipv4", None):
                try:
                    net = ipaddress.ip_interface(str(i1.ipv4)).network
                    subnet_text = str(net)
                except Exception:
                    subnet_text = str(i1.ipv4)
            elif getattr(i2, "ipv4", None):
                try:
                    net = ipaddress.ip_interface(str(i2.ipv4)).network
                    subnet_text = str(net)
                except Exception:
                    subnet_text = str(i2.ipv4)

            link_alias = getattr(link, "alias", None) or getattr(link, "name", f"{d1}-{d2}")
            override = link_overrides.get(link_alias, {})
            if not override and getattr(link, "name", None) in link_overrides:
                override = link_overrides[link.name]
            if not override and f"{d1}-{d2}" in link_overrides:
                override = link_overrides[f"{d1}-{d2}"]
            if not override and f"{d2}-{d1}" in link_overrides:
                override = link_overrides[f"{d2}-{d1}"]

            override_label = override.get("label") or override.get("subnet")
            if override_label:
                subnet_text = str(override_label)

            if not subnet_text:
                continue

            if "offset_x" in override or "offset_y" in override:
                x1 = float(mid_x + override.get("offset_x", 0))
                y1 = float(mid_y + override.get("offset_y", 0))
            else:
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                length = math.hypot(dx, dy)
                if length > 0:
                    offset_dist = 22.0
                    nx = -dy / length
                    ny = dx / length
                    lx = mid_x + (offset_dist * nx)
                    ly = mid_y + (offset_dist * ny)
                else:
                    lx, ly = mid_x, mid_y - 20.0
                x1 = float(lx - 40.0)
                y1 = float(ly - 10.0)

            annotations.append({
                "type": "text",
                "x1": x1,
                "y1": y1,
                "text_content": subnet_text,
                "text_size": int(override.get("text_size", 11)),
                "text_font": "monospace",
                "text_bold": bool(override.get("bold", False)),
                "text_italic": False,
                "text_unit": "pt",
                "color": override.get("color", "#808080FF"),
                "border_color": "#00000000",
                "z_index": int(override.get("z_index", 5)),
            })

    return annotations


def apply_annotations(lab: Any, annotations_list: list[dict[str, Any]]) -> list[Any]:
    """
    Creates annotations in the CML2 lab from a list of annotation dictionaries.
    Defensively strips invalid attributes (e.g., x2/y2 from text annotations)
    and wraps API calls in exception handlers.

    Args:
        lab: virl2_client Lab instance.
        annotations_list: List of annotation property dictionaries.

    Returns:
        list[Any]: List of created annotation instances.
    """
    created = []
    for ann in annotations_list:
        payload = dict(ann)
        ann_type = payload.pop("type", "text")

        # Sanitize text annotations
        if ann_type == "text":
            payload.pop("x2", None)
            payload.pop("y2", None)
            # Property aliasing
            if "text" in payload and "text_content" not in payload:
                payload["text_content"] = payload.pop("text")
            if "font_size" in payload and "text_size" not in payload:
                payload["text_size"] = payload.pop("font_size")
            if "font_family" in payload and "text_font" not in payload:
                payload["text_font"] = payload.pop("font_family")
            if "bold" in payload and "text_bold" not in payload:
                payload["text_bold"] = payload.pop("bold")
            if "italic" in payload and "text_italic" not in payload:
                payload["text_italic"] = payload.pop("italic")

        try:
            obj = lab.create_annotation(annotation_type=ann_type, **payload)
            created.append(obj)
        except Exception as e:
            log.warning(f"Failed to create {ann_type} annotation with payload {payload}: {e}")

    return created


def update_lab_layout_and_annotations_in_place(
    lab_or_client: Any,
    testbed_or_lab_id: Any,
    testbed: Any = None,
    clean_existing: bool = True,
    clear_existing_annotations: bool | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """
    Applies hierarchical layout and visual annotations to an existing CML2 lab
    without restarting nodes, disrupting active sessions, or tearing down peerings.

    Args:
        lab_or_client: virl2_client Lab instance, or ClientLibrary instance.
        testbed_or_lab_id: pyATS Testbed instance, or lab ID string if client passed.
        testbed: pyATS Testbed instance (when lab_or_client is client).
        clean_existing: If True, deletes all prior annotations before creating new ones.
        clear_existing_annotations: Alias for clean_existing.
        client: Optional virl2_client ClientLibrary instance if lab is a string.

    Returns:
        dict[str, Any]: Dictionary containing:
            - 'nodes_updated': Number of nodes whose coordinates were updated (int).
            - 'annotations_created': List of created annotation objects/payloads (list).
    """
    should_clean = clear_existing_annotations if clear_existing_annotations is not None else clean_existing

    if hasattr(lab_or_client, "join_existing_lab") and isinstance(testbed_or_lab_id, str):
        c = lab_or_client
        lab_id = testbed_or_lab_id
        tb = testbed
        lab_obj = c.join_existing_lab(lab_id)
    elif isinstance(lab_or_client, str):
        if client is None:
            raise ValueError("client must be provided when lab is a string identifier")
        lab_obj = client.join_existing_lab(lab_or_client)
        tb = testbed_or_lab_id
    else:
        lab_obj = lab_or_client
        tb = testbed_or_lab_id

    if hasattr(lab_obj, "sync"):
        lab_obj.sync()

    if tb is None:
        return {"nodes_updated": 0, "annotations_created": []}

    parser = TestbedParser(tb)
    devices = parser.get_devices()
    testbed_cml2 = parser.get_custom_cml2()

    # 1. Resolve Node Positions
    positions = resolve_node_positions(devices, testbed_cml2)

    # 2. Update Live Node Coordinates via setters / REST PATCH
    updated_nodes_count = 0
    if hasattr(lab_obj, "nodes"):
        for node in lab_obj.nodes():
            if node.label in positions:
                tx, ty = positions[node.label]
                if node.x != tx or node.y != ty:
                    try:
                        if hasattr(lab_obj, "_session") and hasattr(lab_obj, "id") and hasattr(node, "id"):
                            url = f"labs/{lab_obj.id}/nodes/{node.id}"
                            try:
                                lab_obj._session.patch(url, json={"x": tx, "y": ty})
                            except Exception:
                                pass
                    except Exception:
                        pass
                    node_modified = False
                    try:
                        if node.x != tx:
                            node.x = tx
                            node_modified = True
                        if node.y != ty:
                            node.y = ty
                            node_modified = True
                        if node_modified:
                            updated_nodes_count += 1
                    except Exception as e:
                        log.warning(f"Failed to update coordinates for node {node.label}: {e}")

    # 3. Purge Existing Annotations if requested
    if should_clean and hasattr(lab_obj, "annotations"):
        for ann in list(lab_obj.annotations()):
            try:
                ann.remove()
            except Exception as e:
                log.warning(f"Failed to remove existing annotation {ann}: {e}")

    # 4. Generate All New Annotations
    all_annotations: list[dict[str, Any]] = []
    if testbed_cml2:
        auto_ann = testbed_cml2.get("auto_annotations", {})
        auto_enabled = auto_ann.get("enabled", True)

        if auto_enabled:
            # Group / Area Bounding Boxes
            if auto_ann.get("group_boxes", True):
                groups = testbed_cml2.get("groups", {})
                if groups:
                    pad = auto_ann.get("default_padding", 60)
                    all_annotations.extend(generate_group_annotations(groups, positions, default_padding=pad))

            # Node Callouts & Link Subnets
            link_overrides = testbed_cml2.get("links") or testbed_cml2.get("link_overrides", {})
            all_annotations.extend(generate_node_and_link_annotations(
                tb, positions, devices,
                link_overrides=link_overrides,
                auto_ann_config=auto_ann,
            ))

        # Raw Custom Annotations
        raw_anns = testbed_cml2.get("annotations", [])
        if raw_anns:
            all_annotations.extend(raw_anns)

    # 5. Apply Annotations
    created = apply_annotations(lab_obj, all_annotations)
    if hasattr(lab_obj, "sync"):
        lab_obj.sync()

    log.info(
        f"Updated live lab '{getattr(lab_obj, 'title', 'cml2_lab')}': "
        f"{updated_nodes_count} nodes repositioned, {len(created)} annotations created."
    )
    return {
        "nodes_updated": updated_nodes_count,
        "annotations_created": created,
    }


def get_node_definition(platform: str) -> str:
    """
    Get CML2 node definition for a platform.

    Args:
        platform: pyATS platform name

    Returns:
        CML2 node definition ID
    """
    return PLATFORM_TO_NODE_DEFINITION.get(platform.lower(), platform.lower())


def infer_platform(device_name: str, os: str | None, device_type: str | None) -> str | None:
    """
    Infer platform from device name, OS, or type when not explicitly specified.

    Args:
        device_name: Name of the device
        os: OS type (ios, iosxe, nxos, etc.)
        device_type: Device type (router, switch, etc.)

    Returns:
        Inferred platform or None if cannot be determined
    """
    # Try to infer from device name patterns
    device_name_lower = device_name.lower()
    for pattern, platform in DEVICE_NAME_PATTERNS:
        if re.search(pattern, device_name_lower):
            log.info(f"Inferred platform '{platform}' for device '{device_name}' from name pattern")
            return platform

    # Try to infer from OS
    if os:
        os_lower = os.lower()
        if os_lower in OS_TO_DEFAULT_PLATFORM:
            platform = OS_TO_DEFAULT_PLATFORM[os_lower]
            log.info(f"Inferred platform '{platform}' for device '{device_name}' from OS '{os}'")
            return platform

    return None


# =============================================================================
# Testbed Parser
# =============================================================================


class TestbedParser:
    """Parse pyATS testbed to extract device and link information."""

    # Device names to skip (lowercase) - only infrastructure devices
    SKIP_DEVICES = {
        "terminal_server", "jumphost", "jump_host",
    }

    # Device types to skip (lowercase)
    SKIP_DEVICE_TYPES = {
        "tgn", "traffic_generator", "traffic-generator",
        "trafficgen", "pagent", "trex",
    }

    # OS types that indicate non-CML2 devices (lowercase)
    SKIP_OS_TYPES = {
        "ixia", "ixiangpf", "ixianative", "ixiahltapi",
        "pagent", "trex", "spirent", "stc",
    }

    # Platform types that indicate non-CML2 devices (lowercase)
    SKIP_PLATFORMS = {
        "ixia", "pagent", "trex", "spirent", "stc",
        "n2x", "agilent", "keysight",
    }

    def __init__(self, testbed: Testbed) -> None:
        self.testbed = testbed
        self._devices: dict[str, DeviceInfo] | None = None
        self._links: list[LinkInfo] | None = None
        self._custom_cml2: dict[str, Any] | None = None

    def get_custom_cml2(self) -> dict[str, Any]:
        """Extract testbed-level custom.cml2 metadata."""
        if self._custom_cml2 is not None:
            return self._custom_cml2
        self._custom_cml2 = get_custom_cml2(self.testbed)
        return self._custom_cml2

    @property
    def lab_name(self) -> str:
        """Get lab name from testbed."""
        return self.testbed.name or "pyats_lab"

    def get_devices(self) -> dict[str, DeviceInfo]:
        """Extract network device information from testbed."""
        if self._devices is not None:
            return self._devices

        self._devices = {}
        self._skipped_devices: list[tuple[str, str]] = []  # (name, reason)

        for device_name, device in self.testbed.devices.items():
            # Skip special device names
            if device_name.lower() in self.SKIP_DEVICES:
                self._skipped_devices.append((device_name, "special device name"))
                continue

            # Get device attributes
            device_os = getattr(device, "os", None)
            device_type = getattr(device, "type", None)
            platform = getattr(device, "platform", None)

            # Skip devices with non-CML2 OS types (traffic generators, etc.)
            if device_os and device_os.lower() in self.SKIP_OS_TYPES:
                self._skipped_devices.append((device_name, f"unsupported OS '{device_os}'"))
                log.info(f"Skipping device {device_name}: OS '{device_os}' is not supported in CML2")
                continue

            # Skip devices with non-CML2 device types
            if device_type and device_type.lower() in self.SKIP_DEVICE_TYPES:
                self._skipped_devices.append((device_name, f"device type '{device_type}'"))
                log.info(f"Skipping device {device_name}: type '{device_type}' is not supported in CML2")
                continue

            # Skip devices with non-CML2 platforms
            if platform and platform.lower() in self.SKIP_PLATFORMS:
                self._skipped_devices.append((device_name, f"platform '{platform}'"))
                log.info(f"Skipping device {device_name}: platform '{platform}' is not supported in CML2")
                continue

            # If platform is not set or not a valid CML2 node definition, try to infer
            if not platform or platform.lower() not in PLATFORM_TO_NODE_DEFINITION:
                inferred = infer_platform(device_name, device_os, device_type)
                if inferred:
                    platform = inferred
                else:
                    # Platform is set but not supported, or couldn't infer
                    reason = f"unsupported platform '{platform}'" if platform else "no platform and could not infer"
                    self._skipped_devices.append((device_name, reason))
                    log.warning(f"Skipping device {device_name}: {reason}")
                    continue

            # Extract credentials
            credentials = {}
            if hasattr(device, "credentials") and device.credentials:
                for cred_name, cred in device.credentials.items():
                    credentials[cred_name] = {
                        "username": getattr(cred, "username", "cisco"),
                        "password": getattr(cred, "password", "cisco"),
                    }

            # Get device alias
            device_alias = getattr(device, "alias", None)

            # Hybrid layout and annotation extensions:
            dev_cml2 = get_custom_cml2(device)
            x = dev_cml2.get("x")
            y = dev_cml2.get("y")
            tier = dev_cml2.get("tier")
            role = dev_cml2.get("role")
            group = dev_cml2.get("group")
            callout = dev_cml2.get("callout", {})
            if isinstance(callout, str):
                callout = {"text": callout}
            elif not isinstance(callout, dict):
                callout = {}

            # Format coordinates cleanly
            resolved_x = None
            if x is not None:
                resolved_x = int(x) if isinstance(x, int) or (isinstance(x, float) and x.is_integer()) else float(x)
            resolved_y = None
            if y is not None:
                resolved_y = int(y) if isinstance(y, int) or (isinstance(y, float) and y.is_integer()) else float(y)

            self._devices[device_name] = DeviceInfo(
                name=device_name,
                platform=platform,
                os=device_os or "ios",
                type=device_type or "router",
                alias=device_alias,
                credentials=credentials,
                x=resolved_x,
                y=resolved_y,
                tier=parse_tier(tier, device_name=device_name),
                role=str(role) if role is not None else None,
                group=str(group) if group is not None else None,
                callout=callout,
            )

        # Log summary of skipped devices
        if self._skipped_devices:
            log.info(f"Skipped {len(self._skipped_devices)} device(s) not supported in CML2:")
            for name, reason in self._skipped_devices:
                log.info(f"  - {name}: {reason}")

        return self._devices

    @property
    def skipped_devices(self) -> list[tuple[str, str]]:
        """Return list of (device_name, reason) tuples for skipped devices."""
        if self._devices is None:
            self.get_devices()
        return getattr(self, '_skipped_devices', [])

    def get_alias_map(self) -> dict[str, str]:
        """Build a mapping from device alias to actual device name."""
        alias_map: dict[str, str] = {}
        for device_name, device in self.testbed.devices.items():
            if hasattr(device, "alias") and device.alias:
                alias_map[device.alias] = device_name
        return alias_map

    def get_links(self) -> list[LinkInfo]:
        """Extract link information from testbed links."""
        if self._links is not None:
            return self._links

        self._links = []

        # Check if testbed has links
        if not hasattr(self.testbed, "links") or not self.testbed.links:
            log.info("No links found in testbed")
            return self._links

        # Track slot assignments for interfaces with unparseable names (alias-style like 'leaf2_infra_intf')
        # Maps (device_name, interface_name) -> assigned_slot
        interface_slot_map: dict[tuple[str, str], int] = {}
        device_next_slot: dict[str, int] = defaultdict(int)
        
        # First pass: collect all interfaces and determine slots
        # - For parseable names (Ethernet1/0), extract slot from name
        # - For alias-style names, assign sequential slots per device
        for link in self.testbed.links:
            for intf in link.interfaces:
                device_name = intf.device.name
                intf_name = intf.name
                
                if device_name not in self.get_devices():
                    continue
                
                # Skip if we've already assigned a slot to this interface
                key = (device_name, intf_name)
                if key in interface_slot_map:
                    continue
                
                device_type = getattr(intf.device, 'type', None) or getattr(intf.device, 'platform', None)
                slot = parse_interface_slot(intf_name, device_type)
                
                if slot is not None:
                    interface_slot_map[key] = slot
                    # Track highest slot seen for this device
                    device_next_slot[device_name] = max(device_next_slot[device_name], slot + 1)
        
        # Second pass: assign slots to interfaces that couldn't be parsed
        for link in self.testbed.links:
            for intf in link.interfaces:
                device_name = intf.device.name
                intf_name = intf.name
                
                if device_name not in self.get_devices():
                    continue
                
                key = (device_name, intf_name)
                if key not in interface_slot_map:
                    # Assign next available slot for this device
                    slot = device_next_slot[device_name]
                    device_next_slot[device_name] += 1
                    interface_slot_map[key] = slot
                    log.debug(f"  {device_name}:{intf_name} -> assigned slot={slot} (auto)")

        # Third pass: create links using the slot assignments
        for link in self.testbed.links:
            endpoints = []
            
            # Get interfaces connected to this link
            for intf in link.interfaces:
                device_name = intf.device.name
                intf_name = intf.name
                
                # Skip devices not in our CML2 device list
                if device_name not in self.get_devices():
                    continue
                
                key = (device_name, intf_name)
                slot = interface_slot_map.get(key)
                log.debug(f"  {device_name}:{intf_name} -> slot={slot}")
                
                endpoints.append(
                    LinkEndpoint(
                        device=device_name,
                        interface=intf_name,
                        slot=slot,
                    )
                )
            
            # Only create links with exactly 2 endpoints
            if len(endpoints) == 2:
                self._links.append(LinkInfo(link_id=link.name, endpoints=endpoints))
                log.info(f"Found link: {link.name} ({endpoints[0].device}:{endpoints[0].interface} <-> {endpoints[1].device}:{endpoints[1].interface})")
            elif len(endpoints) > 2:
                log.warning(f"Link {link.name} has {len(endpoints)} endpoints, skipping")

        return self._links


# =============================================================================
# CML2 Lab Builder
# =============================================================================


class CML2LabBuilder:
    """Build CML2 lab from parsed testbed information."""

    def __init__(
        self,
        client: ClientLibrary,
        lab_name: str,
        devices: dict[str, DeviceInfo],
        links: list[LinkInfo],
        alias_map: dict[str, str] | None = None,
        testbed: Testbed | None = None,
        custom_cml2: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.lab_name = lab_name
        self.devices = devices
        self.links = links
        self.alias_map = alias_map or {}  # alias -> actual device name
        self.testbed = testbed
        self.custom_cml2 = custom_cml2 or (get_custom_cml2(testbed) if testbed else {})
        self.lab: Lab | None = None
        self.node_map: dict[str, Node] = {}
        # Maps (device_name, original_interface) -> cml2_interface_name
        self.interface_mapping: dict[tuple[str, str], str] = {}

    def _get_node(self, name: str) -> Node | None:
        """Get node by device name or alias."""
        # Try direct lookup
        if name in self.node_map:
            return self.node_map[name]
        # Try resolving alias to actual name
        actual_name = self.alias_map.get(name)
        if actual_name and actual_name in self.node_map:
            return self.node_map[actual_name]
        return None

    def build(self) -> Lab:
        """Build the complete lab topology."""
        log.info(banner(f"Creating CML2 Lab: {self.lab_name}"))

        # Create lab
        self.lab = self.client.create_lab(title=self.lab_name)
        log.info(f"Created lab: {self.lab.title} (ID: {self.lab.id})")

        try:
            # Create nodes
            self._create_nodes()

            # Sync lab to ensure interfaces are populated
            self.lab.sync()

            # Create links
            self._create_links()

            # Create visual annotations
            self._create_annotations()

            return self.lab

        except Exception as e:
            log.error(f"Failed to build lab: {e}")
            # Clean up on failure
            if self.lab:
                try:
                    self.lab.remove()
                except Exception:
                    pass
            raise

    def _create_nodes(self) -> None:
        """Create all nodes in the lab using resolved coordinates."""
        positions = resolve_node_positions(self.devices, self.custom_cml2)

        for device_name, device_info in self.devices.items():
            node_definition = get_node_definition(device_info.platform)
            x, y = positions.get(device_name, (0, 0))

            log.info(f"Creating node: {device_name} ({node_definition}) at ({x}, {y})")

            node = self.lab.create_node(
                label=device_name,
                node_definition=node_definition,
                x=x,
                y=y,
                populate_interfaces=True,
            )
            self.node_map[device_name] = node
            log.info(f"  Created node ID: {node.id}")

    def _create_annotations(self) -> None:
        """Create all visual annotations on the new lab."""
        if not self.custom_cml2 or not self.lab:
            return

        positions = {dev_name: (node.x, node.y) for dev_name, node in self.node_map.items()}
        all_annotations: list[dict[str, Any]] = []

        auto_ann = self.custom_cml2.get("auto_annotations", {})
        if auto_ann.get("enabled", True):
            if auto_ann.get("group_boxes", True):
                groups = self.custom_cml2.get("groups", {})
                if groups:
                    pad = auto_ann.get("default_padding", 60)
                    all_annotations.extend(generate_group_annotations(groups, positions, default_padding=pad))

            if self.testbed:
                link_overrides = self.custom_cml2.get("links") or self.custom_cml2.get("link_overrides", {})
                all_annotations.extend(generate_node_and_link_annotations(
                    self.testbed, positions, self.devices,
                    link_overrides=link_overrides,
                    auto_ann_config=auto_ann,
                ))

        raw_anns = self.custom_cml2.get("annotations", [])
        if raw_anns:
            all_annotations.extend(raw_anns)

        if all_annotations:
            apply_annotations(self.lab, all_annotations)

    def _get_interface_by_slot(self, node: Node, slot: int) -> Interface | None:
        """Get interface by slot number."""
        for interface in node.interfaces():
            if interface.slot == slot:
                if interface.connected:
                    log.warning(f"Interface slot {slot} on {node.label} is already connected")
                    return None
                return interface
        return None

    def _get_next_available_interface(
        self, node: Node, used_slots: set[int]
    ) -> Interface | None:
        """Get next available interface that hasn't been used and isn't connected."""
        for interface in sorted(node.interfaces(), key=lambda i: i.slot or 0):
            if interface.slot is not None and interface.slot not in used_slots:
                # Also check if interface is already connected in CML2
                if not interface.connected:
                    return interface
        return None

    def _add_interface_to_node(self, node: Node) -> Interface | None:
        """Add a new interface to a CML2 node."""
        try:
            # Get current max slot number
            max_slot = -1
            for intf in node.interfaces():
                if intf.slot is not None and intf.slot > max_slot:
                    max_slot = intf.slot
            
            new_slot = max_slot + 1
            log.info(f"Adding new interface (slot {new_slot}) to node {node.label}")
            
            # Create new interface on the node
            new_intf = node.create_interface(slot=new_slot)
            return new_intf
        except Exception as e:
            log.warning(f"Failed to add interface to {node.label}: {e}")
            return None

    def _create_links(self) -> None:
        """Create all links between nodes."""
        # Track used interfaces per node
        used_interfaces: dict[str, set[int]] = defaultdict(set)

        # Phase 1: Calculate required slots for each node and pre-add interfaces
        log.info("Phase 1: Ensuring all required interfaces exist...")
        required_slots: dict[str, set[int]] = defaultdict(set)
        
        for link_info in self.links:
            if len(link_info.endpoints) != 2:
                continue
            for ep in link_info.endpoints:
                if ep.slot is not None:
                    required_slots[ep.device].add(ep.slot)
        
        # Pre-add interfaces for required slots
        for device_name, slots in required_slots.items():
            node = self._get_node(device_name)
            if not node:
                continue
            
            # Get existing slots
            existing_slots = {intf.slot for intf in node.interfaces() if intf.slot is not None}
            missing_slots = slots - existing_slots
            
            if missing_slots:
                max_needed = max(missing_slots)
                log.info(f"  {device_name}: needs slots up to {max_needed}, has {sorted(existing_slots)}")
                
                # Add interfaces until we have all required slots
                # CML2 adds interfaces sequentially, so add enough to cover max slot
                current_max = max(existing_slots) if existing_slots else -1
                while current_max < max_needed:
                    new_intf = self._add_interface_to_node(node)
                    if new_intf and new_intf.slot is not None:
                        current_max = new_intf.slot
                    else:
                        break
        
        # Sync to ensure all interfaces are available
        if self.lab:
            self.lab.sync()

        # Debug: Log available interfaces for each node after pre-adding
        log.info("Available CML2 interfaces per node (after pre-adding):")
        for device_name, node in self.node_map.items():
            intfs = list(node.interfaces())
            intf_info = [(i.label, i.slot, i.connected) for i in intfs]
            log.info(f"  {device_name}: {len(intfs)} interfaces - {intf_info[:12]}...")

        # Phase 2: Create links with proper slot matching
        log.info("Phase 2: Creating links...")
        for link_info in self.links:
            if len(link_info.endpoints) != 2:
                continue

            ep1, ep2 = link_info.endpoints

            node1 = self._get_node(ep1.device)
            node2 = self._get_node(ep2.device)

            if not node1 or not node2:
                log.warning(f"Skipping link {link_info.link_id}: missing node(s)")
                continue

            # Get interfaces
            intf1: Interface | None = None
            intf2: Interface | None = None

            # Try to match by slot
            log.debug(f"Link {link_info.link_id}: ep1={ep1.device}:{ep1.interface}(slot={ep1.slot}), ep2={ep2.device}:{ep2.interface}(slot={ep2.slot})")
            if ep1.slot is not None:
                intf1 = self._get_interface_by_slot(node1, ep1.slot)
                if intf1:
                    log.debug(f"  Found {ep1.device} slot {ep1.slot} -> {intf1.label}")
                else:
                    log.debug(f"  No interface found for {ep1.device} slot {ep1.slot}")
            if ep2.slot is not None:
                intf2 = self._get_interface_by_slot(node2, ep2.slot)
                if intf2:
                    log.debug(f"  Found {ep2.device} slot {ep2.slot} -> {intf2.label}")
                else:
                    log.debug(f"  No interface found for {ep2.device} slot {ep2.slot}")

            # Fall back to next available interface (only if slot matching failed)
            if intf1 is None:
                intf1 = self._get_next_available_interface(
                    node1, used_interfaces[ep1.device]
                )
                if intf1:
                    log.warning(f"  Fallback: {ep1.device}:{ep1.interface} using next available -> {intf1.label} (slot {intf1.slot})")
            if intf2 is None:
                intf2 = self._get_next_available_interface(
                    node2, used_interfaces[ep2.device]
                )
                if intf2:
                    log.warning(f"  Fallback: {ep2.device}:{ep2.interface} using next available -> {intf2.label} (slot {intf2.slot})")

            if not intf1 or not intf2:
                log.warning(
                    f"Skipping link {link_info.link_id}: no available interfaces "
                    f"and could not add new ones"
                )
                continue

            # Mark interfaces as used
            if intf1.slot is not None:
                used_interfaces[ep1.device].add(intf1.slot)
            if intf2.slot is not None:
                used_interfaces[ep2.device].add(intf2.slot)

            # Store mapping from original interface name to CML2 interface name
            # This is needed because IOL may use different interface names
            self.interface_mapping[(ep1.device, ep1.interface)] = intf1.label
            self.interface_mapping[(ep2.device, ep2.interface)] = intf2.label
            log.info(
                f"Interface mapping: {ep1.device}:{ep1.interface} -> {intf1.label}"
            )
            log.info(
                f"Interface mapping: {ep2.device}:{ep2.interface} -> {intf2.label}"
            )

            log.info(
                f"Creating link: {ep1.device}:{intf1.label} <-> {ep2.device}:{intf2.label}"
            )

            self.lab.create_link(intf1, intf2)

    def configure_nodes(self, config_template: str | None = None) -> None:
        """
        Apply initial configuration to nodes before starting the lab.
        
        By default, sets hostname to the device's alias (if available) or device name.
        Custom configuration can be provided via config_template.
        
        Args:
            config_template: Optional configuration template string.
                            Use {hostname} placeholder for device name/alias.
                            If None, uses default template with just hostname.
        """
        if not self.lab:
            raise RuntimeError("Lab not created")

        log.info(banner("Configuring CML2 Nodes"))

        # Default template sets hostname and basic settings
        default_template = """hostname {hostname}
"""
        template = config_template if config_template else default_template

        for device_name, node in self.node_map.items():
            # Get device info to access alias
            device_info = self.devices.get(device_name)
            
            # Use device name for hostname (Unicon expects hostname to match testbed device name)
            # Note: We use device_name, not alias, because Unicon validates hostname against device name
            hostname = device_name
            
            # Generate config from template
            config = template.format(hostname=hostname)
            
            log.info(f"Applying config to {device_name} (hostname: {hostname})")
            log.debug(f"Config:\n{config}")
            
            try:
                # Set node configuration.
                # In virl2_client, `Node.configuration` is a property that sends a PATCH
                # to CML2 to set the day0 configuration. Assigning to `node.config` only
                # sets a dead attribute on the python object and leaves CML2 day0 config
                # as default ("inserthostname-here"), breaking Unicon prompt matching.
                try:
                    node.configuration = config
                except (AttributeError, TypeError):
                    node.config = config
                log.info(f"  Configuration applied to {device_name}")
            except Exception as e:
                log.warning(f"  Failed to apply config to {device_name}: {e}")

    def start_and_wait(self, timeout: int = 600) -> None:
        """Start the lab and wait for convergence."""
        if not self.lab:
            raise RuntimeError("Lab not created")

        log.info(banner("Starting CML2 Lab"))
        log.info(f"Starting lab: {self.lab.title}")

        self.lab.start(wait=True)
        log.info("Lab started and converged successfully")

    def verify_links(self) -> None:
        """
        Verify that all expected links were created in CML2.
        
        Raises:
            RuntimeError: If expected links are missing in the CML2 lab.
        """
        if not self.lab:
            raise RuntimeError("Lab not created")

        log.info(banner("Verifying CML2 Links"))

        # Sync lab to get latest state
        self.lab.sync()

        # Get actual links from CML2
        actual_links: set[tuple[str, str]] = set()
        for link in self.lab.links():
            intf_a = link.interface_a
            intf_b = link.interface_b
            if intf_a and intf_b:
                node_a = intf_a.node.label
                node_b = intf_b.node.label
                # Store as sorted tuple for comparison
                link_pair = tuple(sorted([node_a, node_b]))
                actual_links.add(link_pair)
                log.info(f"  Found link: {node_a}:{intf_a.label} <-> {node_b}:{intf_b.label}")

        # Get expected links from testbed
        expected_links: set[tuple[str, str]] = set()
        for link_info in self.links:
            if len(link_info.endpoints) == 2:
                ep1, ep2 = link_info.endpoints
                # Resolve aliases to actual device names
                dev1 = self.alias_map.get(ep1.device, ep1.device)
                dev2 = self.alias_map.get(ep2.device, ep2.device)
                link_pair = tuple(sorted([dev1, dev2]))
                expected_links.add(link_pair)

        log.info(f"Expected links: {len(expected_links)}, Actual links: {len(actual_links)}")

        # Check for missing links
        missing_links = expected_links - actual_links
        if missing_links:
            missing_str = ", ".join([f"{a} <-> {b}" for a, b in missing_links])
            error_msg = f"Missing links in CML2 lab: {missing_str}"
            log.error(error_msg)
            raise RuntimeError(error_msg)


# =============================================================================
# CML2 Plugin
# =============================================================================


class CML2Plugin(BasePlugin):
    """
    CML2 Dynamic Topology Plugin.

    Creates a CML2 lab topology from testbed definition, starts it,
    and updates the testbed for test execution.
    """

    name = "CML2Plugin"

    @classmethod
    def configure_parser(cls, parser, legacy_cli: bool = True):
        """Configure CLI arguments for the plugin."""
        grp = parser.add_argument_group("CML2Plugin")

        if legacy_cli:
            enable = ["-cml2_enable"]
            url = ["-cml2_url"]
            username = ["-cml2_username"]
            password = ["-cml2_password"]
            keep_lab = ["-cml2_keep_lab"]
            ssl_verify = ["-cml2_ssl_verify"]
            lab_prefix = ["-cml2_lab_prefix"]
            init_config = ["-cml2_init_config"]
        else:
            enable = ["--cml2-enable"]
            url = ["--cml2-url"]
            username = ["--cml2-username"]
            password = ["--cml2-password"]
            keep_lab = ["--cml2-keep-lab"]
            ssl_verify = ["--cml2-ssl-verify"]
            lab_prefix = ["--cml2-lab-prefix"]
            init_config = ["--cml2-init-config"]

        grp.add_argument(
            *enable,
            dest="cml2_enable",
            action="store_true",
            default=False,
            help="Enable CML2 dynamic topology creation",
        )

        grp.add_argument(
            *url,
            dest="cml2_url",
            action="store",
            default=os.environ.get("CML2_URL"),
            help="CML2 server URL (or set CML2_URL env var)",
        )

        grp.add_argument(
            *username,
            dest="cml2_username",
            action="store",
            default=os.environ.get("CML2_USERNAME"),
            help="CML2 username (or set CML2_USERNAME env var)",
        )

        grp.add_argument(
            *password,
            dest="cml2_password",
            action="store",
            default=os.environ.get("CML2_PASSWORD"),
            help="CML2 password (or set CML2_PASSWORD env var)",
        )

        grp.add_argument(
            *keep_lab,
            dest="cml2_keep_lab",
            action="store_true",
            default=False,
            help="Keep the lab after job completion",
        )

        grp.add_argument(
            *ssl_verify,
            dest="cml2_ssl_verify",
            action="store_true",
            default=False,
            help="Verify SSL certificate (default: False)",
        )

        grp.add_argument(
            *lab_prefix,
            dest="cml2_lab_prefix",
            action="store",
            default="",
            help="Prefix for lab name",
        )

        grp.add_argument(
            *init_config,
            dest="cml2_init_config",
            action="store_true",
            default=True,
            help="Apply initial configuration (hostname) to nodes before starting (default: True)",
        )

        return grp

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.client: ClientLibrary | None = None
        self.lab: Lab | None = None
        self.original_testbed: Testbed | None = None
        self._pre_job_errored: bool = False
        # Maps (device_name, original_interface) -> cml2_interface_name
        self._interface_mapping: dict[tuple[str, str], str] = {}

    def pre_job(self, job) -> None:
        """
        Pre-job hook: Create and start CML2 lab, update testbed.

        Args:
            job: The job object
        """
        # Check if plugin is enabled
        if not self.runtime.args.cml2_enable:
            log.info("CML2Plugin is disabled. Use --cml2-enable to enable.")
            return

        log.info(banner("CML2 Plugin - Pre Job"))

        # Validate configuration
        if not self._validate_config():
            raise RuntimeError("CML2Plugin configuration is incomplete")

        # Store original testbed
        self.original_testbed = self.runtime.testbed

        try:
            # Connect to CML2
            self._connect_to_cml2()

            # Parse testbed - all supported devices will be created in CML2
            parser = TestbedParser(self.original_testbed)
            devices = parser.get_devices()
            links = parser.get_links()

            if not devices:
                log.warning("No supported devices found in testbed to create in CML2.")
                return

            log.info(f"Found {len(devices)} device(s) and {len(links)} link(s)")

            # Build lab name
            lab_name = self.runtime.args.cml2_lab_prefix + parser.lab_name

            # Get alias mapping for device name resolution
            alias_map = parser.get_alias_map()

            # Create and start lab
            builder = CML2LabBuilder(
                self.client,
                lab_name,
                devices,
                links,
                alias_map,
                testbed=self.original_testbed,
            )
            self.lab = builder.build()

            # Apply initial configuration if enabled
            if getattr(self.runtime.args, 'cml2_init_config', True):
                builder.configure_nodes()

            builder.start_and_wait()

            # Verify links were created correctly
            builder.verify_links()

            # Store the interface mapping for testbed update
            self._interface_mapping = builder.interface_mapping

            # Update testbed
            self._update_testbed()

            # Display topology summary
            self._display_topology_summary()

            log.info(banner("CML2 Plugin - Pre Job Complete"))

        except Exception as e:
            log.error(f"CML2Plugin failed: {e}")
            self._pre_job_errored = True
            # Don't cleanup here - let post_job handle it to respect --cml2-keep-lab
            raise

    def post_job(self, job) -> None:
        """
        Post-job hook: Clean up CML2 lab if not keeping it.

        This runs even if pre_job errored, to ensure cleanup happens
        unless --cml2-keep-lab is specified.

        Args:
            job: The job object
        """
        if not self.runtime.args.cml2_enable:
            return

        if self.lab is None:
            if self._pre_job_errored:
                log.info(banner("CML2 Plugin - Post Job"))
                log.info("No lab to cleanup (pre_job failed before lab creation)")
            return

        log.info(banner("CML2 Plugin - Post Job"))

        if self._pre_job_errored:
            log.info("Pre-job failed, attempting cleanup...")

        if self.runtime.args.cml2_keep_lab:
            log.info(f"Keeping lab: {self.lab.title} (ID: {self.lab.id})")
            log.info(f"  URL: {self.runtime.args.cml2_url}/lab/{self.lab.id}")
            return

        log.info(f"Cleaning up lab: {self.lab.title}")
        self._cleanup_lab(wait=True)

        log.info(banner("CML2 Plugin - Post Job Complete"))

    def _validate_config(self) -> bool:
        """Validate plugin configuration."""
        errors = []

        if not self.runtime.args.cml2_url:
            errors.append("CML2 URL is required (--cml2-url or CML2_URL env var)")

        if not self.runtime.args.cml2_username:
            errors.append(
                "CML2 username is required (--cml2-username or CML2_USERNAME env var)"
            )

        if not self.runtime.args.cml2_password:
            errors.append(
                "CML2 password is required (--cml2-password or CML2_PASSWORD env var)"
            )

        # Load testbed if not already loaded (e.g., when --skip-bringup is used)
        if not self.runtime.testbed:
            testbed = self._load_testbed()
            if testbed:
                # Set testbed on job object (runtime.testbed is read-only property)
                if self.runtime.job:
                    self.runtime.job.testbed = testbed
                    log.info(f"Loaded testbed: {testbed.name}")
                else:
                    errors.append("Cannot set testbed: runtime.job is None")
            else:
                errors.append("Testbed is required but could not be loaded")

        if errors:
            for error in errors:
                log.error(error)
            return False

        return True

    def _load_testbed(self) -> "Testbed | None":
        """
        Load testbed from file if not already loaded.
        
        Tries to load from:
        1. --logical-testbed-file argument (for dyntopo logical testbeds)
        2. --testbed-file argument (standard testbed)
        
        Returns:
            Loaded Testbed object or None if no testbed file specified
        """
        # Try logical testbed file first (for dyntopo)
        logical_tb_file = getattr(self.runtime.args, 'logical_testbed_file', None)
        if logical_tb_file and os.path.isfile(logical_tb_file):
            log.info(f"Loading logical testbed from: {logical_tb_file}")
            try:
                # Use TestbedFileLoader to load as raw dict first (handles dyntopo extensions)
                # then convert to Testbed object
                raw_config = TestbedFileLoader().load_arbitrary(logical_tb_file)
                
                # Transform logical testbed: use actual_name for interface names
                # and strip dyntopo-specific keys
                self._transform_logical_testbed(raw_config)
                
                # Now load the cleaned config as a proper Testbed object
                return loader.load(raw_config)
            except Exception as e:
                log.warning(f"Failed to load logical testbed: {e}")
        
        # Try standard testbed file
        testbed_file = getattr(self.runtime.args, 'testbed_file', None)
        if not testbed_file:
            # Also check job's testbed_file
            testbed_file = getattr(getattr(self.runtime, 'job', None), 'testbed_file', None)
        
        if testbed_file and os.path.isfile(testbed_file):
            log.info(f"Loading testbed from: {testbed_file}")
            try:
                return loader.load(testbed_file)
            except Exception as e:
                log.error(f"Failed to load testbed: {e}")
                return None
        
        log.warning("No testbed file found to load")
        return None

    # OS types that should be removed from logical testbed (can't be parsed by Genie)
    SKIP_OS_FOR_TRANSFORM = {
        'pagent', 'trex', 'ixia', 'ixiangpf', 'ixianative', 'spirent', 'stc',
    }
    
    def _transform_logical_testbed(self, config: dict) -> None:
        """
        Transform logical testbed config to be loadable by pyATS.
        
        This method:
        1. Removes devices with unsupported OS types (pagent, traffic generators)
        2. Strips dyntopo-specific keys (logical, ha_requested, etc.)
        3. Renames interfaces from aliases to actual_name values in topology section
        
        Args:
            config: Raw testbed config dict (modified in place)
        """
        # First, identify and remove devices with unsupported OS types
        # These devices (like pagent/traffic generators) have custom interface names
        # that Genie can't parse, and they won't be created in CML2 anyway
        devices_to_remove = set()
        if 'devices' in config:
            for dev_name, dev_config in config['devices'].items():
                if isinstance(dev_config, dict):
                    dev_os = dev_config.get('os', '').lower()
                    dev_type = dev_config.get('type', '').lower()
                    # Check if this device should be skipped
                    if dev_os in self.SKIP_OS_FOR_TRANSFORM or dev_type in {'tgn', 'traffic_generator', 'trafficgen'}:
                        devices_to_remove.add(dev_name)
                        log.info(f"Removing device '{dev_name}' from logical testbed (OS: {dev_os}, type: {dev_type})")
            
            # Remove the devices
            for dev_name in devices_to_remove:
                config['devices'].pop(dev_name, None)
        
        # Also remove these devices from topology section
        if 'topology' in config:
            for dev_name in devices_to_remove:
                config['topology'].pop(dev_name, None)
        
        # Strip dyntopo-specific keys from remaining devices
        # These keys are used by dyntopo but not recognized by pyATS testbed loader
        DYNTOPO_DEVICE_KEYS = [
            'logical',           # Marks device as logical (dyntopo)
            'ha_requested',      # HA mode request (dyntopo)
            'logical_testbed_file',  # Reference to logical testbed
            'local',             # Local IOL process arguments (dyntopo)
            'vcpu',              # Virtual CPU allocation
            'memory',            # Memory allocation
        ]
        if 'devices' in config:
            for dev_name, dev_config in config['devices'].items():
                if isinstance(dev_config, dict):
                    for key in DYNTOPO_DEVICE_KEYS:
                        dev_config.pop(key, None)
        
        # Transform topology section: rename interface aliases to actual_name
        if 'topology' in config:
            new_topology = {}
            for dev_name, dev_topology in config['topology'].items():
                if not isinstance(dev_topology, dict):
                    new_topology[dev_name] = dev_topology
                    continue
                    
                # Check if 'interfaces' key exists, otherwise treat keys as interface names
                if 'interfaces' in dev_topology:
                    interfaces = dev_topology.get('interfaces', {})
                else:
                    # Top-level keys are interface aliases
                    interfaces = dev_topology
                    dev_topology = {'interfaces': {}}
                
                new_interfaces = {}
                for intf_alias, intf_config in interfaces.items():
                    if not isinstance(intf_config, dict):
                        new_interfaces[intf_alias] = intf_config
                        continue
                    
                    # Use actual_name if available, otherwise keep alias
                    actual_name = intf_config.pop('actual_name', None)
                    if actual_name:
                        # Store alias for reference
                        intf_config['alias'] = intf_alias
                        new_interfaces[actual_name] = intf_config
                    else:
                        new_interfaces[intf_alias] = intf_config
                
                if 'interfaces' in config['topology'].get(dev_name, {}):
                    new_topology[dev_name] = dev_topology
                    new_topology[dev_name]['interfaces'] = new_interfaces
                else:
                    new_topology[dev_name] = new_interfaces
            
            config['topology'] = new_topology

    def _display_topology_summary(self) -> None:
        """Display a summary table of the CML2 topology."""
        if not self.lab:
            return

        self.lab.sync()

        log.info(banner("CML2 Topology Summary"))

        # Lab info
        log.info(f"Lab Name: {self.lab.title}")
        log.info(f"Lab ID:   {self.lab.id}")
        log.info(f"Lab URL:  {self.runtime.args.cml2_url}lab/{self.lab.id}")
        log.info("")

        # Device table
        log.info("=" * 80)
        log.info("DEVICES")
        log.info("=" * 80)
        log.info(f"{'Name':<20} {'Platform':<15} {'State':<12} {'Console Port':<15}")
        log.info("-" * 80)

        for node in self.lab.nodes():
            # Get console port from pyATS testbed if available
            console_port = "N/A"
            if self.original_testbed and node.label in self.original_testbed.devices:
                device = self.original_testbed.devices[node.label]
                if hasattr(device, "connections") and "a" in device.connections:
                    conn = device.connections["a"]
                    if hasattr(conn, "arguments") and "line" in conn.arguments:
                        console_port = str(conn.arguments["line"])

            # Get node state (handle both method and property)
            node_state = node.state() if callable(node.state) else node.state
            log.info(
                f"{node.label:<20} {node.node_definition:<15} {node_state:<12} {console_port:<15}"
            )

        log.info("")

        # Connection table
        log.info("=" * 80)
        log.info("CONNECTIONS")
        log.info("=" * 80)
        log.info(f"{'Device':<20} {'Connection':<12} {'Host':<25} {'Port':<10}")
        log.info("-" * 80)

        if self.original_testbed:
            for device_name, device in self.original_testbed.devices.items():
                if device_name == "terminal_server":
                    continue
                if hasattr(device, "connections"):
                    for conn_name, conn in device.connections.items():
                        host = getattr(conn, "host", "N/A") if hasattr(conn, "host") else "N/A"
                        port = "N/A"
                        if hasattr(conn, "arguments") and conn.arguments:
                            port = str(conn.arguments.get("line", "N/A"))
                        log.info(f"{device_name:<20} {conn_name:<12} {host:<25} {port:<10}")

        log.info("")

        # Links table
        log.info("=" * 80)
        log.info("LINKS")
        log.info("=" * 80)
        log.info(f"{'Link':<5} {'Device A':<20} {'Interface A':<20} {'Device B':<20} {'Interface B':<20}")
        log.info("-" * 85)

        link_num = 1
        for link in self.lab.links():
            intf_a = link.interface_a
            intf_b = link.interface_b
            if intf_a and intf_b:
                node_a = intf_a.node.label
                node_b = intf_b.node.label
                log.info(
                    f"{link_num:<5} {node_a:<20} {intf_a.label:<20} {node_b:<20} {intf_b.label:<20}"
                )
                link_num += 1

        if link_num == 1:
            log.info("  (No links)")

        log.info("=" * 80)

    def _connect_to_cml2(self) -> None:
        """Connect to CML2 server."""
        try:
            from virl2_client import ClientLibrary
        except ImportError as e:
            raise ImportError(
                "virl2_client is required for CML2Plugin. "
                "Install it with: pip install virl2_client"
            ) from e

        log.info(f"Connecting to CML2: {self.runtime.args.cml2_url}")

        self.client = ClientLibrary(
            url=self.runtime.args.cml2_url,
            username=self.runtime.args.cml2_username,
            password=self.runtime.args.cml2_password,
            ssl_verify=self.runtime.args.cml2_ssl_verify,
            raise_for_auth_failure=True,
        )

        log.info("Connected to CML2 successfully")

    def _update_testbed(self) -> None:
        """
        Update runtime testbed with CML2 lab connection info.

        Modifies the original testbed in place by:
        - Adding terminal_server device from CML2
        - Updating device connections with CML2 breakout info
        - Updating topology/interfaces from CML2
        - Writing updated testbed to testbed.actual.yaml
        """
        if not self.lab:
            return

        log.info("Retrieving pyATS testbed from CML2...")

        # Get testbed YAML from CML2
        testbed_yaml = self.lab.get_pyats_testbed()
        log.debug(f"CML2 testbed YAML:\n{testbed_yaml}")

        # Load CML2 testbed
        cml2_testbed = loader.load(io.StringIO(testbed_yaml))

        # Update original testbed in place with CML2 connection info
        # Note: self.original_testbed is a reference to runtime.testbed,
        # so modifications are reflected automatically
        self._update_testbed_in_place(self.original_testbed, cml2_testbed)

        # Write updated testbed to testbed.actual.yaml in runinfo directory
        self._write_updated_testbed_yaml()

        log.info("Testbed updated with CML2 connection information")
    
    def _update_testbed_in_place(self, original: Testbed, cml2: Testbed) -> None:
        """
        Update original testbed in place with CML2 connection info.
        
        Args:
            original: Original testbed to modify
            cml2: CML2-generated testbed with connection info
        """
        # Add terminal_server from CML2 testbed if not present
        if "terminal_server" in cml2.devices and "terminal_server" not in original.devices:
            ts_device = cml2.devices["terminal_server"]
            # Update terminal_server credentials to CML2 credentials
            if hasattr(ts_device, "credentials") and ts_device.credentials:
                if "default" in ts_device.credentials:
                    ts_device.credentials.default.username = self.runtime.args.cml2_username
                    ts_device.credentials.default.password = self.runtime.args.cml2_password
            original.add_device(ts_device)
            log.info("Added terminal_server device from CML2 with updated credentials")
        
        # Log CML2 devices for debugging
        log.info(f"CML2 testbed devices: {list(cml2.devices.keys())}")
        log.info(f"Original testbed devices: {list(original.devices.keys())}")
        
        # Update connections for each device in CML2 testbed
        for device_name, cml2_device in cml2.devices.items():
            if device_name == "terminal_server":
                continue
            
            if device_name not in original.devices:
                log.warning(f"Device {device_name} from CML2 not found in original testbed")
                continue
            
            orig_device = original.devices[device_name]
            
            # Update connections from CML2
            if hasattr(cml2_device, "connections") and cml2_device.connections:
                for conn_name, conn in cml2_device.connections.items():
                    orig_device.connections[conn_name] = conn
                log.info(f"Updated connections for device {device_name}")
        
        # Update credentials for ALL original devices to CML2 defaults
        log.info("Starting credential update for all devices...")
        for device_name, orig_device in original.devices.items():
            if device_name == "terminal_server":
                continue
                
            # Always infer platform for CML2 credential lookup
            # (existing platform attribute may be generic like 'router'/'switch')
            device_os = getattr(orig_device, "os", None)
            device_type = getattr(orig_device, "type", None)
            platform = infer_platform(device_name, device_os, device_type)
            log.info(f"DEBUG {device_name}: inferred platform={platform}")
            
            if platform:
                node_def = get_node_definition(platform)
                log.info(f"DEBUG {device_name}: node_def={node_def}, in_creds={node_def in CML2_DEFAULT_CREDENTIALS}")
                if node_def in CML2_DEFAULT_CREDENTIALS:
                    cml2_creds = CML2_DEFAULT_CREDENTIALS[node_def]
                    username = cml2_creds["username"]
                    password = cml2_creds["password"]
                    
                    # Set credentials on both device and connections
                    from pyats.topology.credentials import Credentials
                    creds_dict = {
                        "default": {
                            "username": username,
                            "password": password,
                        },
                        "enable": {
                            "password": password,
                        }
                    }
                    orig_device.credentials = Credentials(creds_dict)
                    
                    # Also set credentials on each connection
                    if hasattr(orig_device, "connections"):
                        for conn_name, conn in orig_device.connections.items():
                            if hasattr(conn, "__setitem__"):
                                conn["credentials"] = creds_dict
                            elif hasattr(conn, "credentials"):
                                conn.credentials = creds_dict
                    
                    log.info(f"Set CML2 credentials for {device_name}: username={username}")
                    log.info(f"  Verified device: {orig_device.credentials.default.username}")
        
        # Update topology/interfaces from CML2 testbed
        self._update_topology_from_cml2(original, cml2)

    def _update_topology_from_cml2(self, original: Testbed, cml2: Testbed) -> None:
        """
        Update original testbed topology with CML2 interface information.
        
        CML2 may use different interface naming than the original testbed (e.g., IOL
        only supports slot 0 interfaces like Ethernet0/0, not Ethernet1/0).
        This method updates interface names IN PLACE using the mapping created during 
        link creation, preserving all link associations.
        
        Args:
            original: Original testbed to modify
            cml2: CML2-generated testbed with interface info
        """
        log.info("Updating topology/interfaces from CML2 using interface mapping...")
        log.info(f"  Interface mapping has {len(self._interface_mapping)} entries")
        
        # Check link state BEFORE renaming
        if hasattr(original, 'links') and original.links:
            broken_before = 0
            for link in original.links:
                if hasattr(link, 'interfaces'):
                    intf_count = len(list(link.interfaces))
                    if intf_count < 2:
                        broken_before += 1
                        log.warning(f"  BEFORE rename - Link {link.name} has only {intf_count} interfaces")
            if broken_before > 0:
                log.error(f"  Found {broken_before} broken links BEFORE renaming!")
            else:
                log.info(f"  All links have 2 interfaces before renaming")
        
        for device_name, orig_device in original.devices.items():
            if device_name == "terminal_server":
                continue
            
            # Check if device has interfaces
            if not hasattr(orig_device, "interfaces") or not orig_device.interfaces:
                log.info(f"  {device_name}: No interfaces found, skipping")
                continue
            
            # Collect interfaces to rename (store interface object, not just name)
            interfaces_to_rename: list[tuple[str, str, object]] = []
            
            for orig_intf_name, intf in list(orig_device.interfaces.items()):
                # Look up CML2 interface name from our mapping
                key = (device_name, orig_intf_name)
                cml2_intf_name = self._interface_mapping.get(key)
                
                if cml2_intf_name and cml2_intf_name != orig_intf_name:
                    interfaces_to_rename.append((orig_intf_name, cml2_intf_name, intf))
            
            # Perform in-place renaming using two-phase approach to avoid collisions
            # Phase 1: Remove all interfaces from dict and store with temp names
            # Phase 2: Add all interfaces back with new names
            # This avoids overwriting when rename target matches another rename source
            
            # Build mapping of old_name -> (new_name, intf_object)
            rename_map: dict[str, tuple[str, object]] = {}
            for orig_intf_name, cml2_intf_name, intf in interfaces_to_rename:
                rename_map[orig_intf_name] = (cml2_intf_name, intf)
                log.info(f"    {device_name}: Renaming interface {orig_intf_name} -> {cml2_intf_name}")
            
            # Phase 1: Remove all old keys from dict (keep intf objects in rename_map)
            for orig_intf_name in rename_map.keys():
                if orig_intf_name in orig_device.interfaces:
                    del orig_device.interfaces[orig_intf_name]
            
            # Phase 2: Update interface names and add back to dict with new keys
            for orig_intf_name, (cml2_intf_name, intf) in rename_map.items():
                # Change the interface name (preserves link association)
                intf.name = cml2_intf_name
                # Add back with new key
                orig_device.interfaces[cml2_intf_name] = intf
                
                # Log link state for debugging
                link = getattr(intf, 'link', None)
                if link:
                    log.debug(f"      Interface {cml2_intf_name} is connected to link {link.name}")
            
            log.info(f"  {device_name}: Updated interfaces: {list(orig_device.interfaces.keys())}")
        
        # Verify link-interface associations after update
        if hasattr(original, 'links') and original.links:
            log.info("  Verifying link-interface associations after update:")
            broken_links = []
            for link in original.links:
                if hasattr(link, 'interfaces'):
                    intf_list = list(link.interfaces)
                    intf_info = [(getattr(i, 'name', '?'), getattr(getattr(i, 'device', None), 'name', '?')) 
                                 for i in intf_list]
                    # Flag links with less than 2 interfaces
                    if len(intf_list) < 2:
                        broken_links.append((link.name, intf_info))
                        log.warning(f"    BROKEN Link {link.name}: only {len(intf_list)} interfaces: {intf_info}")
                    else:
                        log.debug(f"    Link {link.name}: {intf_info}")
            if broken_links:
                log.error(f"  Found {len(broken_links)} broken links with < 2 interfaces!")
            else:
                log.info(f"  All {len(list(original.links))} links have 2 interfaces")

    def _write_updated_testbed_yaml(self) -> None:
        """
        Write updated testbed to testbed.actual.yaml in runinfo directory.
        
        This ensures the archive contains the CML2-updated testbed information
        instead of the original dyntopo testbed.
        
        When --skip-bringup is used, dyntopo doesn't create testbed.actual.yaml,
        so we create it here with the CML2-updated testbed.
        """
        try:
            # Get the runinfo directory from runtime
            runinfo_dir = getattr(self.runtime, 'directory', None)
            if not runinfo_dir:
                runinfo_dir = getattr(getattr(self.runtime, 'runinfo', None), 'runinfo_dir', None)
            if not runinfo_dir:
                log.warning("Could not find runinfo directory, skipping testbed.actual.yaml update")
                return
            
            # Construct the testbed.actual.yaml path
            testbed_yaml_path = os.path.join(runinfo_dir, "testbed.actual.yaml")
            
            # Check if file exists - if it does and has content, it was created by dyntopo
            if os.path.exists(testbed_yaml_path):
                with open(testbed_yaml_path, 'r') as f:
                    content = f.read().strip()
                if content:
                    log.info(f"testbed.actual.yaml already exists with content, updating...")
            else:
                log.info(f"Creating testbed.actual.yaml (not created by dyntopo)...")
            
            # Convert testbed to dictionary for YAML serialization
            testbed_dict = self._testbed_to_dict(self.original_testbed)
            
            # Write the updated testbed YAML
            with open(testbed_yaml_path, 'w') as f:
                yaml.safe_dump(testbed_dict, f, default_flow_style=False, sort_keys=False)
            
            log.info(f"Wrote testbed.actual.yaml at: {testbed_yaml_path}")
            
        except Exception as e:
            log.warning(f"Failed to write updated testbed.actual.yaml: {e}")
            import traceback
            log.debug(traceback.format_exc())
    
    def _testbed_to_dict(self, testbed: Testbed) -> dict:
        """
        Convert a pyATS Testbed object to a dictionary for YAML serialization.
        
        Args:
            testbed: pyATS Testbed object
            
        Returns:
            Dictionary representation of the testbed
        """
        result: dict[str, Any] = {}
        
        # Testbed metadata
        if testbed.name:
            result["testbed"] = {"name": testbed.name}
        
        # Devices section
        devices_dict: dict[str, Any] = {}
        for device_name, device in testbed.devices.items():
            device_dict: dict[str, Any] = {}
            
            # Basic attributes
            for attr in ["alias", "os", "platform", "type", "series", "model"]:
                value = getattr(device, attr, None)
                if value is not None:
                    device_dict[attr] = value
            
            # Credentials
            if hasattr(device, "credentials") and device.credentials:
                creds_dict: dict[str, Any] = {}
                for cred_name, cred in device.credentials.items():
                    cred_info: dict[str, Any] = {}
                    if hasattr(cred, "username") and cred.username:
                        cred_info["username"] = str(cred.username)
                    if hasattr(cred, "password") and cred.password:
                        cred_info["password"] = str(cred.password)
                    if cred_info:
                        creds_dict[cred_name] = cred_info
                if creds_dict:
                    device_dict["credentials"] = creds_dict
            
            # Connections
            if hasattr(device, "connections") and device.connections:
                conns_dict: dict[str, Any] = {}
                for conn_name, conn in device.connections.items():
                    conn_dict: dict[str, Any] = {}
                    
                    # Handle different connection types
                    # Convert host/ip to string to handle IPv4Address/IPv6Address objects
                    if hasattr(conn, "host") and conn.host:
                        conn_dict["host"] = str(conn.host)
                    if hasattr(conn, "ip") and conn.ip:
                        conn_dict["ip"] = str(conn.ip)
                    if hasattr(conn, "port"):
                        conn_dict["port"] = conn.port
                    if hasattr(conn, "protocol"):
                        conn_dict["protocol"] = conn.protocol
                    if hasattr(conn, "arguments") and conn.arguments:
                        if "line" in conn.arguments:
                            conn_dict["arguments"] = {"line": conn.arguments["line"]}
                    
                    # Get class if specified - handle callable/function references
                    conn_class = getattr(conn, "class", None)
                    if conn_class:
                        # Convert to string representation if it's a callable
                        if callable(conn_class):
                            # Try to get module.name format
                            module = getattr(conn_class, "__module__", "")
                            name = getattr(conn_class, "__name__", "")
                            if module and name:
                                conn_class = f"{module}.{name}"
                            elif name:
                                conn_class = name
                            else:
                                conn_class = None  # Can't serialize
                        if conn_class and isinstance(conn_class, str):
                            conn_dict["class"] = conn_class
                    
                    if conn_dict:
                        conns_dict[conn_name] = conn_dict
                
                if conns_dict:
                    device_dict["connections"] = conns_dict
            
            devices_dict[device_name] = device_dict
        
        if devices_dict:
            result["devices"] = devices_dict
        
        # Topology section
        topology_dict: dict[str, Any] = {}
        for device_name, device in testbed.devices.items():
            if not hasattr(device, "interfaces") or not device.interfaces:
                continue
            
            intf_dict: dict[str, Any] = {}
            for intf_name, intf in device.interfaces.items():
                intf_info: dict[str, Any] = {}
                
                # Interface attributes
                if hasattr(intf, "alias") and intf.alias:
                    intf_info["alias"] = intf.alias
                if hasattr(intf, "link") and intf.link:
                    link_name = intf.link.name if hasattr(intf.link, "name") else str(intf.link)
                    intf_info["link"] = link_name
                if hasattr(intf, "type") and intf.type:
                    intf_info["type"] = intf.type
                
                if intf_info:
                    intf_dict[intf_name] = intf_info
            
            if intf_dict:
                topology_dict[device_name] = {"interfaces": intf_dict}
        
        if topology_dict:
            result["topology"] = topology_dict
        
        return result

    def _merge_testbeds(self, original: Testbed, cml2: Testbed) -> Testbed:
        """
        Merge original testbed with CML2 testbed.

        Args:
            original: Original testbed (baseline)
            cml2: CML2-generated testbed (override)

        Returns:
            Merged testbed with original fields preserved and CML2 fields overriding
        """
        # Start with the CML2 testbed as the base (has correct connection info)
        merged = cml2

        # Merge testbed-level attributes from original
        self._merge_testbed_attributes(original, merged)

        # Merge devices
        self._merge_devices(original, merged)

        # Merge topology
        self._merge_topology(original, merged)

        return merged

    def _merge_testbed_attributes(self, original: Testbed, merged: Testbed) -> None:
        """Merge testbed-level attributes from original to merged."""
        # List of attributes to potentially merge
        testbed_attrs = ["alias", "custom", "passwords", "tacacs", "servers"]

        for attr in testbed_attrs:
            if hasattr(original, attr):
                orig_value = getattr(original, attr)
                if orig_value is not None:
                    merged_value = getattr(merged, attr, None)
                    if merged_value is None:
                        setattr(merged, attr, orig_value)

    def _merge_devices(self, original: Testbed, merged: Testbed) -> None:
        """Merge device attributes from original testbed to merged testbed."""
        for device_name, merged_device in merged.devices.items():
            # Handle terminal_server specially - use CML2 credentials
            if device_name == "terminal_server":
                self._set_terminal_server_credentials(merged_device)
                continue

            # Skip if device doesn't exist in original
            if device_name not in original.devices:
                continue

            orig_device = original.devices[device_name]

            # Merge device attributes (original as base, merged overrides)
            self._merge_device_attributes(orig_device, merged_device)

    def _merge_device_attributes(
        self, orig_device: Device, merged_device: Device
    ) -> None:
        """
        Merge attributes from original device to merged device.

        Original attributes are preserved if not present in merged.
        Merged (CML2) attributes take priority.
        """
        # Attributes to merge from original device
        device_attrs = [
            "alias",
            "platform",
            "type",
            "os",
            "series",
            "model",
            "custom",
            "peripherals",
            "power",
            "clean",
            "management",
        ]

        for attr in device_attrs:
            if hasattr(orig_device, attr):
                orig_value = getattr(orig_device, attr)
                if orig_value is not None:
                    merged_value = getattr(merged_device, attr, None)
                    if merged_value is None:
                        try:
                            setattr(merged_device, attr, orig_value)
                        except AttributeError:
                            pass  # Some attributes may be read-only

        # Merge credentials (original credentials preserved)
        self._merge_credentials(orig_device, merged_device)

    def _merge_credentials(
        self, orig_device: Device, merged_device: Device
    ) -> None:
        """Merge credentials from original device to merged device."""
        if not hasattr(orig_device, "credentials") or not orig_device.credentials:
            return

        if not hasattr(merged_device, "credentials"):
            return

        for cred_name, orig_cred in orig_device.credentials.items():
            if cred_name in merged_device.credentials:
                merged_cred = merged_device.credentials[cred_name]
                # Copy credential attributes from original
                for attr in ["username", "password"]:
                    if hasattr(orig_cred, attr):
                        orig_value = getattr(orig_cred, attr)
                        if orig_value is not None:
                            try:
                                setattr(merged_cred, attr, orig_value)
                            except AttributeError:
                                pass
            else:
                # Add credential from original if not in merged
                try:
                    merged_device.credentials[cred_name] = orig_cred
                except Exception:
                    pass

    def _set_terminal_server_credentials(self, terminal_server: Device) -> None:
        """Set terminal server credentials to CML2 credentials."""
        if hasattr(terminal_server, "credentials") and terminal_server.credentials:
            if "default" in terminal_server.credentials:
                terminal_server.credentials.default.username = (
                    self.runtime.args.cml2_username
                )
                terminal_server.credentials.default.password = (
                    self.runtime.args.cml2_password
                )

    def _merge_topology(self, original: Testbed, merged: Testbed) -> None:
        """
        Merge topology/interface attributes from original testbed.

        Preserves alias and other interface attributes from original.
        CML2 connection info (link, type) takes priority.
        """
        if not hasattr(original, "topology") or not original.topology:
            return

        if not hasattr(merged, "topology") or not merged.topology:
            return

        for device_name in merged.topology:
            if device_name not in original.topology:
                continue

            merged_topo = merged.topology[device_name]
            orig_topo = original.topology[device_name]

            if not hasattr(merged_topo, "interfaces") or not hasattr(
                orig_topo, "interfaces"
            ):
                continue

            # Build a mapping of link_id -> original interface attributes
            # This allows matching interfaces by link even if names differ
            orig_link_to_intf: dict[str, Any] = {}
            for intf_name, intf in orig_topo.interfaces.items():
                link = getattr(intf, "link", None)
                if link:
                    link_id = link.name if hasattr(link, "name") else str(link)
                    orig_link_to_intf[link_id] = intf

            # Merge interface attributes
            for intf_name, merged_intf in merged_topo.interfaces.items():
                link = getattr(merged_intf, "link", None)
                if not link:
                    continue

                link_id = link.name if hasattr(link, "name") else str(link)

                # Find matching original interface by link
                orig_intf = orig_link_to_intf.get(link_id)
                if orig_intf:
                    self._merge_interface_attributes(orig_intf, merged_intf)

    def _merge_interface_attributes(self, orig_intf: Any, merged_intf: Any) -> None:
        """
        Merge interface attributes from original to merged.

        Preserves alias and other custom attributes from original.
        """
        # Attributes to merge from original interface
        intf_attrs = ["alias", "ipv4", "ipv6", "mac_address", "custom"]

        for attr in intf_attrs:
            if hasattr(orig_intf, attr):
                orig_value = getattr(orig_intf, attr)
                if orig_value is not None:
                    merged_value = getattr(merged_intf, attr, None)
                    if merged_value is None:
                        try:
                            setattr(merged_intf, attr, orig_value)
                        except AttributeError:
                            pass  # Some attributes may be read-only

    def _cleanup_lab(self, wait: bool = True) -> bool:
        """
        Clean up CML2 lab resources.

        Args:
            wait: Whether to wait for stop/wipe operations to complete

        Returns:
            True if cleanup was successful, False otherwise
        """
        if not self.lab:
            return True

        try:
            log.info(f"Stopping lab: {self.lab.title}...")
            self.lab.stop(wait=wait)

            log.info("Wiping lab...")
            self.lab.wipe(wait=wait)

            log.info("Removing lab...")
            self.lab.remove()

            log.info("Lab cleanup complete")
            self.lab = None
            return True

        except Exception as cleanup_error:
            log.error(f"Failed to cleanup lab: {cleanup_error}")
            if self.lab:
                log.warning(f"Lab may need manual cleanup: {self.lab.id}")
            return False


# =============================================================================
# Entry Point
# =============================================================================

cml2_plugin = {
    "plugins": {
        "CML2Plugin": {
            "class": CML2Plugin,
            "enabled": True,
            "kwargs": {},
            "module": "pyats.contrib.plugins.cml2_plugin.cml2",
            "name": "CML2Plugin",
        }
    }
}
