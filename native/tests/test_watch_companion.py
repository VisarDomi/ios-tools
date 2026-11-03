import asyncio
import importlib.util
from pathlib import Path
import ssl
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

spec = importlib.util.spec_from_file_location('watch_companion', Path(__file__).parents[1] / 'watch_companion.py')
companion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(companion)


class CompanionTransportChecks(unittest.IsolatedAsyncioTestCase):
    def client(self, serial='fixture-phone', certificate=b'fixture-certificate'):
        tls = SimpleNamespace(getpeercert=Mock(return_value=certificate))
        return SimpleNamespace(udid=serial, paired=True, close=AsyncMock(),
            service=SimpleNamespace(writer=SimpleNamespace(get_extra_info=Mock(return_value=tls))))

    def discovery(self, client, on_link=True):
        return SimpleNamespace(paths=Mock(return_value=[Path('private-cache')]),
            read_json=Mock(return_value={'udid': 'fixture-phone', 'address': '192.0.2.1'}),
            interfaces=Mock(return_value=['fixture-interface']), on_link=Mock(return_value=on_link),
            pair_record=Mock(return_value={'DeviceCertificate': ssl.DER_cert_to_PEM_cert(b'fixture-certificate')}),
            single_attempt_tcp=AsyncMock(return_value=client))

    def imports(self, create):
        return patch.dict(sys.modules, {'pymobiledevice3.lockdown': SimpleNamespace(create_using_usbmux=create)})

    async def test_usb_uses_saved_trust_and_closes_after_operation_error(self):
        client = self.client()
        create = AsyncMock(return_value=client)
        with self.imports(create), patch.object(companion, 'discovery_helper') as discovery:
            with self.assertRaisesRegex(RuntimeError, 'operation failed'):
                async with companion.paired_phone('fixture-phone'):
                    raise RuntimeError('operation failed')
        create.assert_awaited_once_with(serial='fixture-phone', autopair=False)
        discovery.assert_not_called()
        client.close.assert_awaited_once()

    async def test_wifi_works_without_usbmux_and_pins_saved_device_certificate(self):
        client = self.client()
        create = AsyncMock(side_effect=ConnectionError('not in usbmux'))
        discovery = self.discovery(client)
        with self.imports(create), patch.object(companion, 'discovery_helper', return_value=discovery):
            async with companion.paired_phone('fixture-phone') as result:
                self.assertIs(result, client)
        self.assertFalse(discovery.single_attempt_tcp.call_args.kwargs['autopair'])
        self.assertEqual(discovery.single_attempt_tcp.call_args.args, ('192.0.2.1',))
        client.close.assert_awaited_once()

    async def test_explicit_wifi_never_uses_connected_usb_phone(self):
        client = self.client()
        create = AsyncMock()
        with self.imports(create), patch.object(companion, 'discovery_helper', return_value=self.discovery(client)):
            async with companion.paired_phone('fixture-phone', wifi_only=True):
                pass
        create.assert_not_called()
        client.close.assert_awaited_once()

    async def test_wrong_phone_or_certificate_is_closed_before_any_watch_request(self):
        for client in (self.client(serial='other-phone'), self.client(certificate=b'other-certificate')):
            create = AsyncMock()
            with self.imports(create), patch.object(companion, 'discovery_helper', return_value=self.discovery(client)):
                with self.assertRaises(ConnectionError):
                    async with companion.paired_phone('fixture-phone', wifi_only=True):
                        self.fail('Unauthenticated endpoint escaped to the Watch caller')
            client.close.assert_awaited_once()

    async def test_stale_endpoint_off_attached_lan_is_not_contacted(self):
        discovery = self.discovery(self.client(), on_link=False)
        with self.imports(AsyncMock()), patch.object(companion, 'discovery_helper', return_value=discovery):
            with self.assertRaises(ConnectionError):
                async with companion.paired_phone('fixture-phone', wifi_only=True):
                    self.fail('Off-LAN endpoint accepted')
        discovery.single_attempt_tcp.assert_not_called()

    async def test_control_connection_closed_on_cancellation_and_rejection(self):
        for outcome in (asyncio.CancelledError(), {'Error': 'Unavailable'}):
            service = SimpleNamespace(close=AsyncMock(), send_recv_plist=AsyncMock())
            if isinstance(outcome, BaseException):
                service.send_recv_plist.side_effect = outcome
            else:
                service.send_recv_plist.return_value = outcome
            phone = SimpleNamespace(start_lockdown_service=AsyncMock(return_value=service))
            with self.assertRaises((asyncio.CancelledError, ConnectionError)):
                await companion.Companion(phone).list()
            service.close.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
