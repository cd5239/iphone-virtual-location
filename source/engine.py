"""Private stdin/stdout worker; no HTTP listener, UI automation, or third-party app launch."""
import argparse
import asyncio
import contextlib
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

from coordinates import to_wgs
from wifi_unicast import WirelessDiscoveryError, discover
from wifi_discovery import discover_paired

request_id=None
request_command=None
def emit(event, message='', **values):
    print(json.dumps(dict(event=event,message=message,request_id=request_id,command=request_command,**values),ensure_ascii=False),flush=True)

class UserError(Exception): pass

class Engine:
    def __init__(self):
        self.stack=None
        self.location=None
        self.tunnel=None
        self.serial=None
        self.active=False
        self.mode='USB'
        self.wifi_host=''
        self.wifi_port=None
        self.wifi_endpoint=''
        self.wifi_candidates={}
        self.discovery='usbmux'
        self.device_name='iPhone'
        self.product_version=''

    async def all_devices(self):
        from pymobiledevice3.usbmux import list_devices
        return await list_devices()

    async def devices(self):
        self.wifi_candidates={}
        self.wifi_endpoint=''
        self.wifi_port=None
        if self.mode=='Network' and self.wifi_host:
            try:
                serial,self.wifi_port=await discover(self.wifi_host)
            except WirelessDiscoveryError as ex:
                raise UserError(str(ex)) from ex
            self.wifi_candidates[serial]=((self.wifi_host,self.wifi_port),)
            self.discovery='manual'
            return [SimpleNamespace(serial=serial,connection_type='Network')]
        devices=[d for d in await self.all_devices() if d.connection_type==self.mode]
        self.discovery='usbmux'
        if self.mode=='Network' and not devices:
            devices=await discover_paired()
            self.wifi_candidates={d.serial:d.endpoints for d in devices}
            self.discovery='mdns'
        return devices

    async def set_mode(self,mode,wifi_host=''):
        if mode not in ('USB','Network'):raise UserError('连接方式无效。')
        wifi_host=(wifi_host or '').strip()
        if mode!=self.mode or wifi_host!=self.wifi_host:
            await self.close()
            self.mode=mode
            self.wifi_host=wifi_host
            self.wifi_port=None
            self.wifi_endpoint=''
            self.wifi_candidates={}

    async def cable_present(self,serial):
        return any(d.serial==serial and d.connection_type=='USB' for d in await self.all_devices())

    async def select(self):
        devices=await self.devices()
        if not devices: raise UserError('未发现局域网中的已配对 iPhone。请先用 USB 完成无线准备，拔线后确认手机与电脑在同一局域网。' if self.mode=='Network' else '没有检测到 USB iPhone。请连接数据线、解锁手机，并确认已信任此电脑。')
        if len(devices)!=1: raise UserError('检测到多台同类设备。为避免改错手机，请只保留目标手机在线。')
        if self.mode=='Network' and await self.cable_present(devices[0].serial):
            raise UserError('已发现无线设备，但同一手机仍连接 USB。请拔线后重试，以验证实际走 Wi-Fi。')
        return devices[0].serial

    async def lockdown(self,serial):
        if self.mode=='Network' and self.wifi_endpoint:
            from pymobiledevice3 import common
            from pymobiledevice3.lockdown import create_using_tcp
            from pymobiledevice3.pair_records import get_preferred_pair_record
            pair=await get_preferred_pair_record(serial,common._HOMEFOLDER)
            if pair is None:raise UserError('找不到这台手机的有线信任记录，请重新插线并确认信任。')
            ld=await create_using_tcp(self.wifi_endpoint,identifier=serial,pair_record=pair,
                                      autopair=False,pair_timeout=5,label='iPhone Direct Location')
            if not ld.paired or ld.udid!=serial:
                await ld.close()
                raise UserError('无线地址对应的手机与准备时配对的手机不一致。')
            return ld
        from pymobiledevice3.lockdown import create_using_usbmux
        return await create_using_usbmux(serial=serial,connection_type=self.mode,
                                        autopair=self.mode=='USB',pair_timeout=10,label='iPhone Direct Location')

    def channel_ready(self):
        return (self.stack is not None and self.tunnel is not None and self.tunnel.rsd is not None
                and self.location is not None
                and not getattr(getattr(self.location,'dtx',None),'_closed',False))

    async def open_network_channel(self,serial):
        # Selection already rejected multiple phones and a target still on USB.
        # Every attempt uses an endpoint from the same authenticated announcement.
        endpoints=self.wifi_candidates.get(serial,((None,None),))
        last_error=None
        async with asyncio.timeout(12):
            for host,port in endpoints:
                self.wifi_endpoint=host or ''
                self.wifi_port=port
                try:
                    async with asyncio.timeout(4):
                        async with await self.lockdown(serial) as ld:
                            if int(ld.product_version.split('.')[0])<17:
                                raise UserError('此直连版本面向 iOS 17.4 及以上系统。')
                            if not await ld.get_developer_mode_status():
                                raise UserError('请在 iPhone「设置 → 隐私与安全性 → 开发者模式」中开启开发者模式后重试。')
                            name=ld.all_values.get('DeviceName','iPhone')
                            version=ld.product_version
                        await self.open_channel(serial)
                        if not self.channel_ready():raise UserError('无线定位通道尚未就绪。')
                        self.device_name,self.product_version=name,version
                        return
                except Exception as ex:
                    last_error=ex
                    await self.close(clear=False)
        if last_error is not None:raise last_error
        raise UserError('没有可用的已配对无线连接地址。')

    async def enable_wifi(self):
        from pymobiledevice3.usbmux import list_devices
        connected=[d for d in await list_devices() if d.connection_type=='USB']
        if len(connected)!=1:raise UserError('无线准备需要且只需连接一台 USB iPhone，请先插线并解锁。')
        from pymobiledevice3.lockdown import create_using_usbmux
        emit('status','正在通过 USB 开启已配对手机的 Wi-Fi 连接…',stage='wifi_setup')
        async with await create_using_usbmux(serial=connected[0].serial,connection_type='USB',pair_timeout=10,label='iPhone Direct Location') as ld:
            await ld.set_enable_wifi_connections(True)
            if not await ld.get_enable_wifi_connections():raise UserError('手机未确认开启 Wi-Fi 连接，请检查手机连接设置。')
            # Prepare a RemotePairing record while the trusted USB lockdown
            # connection is available. The Wi-Fi userspace tunnel can use this
            # record if CoreDeviceProxy is unavailable over the network.
            from pymobiledevice3.remote.tunnel_service import RemotePairingLockdownService
            from pymobiledevice3.exceptions import RemotePairingCompletedError
            service=await RemotePairingLockdownService.create(ld)
            try:
                with contextlib.suppress(RemotePairingCompletedError):
                    await service.connect(autopair=True)
            finally:
                await service.close()
        emit('wifi_enabled','有线准备完成，但尚未验证无线隧道。请拔线、选择无线方式并检测；若自动发现失败，可填写手机 Wi-Fi 的 IP 地址。')

    async def probe(self):
        if self.mode=='Network' and self.stack is not None:
            was_active=self.active
            try:
                if not self.channel_ready():raise ConnectionError('wireless channel closed')
                if await self.cable_present(self.serial):raise UserError('手机已插上 USB，请拔线后验证 Wi-Fi。')
                # Fresh lockdown validation checks reachability/trust; local RSD
                # references alone cannot prove that an idle phone is online.
                async with await self.lockdown(self.serial):pass
                emit('device',f'{self.device_name}  ·  iOS {self.product_version} · Wi-Fi',
                     connection='connected',transport='Network',usable=True,active=self.active,discovery=self.discovery)
            except Exception as ex:
                await self.close(clear=False)
                emit('device',friendly(ex,self.mode),connection='disconnected',transport='Network',usable=False,active=False)
                if was_active:emit('session_lost','手机 Wi-Fi 连接已断开，定位会话已结束。',reason='wifi_disconnected')
            return
        try:
            ds=await self.devices()
        except (UserError,WirelessDiscoveryError) as ex:
            lost=self.active
            await self.close(clear=False)
            emit('device',str(ex),connection='disconnected',transport=self.mode,usable=False,active=False)
            if lost:emit('session_lost','手机 Wi-Fi 连接已断开，定位会话已结束。',reason='wifi_disconnected')
            return
        lost=None
        if self.active and self.serial not in [d.serial for d in ds]:
            await self.close(clear=False)
            lost='usb_disconnected'
        elif self.active and (self.tunnel is None or self.tunnel.rsd is None):
            await self.close(clear=False)
            lost='session_lost'
        if len(ds)!=1:
            missing='未发现局域网中的已配对手机。请先有线准备，拔线后确认两端在同一局域网。' if self.mode=='Network' else '未连接手机，请插入 USB 数据线。'
            emit('device',missing if not ds else '检测到多台设备，请只连接目标手机。',connection='disconnected' if not ds else 'multiple',transport=self.mode,usable=False,active=False)
        else:
            try:
                if self.mode=='Network' and await self.cable_present(ds[0].serial):
                    raise UserError('已发现无线设备，但手机仍插着 USB。请拔线后重新检测。')
                if self.mode=='Network':
                    await self.open_network_channel(ds[0].serial)
                else:
                    async with await self.lockdown(ds[0].serial) as ld:
                        self.device_name=ld.all_values.get('DeviceName','iPhone')
                        self.product_version=ld.product_version
                emit('device',f'{self.device_name}  ·  iOS {self.product_version} · {"Wi-Fi" if self.mode=="Network" else "USB"}',connection='connected',transport=self.mode,usable=True,active=self.active,discovery=self.discovery)
            except Exception as ex:
                if self.mode=='Network':await self.close(clear=False)
                emit('device',('Wi-Fi 已发现，但尚未完成定位通道验证。' if self.mode=='Network' else 'USB 已连接，但尚未完成通信。')+friendly(ex,self.mode),connection='connected',transport=self.mode,usable=False,active=self.active)
        if lost:
            emit('session_lost',('手机 Wi-Fi 连接已断开，定位会话已结束。' if self.mode=='Network' else '手机 USB 已断开，定位会话已结束。') if lost=='usb_disconnected' else '定位会话已中断，请重新点击修改定位。',reason=lost)

    async def open_channel(self,serial):
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
        stack=contextlib.AsyncExitStack()
        try:
            tunnel=UserspaceRsdTunnel(serial=serial,autopair=False,remotepairing_fallback=self.mode=='Network')
            if self.mode=='Network' and self.wifi_endpoint:
                # pymobiledevice3 11.17.0 selects its tunnel provider through this
                # module-level helper. Redirect only the single aopen call; the
                # provider remains owned by UserspaceRsdTunnel's exit stack.
                import pymobiledevice3.remote.userspace_tunnel as tunnel_module
                from pymobiledevice3.remote.tunnel_service import create_core_device_tunnel_service_using_remotepairing
                original=tunnel_module._create_no_root_tunnel_provider
                async def direct_provider(selected,autopair,fallback):
                    if selected!=serial:raise UserError('无线隧道手机标识不匹配。')
                    service=await create_core_device_tunnel_service_using_remotepairing(
                        serial,self.wifi_endpoint,self.wifi_port,autopair=False)
                    return service,None
                tunnel_module._create_no_root_tunnel_provider=direct_provider
                try:rsd=await stack.enter_async_context(tunnel)
                finally:tunnel_module._create_no_root_tunnel_provider=original
            else:
                rsd=await stack.enter_async_context(tunnel)
            dvt=await stack.enter_async_context(DvtProvider(rsd))
            location=await stack.enter_async_context(LocationSimulation(dvt))
        except BaseException:
            await stack.aclose()
            raise
        self.stack,self.tunnel,self.location,self.serial=stack,tunnel,location,serial

    async def ensure(self):
        if self.channel_ready():return
        serial=await self.select()
        await self.close(clear=False)
        emit('status','正在通过 '+('Wi-Fi' if self.mode=='Network' else 'USB')+' 建立手机定位连接…')
        if self.mode=='Network':
            await self.open_network_channel(serial)
            return
        async with await self.lockdown(serial) as ld:
            if int(ld.product_version.split('.')[0])<17:raise UserError('此直连版本面向 iOS 17.4 及以上系统。')
            if not await ld.get_developer_mode_status():raise UserError('请在 iPhone「设置 → 隐私与安全性 → 开发者模式」中手动开启，按提示重启并确认后重试。')
        from pymobiledevice3.exceptions import InvalidServiceError
        try:
            await self.open_channel(serial)
        except InvalidServiceError:
            emit('status','手机需初始化开发者组件，首次可能需要联网下载。请保持连接…')
            from pymobiledevice3.services.mobile_image_mounter import MobileImageMounterService,auto_mount
            from pymobiledevice3.exceptions import AlreadyMountedError
            async with await self.lockdown(serial) as ld:
                async with MobileImageMounterService(ld) as mounter:
                    mounted=await mounter.is_image_mounted('Personalized')
                if not mounted:
                    with contextlib.suppress(AlreadyMountedError):await auto_mount(ld)
            await self.open_channel(serial)

    async def apply(self,request):
        emit('status','正在检查地点和手机连接…',stage='checking')
        lon,lat=to_wgs(request.get('longitude'),request.get('latitude'),request.get('source','WGS84'))
        await self.ensure()
        emit('status','正在向手机发送定位指令，等待手机确认…',stage='sending')
        await self.location.set(lat,lon)
        self.active=True
        emit('applied','手机定位服务已接受修改，正在保持连接。可关闭窗口留在托盘；请在手机地图中确认位置。',longitude=lon,latitude=lat)

    async def clear(self):
        await self.ensure()
        emit('status','正在停止手机的模拟定位，请保持连接…',stage='clearing')
        await self.location.clear()
        # This selector has no reply. Keep the userspace transport alive instead
        # of tearing it down immediately after enqueueing a fire-and-forget send.
        emit('status','停止指令已发出，正在保持连接并补发确认步骤…',stage='settling')
        await asyncio.sleep(3)
        await self.location.clear()
        await asyncio.sleep(2)
        self.active=False
        await self.close(clear=False)
        emit('restored','已两次发送停止模拟指令并保持连接等待，定位会话已结束。此接口不返回真实 GPS，尚不能确认实际位置。请打开手机地图，点击当前位置；若仍未恢复，重开地图后重试。')

    async def close(self,clear=True):
        stack,self.stack=self.stack,None
        location,self.location=self.location,None
        was_active,self.active=self.active,False
        self.tunnel=None
        self.serial=None
        try:
            if clear and was_active and location is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(location.clear(),3)
                    await asyncio.sleep(2)
        finally:
            if stack is not None:
                with contextlib.suppress(Exception):await asyncio.wait_for(stack.aclose(),5)

def friendly(error,transport='USB'):
    kind=type(error).__name__
    if isinstance(error,UserError):return str(error)
    if isinstance(error,(ValueError,TypeError)):return '地点参数无效，请检查经纬度和坐标来源。'
    if isinstance(error,TimeoutError):return ('无线连接超时，请解锁手机并确认两端 Wi-Fi 可互访；也可填写手机当前 IP 后重试。' if transport=='Network' else '连接超时。请解锁手机、重新插拔数据线后重试；若正在首次下载组件，请确认网络可用。')
    if any(s in kind for s in ['Pair','Password','Locked','Trust']):return '手机尚未信任此电脑或屏幕已锁定。请解锁并在手机上确认信任，再重试。'
    if any(s in kind for s in ['Connection','NoDevice','BrokenPipe','NotConnected']):return ('无线连接已中断，请解锁手机、检查 Wi-Fi 和当前 IP 后重新检测。' if transport=='Network' else '手机连接已中断，请重新插拔数据线并解锁后重试。')
    if 'DeveloperMode' in kind:return '请在手机中手动开启开发者模式，重启并确认后重试。'
    return f'本次操作未完成（{kind}）。请重新连接手机后重试。'

async def serve():
    global request_id,request_command
    engine=Engine()
    emit('ready')
    try:
        while True:
            line=await asyncio.to_thread(sys.stdin.readline)
            if not line:break
            command={}
            try:
                parsed=json.loads(line.lstrip('\ufeff'))
                if not isinstance(parsed,dict):raise UserError('操作请求格式不正确。')
                command=parsed
                name=command.get('command')
                request_id=command.get('request_id')
                request_command=name
                if name=='shutdown':break
                if name!='enable_wifi':await engine.set_mode(command.get('mode','USB'),command.get('wifi_host',''))
                if name=='probe':await asyncio.wait_for(engine.probe(),20)
                elif name=='apply':await asyncio.wait_for(engine.apply(command),240)
                elif name=='clear':await asyncio.wait_for(engine.clear(),90)
                elif name=='enable_wifi':await asyncio.wait_for(engine.enable_wifi(),90)
                else:raise UserError('未知操作。')
            except Exception as ex:
                # Drop failed sessions so a subsequent click creates fresh connections.
                if command.get('command')!='probe':await engine.close()
                elif engine.mode=='Network':await engine.close(clear=False)
                emit('error',friendly(ex,engine.mode),error_type=type(ex).__name__,session_ended=command.get('command')!='probe')
    finally:
        await engine.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state-dir',type=Path,required=True)
    args=parser.parse_args()
    if sys.stdout:sys.stdout.reconfigure(encoding='utf-8')
    if sys.stdin:sys.stdin.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.CRITICAL)
    import pymobiledevice3.common as common
    # Library 11.17.0 has no public cache-path environment variable. Override its one
    # cache root BEFORE importing device services; do not touch the user's home dir.
    common._HOMEFOLDER=args.state_dir.resolve()
    common._HOMEFOLDER.mkdir(parents=True,exist_ok=True)
    asyncio.run(serve())

if __name__=='__main__':main()
