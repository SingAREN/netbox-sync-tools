import unittest
import ipaddress
# Assumes vlan_parser_v1.2.py has been renamed to vlan_parser.py
from src.parsers import vlan_parser


class TestVLANParser(unittest.TestCase):

    def test_explode_ranges(self):
        """Test that VLAN ranges are correctly exploded into individual strings."""
        input_list = ['10', '20-22', '30']
        expected = ['10', '20', '21', '22', '30']
        result = vlan_parser.explode_ranges(input_list)
        self.assertEqual(result, expected)

    def test_parse_slx_vlan(self):
        """Test SLX config parsing for VLAN IDs, names, and router interfaces."""
        mock_config = """
vlan 10
 name SERVERS
 router-interface Ve 10
!
vlan 20
 name GUEST
        """
        result = vlan_parser.parse_slx_vlan(mock_config)

        self.assertIn('10', result)
        self.assertEqual(result['10']['vlan_name'], 'SERVERS')
        self.assertEqual(result['10']['vlan_interface'], 'Ve 10')

        self.assertIn('20', result)
        self.assertEqual(result['20']['vlan_name'], 'GUEST')
        self.assertEqual(result['20']['vlan_interface'], '')

    def test_parse_edgecore_vlan(self):
        """Test Edgecore config parsing."""
        mock_config = "vlan 51 bridge 1 name AS134148_NSCC state enable\n!"
        result = vlan_parser.parse_edgecore_vlan(mock_config)

        self.assertIn('51', result)
        self.assertEqual(result['51']['vlan_name'], 'AS134148_NSCC')

    def test_vlan_port_mappings(self):
        """Test that interfaces and IPs are correctly mapped to existing VLANs."""
        # Initial dictionary structure simulating output from parse_slx_vlan
        master_dict = {
            "missing": [],
            "10": {
                'vid': '10', 'vlan_interface': 'Ve 10', 'vlan_name': 'SERVERS',
                'vlan_interface_prefix': {'ipv4': [], 'ipv6': []},
                'vlan_interface_description': '',
                'interfaces': {'tagged': [], 'untagged': []}
            }
        }

        mock_config = """
interface Ethernet 0/1
 switchport trunk allowed vlan add 10
!
interface Ethernet 0/2
 switchport access vlan 10
!
interface Ve 10
 ip address 192.168.1.1/24
 description Core Gateway
        """

        result = vlan_parser.vlan_port_mappings(mock_config, master_dict)

        # Check Interface mappings
        self.assertIn('Ethernet 0/1', result['10']['interfaces']['tagged'])
        self.assertIn('Ethernet 0/2', result['10']['interfaces']['untagged'])

        # Check Ve mappings
        self.assertEqual(result['10']['vlan_interface_description'], 'Core Gateway')
        self.assertIn('192.168.1.1/24', result['10']['vlan_interface_prefix']['ipv4'])


if __name__ == '__main__':
    unittest.main()
