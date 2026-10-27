#!/usr/bin/env python3
"""Build and ad-hoc seal a small simulator-only UIKit/WebKit diagnostic app."""
import argparse,json,os,platform,plistlib,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
if platform.system()!='Darwin' or not os.environ.get('IOS_WORKLOAD_ACTIVE'):raise SystemExit('Run on the Mac through mac-workload build')
root=Path(__file__).resolve().parent;app=Path(a.output).resolve()/'SimulatorHealth.app';app.mkdir(parents=True,exist_ok=True)
sdk=subprocess.check_output(['xcrun','--sdk','iphonesimulator','--show-sdk-path'],text=True).strip()
arch='x86_64' if platform.machine()=='x86_64' else 'arm64'
subprocess.run(['xcrun','--sdk','iphonesimulator','swiftc','-parse-as-library','-swift-version','5','-sdk',sdk,'-target',arch+'-apple-ios26.0-simulator','-framework','UIKit','-framework','WebKit',str(root/'Health.swift'),'-o',str(app/'SimulatorHealth')],check=True)
info=dict(CFBundleExecutable='SimulatorHealth',CFBundleIdentifier='com.visar.SimulatorHealth.QA',CFBundleName='SimulatorHealth',CFBundleDisplayName='Simulator Health',CFBundlePackageType='APPL',CFBundleVersion='1',CFBundleShortVersionString='1.0',CFBundleSupportedPlatforms=['iPhoneSimulator'],MinimumOSVersion='26.0',UIDeviceFamily=[1],UILaunchScreen={},UIApplicationSceneManifest={'UIApplicationSupportsMultipleScenes':False},UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'])
(app/'Info.plist').write_bytes(plistlib.dumps(info))
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
print(json.dumps({'app':str(app),'arch':arch,'sdk':sdk}))
