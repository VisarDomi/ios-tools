"""Inspect the paired Watch without attaching to Apple's shared RSD session.

USB/network lockdown and the existing authenticated LAN-discovery cache use the
same saved phone trust. Nothing here pairs a device or changes its preferences.
"""
import asyncio
from contextlib import asynccontextmanager
import hmac
import importlib.machinery
import importlib.util
from pathlib import Path
import ssl


def validate_phone(client, serial, record=None):
    if not client.paired or client.udid != serial:
        raise ConnectionError('The configured paired iPhone did not authenticate.')
    if record is not None:
        certificate = record['DeviceCertificate']
        if isinstance(certificate, bytes):
            certificate = certificate.decode('ascii')
        expected = ssl.PEM_cert_to_DER_cert(certificate)
        tls = client.service.writer.get_extra_info('ssl_object')
        if tls is None or not hmac.compare_digest(tls.getpeercert(binary_form=True), expected):
            raise ConnectionError('The phone endpoint did not present its saved device certificate.')


def discovery_helper():
    path = Path.home() / 'Developer/ios-tools/native/scripts/phone-discovery'
    loader = importlib.machinery.SourceFileLoader('t3_phone_discovery', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@asynccontextmanager
async def paired_phone(serial, wifi_only=False, progress=lambda _: None):
    from pymobiledevice3.lockdown import create_using_usbmux
    client = None
    try:
        if not wifi_only:
            progress('phone-usbmux-lockdown')
            try:
                client = await asyncio.wait_for(create_using_usbmux(serial=serial, autopair=False), 8)
            except Exception:
                # Absence from usbmux is not absence from the LAN. The existing
                # monitor retains a certificate-authenticated endpoint there.
                pass
        record = None
        if client is None:
            progress('phone-lan-lockdown')
            discovery = discovery_helper()
            state = discovery.read_json(discovery.paths(serial)[0])
            address = state.get('address')
            if state.get('udid') != serial or not discovery.on_link(address, discovery.interfaces()):
                raise ConnectionError('No configured phone endpoint on an attached LAN; no new pairing attempted.')
            record = discovery.pair_record(serial)
            client = await asyncio.wait_for(discovery.single_attempt_tcp(
                address, identifier=serial, autopair=False, pair_record=record), 8)
        validate_phone(client, serial, record)
        progress('phone-authenticated')
        yield client
    finally:
        if client is not None:
            await asyncio.wait_for(client.close(), 3)


class Companion:
    """Own each short control connection; leave Apple's lockdown forward alone."""
    service_name = 'com.apple.companion_proxy'

    def __init__(self, phone):
        self.phone = phone

    async def request(self, command):
        service = await self.phone.start_lockdown_service(self.service_name)
        try:
            result = await asyncio.wait_for(service.send_recv_plist(command), 10)
            if result.get('Error'):
                raise ConnectionError('The paired-phone companion service rejected the request.')
            return result
        finally:
            await asyncio.wait_for(service.close(), 3)

    async def list(self):
        return (await self.request({'Command': 'GetDeviceRegistry'})).get('PairedDevicesArray', [])

    async def get_value(self, udid, key):
        result = await self.request({'Command': 'GetValueFromRegistry', 'GetValueGizmoUDIDKey': udid,
                                     'GetValueKeyKey': key})
        return result.get('RetrievedValueDictionary', {})

    async def start_forwarding_service_port(self, port, service_name=None):
        command = {'Command': 'StartForwardingServicePort', 'GizmoRemotePortNumber': port,
                   'IsServiceLowPriority': False, 'PreferWifi': False}
        if service_name is not None:
            command['ForwardedServiceName'] = service_name
        return (await self.request(command)).get('CompanionProxyServicePort')

    async def stop_forwarding_service_port(self, port):
        return await self.request({'Command': 'StopForwardingServicePort', 'GizmoRemotePortNumber': port})


@asynccontextmanager
async def paired_watch(phone_id, watch_id, wifi_only=False, progress=lambda _: None):
    from pymobiledevice3 import usbmux
    from pymobiledevice3.lockdown import TcpLockdownClient
    async with await usbmux.create_mux() as mux:
        record = await mux.get_pair_record(watch_id)
    if not record:
        raise ConnectionError('No existing native Watch trust record; no new pairing attempted.')
    async with paired_phone(phone_id, wifi_only=wifi_only, progress=progress) as phone:
        proxy = Companion(phone)
        progress('companion-registry')
        if watch_id not in await proxy.list():
            raise ConnectionError('The intended Watch is not paired with this iPhone.')
        ports, owned, connections = {}, [], []
        client = None

        async def connect(port):
            if port not in ports:
                assigned = await proxy.start_forwarding_service_port(port)
                if not assigned:
                    raise ConnectionError('The Watch service could not be forwarded.')
                ports[port] = int(assigned)
                owned.append(port)
            connection = await phone.create_service_connection(ports[port])
            connections.append(connection)
            return connection

        class WatchClient(TcpLockdownClient):
            async def create_service_connection(self, port):
                return await connect(port)

            async def areestablish_connection(self):
                raise ConnectionError('Watch connection changed; retry after it reconnects.')

        try:
            progress('watch-lockdown-listener')
            listener = await phone.start_lockdown_service(proxy.service_name)
            try:
                await listener.send_plist({'Command': 'StartListeningForDevices'})
                while True:
                    event = await asyncio.wait_for(listener.recv_plist(), 10)
                    if event.get('GizmoUDIDKey') == watch_id and event.get('CompanionLockdownProxyPort'):
                        # This listener is Apple's, not ours to stop.
                        ports[62078] = int(event['CompanionLockdownProxyPort'])
                        break
            finally:
                await asyncio.wait_for(listener.close(), 3)
            progress('watch-lockdown-session')
            client = await asyncio.wait_for(WatchClient.create(
                await connect(62078), hostname=getattr(phone, 'hostname', None) or phone.udid,
                port=62078, identifier=watch_id, autopair=False, pair_record=record), 20)
            validate_phone(client, watch_id, record)
            if not client.all_values.get('ProductType', '').startswith('Watch'):
                raise ConnectionError('The expected Watch did not authenticate.')
            progress('watch-authenticated')
            yield client
        finally:
            for connection in reversed(connections):
                try: await asyncio.wait_for(connection.close(), 3)
                except Exception: pass
            if client is not None:
                try: await asyncio.wait_for(client.close(), 3)
                except Exception: pass
            for port in reversed(owned):
                try: await asyncio.wait_for(proxy.stop_forwarding_service_port(port), 5)
                except Exception: pass
