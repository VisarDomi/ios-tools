"""Offline regressions for roaming, wrong-device rejection and unicast DNS."""
import asyncio
import importlib.machinery
import importlib.util
import ipaddress
from pathlib import Path
import ssl
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

loader = importlib.machinery.SourceFileLoader('phone_discovery', str(Path(__file__).parents[1] / 'scripts/phone-discovery'))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

UDID = '00008101-000639912881401E'
ADDRESS = '192.168.7.45'
HOST = 'Test-Phone.local.'
UUID = '12345678-1234-1234-1234-123456789abc'
ALIAS = UUID + '.' + m.SERVICE
NETWORKS = [dict(interface='en4', address='192.168.7.199', network=ipaddress.ip_network('192.168.7.0/24'))]


def packet():
    question = m.encode_name(m.SERVICE) + struct.pack('!HH', 12, 1)
    def record(owner, kind, value):
        return owner + struct.pack('!HHIH', kind, 1, 120, len(value)) + value
    return struct.pack('!6H', 0, 0x8400, 1, 5, 0, 0) + question + b''.join([
        record(b'\xc0\x0c', 12, m.encode_name(ALIAS)),
        record(m.encode_name(ALIAS), 33, struct.pack('!HHH', 0, 0, 64000) + m.encode_name(HOST)),
        record(m.encode_name(ALIAS), 16, b'\x05ver=1'),
        record(m.encode_name(HOST), 28, ipaddress.ip_address('fe80::1234').packed),
        record(m.encode_name(HOST), 1, ipaddress.ip_address(ADDRESS).packed),
    ])


class DiscoveryTests(unittest.TestCase):
    def test_only_active_physical_lan_interfaces_are_scanned(self):
        text = '''en0: flags=8863<UP,BROADCAST,RUNNING>
    inet 192.168.8.198 netmask 0xffffff00
    status: inactive
en4: flags=8863<UP,BROADCAST,RUNNING>
    inet 192.168.7.199 netmask 0xffffff00
    status: active
utun3: flags=8051<UP,POINTOPOINT,RUNNING>
    inet 10.9.0.1 netmask 0xffffff00
    status: active
lo0: flags=8049<UP,LOOPBACK,RUNNING>
    inet 127.0.0.1 netmask 0xff000000
    status: active
'''
        self.assertEqual(m.interfaces(text), NETWORKS)
        self.assertIsNone(m.on_link('10.9.0.2', NETWORKS))
        self.assertIsNone(m.on_link('192.168.7.199', NETWORKS))

    def test_large_network_scan_stays_in_local_24_and_is_bounded(self):
        network = dict(NETWORKS[0], network=ipaddress.ip_network('192.168.0.0/16'))
        addresses = m.scan_addresses([network])
        self.assertEqual(len(addresses), 253)
        self.assertTrue(all(a.startswith('192.168.7.') for a in addresses))
        self.assertNotIn(network['address'], addresses)
        many = [dict(interface='en4', address='10.%s.0.1' % i, network=ipaddress.ip_network('10.%s.0.0/22' % i)) for i in range(4)]
        self.assertLessEqual(len(m.scan_addresses(many)), 1024)

    def test_dual_connected_interfaces_use_the_phones_actual_route(self):
        ethernet = dict(NETWORKS[0], interface='en0', address='192.168.7.198')
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'interface: en4')):
            self.assertEqual(m.endpoint_network(ADDRESS, [ethernet] + NETWORKS)['interface'], 'en4')

    def test_stale_cached_ip_and_neighbours_are_filtered_to_current_lan(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(m, 'DIRECTORY', Path(temporary)), \
             patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '? (192.168.7.56) at aa\n? (10.0.0.9) at bb')):
            (Path(temporary) / 'state.json').write_text('{"network":"Test-Phone.local|192.168.7.45|interface: en4"}')
            self.assertEqual(m.candidate_addresses(NETWORKS, {'address': '192.168.2.45'}), [ADDRESS, '192.168.7.56'])

    def test_parses_compressed_dns_and_preserves_current_service(self):
        records = m.parse_dns(packet())
        service = m.service_record(ADDRESS, records)
        self.assertEqual(service, dict(instance=UUID, host=HOST, port=64000, ip='fe80::1234', txt=['ver=1']))

    def test_incomplete_response_fetches_only_missing_records(self):
        records = m.parse_dns(packet())
        query = Mock(side_effect=[records[1:3], records[3:]])
        self.assertEqual(m.service_record(ADDRESS, records[:1], query)['ip'], 'fe80::1234')
        self.assertEqual(query.call_args_list[0].args, (ADDRESS, [(ALIAS, 33), (ALIAS, 16)]))
        self.assertEqual(query.call_args_list[1].args, (ADDRESS, [(HOST, 1), (HOST, 28)]))

    def test_unrelated_host_address_is_never_advertised(self):
        records = m.parse_dns(packet())
        for record in records[3:]: record['name'] = 'Other-Phone.local.'
        with self.assertRaises(RuntimeError): m.service_record(ADDRESS, records, lambda *args: records[3:])

    def test_ipv4_fallback_must_match_authenticated_phone(self):
        records = [r for r in m.parse_dns(packet()) if r['type'] != 28]
        self.assertEqual(m.service_record(ADDRESS, records)['ip'], ADDRESS)
        records[-1]['value'] = '192.168.7.56'
        with self.assertRaises(RuntimeError): m.service_record(ADDRESS, records)

    def test_goodbye_record_with_zero_ttl_is_not_published(self):
        records = m.parse_dns(packet())
        records[0]['ttl'] = 0
        with self.assertRaises(RuntimeError): m.service_record(ADDRESS, records)

    def test_rejects_truncation_and_compression_cycles(self):
        loop = struct.pack('!6H', 0, 0x8400, 0, 1, 0, 0) + b'\xc0\x0c' + b'\0' * 10
        for data in [b'', packet()[:-1], loop, packet()[:14]]:
            with self.subTest(size=len(data)), self.assertRaises(ValueError): m.parse_dns(data)

    def test_dns_source_must_be_the_verified_peer(self):
        stream = Mock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.recvfrom.return_value = (packet(), ('192.168.7.56', 5353))
        with patch.object(m.socket, 'socket', return_value=stream), self.assertRaises(ValueError):
            m.dns_query(ADDRESS, [(m.SERVICE, 12)])

    def test_read_only_pair_record_uses_validated_device_path(self):
        import plistlib
        with patch.object(Path, 'read_bytes', side_effect=PermissionError), \
             patch.object(m.subprocess, 'check_output', return_value=plistlib.dumps({'DeviceCertificate': b'test'})) as read:
            self.assertEqual(m.pair_record(UDID)['DeviceCertificate'], b'test')
        self.assertEqual(read.call_args.args[0], ['/usr/bin/sudo', '-n', '/bin/cat', '/var/db/lockdown/' + UDID + '.plist'])
        for invalid in ['../other', 'a' * 23, '--' + 'z' * 24]:
            with self.assertRaises(ValueError): m.pair_record(invalid)

    def test_transient_failure_keeps_only_recent_endpoint_on_same_interface(self):
        child = Mock(); child.poll.return_value = None
        previous = dict(address=ADDRESS, interface='en4', verified=100)
        self.assertTrue(m.retain_endpoint(previous, NETWORKS, child, 130))
        self.assertFalse(m.retain_endpoint(previous, NETWORKS, child, 160))
        self.assertFalse(m.retain_endpoint(previous, [], child, 130))
        self.assertFalse(m.retain_endpoint(previous, [dict(NETWORKS[0], interface='en0')], child, 130))
        self.assertFalse(m.retain_endpoint(previous, NETWORKS, child, 99))
        child.poll.return_value = 1
        self.assertFalse(m.retain_endpoint(previous, NETWORKS, child, 130))


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    def client(self, udid=UDID, certificate=b'trusted-leaf', paired=True):
        tls = Mock(); tls.getpeercert.return_value = certificate
        writer = Mock(); writer.get_extra_info.return_value = tls
        return SimpleNamespace(paired=paired, udid=udid, service=SimpleNamespace(writer=writer), close=AsyncMock())

    async def test_exact_certificate_and_identity_are_required_without_pairing(self):
        record = {'DeviceCertificate': ssl.DER_cert_to_PEM_cert(b'trusted-leaf').encode()}
        for client, expected in [(self.client(), True), (self.client(udid='b' * 24), False),
                                 (self.client(certificate=b'another-leaf'), False), (self.client(paired=False), False)]:
            connector = AsyncMock(return_value=client)
            self.assertEqual(await m.verify(ADDRESS, UDID, record, connector), expected)
            connector.assert_awaited_once_with(ADDRESS, identifier=UDID, autopair=False, pair_record=record)
            client.close.assert_awaited_once()

    async def test_failed_trust_does_not_attempt_new_pairing(self):
        connector = AsyncMock(side_effect=RuntimeError('InvalidHostID'))
        self.assertFalse(await m.verify(ADDRESS, UDID, {}, connector))
        self.assertEqual(connector.await_count, 1)
        self.assertFalse(connector.call_args.kwargs['autopair'])

    async def test_dhcp_move_finds_correct_phone_despite_another_iphone(self):
        async def verify(address, *args):
            if address.endswith('.56'): await asyncio.sleep(.02)
            return address == ADDRESS
        with patch.object(m, 'candidate_addresses', return_value=['192.168.7.56']), \
             patch.object(m, 'scan_addresses', return_value=['192.168.7.56', ADDRESS]), \
             patch.object(m, 'port_open', side_effect=lambda a: not a.endswith('.54')), \
             patch.object(m, 'verify', side_effect=verify) as checked:
            actual = await m.find_phone(UDID, {}, NETWORKS, {'address': '192.168.7.54'})
        self.assertEqual(actual, ADDRESS)
        self.assertIn(ADDRESS, [c.args[0] for c in checked.call_args_list])

    async def test_no_reachable_trusted_device_is_a_failure(self):
        with patch.object(m, 'candidate_addresses', return_value=[ADDRESS]), \
             patch.object(m, 'scan_addresses', return_value=[ADDRESS]), \
             patch.object(m, 'port_open', return_value=True), patch.object(m, 'verify', return_value=False):
            with self.assertRaises(RuntimeError): await m.find_phone(UDID, {}, NETWORKS, {})


if __name__ == '__main__': unittest.main()
