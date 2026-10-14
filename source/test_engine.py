import asyncio
import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from coordinates import validate,to_wgs,wgs_to_gcj
from engine import Engine,UserError
import wifi_unicast

class CoordinateTests(unittest.TestCase):
    def test_invalid_never_accepted(self):
        for lon,lat in [(181,0),(0,91),(float('nan'),0),(0,float('inf'))]:
            with self.assertRaises(ValueError):validate(lon,lat)
    def test_wgs_not_converted(self):
        self.assertEqual(to_wgs(-122.03,37.33,'WGS84'),(-122.03,37.33))
    def test_gcj_inverse_roundtrip(self):
        for original in [(104.01,30.8),(116.3,39.9),(121.5,31.2)]:
            converted=to_wgs(*wgs_to_gcj(*original),'GCJ02')
            for a,b in zip(original,converted):self.assertAlmostEqual(a,b,places=7)
    def test_invalid_source(self):
        with self.assertRaises(ValueError):to_wgs(103,30,'UNKNOWN')

class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_ip_discovery_selects_only_paired_phone(self):
        e=Engine();await e.set_mode('Network','192.0.2.15')
        async def found(host):
            self.assertEqual(host,'192.0.2.15')
            return 'phone',12345
        async def inventory():return []
        e.all_devices=inventory
        with patch('engine.discover',side_effect=found):
            self.assertEqual(await e.select(),'phone')
        self.assertEqual(e.wifi_port,12345)
    async def test_manual_ip_probe_requires_working_tunnel(self):
        e=Engine();e.mode='Network';e.wifi_host='192.0.2.15'
        async def devices():return [SimpleNamespace(serial='phone')]
        async def cable(serial):return False
        class Lockdown:
            all_values={'DeviceName':'test'};product_version='26.6.2'
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def get_developer_mode_status(self):return True
        async def lockdown(serial):return Lockdown()
        bad_tunnel=AsyncMock(side_effect=ConnectionError('tunnel failed'))
        e.devices=devices;e.cable_present=cable;e.lockdown=lockdown;e.open_channel=bad_tunnel
        with contextlib.redirect_stdout(io.StringIO()) as output:await e.probe()
        self.assertFalse(json.loads(output.getvalue().splitlines()[0])['usable'])
        bad_tunnel.assert_awaited_once()
    async def test_wireless_selection_excludes_usb_and_requires_unplug(self):
        e=Engine();e.mode='Network'
        both=[SimpleNamespace(serial='phone',connection_type='USB'),SimpleNamespace(serial='phone',connection_type='Network')]
        async def inventory():return both
        e.all_devices=inventory
        with self.assertRaisesRegex(UserError,'拔线'):await e.select()
        both.pop(0)
        self.assertEqual(await e.select(),'phone')
    async def test_wireless_probe_reports_transport(self):
        e=Engine();e.mode='Network'
        async def inventory():return [SimpleNamespace(serial='phone',connection_type='Network')]
        class Lockdown:
            all_values={'DeviceName':'test'};product_version='26.6.2'
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def get_developer_mode_status(self):return True
        async def lockdown(serial):return Lockdown()
        async def channel(serial):
            e.stack=SimpleNamespace(aclose=AsyncMock());e.tunnel=SimpleNamespace(rsd=object());e.location=object();e.serial=serial
        e.all_devices=inventory;e.lockdown=lockdown;e.open_channel=AsyncMock(side_effect=channel)
        with contextlib.redirect_stdout(io.StringIO()) as output:await e.probe()
        result=json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(result['transport'],'Network');self.assertTrue(result['usable'])
        e.open_channel.assert_awaited_once_with('phone')
    async def test_invalid_mode_rejected_without_mutation(self):
        e=Engine()
        with self.assertRaises(UserError):await e.set_mode('Other')
        self.assertEqual(e.mode,'USB')
    async def test_wifi_setup_only_with_one_usb_phone(self):
        e=Engine()
        async def inventory():return [SimpleNamespace(serial='phone',connection_type='Network')]
        with patch('pymobiledevice3.usbmux.list_devices',side_effect=inventory):
            with self.assertRaises(UserError):await e.enable_wifi()
    async def test_wifi_setup_enables_and_prepares_remote_pairing(self):
        calls=[];e=Engine()
        async def inventory():return [SimpleNamespace(serial='phone',connection_type='USB')]
        class Lockdown:
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
            async def set_enable_wifi_connections(self,value):calls.append(('wifi',value))
            async def get_enable_wifi_connections(self):return True
        async def lockdown(**kwargs):
            self.assertEqual(kwargs['connection_type'],'USB')
            return Lockdown()
        class Pairing:
            async def connect(self,autopair):calls.append(('pair',autopair))
            async def close(self):calls.append('close')
        async def pairing_create(lockdown):return Pairing()
        with patch('pymobiledevice3.usbmux.list_devices',side_effect=inventory),patch('pymobiledevice3.lockdown.create_using_usbmux',side_effect=lockdown),patch('pymobiledevice3.remote.tunnel_service.RemotePairingLockdownService.create',side_effect=pairing_create),contextlib.redirect_stdout(io.StringIO()) as output:
            await e.enable_wifi()
        self.assertEqual(calls,[('wifi',True),('pair',True),'close'])
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['event'],'wifi_enabled')
    async def test_restore_keeps_transport_alive_for_no_reply_command(self):
        calls=[];e=Engine();e.active=True
        class Location:
            async def clear(self):calls.append('clear')
        async def ensure():e.location=Location()
        async def settle(seconds):calls.append(('wait',seconds))
        async def close(clear=True):calls.append(('close',clear))
        e.ensure=ensure;e.close=close
        with patch('engine.asyncio.sleep',side_effect=settle),contextlib.redirect_stdout(io.StringIO()) as output:
            await e.clear()
        self.assertEqual(calls,['clear',('wait',3),'clear',('wait',2),('close',False)])
        self.assertFalse(e.active)
        self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['event'],'restored')
    async def test_failed_restore_never_reports_completion(self):
        e=Engine()
        class Location:
            async def clear(self):raise ConnectionError()
        async def ensure():e.location=Location()
        e.ensure=ensure
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(ConnectionError):await e.clear()
        self.assertNotIn('restored',output.getvalue())
    async def test_tunnel_loss_does_not_report_usb_unplug(self):
        e=Engine();e.active=True;e.serial='test';e.tunnel=SimpleNamespace(rsd=None)
        async def devices():return [SimpleNamespace(serial='test')]
        class Lockdown:
            all_values={'DeviceName':'test'};product_version='26.6.2'
            async def __aenter__(self):return self
            async def __aexit__(self,*a):pass
        async def lockdown(serial):return Lockdown()
        e.devices=devices;e.lockdown=lockdown
        with contextlib.redirect_stdout(io.StringIO()) as output:await e.probe()
        events=[json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(events[0]['connection'],'connected')
        self.assertEqual(events[1]['reason'],'session_lost')
        self.assertFalse(e.active)
    async def test_unplug_then_reconnect_emits_updated_state(self):
        e=Engine();e.active=True;e.serial='test'
        async def devices():return []
        e.devices=devices
        with contextlib.redirect_stdout(io.StringIO()) as output:await e.probe()
        events=[json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(events[0]['connection'],'disconnected')
        self.assertFalse(events[0]['usable'])
        self.assertEqual(events[1]['reason'],'usb_disconnected')
    async def test_multiple_devices_rejected(self):
        e=Engine()
        async def devices():return [SimpleNamespace(serial='a'),SimpleNamespace(serial='b')]
        e.devices=devices
        with self.assertRaises(UserError):await e.select()
    async def test_no_device_rejected(self):
        e=Engine()
        async def devices():return []
        e.devices=devices
        with self.assertRaises(UserError):await e.select()
    async def test_bad_coordinates_cannot_open_device(self):
        e=Engine()
        async def ensure():self.fail('Device must not be opened for invalid coordinates')
        e.ensure=ensure
        with self.assertRaises(ValueError):await e.apply(dict(longitude=200,latitude=10,source='WGS84'))
    async def test_latitude_longitude_order(self):
        calls=[];e=Engine()
        class Location:
            async def set(self,lat,lon):calls.append((lat,lon))
        async def ensure():e.location=Location()
        e.ensure=ensure
        with contextlib.redirect_stdout(io.StringIO()):await e.apply(dict(longitude=-122.03,latitude=37.33,source='WGS84'))
        self.assertEqual(calls,[(37.33,-122.03)])
        self.assertTrue(e.active)
    async def test_clear_failure_does_not_skip_resource_cleanup(self):
        calls=[];e=Engine();e.active=True
        class Location:
            async def clear(self):calls.append('clear');raise ConnectionError()
        class Stack:
            async def aclose(self):calls.append('close')
        e.location=Location();e.stack=Stack()
        await e.close()
        self.assertEqual(calls,['clear','close']);self.assertFalse(e.active);self.assertIsNone(e.stack)

class UnicastDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_bad_phone_address(self):
        with self.assertRaises(wifi_unicast.WirelessDiscoveryError):
            await wifi_unicast.discover('not-an-ip')
    async def test_uses_only_authenticated_remote_pairing_answer(self):
        from pymobiledevice3.bonjour import REMOTEPAIRING_SERVICE_NAME,QTYPE_PTR,QTYPE_SRV,QTYPE_TXT
        target='test.'+REMOTEPAIRING_SERVICE_NAME
        records=[{'type':QTYPE_PTR,'name':REMOTEPAIRING_SERVICE_NAME,'ptrdname':target},
                 {'type':QTYPE_SRV,'name':target,'port':12345},
                 {'type':QTYPE_TXT,'name':target,'txt':{'identifier':'advertised','authTag':'tag'}}]
        from pymobiledevice3.remote.tunnel_service import PEER_ALT_IRK_KEY
        pairs=[('trusted',None,{PEER_ALT_IRK_KEY:b'key'})]
        with patch('pymobiledevice3.pair_records.iter_remote_pair_records_by_identifier',return_value=iter(pairs)),patch('pymobiledevice3.remote.tunnel_service.validate_auth_tag',return_value=True):
            self.assertEqual(wifi_unicast._match(records),('trusted',12345))
        with patch('pymobiledevice3.pair_records.iter_remote_pair_records_by_identifier',return_value=iter(pairs)),patch('pymobiledevice3.remote.tunnel_service.validate_auth_tag',return_value=False):
            with self.assertRaises(wifi_unicast.WirelessDiscoveryError):wifi_unicast._match(records)

if __name__=='__main__':unittest.main()
