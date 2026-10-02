#!/usr/bin/env python3
"""Inspect one installed app's WebKit page on the paired iPhone, from the Mac.

Run with the Mac's inspector Python (`inspector/.venv`, see README.md):
  app-inspector.py --bundle com.visar.AsuraReader.paid --url-prefix asura://app/ \
    --snapshot-file <repo>/apps/ios/scripts/inspector-snapshot.js [--evaluate-file probe.js]
Each repository keeps its own page snapshot. Cookie mode prints flags and expiry only, never values.
"""
import argparse, asyncio, base64, json, logging
from pathlib import Path
from urllib.parse import urlparse
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.remote.native_tunnel import establish_native_rsd
from pymobiledevice3.services.webinspector import WebinspectorService

DEFAULT_SNAPSHOT = """JSON.stringify({url: location.href, ready: document.readyState, visible: document.visibilityState,
    title: document.title, scrollY, history: history.length})"""


def find_cookies(obj):
    if isinstance(obj, dict):
        if 'cookies' in obj: return obj['cookies']
        for key, value in obj.items():
            if key == 'message' and isinstance(value, str):
                try: value = json.loads(value)
                except ValueError: continue
            found = find_cookies(value)
            if found is not None: return found
    return None


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bundle', action='append', required=True, help='App bundle ID (repeatable)')
    parser.add_argument('--url-prefix', default='', help="Only pages whose URL starts with this, e.g. ytb://app/")
    parser.add_argument('--snapshot-file', help="The repository's page snapshot expression (JSON.stringify(...))")
    parser.add_argument('--evaluate-file', help='Extra JavaScript to evaluate once; its value is printed as RESULT')
    parser.add_argument('--after', type=float, help='Seconds to wait (max 30) before a second AFTER snapshot')
    parser.add_argument('--console', action='store_true', help='Print console messages while connected')
    parser.add_argument('--screenshot', help='Save a viewport screenshot to this path')
    parser.add_argument('--cookies', nargs='+', metavar='NAME', help="Print only these cookies' flags and expiry, never values")
    parser.add_argument('--rsd', action='store_true', help='Connect through the RemoteXPC tunnel instead of USB (usbmux)')
    parser.add_argument('--device', help='Phone UDID; defaults to "device" in ios-tools.local.json')
    args = parser.parse_args()
    device = args.device or json.loads((Path(__file__).resolve().parents[1] / 'ios-tools.local.json').read_text())['device']
    snapshot = Path(args.snapshot_file).read_text() if args.snapshot_file else DEFAULT_SNAPSHOT
    logging.disable(logging.CRITICAL)
    lockdown = await (establish_native_rsd(serial=device) if args.rsd else create_using_usbmux(serial=device))
    inspector = WebinspectorService(lockdown=lockdown)
    try:
        await asyncio.wait_for(inspector.connect(), 15)
        pages = [p for p in await inspector.get_open_application_pages(timeout=5)
                 if p.application.bundle in args.bundle and p.page.web_url.startswith(args.url_prefix)]
        print('PAGES', json.dumps([{'id': p.page.id_, 'url': urlparse(p.page.web_url)._replace(query='').geturl()} for p in pages]), flush=True)
        if len(pages) != 1:
            raise SystemExit('Need exactly one matching page; open and unlock the app in the foreground')
        session = await asyncio.wait_for(inspector.inspector_session(pages[0].application, pages[0].page), 15)
        await asyncio.wait_for(session.runtime_enable(), 10)
        if args.console:
            session.response_methods['Console.messageAdded'] = lambda e: print('CONSOLE', json.dumps(
                {k: e['params'].get('message', {}).get(k) for k in ['level', 'text', 'parameters']}), flush=True)
            await asyncio.wait_for(session.console_enable(), 10)
        print('SNAPSHOT', await asyncio.wait_for(session.runtime_evaluate(snapshot), 15), flush=True)
        if args.cookies:
            response = await asyncio.wait_for(session.send_command('Page.getCookies'), 10)
            print('COOKIES', json.dumps([{k: c.get(k) for k in ('name', 'domain', 'path', 'expires', 'session', 'httpOnly', 'secure', 'sameSite')}
                                         for c in find_cookies(response) or [] if c.get('name') in args.cookies]), flush=True)
        if args.evaluate_file:
            print('RESULT', await asyncio.wait_for(session.runtime_evaluate(Path(args.evaluate_file).read_text()), 20), flush=True)
        if args.after is not None:
            await asyncio.sleep(min(30, max(0, args.after)))
            print('AFTER', await asyncio.wait_for(session.runtime_evaluate(snapshot), 15), flush=True)
        if args.screenshot:
            dims = json.loads(await session.runtime_evaluate('JSON.stringify({width:innerWidth,height:innerHeight})'))
            result = await asyncio.wait_for(session.send_command('Page.snapshotRect', x=0, y=0, coordinateSystem='Viewport', **dims), 15)
            if result.get('method') == 'Target.dispatchMessageFromTarget': result = json.loads(result['params']['message'])
            payload = result.get('result', result)
            if 'dataURL' in payload:
                Path(args.screenshot).write_bytes(base64.b64decode(payload['dataURL'].split(',', 1)[1]))
                print('SCREENSHOT', args.screenshot, flush=True)
            else:
                print('SCREENSHOT_UNAVAILABLE', json.dumps(result.get('error', {})), flush=True)
    finally:
        await inspector.close()
        await lockdown.close()

asyncio.run(main())
