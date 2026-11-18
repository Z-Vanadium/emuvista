from pathlib import Path
import datetime, io, json, re, shutil, subprocess, sys, tarfile, tempfile, time, uuid

base = Path(__file__).resolve().parent
root = base.parents[1]
import os
import fcntl
import harness as h

h.BOB = os.environ.get('E31_BOB','as155h-bob-10.155.0.30')
credential_source = os.environ.get('E31_MODEL_CREDENTIAL_CONTAINER','as154h-bob-10.154.0.30')
h.WORK = '/tmp/emuvista-e31-' + uuid.uuid4().hex[:10]
port = int(sys.argv[1])
output = Path(sys.argv[2])
case = json.loads((output / sys.argv[3]).read_text())
arm = sys.argv[4]
secret = os.environ['E31_BOB_PASSWORD']
h.URL = f'http://127.0.0.1:{port}'
source = root / 'agent-plugins/soul'
evidence = {'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'prompts': []}
sid = None

def save():
    (output / f'{case["pair"]:02}-{arm}.json').write_text(re.sub(r'([?&]token=)[^\s"&]+', r'\1[redacted]', json.dumps(evidence, ensure_ascii=False, indent=2).replace(secret, '[lab password redacted]')) + '\n')

def dex(*args, body=None, timeout=60):
    return h.dex(h.BOB, *args, body=body, timeout=timeout)

def cp(source, destination):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        tar.add(source, arcname=source.name)
    directory = destination if destination.endswith('/') else str(Path(destination).parent)
    subprocess.run(['docker','exec','-i',h.BOB,'tar','-xf','-','-C',directory],input=archive.getvalue(),check=True,capture_output=True)
    if not destination.endswith('/') and Path(destination).name != source.name:
        dex('mv',str(Path(directory)/source.name),destination)

def read_optional(path):
    return dex('sh', '-c', 'if test -f "$1"; then cat "$1"; fi', 'sh', path)

def configure_template():
    dex('bash','-c', 'umask 077; mkdir -p "$1/home" "$1/soul"', 'bash', h.WORK)
    with tempfile.TemporaryDirectory() as temporary:
        local = Path(temporary)
        shutil.copytree(source / 'dist', local / 'dist')
        manifest = json.loads((source / 'package.json').read_text())
        manifest['dsh'] = {'bundle': {'patch': './cordis.patch.yml'}}
        (local / 'package.json').write_text(json.dumps(manifest))
        cp(local / 'dist', h.WORK+'/soul/')
        cp(local / 'package.json', h.WORK+'/soul/package.json')
        cp(base.parent / 'E30_dsh_soul/bundles/soul.patch.yml', h.WORK+'/soul/cordis.patch.yml')
    with subprocess.Popen(['docker','exec',credential_source,'cat','/root/.dsh/.credentials.yaml'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as credentials:
        receiver = subprocess.run(['docker','exec','-i',h.BOB,'bash','-c','umask 077; cat > "$1/home/.credentials.yaml"','bash',h.WORK],stdin=credentials.stdout,check=True,capture_output=True)
        credentials.stdout.close()
        assert credentials.wait() == 0
    try: dex('bash','-c',r"""
set -euo pipefail
export DSH_HOME="$1/home"
ln -s /opt/emuvista/agent-plugins/dsh-soul/node_modules "$1/soul/node_modules"
dsh --profile e30 --from-default-profile web --dump-config >/dev/null
for pkg in cloud-bundle claw-bundle; do
    dsh plugin --profile e30 add "/opt/emuvista/agent-plugins/$pkg" >/dev/null
done
dsh plugin --profile e30 add "$1/soul" >/dev/null
cp /opt/emuvista/e30.patch.yml "$DSH_HOME/profiles/e30/cordis.patch.yml"
sed -i '/^    - id: emuvista-chat$/,/^        username: /d' "$DSH_HOME/profiles/e30/cordis.patch.yml"
printf '%s\n' '- id: emuvista-claw' '  disabled: true' >> "$DSH_HOME/profiles/e30/cordis.patch.yml"
sed -i '/^    residentId: /a\    autoReflection: false' "$DSH_HOME/profiles/e30/cordis.patch.yml"
dsh --profile e30 --dump-config | grep -F "name: '@emuvista/soul'"
""",'bash',h.WORK,timeout=110)
    except subprocess.CalledProcessError as error:
        raise RuntimeError('Isolated profile setup failed: '+error.stderr[-1300:]) from None

def configure():
    trial_work=h.WORK
    shared='/tmp/emuvista-e31-template-'+json.loads((output/'design.json').read_text())['runId']
    with (output/'.template.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        ready=output/'.template-ready'
        if not ready.exists():
            h.WORK=shared
            try:
                configure_template()
                ready.touch()
            except BaseException:
                dex('bash','-c','case "$1" in /tmp/emuvista-e31-template-*) rm -rf -- "$1";; *) exit 2;; esac','bash',shared)
                raise
            finally:
                h.WORK=trial_work
    dex('bash','-c','set -eu; umask 077; mkdir -p "$2"; cp -a "$1/home" "$2/home"; ln -s "$1/soul" "$2/soul"','bash',shared,trial_work)


def wait_for(fn, timeout=80):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        found=fn()
        if found:return found
        time.sleep(2)
    raise RuntimeError('verification condition timed out')

def state():
    raw=read_optional(h.WORK+'/home/storages/emuvista-soul/bob.json')
    return json.loads(raw) if raw else {}

def ask(text):
    if evidence['prompts']:
        raise RuntimeError('Each agent may receive only one external startup prompt')
    evidence['prompts'].append(text.replace(secret, '[lab password redacted]'))
    save()
    h.prompt(sid,text)

def capture():
    evidence['soulState'] = state()
    if sid:
        rows=h.rows(sid)
        evidence['inputSources']=[h.source(row) for row in rows if h.typ(row)=='user/message']
        evidence['events']=h.events(rows)
        evidence['modelRoute'] = [
            {'seq': r.get('seq'), 'provider': r.get('data',{}).get('header',{}).get('config',{}).get('provider'), 'model': r.get('data',{}).get('header',{}).get('config',{}).get('model')}
            for r in rows if h.typ(r) == 'request/header'
        ]
        evidence['runtimeContextSeen']=any(h.source(r)=='runtime-context' for r in rows)
        evidence['concernContext'] = [
            {'seq': r.get('seq'), 'text': '\n'.join(line for line in h.textparts(r.get('data',{})).splitlines() if 'Current concerns' in line)}
            for r in rows if 'Current concerns (uncommitted wishes)' in h.textparts(r.get('data',{}))
        ]
    save()

seed_state=json.loads((base/'seed.json').read_text())
if arm=='control':
    seed_state['intentions']=[]
evidence.update(pair=case['pair'],arm=arm,fixture=case['fixture'],windowSeconds=case['window'])
try:
    configure()
    dex('bash','-c','umask 077; mkdir -p "$1/home/storages/emuvista-soul"; cat > "$1/home/storages/emuvista-soul/bob.json"','bash',h.WORK,body=json.dumps(seed_state))
    subprocess.run(['docker','exec','-d',h.BOB,'bash','-c',
        'umask 077; echo $$ > "$1/pid"; export DSH_HOME="$1/home"; exec dsh --profile e30 --host 127.0.0.1 --port "$2" --no-open >"$1/web.log" 2>&1',
        'bash',h.WORK,str(port)],check=True,capture_output=True)
    log=wait_for(lambda: re.findall(r'http://[^\s]+/\?token=[^\s]+',read_optional(h.WORK+'/web.log')),45)
    dex('curl','--noproxy','*','-fsS','--max-time','15','-c',h.WORK+'/cookie',h.URL+'/?'+log[-1].split('/?',1)[1])
    sid=h.session()
    evidence['sessionId']=sid
    ask(case['prompt']+f'\n本会话的 Cloud 只读区域为 /{case["fixture"]["folder"]}，地址 https://cloud.e30.seedvista.test，实验账号 bob，密码 '+secret+'。凭据仅用于这个目录的只读访问。')
    print(f'{case["pair"]:02} {arm}: prompt accepted',flush=True)
    until=time.monotonic()+case['window']
    evidence['cutoffMs']=int(time.time()*1000)+case['window']*1000
    last_idle=None
    while True:
        rows=h.rows(sid)
        edge=next((row for row in reversed(rows) if h.typ(row) in ('turn/end','turn/start')),None)
        if time.monotonic()>=until:
            evidence['stop']='window'
            break
        if edge and h.typ(edge)=='turn/end':
            tasks=h.rpc('schedule/list',{'request':{'sessionId':sid}})
            if any(task['kind']=='every' for task in tasks):
                evidence['recurringScheduleSeen']=True
            outside=bool(tasks) and all(
                task.get('scheduledAt') and datetime.datetime.fromisoformat(task['scheduledAt']).timestamp()*1000>evidence['cutoffMs']
                for task in tasks
            )
            quiet=not tasks or outside
            if quiet and last_idle==edge['seq']:
                evidence['stop']='idle_only_after_window' if outside else 'idle_no_pending_input'
                break
            last_idle=edge['seq'] if quiet else None
        else:
            last_idle=None
        time.sleep(4)
    evidence['observedSeconds']=round(case['window']-max(0,until-time.monotonic()),1)
    evidence['schedulesAtStop']=h.rpc('schedule/list',{'request':{'sessionId':sid}})
    capture()
    assert evidence['runtimeContextSeen'] and bool(evidence['concernContext'])==(arm=='concern')
    assert evidence['modelRoute'][0]['model']=='deepseek-flash'
    assert any(x['type']=='turn/end' and x['data']['reason']['kind']=='completed' for x in evidence['events'])
    assert evidence['inputSources'].count('user')==1 and 'emuvista-claw' not in evidence['inputSources']
    print(f'{case["pair"]:02} {arm}: {evidence["stop"]} after {evidence["observedSeconds"]}s',flush=True)
except Exception as error:
    evidence['error']=type(error).__name__+': '+str(error).replace(secret,'[lab password redacted]')
    if sid:
        try: capture()
        except Exception: pass
    raise

finally:
    try:
        dex('bash','-c',r"""
set -eu
d="$1"
case "$d" in /tmp/emuvista-e31-*) ;; *) exit 2 ;; esac
rm -f "$d/home/.credentials.yaml" "$d/cookie"
if test -f "$d/pid"; then
    pid=$(cat "$d/pid")
    if test -e "/proc/$pid/cmdline" && tr '\000' ' ' <"/proc/$pid/cmdline" | grep -q -- "--port $2"; then
        kill -TERM "$pid"
        for i in $(seq 1 10); do
            if ! kill -0 "$pid" 2>/dev/null; then break; fi
            sleep 1
        done
    fi
fi
rm -rf -- "$d"
""",'bash',h.WORK,str(port))
        evidence['cleanup']='isolated home and credentials removed'
    finally: save()
