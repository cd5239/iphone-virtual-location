"""Build existing pylzss/lzfse dependencies with a workspace-local Zig compiler.

Usage: python build-compression.py --zig ZIG --python-sdk SDK --output SITE_PACKAGES
Sources are the unmodified upstream sdists in third-party-sources.
"""
import argparse
from pathlib import Path
import subprocess
import tarfile
import tempfile

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--python-sdk',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    zig=args.zig.resolve();sdk=args.python_sdk.resolve();output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='compression-build-') as temporary:
        root=Path(temporary)
        for name in ('pylzss-0.3.4','lzfse-0.4.2'):
            archive=Path(__file__).parent/'third-party-sources'/(name+'.tar.gz')
            with tarfile.open(archive) as source:source.extractall(root,filter='data')
        common=[str(zig),'cc','-shared','-O2','-target','x86_64-windows-gnu','-DPY_SSIZE_T_CLEAN',
                '-I'+str(sdk/'include'),'-L'+str(sdk/'libs'),'-lpython313']
        lzss=root/'pylzss-0.3.4'
        subprocess.run(common+['-I'+str(lzss/'include'),str(lzss/'pylzss.c'),'-o',str(output/'lzss.pyd')],check=True)
        lzfse=root/'lzfse-0.4.2';src=lzfse/'lzfse'/'src'
        files=[str(p) for p in src.glob('*.c') if p.name!='lzfse_main.c']
        subprocess.run(common+['-I'+str(src),str(lzfse/'pylzfse.c'),*files,'-o',str(output/'lzfse.pyd')],check=True)
    print('Built pylzss 0.3.4 and lzfse 0.4.2 for CPython 3.13 x64')

if __name__=='__main__':main()
