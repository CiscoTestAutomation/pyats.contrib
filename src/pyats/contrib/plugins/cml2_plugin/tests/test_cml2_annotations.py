"""Unit test suite for pyats.contrib CML2 plugin hybrid layout and annotation engine.

Runs 100% offline with zero external network or CML2 credentials required.
Compatible with standard unittest runner:
    python3 -m unittest vendor/ext_pyats.contrib/src/pyats/contrib/plugins/cml2_plugin/tests/test_cml2_annotations.py
    python3 -m unittest tests/test_cml2_plugin_annotations.py
    python3 -m unittest discover -s tests
"""

import math
import sys
import types
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

# =============================================================================
# 1. Environment & sys.modules Bootstrap
# =============================================================================

CURRENT_FILE = Path(__file__).resolve()
VENDOR_SRC = None
for parent in CURRENT_FILE.parents:
    if (parent / "pyats" / "contrib" / "plugins").is_dir():
        VENDOR_SRC = parent
        break
    if (parent / "vendor" / "ext_pyats.contrib" / "src").is_dir():
        VENDOR_SRC = parent / "vendor" / "ext_pyats.contrib" / "src"
        break

if VENDOR_SRC and str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))

# Import pyats to let Python discover it as a namespace package
import pyats

for mod_name in [
    "yaml",
    "pyats.easypy",
    "pyats.easypy.plugins",
    "pyats.easypy.plugins.bases",
    "pyats.log",
    "pyats.log.utils",
    "pyats.topology",
    "pyats.topology.loader",
    "virl2_client",
    "virl2_client.models",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

class _BasePluginStub:
    def __init__(self, *args, **kwargs): pass
sys.modules["pyats.easypy.plugins.bases"].BasePlugin = _BasePluginStub
sys.modules["pyats.log.utils"].banner = lambda s: str(s)

class _TestbedFileLoaderStub:
    def load(self, *args, **kwargs): return None
sys.modules["pyats.topology.loader"].TestbedFileLoader = _TestbedFileLoaderStub
sys.modules["pyats.topology"].loader = sys.modules["pyats.topology.loader"]

# Import target plugin module
import pyats.contrib.plugins.cml2_plugin.cml2 as cml2


# =============================================================================
# 2. Lightweight Mock Fixtures
# =============================================================================

class MockAnnotation:
    """Mock representing a CML2 annotation object."""
    def __init__(self, ann_id: str, ann_type: str, lab=None, **kwargs):
        self.id = ann_id
        self.type = ann_type
        self.lab = lab
        self.properties = dict(kwargs)
        self.removed = False

    def __getattr__(self, name: str):
        if name in self.properties:
            return self.properties[name]
        raise AttributeError(f"MockAnnotation has no property '{name}'")

    def remove(self) -> None:
        self.removed = True
        if self.lab and hasattr(self.lab, "remove_annotation"):
            self.lab.remove_annotation(self)

    def as_dict(self) -> dict:
        res = dict(self.properties)
        res["id"] = self.id
        res["type"] = self.type
        return res


class MockNode:
    """Mock representing a CML2 lab node."""
    def __init__(self, node_id: str, label: str, x: int = 0, y: int = 0, state: str = "STARTED"):
        self.id = node_id
        self.label = label
        self._x = int(x)
        self._y = int(y)
        self.state = state
        self.property_updates = []
        self._interfaces = []

    @property
    def x(self) -> int:
        return self._x

    @x.setter
    def x(self, val: int) -> None:
        self.property_updates.append(("x", int(val)))
        self._x = int(val)

    @property
    def y(self) -> int:
        return self._y

    @y.setter
    def y(self, val: int) -> None:
        self.property_updates.append(("y", int(val)))
        self._y = int(val)

    def interfaces(self):
        return self._interfaces


class MockLab:
    """Mock representing a CML2 lab instance."""
    def __init__(self, lab_id: str = "mock-lab-1a9037de", title: str = "bgp_automation"):
        self.id = lab_id
        self.title = title
        self._nodes: dict[str, MockNode] = {}
        self._annotations: dict[str, MockAnnotation] = {}
        self._session = unittest.mock.MagicMock()
        self.synced = False
        self.ann_counter = 0

    def sync(self) -> None:
        self.synced = True

    def nodes(self) -> list[MockNode]:
        return list(self._nodes.values())

    def get_node_by_label(self, label: str) -> MockNode | None:
        return self._nodes.get(label)

    def annotations(self) -> list[MockAnnotation]:
        return list(self._annotations.values())

    def create_annotation(self, annotation_type: str, **kwargs) -> MockAnnotation:
        self.ann_counter += 1
        ann_id = f"ann-{self.ann_counter:04d}"
        ann = MockAnnotation(ann_id, annotation_type, lab=self, **kwargs)
        self._annotations[ann_id] = ann
        return ann

    def remove_annotation(self, annotation: MockAnnotation) -> None:
        if annotation.id in self._annotations:
            del self._annotations[annotation.id]


class MockClientLibrary:
    """Mock representing virl2_client.ClientLibrary."""
    def __init__(self, lab: MockLab | None = None):
        self.lab = lab or MockLab()

    def join_existing_lab(self, lab_id_or_title: str) -> MockLab:
        return self.lab

    def create_lab(self, title: str) -> MockLab:
        self.lab.title = title
        return self.lab


def build_mock_testbed(custom_cml2: dict | None = None, device_custom: dict | None = None) -> SimpleNamespace:
    """Helper to build a mock 5-node BGP testbed."""
    device_custom = device_custom or {}
    devices = {}
    router_specs = [
        ("R1", "iol", "Primary Border (Edge-1)", "10.255.0.1/32"),
        ("R2", "iol", "Secondary Border (Edge-2)", "10.255.0.2/32"),
        ("R3", "iol", "Core Route Reflector", "10.255.0.3/32"),
        ("R4", "iol", "Internal Client", "10.255.0.4/32"),
        ("R5", "iol", "Upstream Transit (ISP-1)", "10.255.0.5/32"),
    ]

    for name, platform, role, lo0 in router_specs:
        dev = SimpleNamespace(
            name=name,
            alias=name,
            platform=platform,
            os="iosxe",
            type="router",
            custom={"cml2": device_custom.get(name, {})},
            topology=SimpleNamespace(
                interfaces={
                    "Loopback0": SimpleNamespace(name="Loopback0", ipv4=lo0),
                    "Ethernet0/0": SimpleNamespace(name="Ethernet0/0"),
                }
            ),
        )
        devices[name] = dev

    links = []
    link_definitions = [
        ("R1-R5", "R1", "Ethernet0/0", "10.0.15.1/30", "R5", "Ethernet0/0", "10.0.15.2/30"),
        ("R2-R5", "R2", "Ethernet0/0", "10.0.25.1/30", "R5", "Ethernet0/1", "10.0.25.2/30"),
        ("R1-R2", "R1", "Ethernet0/1", "10.0.12.1/30", "R2", "Ethernet0/1", "10.0.12.2/30"),
        ("R1-R3", "R1", "Ethernet0/2", "10.0.13.1/30", "R3", "Ethernet0/0", "10.0.13.2/30"),
        ("R2-R3", "R2", "Ethernet0/2", "10.0.23.1/30", "R3", "Ethernet0/1", "10.0.23.2/30"),
        ("R3-R4", "R3", "Ethernet0/2", "10.0.34.1/30", "R4", "Ethernet0/0", "10.0.34.2/30"),
    ]

    for alias, d1, i1_name, ip1, d2, i2_name, ip2 in link_definitions:
        intf1 = SimpleNamespace(name=i1_name, ipv4=ip1, device=devices[d1])
        intf2 = SimpleNamespace(name=i2_name, ipv4=ip2, device=devices[d2])
        link = SimpleNamespace(alias=alias, name=alias, interfaces=[intf1, intf2])
        links.append(link)

    return SimpleNamespace(
        name="bgp_automation",
        devices=devices,
        links=links,
        custom={"cml2": custom_cml2 or {}},
    )


# =============================================================================
# 3. Test Cases (10 Classes, 49 Test Scenarios)
# =============================================================================

class TestCML2CustomSchemaParsing(unittest.TestCase):
    """1. Test parsing of testbed.custom.cml2 and device-level custom.cml2 schemas."""

    def test_parse_full_valid_custom_cml2(self):
        """Scenario 1: Full valid custom.cml2 metadata extraction."""
        dev_custom = {
            "R1": {"x": -180, "y": -60, "tier": 2, "role": "Edge-1", "group": "as65001", "callout": {"text": "R1 Callout"}},
            "R5": {"x": 0, "y": -240, "tier": 1, "role": "ISP-1", "group": "as65100"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertEqual(devices["R1"].x, -180)
        self.assertEqual(devices["R1"].y, -60)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R1"].role, "Edge-1")
        self.assertEqual(devices["R1"].group, "as65001")
        self.assertEqual(devices["R1"].callout_text, "R1 Callout")
        self.assertEqual(devices["R5"].x, 0)
        self.assertEqual(devices["R5"].y, -240)
        self.assertEqual(devices["R5"].tier, 1)

    def test_parse_partial_custom_cml2_device_only(self):
        """Scenario 2: Device-level metadata without explicit coordinates."""
        dev_custom = {
            "R1": {"tier": 2, "role": "Border"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertIsNone(devices["R1"].x)
        self.assertIsNone(devices["R1"].y)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R1"].role, "Border")

    def test_parse_missing_custom_cml2_legacy_testbed(self):
        """Scenario 3: Legacy testbed without custom.cml2 metadata."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        for dev in devices.values():
            self.assertIsNone(dev.x)
            self.assertIsNone(dev.y)
            self.assertIsNone(dev.tier)
            self.assertIsNone(dev.role)
            self.assertIsNone(dev.group)

    def test_parse_skipped_infrastructure_devices(self):
        """Scenario 4: Exclusion of non-routable infrastructure devices."""
        tb = build_mock_testbed()
        tb.devices["terminal_server"] = SimpleNamespace(
            name="terminal_server", platform="terminal_server", os="linux", type="terminal_server"
        )
        tb.devices["traffic_gen"] = SimpleNamespace(
            name="traffic_gen", platform="trex", os="linux", type="trex"
        )
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertNotIn("terminal_server", devices)
        self.assertNotIn("traffic_gen", devices)

    def test_parse_group_definitions(self):
        """Scenario 5: Group and area definition extraction from testbed custom."""
        groups = {
            "as65100": {
                "title": "AS 65100: External Transit (ISP-1)",
                "members": ["R5"],
                "color": "#CE8943FF",
                "border_color": "#808080FF",
                "border_radius": 8,
            },
            "as65001": {
                "title": "AS 65001: Enterprise Network",
                "members": ["R1", "R2", "R3", "R4"],
                "color": "#45CFBCFF",
            },
        }
        tb = build_mock_testbed(custom_cml2={"groups": groups})
        parser = cml2.TestbedParser(tb)
        cml2_meta = parser.get_custom_cml2()

        self.assertIn("groups", cml2_meta)
        self.assertEqual(cml2_meta["groups"]["as65100"]["title"], "AS 65100: External Transit (ISP-1)")
        self.assertEqual(cml2_meta["groups"]["as65100"]["members"], ["R5"])
        self.assertEqual(cml2_meta["groups"]["as65100"]["border_radius"], 8)
        self.assertEqual(cml2_meta["groups"]["as65001"]["members"], ["R1", "R2", "R3", "R4"])


class TestCML2NodeLayoutEngines(unittest.TestCase):
    """2. Test explicit diamond coordinates vs hierarchical and circular layouts."""

    def test_circular_layout_fallback(self):
        """Scenario 6: Fallback circular layout for legacy testbeds."""
        pos = cml2.calculate_node_positions(5, radius=200)
        self.assertEqual(len(pos), 5)
        self.assertEqual(pos[0], (0, -200))
        self.assertEqual(cml2.calculate_node_positions(0), [])
        self.assertEqual(cml2.calculate_node_positions(1), [(0, 0)])

    def test_explicit_diamond_coordinates(self):
        """Scenario 7: Explicit North-South Diamond layout coordinates."""
        dev_custom = {
            "R5": {"x": 0, "y": -240},
            "R1": {"x": -180, "y": -60},
            "R2": {"x": 180, "y": -60},
            "R3": {"x": 0, "y": 120},
            "R4": {"x": 0, "y": 280},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        pos = cml2.calculate_hierarchical_positions(devices)
        self.assertEqual(pos["R5"], (0, -240))
        self.assertEqual(pos["R1"], (-180, -60))
        self.assertEqual(pos["R2"], (180, -60))
        self.assertEqual(pos["R3"], (0, 120))
        self.assertEqual(pos["R4"], (0, 280))

    def test_hierarchical_tier_automatic_layout(self):
        """Scenario 8: Automated hierarchical tier positioning and symmetry."""
        dev_custom = {
            "R5": {"tier": 1},
            "R1": {"tier": 2},
            "R2": {"tier": 2},
            "R3": {"tier": 3},
            "R4": {"tier": 4},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        pos = cml2.calculate_hierarchical_positions(devices)
        self.assertLess(pos["R5"][1], pos["R1"][1])
        self.assertEqual(pos["R1"][1], pos["R2"][1])
        self.assertLess(pos["R1"][1], pos["R3"][1])
        self.assertLess(pos["R3"][1], pos["R4"][1])

        self.assertEqual(pos["R1"][0], -pos["R2"][0])
        self.assertLess(pos["R1"][0], 0)
        self.assertGreater(pos["R2"][0], 0)
        self.assertEqual(pos["R5"][0], 0)
        self.assertEqual(pos["R3"][0], 0)
        self.assertEqual(pos["R4"][0], 0)

    def test_mixed_explicit_and_tier_layout(self):
        """Scenario 9: Mixing explicit coordinates with tier-based placement."""
        dev_custom = {
            "R1": {"x": -180, "y": -60},
            "R2": {"x": 180, "y": -60},
            "R5": {"tier": 1},
            "R3": {"tier": 3},
            "R4": {"tier": 4},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        pos = cml2.calculate_hierarchical_positions(devices)
        self.assertEqual(pos["R1"], (-180, -60))
        self.assertEqual(pos["R2"], (180, -60))
        self.assertLess(pos["R5"][1], pos["R3"][1])
        self.assertLess(pos["R3"][1], pos["R4"][1])

    def test_default_tier_assignment_when_omitted(self):
        """Scenario 10: Fallback to default tier (Tier 2) when unspecified."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        pos = cml2.calculate_hierarchical_positions({"R1": devices["R1"]})
        self.assertIn("R1", pos)
        self.assertEqual(pos["R1"], (0, 20))


class TestCML2GroupBoundingBoxes(unittest.TestCase):
    """3. Test automated bounding boxes and CML2 coordinate semantics."""

    def test_single_node_bounding_box_as65100(self):
        """Scenario 11: Single-node group bounding box (AS 65100)."""
        node_pos = {"R5": (0, -240)}
        groups = {
            "as65100": {
                "title": "AS 65100: External Transit (ISP-1)",
                "members": ["R5"],
                "color": "#CE8943FF",
                "border_color": "#808080FF",
                "border_radius": 8,
                "half_width": 190,
                "half_height": 70,
                "z_index": 0,
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        self.assertEqual(len(anns), 2)

        rect = next(a for a in anns if a["type"] == "rectangle")
        self.assertEqual(rect["x1"], -190.0)
        self.assertEqual(rect["y1"], -310.0)
        self.assertEqual(rect["x2"], 380.0)
        self.assertEqual(rect["y2"], 140.0)
        self.assertGreater(rect["x2"], 0)
        self.assertGreater(rect["y2"], 0)
        self.assertEqual(rect["color"], "#CE8943FF")
        self.assertEqual(rect["border_radius"], 8)
        self.assertEqual(rect["z_index"], 0)

        title = next(a for a in anns if a["type"] == "text")
        self.assertEqual(title["text_content"], "AS 65100: External Transit (ISP-1)")
        self.assertEqual(title["x1"], -175.0)
        self.assertEqual(title["y1"], -288.0)
        self.assertNotIn("x2", title)
        self.assertNotIn("y2", title)
        self.assertEqual(title["z_index"], 2)

    def test_multi_node_bounding_box_as65001(self):
        """Scenario 12: Multi-node group bounding box containment (AS 65001)."""
        node_pos = {
            "R1": (-180, -60),
            "R2": (180, -60),
            "R3": (0, 120),
            "R4": (0, 280),
        }
        groups = {
            "as65001": {
                "title": "AS 65001",
                "members": ["R1", "R2", "R3", "R4"],
                "padding": 60,
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        rect = next(a for a in anns if a["type"] == "rectangle")
        self.assertEqual(rect["x1"], -240.0)
        self.assertEqual(rect["y1"], -125.0)
        self.assertEqual(rect["x2"], 480.0)
        self.assertEqual(rect["y2"], 470.0)

        for name, (nx, ny) in node_pos.items():
            self.assertGreaterEqual(nx, rect["x1"], f"{name} X left bound")
            self.assertLessEqual(nx, rect["x1"] + rect["x2"], f"{name} X right bound")
            self.assertGreaterEqual(ny, rect["y1"], f"{name} Y top bound")
            self.assertLessEqual(ny, rect["y1"] + rect["y2"], f"{name} Y bottom bound")

    def test_group_explicit_coordinate_override(self):
        """Scenario 13: Explicit coordinate override on group."""
        node_pos = {"R1": (0, 0)}
        groups = {
            "g1": {
                "title": "Explicit Group",
                "members": ["R1"],
                "x1": -435.0,
                "y1": -125.0,
                "x2": 870.0,
                "y2": 480.0,
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        rect = next(a for a in anns if a["type"] == "rectangle")
        self.assertEqual(rect["x1"], -435.0)
        self.assertEqual(rect["y1"], -125.0)
        self.assertEqual(rect["x2"], 870.0)
        self.assertEqual(rect["y2"], 480.0)

    def test_group_empty_or_unplaced_members(self):
        """Scenario 14: Graceful handling of unplaced group members."""
        node_pos = {"R1": (0, 0)}
        groups = {
            "ghost": {
                "title": "Ghost Group",
                "members": ["NonExistent1", "NonExistent2"],
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        self.assertEqual(len(anns), 0)

    def test_group_z_index_and_color_formatting(self):
        """Scenario 15: Group z-index layering and 8-character hex RGBA color validation."""
        node_pos = {"R1": (0, 0)}
        groups = {
            "g1": {
                "title": "Group 1",
                "members": ["R1"],
                "color": "#1094DFFF",
                "border_color": "#808080FF",
                "z_index": 0,
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        rect = next(a for a in anns if a["type"] == "rectangle")
        title = next(a for a in anns if a["type"] == "text")

        self.assertEqual(rect["z_index"], 0)
        self.assertEqual(title["z_index"], 2)
        self.assertTrue(rect["color"].startswith("#"))
        self.assertEqual(len(rect["color"]), 9)


class TestCML2CalloutsAndLinkAnnotations(unittest.TestCase):
    """4. Test per-node callouts and link subnet annotations."""

    def test_node_callout_extraction_from_loopback(self):
        """Scenario 16: Automatic Loopback0 IP and role extraction."""
        dev_custom = {"R1": {"role": "Primary Border (Edge-1)"}}
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        node_pos = {"R1": (-180, -60), "R2": (180, -60)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r1_ann = next(a for a in anns if a["type"] == "text" and "10.255.0.1" in a["text_content"])
        self.assertIn("Lo0: 10.255.0.1/32", r1_ann["text_content"])
        self.assertIn("Primary Border", r1_ann["text_content"])

    def test_node_callout_custom_override_and_offsets(self):
        """Scenario 17: Explicit callout text and custom offset override."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        devices["R1"].callout = {"text": "Custom R1 Badge", "offset_x": -200, "offset_y": -15}
        node_pos = {"R1": (-180, -60)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r1_ann = next(a for a in anns if a["type"] == "text" and "Custom R1 Badge" in a["text_content"])
        self.assertEqual(r1_ann["text_content"], "Custom R1 Badge")
        self.assertEqual(r1_ann["x1"], -380.0)
        self.assertEqual(r1_ann["y1"], -75.0)

    def test_node_callout_horizontal_anchor_direction(self):
        """Scenario 18: Non-colliding anchor directions (left vs right of icon)."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        node_pos = {"R1": (-180, -60), "R2": (180, -60)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r1_ann = next(a for a in anns if a["type"] == "text" and "10.255.0.1" in a["text_content"])
        r2_ann = next(a for a in anns if a["type"] == "text" and "10.255.0.2" in a["text_content"])

        self.assertEqual(r1_ann["x1"], -380.0)
        self.assertEqual(r2_ann["x1"], 220.0)
        self.assertLess(r1_ann["x1"], -180 - 30)
        self.assertGreater(r2_ann["x1"], 180 + 30)

    def test_link_subnet_extraction_and_canonical_midpoint(self):
        """Scenario 19: Link subnet extraction, midpoint calculation, and canonical sorting."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        node_pos = {
            "R1": (-180, -60),
            "R5": (0, -240),
        }
        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r1_r5_ann = next(a for a in anns if "10.0.15.0/30" in a["text_content"])
        self.assertEqual(r1_r5_ann["text_content"], "10.0.15.0/30")

        tb_rev = build_mock_testbed()
        r1_r5_link = next(l for l in tb_rev.links if l.alias == "R1-R5")
        r1_r5_link.interfaces.reverse()
        anns_rev = cml2.generate_node_and_link_annotations(tb_rev, node_pos, devices)
        r1_r5_ann_rev = next(a for a in anns_rev if "10.0.15.0/30" in a["text_content"])
        self.assertEqual(r1_r5_ann["x1"], r1_r5_ann_rev["x1"])
        self.assertEqual(r1_r5_ann["y1"], r1_r5_ann_rev["y1"])

    def test_link_subnet_manual_offset_override(self):
        """Scenario 20: Link label and offset override mechanics."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        node_pos = {
            "R1": (-180, -60),
            "R5": (0, -240),
            "R2": (180, -60),
            "R3": (0, 120),
            "R4": (0, 280),
        }
        overrides = {
            "R1-R5": {
                "label": "10.0.15.0/30\neBGP + BFD",
                "offset_x": -87,
                "offset_y": -58,
            }
        }
        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices, link_overrides=overrides)
        link_ann = next(a for a in anns if "10.0.15.0/30" in a["text_content"])
        self.assertEqual(link_ann["text_content"], "10.0.15.0/30\neBGP + BFD")
        self.assertEqual(link_ann["x1"], -177.0)
        self.assertEqual(link_ann["y1"], -208.0)


class TestCML2AnnotationApplication(unittest.TestCase):
    """5. Test dispatching annotations and sanitizing forbidden properties."""

    def test_apply_annotations_strips_x2_y2_on_text(self):
        """Scenario 21: Defensive stripping of x2/y2 from text annotations."""
        lab = MockLab()
        raw = [
            {"type": "text", "text_content": "Banner", "x1": 0, "y1": 0, "x2": 100, "y2": 50},
        ]
        cml2.apply_annotations(lab, raw)
        text_ann = next(a for a in lab.annotations() if a.type == "text")
        self.assertNotIn("x2", text_ann.properties)
        self.assertNotIn("y2", text_ann.properties)

    def test_apply_annotations_retains_x2_y2_on_rectangle(self):
        """Scenario 22: Retention of x2/y2 as width/height on rectangle annotations."""
        lab = MockLab()
        raw = [
            {"type": "rectangle", "x1": -100, "y1": -100, "x2": 200, "y2": 200, "color": "#CE8943FF"},
        ]
        cml2.apply_annotations(lab, raw)
        rect_ann = next(a for a in lab.annotations() if a.type == "rectangle")
        self.assertEqual(rect_ann.properties["x2"], 200)
        self.assertEqual(rect_ann.properties["y2"], 200)

    def test_apply_annotations_dispatches_all_types(self):
        """Scenario 23: Successful dispatch of text, rectangle, line, and ellipse annotations."""
        lab = MockLab()
        raw = [
            {"type": "text", "text_content": "T"},
            {"type": "rectangle", "x1": 0, "y1": 0, "x2": 10, "y2": 10},
            {"type": "line", "x1": 0, "y1": 0, "x2": 20, "y2": 20},
            {"type": "ellipse", "x1": 0, "y1": 0, "x2": 30, "y2": 30},
        ]
        created = cml2.apply_annotations(lab, raw)
        self.assertEqual(len(created), 4)
        types_created = {a.type for a in lab.annotations()}
        self.assertEqual(types_created, {"text", "rectangle", "line", "ellipse"})

    def test_apply_annotations_defensive_exception_shielding(self):
        """Scenario 24: Fault-tolerance against single annotation creation failures."""
        lab = MockLab()
        lab.create_annotation = unittest.mock.MagicMock(side_effect=[Exception("Server Error"), MockAnnotation("a2", "text")])
        created = cml2.apply_annotations(lab, [{"type": "bad"}, {"type": "text", "text_content": "ok"}])
        self.assertEqual(len(created), 1)


class TestCML2InPlaceLabUpdates(unittest.TestCase):
    """6. Test update_lab_layout_and_annotations_in_place() execution."""

    def test_in_place_update_moves_nodes_and_creates_annotations(self):
        """Scenario 25: Live node repositioning, stale purge, and annotation generation."""
        lab = MockLab("test-lab-123", "bgp_automation")
        for name in ["R1", "R2", "R3", "R4", "R5"]:
            lab._nodes[name] = MockNode(f"node-{name}", name, x=0, y=0, state="STARTED")
        old_ann = lab.create_annotation("text", text_content="Old annotation")

        client = MockClientLibrary(lab)
        dev_custom = {
            "R5": {"x": 0, "y": -240, "tier": 1},
            "R1": {"x": -180, "y": -60, "tier": 2},
            "R2": {"x": 180, "y": -60, "tier": 2},
            "R3": {"x": 0, "y": 120, "tier": 3},
            "R4": {"x": 0, "y": 280, "tier": 4},
        }
        tb = build_mock_testbed(
            custom_cml2={
                "groups": {
                    "as65100": {"title": "AS65100", "members": ["R5"], "half_width": 190, "half_height": 70}
                }
            },
            device_custom=dev_custom,
        )

        res = cml2.update_lab_layout_and_annotations_in_place(client, "test-lab-123", tb, clear_existing_annotations=True)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertGreaterEqual(len(res["annotations_created"]), 1)
        self.assertEqual(res["nodes_updated"], 5)
        self.assertTrue(old_ann.removed)
        self.assertEqual(lab._nodes["R1"].x, -180)
        self.assertEqual(lab._nodes["R1"].y, -60)
        self.assertEqual(lab._nodes["R5"].x, 0)
        self.assertEqual(lab._nodes["R5"].y, -240)
        self.assertEqual(lab._nodes["R1"].state, "STARTED")
        self.assertTrue(lab.synced)

    def test_in_place_update_preserves_annotations_when_clear_false(self):
        """Scenario 26: Preserving existing annotations when clean_existing=False."""
        lab = MockLab("test-lab-123", "bgp_automation")
        lab._nodes["R1"] = MockNode("node-R1", "R1", x=0, y=0)
        old_ann = lab.create_annotation("text", text_content="Old annotation")
        client = MockClientLibrary(lab)
        tb = build_mock_testbed()

        res = cml2.update_lab_layout_and_annotations_in_place(client, "test-lab-123", tb, clean_existing=False)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertFalse(old_ann.removed)

    def test_in_place_update_skips_unchanged_node_coordinates(self):
        """Scenario 27: Avoiding redundant coordinate updates when positions match."""
        lab = MockLab("test-lab-123", "bgp_automation")
        lab._nodes["R5"] = MockNode("node-R5", "R5", x=0, y=-240)
        client = MockClientLibrary(lab)
        dev_custom = {"R5": {"x": 0, "y": -240}}
        tb = build_mock_testbed(device_custom=dev_custom)

        res = cml2.update_lab_layout_and_annotations_in_place(client, "test-lab-123", tb)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertEqual(res["nodes_updated"], 0)
        self.assertEqual(len(lab._nodes["R5"].property_updates), 0)

    def test_in_place_update_maintains_started_node_state(self):
        """Scenario 28: Zero disruption to node STARTED state."""
        lab = MockLab("test-lab-123", "bgp_automation")
        for name in ["R1", "R2"]:
            lab._nodes[name] = MockNode(f"node-{name}", name, x=0, y=0, state="STARTED")
        client = MockClientLibrary(lab)
        dev_custom = {"R1": {"x": -180, "y": -60}, "R2": {"x": 180, "y": -60}}
        tb = build_mock_testbed(device_custom=dev_custom)

        res = cml2.update_lab_layout_and_annotations_in_place(client, "test-lab-123", tb)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertEqual(lab._nodes["R1"].state, "STARTED")
        self.assertEqual(lab._nodes["R2"].state, "STARTED")


class TestCML2EdgeCasesAndCompatibility(unittest.TestCase):
    """7. Test edge cases and zero-configuration backward compatibility."""

    def test_backward_compatibility_zero_custom_cml2(self):
        """Scenario 29: Complete backward compatibility with zero custom.cml2."""
        lab = MockLab()
        for name in ["R1", "R2", "R3"]:
            lab._nodes[name] = MockNode(f"node-{name}", name, x=0, y=0)
        client = MockClientLibrary(lab)
        tb = build_mock_testbed()

        res = cml2.update_lab_layout_and_annotations_in_place(client, "test", tb)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertEqual(len(res["annotations_created"]), 0)
        self.assertEqual(res["nodes_updated"], 3)
        self.assertNotEqual((lab._nodes["R1"].x, lab._nodes["R1"].y), (0, 0))

    def test_empty_testbed(self):
        """Scenario 30: Empty testbed with zero devices or links."""
        lab = MockLab()
        client = MockClientLibrary(lab)
        tb = SimpleNamespace(devices={}, links=[], custom={})
        res = cml2.update_lab_layout_and_annotations_in_place(client, "empty", tb)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertEqual(len(res["annotations_created"]), 0)
        self.assertEqual(res["nodes_updated"], 0)

    def test_none_testbed(self):
        """Scenario 31: Null testbed returns dictionary with zero counts."""
        lab = MockLab()
        res = cml2.update_lab_layout_and_annotations_in_place(lab, None)
        self.assertIsInstance(res, dict)
        self.assertIn("nodes_updated", res)
        self.assertIn("annotations_created", res)
        self.assertEqual(len(res["annotations_created"]), 0)
        self.assertEqual(res["nodes_updated"], 0)

    def test_single_device_testbed(self):
        """Scenario 32: Single-device testbed centered at origin."""
        dev = SimpleNamespace(
            name="R1", alias="R1", platform="iol", os="iosxe", type="router", custom={},
            topology=SimpleNamespace(interfaces={}),
        )
        tb = SimpleNamespace(devices={"R1": dev}, links=[], custom={"cml2": {"groups": {"g1": {"members": ["R1"]}}}})
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        pos = cml2.resolve_node_positions(devices)
        self.assertEqual(pos["R1"], (0, 0))

    def test_non_p2p_or_missing_ip_link(self):
        """Scenario 33: Non-point-to-point links (e.g. 1 or 3 endpoints) safely skipped."""
        tb = build_mock_testbed()
        bad_link1 = SimpleNamespace(alias="bad1", interfaces=[SimpleNamespace(name="e0")])
        bad_link3 = SimpleNamespace(alias="bad3", interfaces=[SimpleNamespace(name="e0"), SimpleNamespace(name="e1"), SimpleNamespace(name="e2")])
        tb.links.extend([bad_link1, bad_link3])

        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        anns = cml2.generate_node_and_link_annotations(tb, {"R1": (0, 0)}, devices)
        self.assertIsInstance(anns, list)


class TestCML2TierParsingAndResolution(unittest.TestCase):
    """8. Test string tier parsing, canonical resolution, and fault handling."""

    def test_parse_string_tier_canonical_names(self):
        """Scenario 34: Canonical string tier parsing (core->3, edge->2, isp->1, client->4)."""
        dev_custom = {
            "R5": {"tier": "isp"},
            "R1": {"tier": "edge"},
            "R2": {"tier": "edge"},
            "R3": {"tier": "core"},
            "R4": {"tier": "client"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertEqual(devices["R5"].tier, 1)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R2"].tier, 2)
        self.assertEqual(devices["R3"].tier, 3)
        self.assertEqual(devices["R4"].tier, 4)

    def test_parse_string_tier_case_insensitivity(self):
        """Scenario 35: Case-insensitive string tier parsing (CORE, Edge, ISP, CLIENT)."""
        dev_custom = {
            "R5": {"tier": "ISP"},
            "R1": {"tier": "EDGE"},
            "R2": {"tier": "Edge"},
            "R3": {"tier": "CORE"},
            "R4": {"tier": "Client"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertEqual(devices["R5"].tier, 1)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R2"].tier, 2)
        self.assertEqual(devices["R3"].tier, 3)
        self.assertEqual(devices["R4"].tier, 4)

    def test_parse_string_tier_whitespace_tolerance(self):
        """Scenario 36: Leading/trailing whitespace tolerance (' core ', ' edge\\t', '\\nisp ')."""
        dev_custom = {
            "R5": {"tier": "  isp\n"},
            "R1": {"tier": "\tedge  "},
            "R3": {"tier": " core "},
            "R4": {"tier": "  client  "},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertEqual(devices["R5"].tier, 1)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R3"].tier, 3)
        self.assertEqual(devices["R4"].tier, 4)

    def test_parse_string_tier_digit_strings(self):
        """Scenario 37: String digits ('1', ' 2 ', '3', '4') cleanly parsed to int."""
        dev_custom = {
            "R5": {"tier": "1"},
            "R1": {"tier": " 2 "},
            "R3": {"tier": "3"},
            "R4": {"tier": "4"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertEqual(devices["R5"].tier, 1)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R3"].tier, 3)
        self.assertEqual(devices["R4"].tier, 4)

    def test_parse_string_tier_extended_aliases(self):
        """Scenario 38: Architectural synonyms (external, transit, border, leaf, spine, rr, access)."""
        dev_custom = {
            "R5": {"tier": "external"},
            "R1": {"tier": "border"},
            "R2": {"tier": "leaf"},
            "R3": {"tier": "rr"},
            "R4": {"tier": "access"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        self.assertEqual(devices["R5"].tier, 1)
        self.assertEqual(devices["R1"].tier, 2)
        self.assertEqual(devices["R2"].tier, 2)
        self.assertEqual(devices["R3"].tier, 3)
        self.assertEqual(devices["R4"].tier, 4)

    def test_parse_string_tier_invalid_raises_value_error(self):
        """Scenario 39: Invalid string tier raises informative ValueError."""
        dev_custom = {"R1": {"tier": "invalid_tier"}}
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        with self.assertRaises(ValueError) as cm:
            parser.get_devices()
        self.assertIn("Invalid string tier 'invalid_tier'", str(cm.exception))
        self.assertIn("R1", str(cm.exception))

    def test_hierarchical_layout_with_string_tiers(self):
        """Scenario 40: End-to-end hierarchical placement using string tiers."""
        dev_custom = {
            "R5": {"tier": "isp"},
            "R1": {"tier": "edge"},
            "R2": {"tier": "edge"},
            "R3": {"tier": "core"},
            "R4": {"tier": "client"},
        }
        tb = build_mock_testbed(device_custom=dev_custom)
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()

        pos = cml2.calculate_hierarchical_positions(devices)
        self.assertLess(pos["R5"][1], pos["R1"][1])
        self.assertEqual(pos["R1"][1], pos["R2"][1])
        self.assertLess(pos["R1"][1], pos["R3"][1])
        self.assertLess(pos["R3"][1], pos["R4"][1])
        self.assertEqual(pos["R1"][0], -pos["R2"][0])


class TestCML2CalloutSingleAxisOverrides(unittest.TestCase):
    """9. Test single-axis callout overrides (specifying offset_x or offset_y independently)."""

    def test_callout_override_offset_x_only_left_node(self):
        """Scenario 41: Left node (x < 0) with offset_x only; Y retains default -15.0."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        devices["R1"].callout = {"text": "Custom R1", "offset_x": -220}
        node_pos = {"R1": (-180, -60)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r1_ann = next(a for a in anns if a["type"] == "text" and a["text_content"] == "Custom R1")
        self.assertEqual(r1_ann["x1"], -400.0)  # -180 + (-220)
        self.assertEqual(r1_ann["y1"], -75.0)   # -60 + (-15) default Y

    def test_callout_override_offset_y_only_left_node(self):
        """Scenario 42: Left node (x < 0) with offset_y only; X retains default -200.0."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        devices["R1"].callout = {"text": "Custom R1", "offset_y": -35}
        node_pos = {"R1": (-180, -60)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r1_ann = next(a for a in anns if a["type"] == "text" and a["text_content"] == "Custom R1")
        self.assertEqual(r1_ann["x1"], -380.0)  # -180 + (-200) default X
        self.assertEqual(r1_ann["y1"], -95.0)   # -60 + (-35)

    def test_callout_override_offset_x_only_right_node(self):
        """Scenario 43: Right node (x > 0) with offset_x only; Y retains default -15.0."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        devices["R2"].callout = {"text": "Custom R2", "offset_x": 60}
        node_pos = {"R2": (180, -60)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r2_ann = next(a for a in anns if a["type"] == "text" and a["text_content"] == "Custom R2")
        self.assertEqual(r2_ann["x1"], 240.0)   # 180 + 60
        self.assertEqual(r2_ann["y1"], -75.0)   # -60 + (-15) default Y

    def test_callout_override_offset_y_only_center_node(self):
        """Scenario 44: Center node (x == 0) with offset_y only; X retains default +45.0."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        devices["R3"].callout = {"text": "Custom R3", "offset_y": 10}
        node_pos = {"R3": (0, 120)}

        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices)
        r3_ann = next(a for a in anns if a["type"] == "text" and a["text_content"] == "Custom R3")
        self.assertEqual(r3_ann["x1"], 45.0)    # 0 + 45 default X
        self.assertEqual(r3_ann["y1"], 130.0)   # 120 + 10


class TestCML2KeyAliasingAndSchemaTolerance(unittest.TestCase):
    """10. Test schema key aliasing and backward compatibility tolerance."""

    def test_group_aliasing_devices_instead_of_members(self):
        """Scenario 45: Groups configured with 'devices' alias instead of 'members'."""
        node_pos = {"R1": (-180, -60), "R2": (180, -60)}
        groups = {
            "as65001": {
                "title": "AS 65001",
                "devices": ["R1", "R2"],
                "padding": 60,
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        self.assertEqual(len(anns), 2)
        rect = next(a for a in anns if a["type"] == "rectangle")
        self.assertEqual(rect["x1"], -240.0)
        self.assertEqual(rect["x2"], 480.0)

    def test_link_aliasing_link_overrides_and_subnet(self):
        """Scenario 46: Links configured with 'link_overrides' and 'subnet' instead of 'links' and 'label'."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        node_pos = {"R1": (-180, -60), "R5": (0, -240)}

        testbed_cml2 = {
            "link_overrides": {
                "R1-R5": {
                    "subnet": "10.0.15.0/30\neBGP Demarcation",
                    "offset_x": -10,
                    "offset_y": -20,
                }
            }
        }
        overrides = testbed_cml2.get("links") or testbed_cml2.get("link_overrides", {})
        anns = cml2.generate_node_and_link_annotations(tb, node_pos, devices, link_overrides=overrides)
        link_ann = next(a for a in anns if "eBGP Demarcation" in a["text_content"])
        self.assertEqual(link_ann["text_content"], "10.0.15.0/30\neBGP Demarcation")
        self.assertEqual(link_ann["x1"], -100.0)
        self.assertEqual(link_ann["y1"], -170.0)

    def test_layout_engine_aliasing_style_instead_of_engine(self):
        """Scenario 47: Layout engine configured with 'style' instead of 'engine'."""
        dev = SimpleNamespace(name="R1", alias="R1", platform="iol", os="iosxe", type="router", custom={})
        devices = {"R1": dev, "R2": dev, "R3": dev}
        cml2_meta = {"layout": {"style": "circular", "radius": 150}}
        pos = cml2.resolve_node_positions(devices, cml2_meta)
        self.assertEqual(len(pos), 3)

    def test_group_title_size_aliasing_title_font_size(self):
        """Scenario 48: Group title font size configured with 'title_font_size' instead of 'title_size'."""
        node_pos = {"R1": (0, 0)}
        groups = {
            "g1": {
                "title": "Group 1",
                "members": ["R1"],
                "title_font_size": 16,
            }
        }
        anns = cml2.generate_group_annotations(groups, node_pos)
        title = next(a for a in anns if a["type"] == "text")
        self.assertEqual(title["text_size"], 16)

    def test_auto_annotations_aliasing_subnets_instead_of_link_labels(self):
        """Scenario 49: Auto annotations configured with 'subnets: false' instead of 'link_labels: false'."""
        tb = build_mock_testbed()
        parser = cml2.TestbedParser(tb)
        devices = parser.get_devices()
        node_pos = {"R1": (-180, -60), "R5": (0, -240)}

        anns = cml2.generate_node_and_link_annotations(
            tb, node_pos, devices, auto_ann_config={"enabled": True, "subnets": False}
        )
        link_anns = [a for a in anns if "10.0.15.0/30" in a.get("text_content", "")]
        self.assertEqual(len(link_anns), 0)
        node_anns = [a for a in anns if "10.255.0.1" in a.get("text_content", "")]
        self.assertEqual(len(node_anns), 1)


if __name__ == "__main__":
    unittest.main()
