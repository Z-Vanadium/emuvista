from pathlib import Path
import argparse
import os
import runpy
import shutil
import subprocess
import sys
import time

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('experiment',type=Path)
    parser.add_argument('mode',choices=['timing','review'])
    parser.add_argument('pid',type=int)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--label',default='formal')
    parser.add_argument('--final-label',default='formal-final')
    args=parser.parse_args()
    runtime=args.experiment/'.runtime'
    original=runtime/args.label
    code=runpy.run_path(str(Path(__file__).resolve().with_name('run.py')))
    read=code['read']
    summarize=code['summary']
    write=code['harness'].write
    while not (original/'status.json').exists():
        try:
            os.kill(args.pid,0)
        except ProcessLookupError:
            if not (original/'design.json').is_file():
                raise
            break
        if Path(f'/proc/{args.pid}/stat').read_text().rsplit(')',1)[-1].split()[0]=='Z':
            break
        time.sleep(10)
    planned=len(read(original/'design.json')['combinations'])
    valid={}
    output=runtime/args.final_label
    output.mkdir()
    sources=[args.label]
    for attempt in range(4):
        current=runtime/sources[-1]
        summarize(current,args.mode)
        for row in read(current/'summary.json')['rows']:
            valid.setdefault(row['pair'],current)
        missing=sorted(set(range(1,planned+1))-valid.keys())
        if not missing or attempt==3:
            break
        label=f'{args.label}-recovery-{attempt+1}'
        sources.append(label)
        print('Replacing pre-scoring failures:',missing,flush=True)
        subprocess.run([sys.executable,'-u',str(args.experiment/'run.py'),label,
                        '--pairs',str(planned),'--index','12','--port',str(args.port),'--jobs','1',
                        '--settle-early','--choose',*map(str,missing)],check=False)
    names=['case.json','publication.json','concern.json','control.json']
    if args.mode=='review':
        names.extend(['concern-receipts.json','control-receipts.json'])
    for pair,source in valid.items():
        for name in names:
            dst=f'{pair:02}-{name}'
            shutil.copyfile(source/dst,output/dst)
    write(output/'sources.json', {k:v.name for k,v in valid.items()})
    write(output/'design.json',read(original/'design.json'))
    summarize(output,args.mode)
    write(output/'status.json',dict(finished=not missing,failedPairs=missing))
    print('Valid formal pairs:',len(valid),'of',planned,flush=True)
    if missing:
        raise RuntimeError(f'Unresolved formal pairs: {missing}')

if __name__=='__main__':
    main()
