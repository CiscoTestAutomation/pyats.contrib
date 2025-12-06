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

            # Skip devices without platform
            platform = getattr(device, "platform", None)
            if not platform:
                log.warning(f"Device {device_name} has no platform, skipping")
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
                os=getattr(device, "os", "ios"),
                type=getattr(device, "type", "router"),
                credentials=credentials,
            )

        return self._devices

    def get_links(self) -> list[LinkInfo]:
        """Extract link information from testbed topology."""
        if self._links is not None:
            return self._links

        # Collect all link endpoints
        link_endpoints: dict[str, list[LinkEndpoint]] = defaultdict(list)

        # Iterate through topology
        if not hasattr(self.testbed, "topology") or not self.testbed.topology:
            self._links = []
            return self._links

        for device_name in self.testbed.topology:
            device_topo = self.testbed.topology[device_name]

            # Skip devices not in our device list
            if device_name.lower() in self.SKIP_DEVICES:
                continue

            if not hasattr(device_topo, "interfaces"):
                continue

            for intf_name, intf in device_topo.interfaces.items():
                # Get link ID
                link_id = getattr(intf, "link", None)
                if not link_id:
                    continue

                # Get link name if link is an object
                if hasattr(link_id, "name"):
                    link_id = link_id.name

                slot = parse_interface_slot(intf_name)

                link_endpoints[link_id].append(
                    LinkEndpoint(
                        device=device_name,
                        interface=intf_name,
                        slot=slot,
                    )
                )

        # Convert to LinkInfo objects (only links with exactly 2 endpoints)
        self._links = []
        for link_id, endpoints in link_endpoints.items():
            if len(endpoints) == 2:
                self._links.append(LinkInfo(link_id=link_id, endpoints=endpoints))
            elif len(endpoints) > 2:
                log.warning(f"Link {link_id} has {len(endpoints)} endpoints, skipping")
            # Single endpoint links are ignored (not connected)

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
    ) -> None:
        self.client = client
        self.lab_name = lab_name
        self.devices = devices
        self.links = links
        self.lab: Lab | None = None
        self.node_map: dict[str, Node] = {}

    def build(self) -> Lab:
        """Build the complete lab topology."""
        log.info(banner(f"Creating CML2 Lab: {self.lab_name}"))

        # Create lab
        self.lab = self.client.create_lab(title=self.lab_name)
        log.info(f"Created lab: {self.lab.title} (ID: {self.lab.id})")

        try:
            # Create nodes
            self._create_nodes()

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

            node1 = self.node_map.get(ep1.device)
            node2 = self.node_map.get(ep2.device)

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

            # Create and start lab
            builder = CML2LabBuilder(self.client, lab_name, devices, links)
            self.lab = builder.build()
            builder.start_and_wait()

            # Update testbed
            self._update_testbed()

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

        Merging strategy:
        - Original testbed fields are preserved as baseline
        - CML2 testbed fields override original fields
        - Fields only in original testbed are kept
        """
        if not self.lab:
            return

        log.info("Retrieving pyATS testbed from CML2...")

        # Get testbed YAML from CML2
        testbed_yaml = self.lab.get_pyats_testbed()

        # Load CML2 testbed
        cml2_testbed = loader.load(io.StringIO(testbed_yaml))

        # Merge testbeds: original as base, CML2 overrides
        merged_testbed = self._merge_testbeds(self.original_testbed, cml2_testbed)

        # Update runtime testbed
        self.runtime.testbed = merged_testbed

        log.info("Testbed updated with CML2 connection information")

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
