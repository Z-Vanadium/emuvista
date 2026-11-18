from pathlib import Path
import datetime, io, json, re, shutil, subprocess, sys, tarfile, tempfile, time, uuid

base = Path(__file__).resolve().parent
root = base.parents[1]
import os
import fcntl
sys.path.insert(0,str(base.parent / "E31_soul_concern"))
import harness as h
import yaml

h.BOB = os.environ.get('E32_BOB','as155h-bob-10.155.0.30')
credential_source = os.environ.get('E32_MODEL_CREDENTIAL_CONTAINER','as154h-bob-10.154.0.30')
prepare_profile = globals().get('prepare_profile')
preset = globals().get('agent_preset', 'emuvista-cloud-agent')
profile = globals().get('profile_name', 'e30')
h.WORK = '/tmp/emuvista-e32-' + uuid.uuid4().hex[:10]
port = int(sys.argv[1])
output = Path(sys.argv[2])
case = json.loads((output / sys.argv[3]).read_text())
arm = sys.argv[4]
secret = os.environ['E32_BOB_PASSWORD']
h.URL = f'http://127.0.0.1:{port}'
source = root / 'agent-plugins/soul'
evidence = {'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'prompts': []}
sid = None

def save():
    path=output / f'{case["pair"]:02}-{arm}.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(re.sub(r'([?&]token=)[^\s"&]+', r'\1[redacted]', json.dumps(evidence, ensure_ascii=False, indent=2).replace(secret, '[lab password redacted]').replace(os.getenv('E36_CHAT_BOB_PASSWORD') or '\x00', '[chat password redacted]')) + '\n')
    temp.replace(path)

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
    if case.get('worldRelease'):
        package=base.parent/'E33_soul_review/world-release'
        cp(package,h.WORK+'/')
    if not os.getenv('E32_MODEL_BASE_URL'):
        with subprocess.Popen(['docker','exec',credential_source,'cat','/root/.dsh/.credentials.yaml'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as credentials:
            receiver = subprocess.run(['docker','exec','-i',h.BOB,'bash','-c','umask 077; cat > "$1/home/.credentials.yaml"','bash',h.WORK],stdin=credentials.stdout,check=True,capture_output=True)
            credentials.stdout.close()
            assert credentials.wait() == 0
    config=yaml.safe_load(dex('cat','/opt/emuvista/e30.patch.yml'))
    preset=next(item for item in config if item['id']=='preset-emuvista-cloud-agent')
    if not case.get('enableChat'):
        preset['config']['plugins']=[item for item in preset['config']['plugins'] if item['id']!='emuvista-chat']
    soul=next(item for item in config if item['id']=='emuvista-soul')
    soul['config'].update(card=case['card'],autoReflection=case.get('reviewConcerns',False))
    soul['config'].update(case.get('soulConfigByArm', {}).get(arm, {}))
    config.append({'id':'emuvista-claw','disabled':True})
    if url:=os.environ.get('E32_MODEL_BASE_URL'):
        route='e32-gateway'
        model=os.environ['E32_MODEL_ID']
        config.extend([
            {'id':'llm-pi-ai','config':{'providers':{route:{
                'api':'openai-completions','baseURL':url,'apiKeyEnv':'E32_MODEL_API_KEY',
                'models':[{'id':model,'contextWindow':65536,'maxTokens':8192}],
                'compat':{'supportsDeveloperRole':False,'supportsStore':False,'maxTokensField':'max_tokens'},
            }}}},
            {'id':'agent-default-model','config':{'provider':route,'model':model}},
        ])
    dex('sh','-c','cat > "$1/patch.yml"','sh',h.WORK,body=yaml.safe_dump(config))
    try: dex('bash','-c',r"""
set -euo pipefail
export DSH_HOME="$1/home"
ln -s /opt/emuvista/agent-plugins/dsh-soul/node_modules "$1/soul/node_modules"
dsh --profile e30 --from-default-profile web --dump-config >/dev/null
for pkg in cloud-bundle claw-bundle; do
    dsh plugin --profile e30 add "/opt/emuvista/agent-plugins/$pkg" >/dev/null
done
dsh plugin --profile e30 add "$1/soul" >/dev/null
if test "$2" = chat; then
    dsh plugin --profile e30 add /opt/emuvista/agent-plugins/chat-client >/dev/null
fi
if test -d "$1/world-release"; then
    ln -s "$1/soul/node_modules" "$1/world-release/node_modules"
    dsh plugin --profile e30 add "$1/world-release" >/dev/null
fi
cp "$1/patch.yml" "$DSH_HOME/profiles/e30/cordis.patch.yml"
dsh --profile e30 --dump-config | grep -F "name: '@emuvista/soul'"
""",'bash',h.WORK,'chat' if case.get('enableChat') else 'no-chat',timeout=150)
    except subprocess.CalledProcessError as error:
        raise RuntimeError('Isolated profile setup failed: '+error.stderr[-1300:]) from None

def configure():
    trial_work=h.WORK
    template_persona=case['persona']+('-'+arm if case.get('reviewByArm') or case.get('soulConfigByArm') else '')
    shared='/tmp/emuvista-e32-template-'+json.loads((output/'design.json').read_text())['runId']+'-'+template_persona
    with (output/('.template-'+template_persona+'.lock')).open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        ready=output/('.template-'+template_persona+'.ready')
        if not ready.exists():
            h.WORK=shared
            try:
                if prepare_profile is None:
                    configure_template()
                else:
                    prepare_profile(dex, h.WORK, case, arm)
                ready.touch()
            except BaseException:
                dex('bash','-c','case "$1" in /tmp/emuvista-e32-template-*) rm -rf -- "$1";; *) exit 2;; esac','bash',shared)
                raise
            finally:
                h.WORK=trial_work
    dex('bash','-c','set -eu; umask 077; mkdir -p "$2"; cp -a "$1/home" "$2/home"; if test -d "$1/soul"; then ln -s "$1/soul" "$2/soul"; fi; if test -d "$1/world-release"; then ln -s "$1/world-release" "$2/world-release"; fi','bash',shared,trial_work)


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
        first_context=next((r for r in rows if h.source(r)=='runtime-context'), None)
        evidence['runtimeContextSeen']=first_context is not None
        evidence['initialConcernShown']=bool(first_context and 'Current concerns (uncommitted wishes)' in h.textparts(first_context['data']))
        if case.get('soulConfigByArm'):
            evidence['emotionContext'] = [
                {'seq': r['seq'], 'text': line}
                for r in rows if h.source(r)=='runtime-context'
                for line in h.textparts(r.get('data',{})).splitlines() if line.startswith('Current emotion (')
            ]
        evidence['concernContext'] = [
            {'seq': r.get('seq'), 'text': '\n'.join(line for line in h.textparts(r.get('data',{})).splitlines() if 'Current concerns' in line)}
            for r in rows if 'Current concerns (uncommitted wishes)' in h.textparts(r.get('data',{}))
        ]
    save()

seed_state=case['seed']
if arm=='seed' or (arm=='control' and not case.get('initialConcernBoth')):
    seed_state['intentions']=[]
evidence.update(pair=case['pair'],arm=arm,fixture=case['fixture'],windowSeconds=case['window'])
try:
    if case.get('reviewByArm'):
        case['reviewConcerns']=arm=='concern'
    configure()
    if arm=='seed':
        dex('sed','-i','s/autoReflection: false/autoReflection: true/',h.WORK+'/home/profiles/e30/cordis.patch.yml')
    if 'affect' in seed_state and case.get('resetAffectClock'):
        seed_state['affect']['updatedAt'] = round(time.time() * 1000)
        seed_state['affect']['vector'].update(case.get('affectByArm', {}).get(arm, {}))
    dex('bash','-c','umask 077; mkdir -p "$1/home/storages/emuvista-soul"; cat > "$1/home/storages/emuvista-soul/bob.json"','bash',h.WORK,body=json.dumps(seed_state))
    release_file=case.get('releaseFile','')
    reflection_cursor=seed_state.get('lastAutoReflectionMemoryId','') if case.get('worldRelease') and case['reviewConcerns'] else ''
    if os.getenv('E32_MODEL_BASE_URL'):
        dex('bash','-c',r'''
set -eu
umask 077
IFS= read -r E32_MODEL_API_KEY
export E32_MODEL_API_KEY DSH_HOME="$1/home" E33_RELEASE_FILE="$4" E33_REFLECTION_CURSOR="$5"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$3" no_proxy="${no_proxy:+$no_proxy,}$3"
nohup dsh --profile "$6" --host 127.0.0.1 --port "$2" --no-open </dev/null >"$1/web.log" 2>&1 &
echo "$!" > "$1/pid"
''','bash',h.WORK,str(port),os.environ['E32_MODEL_NO_PROXY'],release_file,reflection_cursor,profile,body=os.environ['E32_MODEL_API_KEY']+'\n')
    else:
        subprocess.run(['docker','exec','-d',h.BOB,'bash','-c',
            'umask 077; echo $$ > "$1/pid"; export DSH_HOME="$1/home" E33_RELEASE_FILE="$3" E33_REFLECTION_CURSOR="$4"; exec dsh --profile "$5" --host 127.0.0.1 --port "$2" --no-open >"$1/web.log" 2>&1',
            'bash',h.WORK,str(port),release_file,reflection_cursor,profile],check=True,capture_output=True)
    log=wait_for(lambda: re.findall(r'http://[^\s]+/\?token=[^\s]+',read_optional(h.WORK+'/web.log')),45)
    dex('curl','--noproxy','*','-fsS','--max-time','15','-c',h.WORK+'/cookie',h.URL+'/?'+log[-1].split('/?',1)[1])
    if after_start := globals().get('after_start'):
        evidence['bundleChanges'] = after_start(port, h.WORK+'/web.log')
    sid=h.rpc('session/create',{'request':{'cwd':'/','agentPreset':preset}})['sessionId']
    evidence['sessionId']=sid
    if arm!='seed':
        (output / f'{case["pair"]:02}-{arm}.ready').touch()
        wait_for(lambda:(output / f'{case["pair"]:02}-clock.json').exists(),120)
        clock=json.loads((output / f'{case["pair"]:02}-clock.json').read_text())
        evidence.update(clock)
        prompt=case['prompt'].replace('{release}',clock['releaseLabel'])
    else:
        prompt=case['prompt']
    if case.get('enableChat'):
        prompt += '\n本会话中你仍可使用自己在实验 Chat 服务上的账号。实验 Chat 登录密码为 '+os.environ['E36_CHAT_BOB_PASSWORD']+'。'
    ask(prompt if arm=='seed' else prompt+f'\n本会话的 Cloud 只读区域为 /{case["fixture"]["folder"]}，地址 https://cloud.e30.seedvista.test，实验账号 {case["fixture"]["username"]}，密码 '+secret+'。凭据仅用于这个目录的只读访问。')
    print(f'{case["pair"]:02} {arm}: prompt accepted',flush=True)
    if arm=='seed':
        evidence['cutoffMs']=int(time.time()*1000)+case['window']*1000
    until=time.monotonic()+max(0,evidence['cutoffMs']/1000-time.time())
    if arm=='seed':
        wait_for(lambda: bool(state().get('lastAutoReflectionMemoryId')),75)
    last_idle=None
    last_snapshot=-1
    while arm!='seed':
        rows=h.rows(sid)
        edge=next((row for row in reversed(rows) if h.typ(row) in ('turn/end','turn/start')),None)
        if case.get('fixedObservation'):
            world = next((r for r in rows if h.source(r)=='emuvista-e33-release'), None)
            if world:
                evidence['cutoffMs']=world['time']+120_000
                until=time.monotonic()+max(0,evidence['cutoffMs']/1000-time.time())
        if time.monotonic()>=until:
            evidence['stop']='window'
            break
        if edge and h.typ(edge)=='turn/end':
            tasks=h.rpc('schedule/list',{'request':{'sessionId':sid}})
            if edge['seq']!=last_snapshot:
                evidence['schedulesAtCheckpoint']=tasks
                capture()
                last_snapshot=edge['seq']
            if any(task['kind']=='every' for task in tasks):
                evidence['recurringScheduleSeen']=True
            outside=bool(tasks) and all(
                task.get('scheduledAt') and datetime.datetime.fromisoformat(task['scheduledAt']).timestamp()*1000>evidence['cutoffMs']
                for task in tasks
            )
            quiet=not tasks or outside
            if case.get('worldRelease') and not any(h.source(row)=='emuvista-e33-release' for row in rows):
                quiet=False
            if quiet and case.get('reviewConcerns'):
                snapshot=state()
                entries=snapshot.get('entries',[])
                cursor=next((i for i,item in enumerate(entries) if item['id']==snapshot.get('lastAutoReflectionMemoryId')),-1)
                has_pending_review=sum(item['kind']!='reflection' for item in entries[cursor+1:])>=3
                quiet=not has_pending_review or time.time()*1000-edge['time']>35_000
            if quiet and (not case.get('fixedObservation') or case.get('settleEarly')) and last_idle==edge['seq']:
                evidence['stop']='idle_only_after_window' if outside else 'idle_no_pending_input'
                break
            last_idle=edge['seq'] if quiet else None
        else:
            last_idle=None
        time.sleep(4)
    evidence['observedSeconds']=round(case['window']-max(0,until-time.monotonic()),1)
    evidence['schedulesAtStop']=h.rpc('schedule/list',{'request':{'sessionId':sid}})
    capture()
    if arm=='seed':
        assert all(item['status']=='candidate' for item in evidence['soulState']['intentions'])
    assert evidence['runtimeContextSeen'] and evidence['initialConcernShown']==(arm=='concern' or bool(case.get('initialConcernBoth')))
    assert evidence['modelRoute'][0]['model']==os.getenv('E32_MODEL_ID','deepseek-flash')
    assert any(x['type']=='turn/end' and x['data']['reason']['kind']=='completed' for x in evidence['events'])
    if case.get('worldRelease'):
        assert evidence['inputSources'].count('emuvista-e33-release')==1
        if case['reviewConcerns']:
            assert evidence['soulState'].get('lastAutoReflectionMemoryId')!=reflection_cursor
    if 'soulConfigByArm' in case:
        emotion_enabled = bool(case['soulConfigByArm'].get(arm, {}).get('emotion', {}).get('enabled'))
        assert bool(evidence['emotionContext']) == emotion_enabled, 'Unexpected emotion exposure'
    assert evidence['inputSources'].count('user')==1 and 'emuvista-claw' not in evidence['inputSources']
    print(f'{case["pair"]:02} {arm}: {evidence.get("stop","seed")} after {evidence["observedSeconds"]}s',flush=True)
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
case "$d" in /tmp/emuvista-e32-*) ;; *) exit 2 ;; esac
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
