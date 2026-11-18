"""Continue to the formal phase after valid smoke and pilot evidence."""
from pathlib import Path
import subprocess
import sys
import time
import json

from analyze import report

HERE=Path(__file__).resolve().parent
RUNTIME=HERE/'.runtime'

def wait_phase(name,seconds):
    phase=RUNTIME/name
    end=time.monotonic()+seconds
    while not (phase/'status.json').exists():
        if time.monotonic()>end:
            raise RuntimeError(f'No completion status for {name}')
        time.sleep(10)
    status=json.loads((phase/'status.json').read_text())
    if status['failedPairs']:
        raise RuntimeError(f'{name} failed: {status["failedPairs"]}')
    scopes=list(phase.glob('*-scope.json'))
    if not scopes or not all(json.loads(path.read_text())['isolated'] for path in scopes):
        raise RuntimeError(f'Missing Cloud isolation proof for {name}')
    return report(phase)

def main():
    smoke=wait_phase('smoke-scoped',600)
    if smoke['validPairs']!=2 or not all(smoke['counts'][arm]['wakeRead']==2 for arm in ('concern','control')):
        raise RuntimeError('Timed smoke must prove actual reminder delivery and a successful formal-version read in each arm')
    pilot=wait_phase('pilot-scoped',25*3600)
    if pilot['validPairs']!=6:
        raise RuntimeError('Pilot must contain six valid pairs')
    print('Calibration gates passed. Starting frozen 48-pair formal phase.',flush=True)
    result=subprocess.run([sys.executable,'-u',str(HERE/'run.py'),'formal','--port','14300',
                           '--seeds',str(RUNTIME/'seed-retry/seeds.json')],cwd=HERE)
    formal=RUNTIME/'formal'
    if (formal/'design.json').exists():
        report(formal)
    if result.returncode:
        raise RuntimeError('Formal batch did not complete normally')
    print('Formal trajectories and review packet are available.',flush=True)

if __name__=='__main__':main()
