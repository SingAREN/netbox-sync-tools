import unittest
from unittest.mock import MagicMock, patch
from src.importers import vlan_importer


class TestNetBoxImporter(unittest.TestCase):

    def test_port_based_vlan_mapping(self):
        """Test the transformation from VLAN-centric to Interface-centric mappings."""
        input_vlans = {
            "10": {"interfaces": {"tagged": ["Eth1/1"], "untagged": []}},
            "20": {"interfaces": {"tagged": [], "untagged": ["Eth1/2"]}},
            "missing": []
        }

        expected = {
            "Eth1/1": {"tagged": ["10"], "untagged": ""},
            "Eth1/2": {"tagged": [], "untagged": "20"}
        }

        result = vlan_importer.port_based_vlan_mapping(input_vlans)
        self.assertEqual(result, expected)

    def test_get_or_create_tag_exists(self):
        """Test tag retrieval when the tag already exists in NetBox."""
        mock_nb = MagicMock()
        mock_tag = MagicMock()
        mock_tag.id = 123
        mock_nb.extras.tags.get.return_value = mock_tag

        result = vlan_importer.get_or_create_tag(mock_nb, "device-1")

        self.assertEqual(result.id, 123)
        mock_nb.extras.tags.create.assert_not_called()

    def test_sync_vlan_port_mappings_drift(self):
        """Test that drift is detected and the interface save method is called."""
        # 1. Setup Mock PyNetbox Interface
        mock_interface = MagicMock()
        mock_interface.name = "Eth1/1"
        mock_interface.untagged_vlan = None
        mock_interface.tagged_vlans = []

        # 2. Setup Mock VLANs from NetBox to populate the lookup dictionary
        mock_vlan_10 = MagicMock()
        mock_vlan_10.vid = 10
        mock_vlan_10.id = 999  # Internal NetBox ID

        # 3. Setup Port Mappings (Desired State)
        port_mappings = {
            "Eth1/1": {"tagged": [], "untagged": "10"}
        }

        # 4. Execute the function
        vlan_importer.sync_vlan_port_mappings(
            interface_list=[mock_interface],
            port_mappings=port_mappings,
            vlan_list=[mock_vlan_10]
        )

        # 5. Assertions
        # The script should have updated the untagged vlan to ID 999, set mode to access, and saved
        self.assertEqual(mock_interface.untagged_vlan, 999)
        self.assertEqual(mock_interface.mode, 'access')
        mock_interface.save.assert_called_once()

    def test_sync_vlan_port_mappings_no_drift(self):
        """Test that if the desired state matches NetBox, no save is triggered."""
        mock_interface = MagicMock()
        mock_interface.name = "Eth1/1"

        # Simulate an interface already correctly configured with NetBox ID 999
        untagged_mock = MagicMock()
        untagged_mock.id = 999
        mock_interface.untagged_vlan = untagged_mock
        mock_interface.tagged_vlans = []

        mock_vlan_10 = MagicMock()
        mock_vlan_10.vid = 10
        mock_vlan_10.id = 999

        port_mappings = {
            "Eth1/1": {"tagged": [], "untagged": "10"}
        }

        vlan_importer.sync_vlan_port_mappings(
            interface_list=[mock_interface],
            port_mappings=port_mappings,
            vlan_list=[mock_vlan_10]
        )

        # save() should NOT be called because states match
        mock_interface.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
