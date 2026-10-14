import asyncio
import base64
import contextlib
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from engine import Engine,UserError
from wifi_discovery import discover_paired,paired_devices
from wifi_unicast import authenticated_identifier
from pymobiledevice3.remote.siphash import compute_auth_tag


def record(serial='synthetic-phone',key=b'0123456789abcdef'):
    return (serial,None,{'peer_alt_irk':key})


def advert(key=b'0123456789abcdef',hosts=('192.0.2.15',),port=12345):
    identifier='synthetic-announcement'
    return SimpleNamespace(properties={'identifier':identifier,'authTag':base64.b64encode(compute_auth_tag(key,identifier)).decode()},
                           port=port,addresses=[SimpleNamespace(full_ip=h) for h in hosts])


class AuthenticatedDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_actual_auth_tag_matches_existing_pair(self):
        self.assertEqual(authenticated_identifier(advert().properties,[record()]),'synthetic-phone')

    def test_unpaired_and_forged_adverts_are_rejected(self):
        wrong=advert(key=b'fedcba9876543210')
        self.assertEqual(paired_devices([wrong],[record()]),[])
        wrong.properties['authTag']='malformed!'
        self.assertEqual(paired_devices([wrong],[record()]),[])

    def test_missing_auth_and_stale_records_are_rejected(self):
        a=advert();a.properties.pop('authTag')
        self.assertEqual(paired_devices([a],[record()]),[])
        self.assertEqual(paired_devices([advert()],[('old',None,{})]),[])

    def test_ambiguous_local_identity_is_rejected(self):
        self.assertIsNone(authenticated_identifier(advert().properties,[record('one'),record('two')]))

    def test_duplicate_announcements_do_not_become_multiple_phones(self):
        a=advert(hosts=('192.0.2.15','192.0.2.15','fe80::1%20'))
        devices=paired_devices([a,a],[record()])
        self.assertEqual(len(devices),1)
        self.assertEqual(devices[0].endpoints,(('192.0.2.15',12345),('fe80::1%20',12345)))

    def test_ports_and_local_addresses_are_validated(self):
        for port in ('bad',None,0,65536):
            self.assertEqual(paired_devices([advert(port=port)],[record()]),[])
        hosts=('127.0.0.1','::1','224.0.0.251','0.0.0.0','8.8.8.8','invalid')
        self.assertEqual(paired_devices([advert(hosts=hosts)],[record()]),[])

    def test_multiple_paired_phones_remain_distinct(self):
        other_key=b'fedcba9876543210'
        devices=paired_devices([advert(),advert(key=other_key,hosts=('192.0.2.16',))],
                               [record(),record('second',other_key)])
        self.assertEqual({d.serial for d in devices},{'synthetic-phone','second'})

    def test_endpoint_attempts_are_bounded(self):
        devices=paired_devices([advert(hosts=tuple('192.0.2.'+str(i) for i in range(1,10)))],[record()])
        self.assertEqual(len(devices[0].endpoints),3)

    async def test_no_pairs_skips_browse(self):
        with patch('pymobiledevice3.pair_records.iter_remote_pair_records_by_identifier',return_value=iter([])), \
             patch('pymobiledevice3.bonjour.browse_remotepairing',new_callable=AsyncMock) as browser:
            self.assertEqual(await discover_paired(),[])
            browser.assert_not_awaited()

    async def test_browse_uses_four_seconds_and_authenticates_before_return(self):
        with patch('pymobiledevice3.pair_records.iter_remote_pair_records_by_identifier',return_value=iter([record()])), \
             patch('pymobiledevice3.bonjour.browse_remotepairing',new_callable=AsyncMock,return_value=[advert()]) as browser:
            self.assertEqual(len(await discover_paired()),1)
            browser.assert_awaited_once_with(timeout=4)


class WirelessChannelTests(unittest.IsolatedAsyncioTestCase):
    def engine(self,manual=False):
        e=Engine();e.mode='Network';e.wifi_host='192.0.2.15' if manual else ''
        e.devices=AsyncMock(return_value=[SimpleNamespace(serial='synthetic-phone',connection_type='Network')])
        e.all_devices=AsyncMock(return_value=[])
        class Lockdown:
            all_values={'DeviceName':'synthetic'};product_version='26.6.2'
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def get_developer_mode_status(self):return True
        e.lockdown=AsyncMock(return_value=Lockdown())
        return e

    async def events(self,e):
        with contextlib.redirect_stdout(io.StringIO()) as output:await e.probe()
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def working_channel(self,e):
        async def open_channel(serial):
            e.stack=SimpleNamespace(aclose=AsyncMock());e.serial=serial
            e.tunnel=SimpleNamespace(rsd=object());e.location=SimpleNamespace(dtx=SimpleNamespace(_closed=False))
        return AsyncMock(side_effect=open_channel)

    async def test_empty_network_inventory_uses_fallback(self):
        e=Engine();e.mode='Network';e.all_devices=AsyncMock(return_value=[])
        candidate=SimpleNamespace(serial='synthetic-phone',endpoints=(('192.0.2.15',12345),))
        with patch('engine.discover_paired',new_callable=AsyncMock,return_value=[candidate]) as fallback:
            self.assertEqual((await e.devices())[0].serial,'synthetic-phone')
            self.assertEqual(e.wifi_candidates['synthetic-phone'],candidate.endpoints)
            self.assertEqual(e.discovery,'mdns');fallback.assert_awaited_once()

    async def test_usbmux_network_devices_keep_priority(self):
        e=Engine();e.mode='Network';d=SimpleNamespace(serial='synthetic-phone',connection_type='Network')
        e.all_devices=AsyncMock(return_value=[d])
        with patch('engine.discover_paired',new_callable=AsyncMock) as fallback:
            self.assertEqual(await e.devices(),[d]);fallback.assert_not_awaited()

    async def test_usb_never_browses_wireless_services(self):
        e=Engine();e.all_devices=AsyncMock(return_value=[])
        with patch('engine.discover_paired',new_callable=AsyncMock) as fallback:
            self.assertEqual(await e.devices(),[]);fallback.assert_not_awaited()

    async def test_auto_and_manual_failed_channel_are_not_usable(self):
        for manual in (False,True):
            e=self.engine(manual);e.open_channel=AsyncMock(side_effect=ConnectionError())
            events=await self.events(e)
            self.assertFalse(events[0]['usable']);self.assertIsNone(e.location)
            e.open_channel.assert_awaited_once()

    async def test_channel_return_without_resources_cannot_report_usable(self):
        e=self.engine();e.open_channel=AsyncMock()
        self.assertFalse((await self.events(e))[0]['usable'])

    async def test_auto_and_manual_open_complete_channel_before_usable(self):
        for manual in (False,True):
            e=self.engine(manual);e.open_channel=self.working_channel(e)
            self.assertTrue((await self.events(e))[0]['usable'])
            e.open_channel.assert_awaited_once_with('synthetic-phone')

    async def test_multiple_phones_never_open_a_channel(self):
        e=self.engine();e.devices.return_value.append(SimpleNamespace(serial='second'))
        e.open_channel=AsyncMock()
        self.assertEqual((await self.events(e))[0]['connection'],'multiple')
        e.open_channel.assert_not_awaited()

    async def test_target_still_on_usb_never_opens_a_channel(self):
        e=self.engine();e.all_devices.return_value=[SimpleNamespace(serial='synthetic-phone',connection_type='USB')]
        e.open_channel=AsyncMock()
        self.assertFalse((await self.events(e))[0]['usable']);e.open_channel.assert_not_awaited()

    async def test_second_endpoint_can_work_after_first_fails(self):
        e=self.engine();e.wifi_candidates={'synthetic-phone':(('192.0.2.14',12345),('192.0.2.15',12345))}
        attempts=[];good=self.working_channel(e)
        async def channel(serial):
            attempts.append(e.wifi_endpoint)
            if len(attempts)==1:raise ConnectionError()
            await good(serial)
        e.open_channel=channel
        self.assertTrue((await self.events(e))[0]['usable'])
        self.assertEqual(attempts,['192.0.2.14','192.0.2.15'])
        self.assertEqual(e.wifi_endpoint,'192.0.2.15')

    async def test_cached_session_health_failure_closes_and_reports_loss(self):
        e=self.engine();await self.working_channel(e)('synthetic-phone');e.active=True
        stack=e.stack;e.lockdown=AsyncMock(side_effect=ConnectionError())
        events=await self.events(e)
        self.assertFalse(events[0]['usable']);self.assertFalse(events[0]['active'])
        self.assertEqual(events[1]['reason'],'wifi_disconnected')
        stack.aclose.assert_awaited_once();e.devices.assert_not_awaited()

    async def test_closed_dvt_cannot_report_usable(self):
        e=self.engine();await self.working_channel(e)('synthetic-phone');e.location.dtx._closed=True
        self.assertFalse((await self.events(e))[0]['usable'])
        e.lockdown.assert_not_awaited()

    async def test_direct_lockdown_never_pairs_and_checks_identity(self):
        from pymobiledevice3 import common
        e=Engine();e.mode='Network';e.wifi_endpoint='192.0.2.15'
        ld=SimpleNamespace(paired=True,udid='wrong',close=AsyncMock())
        with patch('pymobiledevice3.pair_records.get_preferred_pair_record',new_callable=AsyncMock,return_value={'synthetic':'record'}), \
             patch('pymobiledevice3.lockdown.create_using_tcp',new_callable=AsyncMock,return_value=ld) as create:
            with self.assertRaises(UserError):await e.lockdown('synthetic-phone')
            self.assertFalse(create.call_args.kwargs['autopair'])
            ld.close.assert_awaited_once()

    async def test_usbmux_network_lockdown_never_autopairs(self):
        e=Engine();e.mode='Network'
        with patch('pymobiledevice3.lockdown.create_using_usbmux',new_callable=AsyncMock) as create:
            await e.lockdown('synthetic-phone')
            self.assertFalse(create.call_args.kwargs['autopair'])
            self.assertEqual(create.call_args.kwargs['connection_type'],'Network')


if __name__=='__main__':unittest.main()
