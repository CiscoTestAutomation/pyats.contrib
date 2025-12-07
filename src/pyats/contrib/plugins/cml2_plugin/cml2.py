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
import logging
import math
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyats.easypy.plugins.bases import BasePlugin
from pyats.log.utils import banner
from pyats.topology import loader

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
    "iosv": "iol",
    "iol": "iol",
    "iosvl2": "ioll2",
    "ioll2": "ioll2",
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
    "ios": "iol",
    "iosxe": "csr1000v",
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
    (r"iol", "iol"),
]

# CML2 default credentials by node definition
# Reference: https://developer.cisco.com/docs/modeling-labs/faq/
CML2_DEFAULT_CREDENTIALS: dict[str, dict[str, str]] = {
    # IOL (IOS on Linux)
    "iol": {"username": "cisco", "password": "cisco"},
    "ioll2": {"username": "cisco", "password": "cisco"},
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
# Data Classes
# =============================================================================


@dataclass
class DeviceInfo:
    """Information about a device extracted from testbed."""

    name: str
    platform: str
    os: str
    type: str
    credentials: dict[str, Any] = field(default_factory=dict)


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


def parse_interface_slot(interface_name: str) -> int | None:
    """
    Parse interface name to extract slot number.

    Examples:
        Ethernet0/0 -> 0
        Ethernet0/1 -> 1
        GigabitEthernet0/0/0/0 -> 0
        Ethernet1/1 -> 1 (second number)
        mgmt0 -> None (management interface)

    Args:
        interface_name: Interface name string

    Returns:
        Slot number or None if cannot be determined
    """
    # Skip loopback and management interfaces
    lower_name = interface_name.lower()
    if lower_name.startswith(("loopback", "loop", "lo", "mgmt", "management")):
        return None

    # Try to extract slot from common patterns
    # Pattern: Ethernet0/0, GigabitEthernet0/0, etc.
    match = re.search(r"(\d+)[/:](\d+)(?:[/:](\d+))?(?:[/:](\d+))?$", interface_name)
    if match:
        # Use the second-to-last number as slot for most cases
        numbers = [int(g) for g in match.groups() if g is not None]
        if len(numbers) >= 2:
            return numbers[-1]  # Last number is typically the port/slot
        return numbers[0]

    # Pattern: eth0, ens0, etc.
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

    SKIP_DEVICES = {"terminal_server", "jumphost", "jump_host"}

    def __init__(self, testbed: Testbed) -> None:
        self.testbed = testbed
        self._devices: dict[str, DeviceInfo] | None = None
        self._links: list[LinkInfo] | None = None

    @property
    def lab_name(self) -> str:
        """Get lab name from testbed."""
        return self.testbed.name or "pyats_lab"

    def get_devices(self) -> dict[str, DeviceInfo]:
        """Extract network device information from testbed."""
        if self._devices is not None:
            return self._devices

        self._devices = {}

        for device_name, device in self.testbed.devices.items():
            # Skip special devices
            if device_name.lower() in self.SKIP_DEVICES:
                continue

            # Get device attributes
            device_os = getattr(device, "os", None)
            device_type = getattr(device, "type", None)

            # Get platform or infer it
            platform = getattr(device, "platform", None)
            # If platform is not set or not a valid CML2 node definition, try to infer
            if not platform or platform.lower() not in PLATFORM_TO_NODE_DEFINITION:
                inferred = infer_platform(device_name, device_os, device_type)
                if inferred:
                    platform = inferred
                elif not platform:
                    log.warning(
                        f"Device {device_name} has no platform and could not infer one, skipping"
                    )
                    continue

            # Extract credentials
            credentials = {}
            if hasattr(device, "credentials") and device.credentials:
                for cred_name, cred in device.credentials.items():
                    credentials[cred_name] = {
                        "username": getattr(cred, "username", "cisco"),
                        "password": getattr(cred, "password", "cisco"),
                    }

            self._devices[device_name] = DeviceInfo(
                name=device_name,
                platform=platform,
                os=device_os or "ios",
                type=device_type or "router",
                credentials=credentials,
            )

        return self._devices

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

        # Iterate through testbed links
        for link in self.testbed.links:
            endpoints = []
            
            # Get interfaces connected to this link
            for intf in link.interfaces:
                device_name = intf.device.name
                intf_name = intf.name
                
                # Skip devices not in our device list
                if device_name.lower() in self.SKIP_DEVICES:
                    continue
                
                slot = parse_interface_slot(intf_name)
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
    ) -> None:
        self.client = client
        self.lab_name = lab_name
        self.devices = devices
        self.links = links
        self.alias_map = alias_map or {}  # alias -> actual device name
        self.lab: Lab | None = None
        self.node_map: dict[str, Node] = {}

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
        """Create all nodes in the lab."""
        positions = calculate_node_positions(len(self.devices))

        for i, (device_name, device_info) in enumerate(self.devices.items()):
            node_definition = get_node_definition(device_info.platform)
            x, y = positions[i] if i < len(positions) else (0, 0)

            log.info(f"Creating node: {device_name} ({node_definition})")

            node = self.lab.create_node(
                label=device_name,
                node_definition=node_definition,
                x=x,
                y=y,
                populate_interfaces=True,
            )
            self.node_map[device_name] = node
            log.info(f"  Created node ID: {node.id}")

    def _get_interface_by_slot(self, node: Node, slot: int) -> Interface | None:
        """Get interface by slot number."""
        for interface in node.interfaces():
            if interface.slot == slot:
                return interface
        return None

    def _get_next_available_interface(
        self, node: Node, used_slots: set[int]
    ) -> Interface | None:
        """Get next available interface that hasn't been used."""
        for interface in sorted(node.interfaces(), key=lambda i: i.slot or 0):
            if interface.slot is not None and interface.slot not in used_slots:
                return interface
        return None

    def _create_links(self) -> None:
        """Create all links between nodes."""
        # Track used interfaces per node
        used_interfaces: dict[str, set[int]] = defaultdict(set)

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
            if ep1.slot is not None:
                intf1 = self._get_interface_by_slot(node1, ep1.slot)
            if ep2.slot is not None:
                intf2 = self._get_interface_by_slot(node2, ep2.slot)

            # Fall back to next available interface
            if intf1 is None:
                intf1 = self._get_next_available_interface(
                    node1, used_interfaces[ep1.device]
                )
            if intf2 is None:
                intf2 = self._get_next_available_interface(
                    node2, used_interfaces[ep2.device]
                )

            if not intf1 or not intf2:
                log.warning(
                    f"Skipping link {link_info.link_id}: no available interfaces"
                )
                continue

            # Mark interfaces as used
            if intf1.slot is not None:
                used_interfaces[ep1.device].add(intf1.slot)
            if intf2.slot is not None:
                used_interfaces[ep2.device].add(intf2.slot)

            log.info(
                f"Creating link: {ep1.device}:{intf1.label} <-> {ep2.device}:{intf2.label}"
            )

            self.lab.create_link(intf1, intf2)

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
        else:
            enable = ["--cml2-enable"]
            url = ["--cml2-url"]
            username = ["--cml2-username"]
            password = ["--cml2-password"]
            keep_lab = ["--cml2-keep-lab"]
            ssl_verify = ["--cml2-ssl-verify"]
            lab_prefix = ["--cml2-lab-prefix"]

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

        return grp

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.client: ClientLibrary | None = None
        self.lab: Lab | None = None
        self.original_testbed: Testbed | None = None

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

            # Parse testbed
            parser = TestbedParser(self.original_testbed)
            devices = parser.get_devices()
            links = parser.get_links()

            if not devices:
                log.warning("No devices found in testbed, skipping CML2 lab creation")
                return

            log.info(f"Found {len(devices)} device(s) and {len(links)} link(s)")

            # Build lab name
            lab_name = self.runtime.args.cml2_lab_prefix + parser.lab_name

            # Get alias mapping for device name resolution
            alias_map = parser.get_alias_map()

            # Create and start lab
            builder = CML2LabBuilder(self.client, lab_name, devices, links, alias_map)
            self.lab = builder.build()
            builder.start_and_wait()

            # Verify links were created correctly
            builder.verify_links()

            # Update testbed
            self._update_testbed()

            # Display topology summary
            self._display_topology_summary()

            log.info(banner("CML2 Plugin - Pre Job Complete"))

        except Exception as e:
            log.error(f"CML2Plugin failed: {e}")
            self._cleanup_on_error()
            raise

    def post_job(self, job) -> None:
        """
        Post-job hook: Clean up CML2 lab if not keeping it.

        Args:
            job: The job object
        """
        if not self.runtime.args.cml2_enable:
            return

        if self.lab is None:
            return

        log.info(banner("CML2 Plugin - Post Job"))

        if self.runtime.args.cml2_keep_lab:
            log.info(f"Keeping lab: {self.lab.title} (ID: {self.lab.id})")
            log.info(f"  URL: {self.runtime.args.cml2_url}")
            return

        log.info(f"Cleaning up lab: {self.lab.title}")

        try:
            # Stop lab
            log.info("Stopping lab...")
            self.lab.stop(wait=True)

            # Wipe lab
            log.info("Wiping lab...")
            self.lab.wipe(wait=True)

            # Remove lab
            log.info("Removing lab...")
            self.lab.remove()

            log.info("Lab cleanup complete")

        except Exception as e:
            log.error(f"Failed to cleanup lab: {e}")
            log.warning(f"Lab may need manual cleanup: {self.lab.id}")

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

        if not self.runtime.testbed:
            errors.append("Testbed is required")

        if errors:
            for error in errors:
                log.error(error)
            return False

        return True

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
        """
        if not self.lab:
            return

        log.info("Retrieving pyATS testbed from CML2...")

        # Get testbed YAML from CML2
        testbed_yaml = self.lab.get_pyats_testbed()

        # Load CML2 testbed
        cml2_testbed = loader.load(io.StringIO(testbed_yaml))

        # Update original testbed in place with CML2 connection info
        self._update_testbed_in_place(self.original_testbed, cml2_testbed)

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

    def _cleanup_on_error(self) -> None:
        """Clean up resources on error."""
        if self.lab:
            try:
                log.info("Cleaning up lab due to error...")
                self.lab.stop(wait=False)
                self.lab.wipe(wait=False)
                self.lab.remove()
            except Exception as cleanup_error:
                log.warning(f"Failed to cleanup lab: {cleanup_error}")


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
