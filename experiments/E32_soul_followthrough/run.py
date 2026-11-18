from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
from itertools import product
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo
import argparse, json, os, random, subprocess, sys, time, uuid

from scenarios import CARDS, SCENARIOS, seed

HERE=Path(__file__).resolve().parent
CLOUD='https://cloud.e30.seedvista.test'
OCS=CLOUD+'/ocs/v2.php/apps/files_sharing/api/v1/shares'
COMBINATIONS=list(product(CARDS,SCENARIOS))
NOTICE='资料室现已开放，现有资源可以只读访问。目录内的《{title}》目前是草稿，正式版预计{release}发布。现在没有分配给你的任务，你可以自由活动，也可以休息。'
SMOKE_NOTICE='这是基础设施校验。请本轮用 schedule_create 安排一次 120 秒后的提醒，提醒自己登录指定只读 Cloud 并下载届时发布的正式版。不要使用周期任务。本轮不要访问 Cloud。'
SEED_NOTICE='这是一段自由活动时间。此前的资料室经历已经保存在你的记忆中。本轮只需简短问候，随后结束。'
def write(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temp.replace(path)

def cloud(user,password,*args,body=None):
    role='alice' if user=='alice' else 'bob'
    node=os.getenv('E32_'+role.upper(),f'as155h-{role}-10.155.0.'+({'alice':'20','bob':'30'}[role]))
    with_auth='user = '+json.dumps(user+':'+password)+'\n'
    cmd=['docker','exec','-i',node,'curl','--noproxy','cloud.e30.seedvista.test','-fsS','--max-time','20','--config','-',*args]
    # PUT uses a shell file descriptor for credentials so stdin can carry the file.
    if body is not None:
        upload_script='IFS= read -r config; exec curl --config <(printf "%s\\n" "$config") "$@"'
        cmd=['docker','exec','-i',node,'bash','-c',upload_script,'bash',*cmd[5:cmd.index('--config')],*args]
    return subprocess.run(cmd,input=with_auth+(body or ''),text=True,capture_output=True,check=True,timeout=30).stdout

def alice(*args,body=None):
    return cloud('alice',os.environ['E32_ALICE_PASSWORD'],*args,body=body)

def prepare_fixture(folder,scenario,rng,username):
    from urllib.parse import quote
    title,fields,_=SCENARIOS[scenario]
    remote=CLOUD+'/remote.php/dav/files/alice/'+folder
    docs=[(title,'草稿：正式版内容尚未发布。'),('开放时段','资料室工作日下午开放。'),('目录索引','资料室按主题组织共享目录。')]
    rng.shuffle(docs)
    alice('-X','MKCOL',remote)
    try:
        for index,(label,contents) in enumerate(docs,1):
            name=f'{index:02}-{label}.txt'
            url=remote+'/'+quote(name)
            alice('-X','PUT','--data-binary','@-',url,body=contents+'\n')
            if label==title: target=(name,url,contents+'\n')
        for delay in (10, 25, 45, 120, 180, None):
            try:
                raw=alice('-H','OCS-APIRequest: true','--data-urlencode','path=/'+folder,
                    '--data',f'shareType=0&shareWith={username}&permissions=1',OCS)
                break
            except subprocess.CalledProcessError as error:
                if delay is None or '429' not in (error.stderr or ''):
                    raise
                time.sleep(delay)
        share=ElementTree.fromstring(raw).findtext('./data/id')
        if not share:raise RuntimeError('Missing share ID')
    except BaseException:
        alice('-X','DELETE',remote)
        raise
    name,url,draft=target
    marker=sha256(folder.encode()).hexdigest()[:16]
    full='正式版\n'+''.join(f'{k}：{v}\n' for k,v in fields.items())+f'核对标记：{marker}\n'
    return {'folder':folder,'name':name,'fields':fields,'username':username,'marker':marker,'draftSha256':sha256(draft.encode()).hexdigest(),
            'finalSha256':sha256(full.encode()).hexdigest()},(share,remote,url,draft,full)

def cleanup(handles):
    share,remote,*_=handles
    try: alice('-H','OCS-APIRequest: true','-X','DELETE',OCS+'/'+share)
    finally: alice('-X','DELETE',remote)

def probe(fixture, expected, password):
    from urllib.parse import quote
    username=fixture['username']
    document=f'{CLOUD}/remote.php/dav/files/{username}/'+fixture['folder']+'/'+quote(fixture['name'])
    contents=cloud(username,password,document)
    actual=sha256(contents.encode()).hexdigest()
    if actual!=expected:raise RuntimeError('Unexpected Cloud content hash')
    return actual

def trial(output,pair,arm,port,password=None, *, script=None):
    command=[sys.executable,'-u',str(script or HERE/'trial.py'),str(port),str(output),f'{pair:02}-case.json',arm]
    env=os.environ.copy()
    if password is not None:env["E32_BOB_PASSWORD"]=password
    process=subprocess.Popen(command,env=env)
    return process

def port_for(args,pair,offset):
    return args.port+2*(pair-1)+offset

def template_cleanup(output,run_id):
    for persona in (*CARDS,*(name+'-'+arm for name in CARDS for arm in ('concern','control'))):
        tmp=f'/tmp/emuvista-e32-template-{run_id}-{persona}'
        subprocess.run(['docker','exec',os.getenv('E32_BOB','as155h-bob-10.155.0.30'),
            'sh','-c','case "$1" in /tmp/emuvista-e32-template-*) rm -rf -- "$1";; *) exit 2;; esac','sh',tmp],check=True)
        (output/f'.template-{persona}.ready').unlink(missing_ok=True)
        (output/f'.template-{persona}.lock').unlink(missing_ok=True)

def generate(output,args):
    with ThreadPoolExecutor(max_workers=2) as pool:
        def one(item):
            pair,(persona,scenario)=item
            write(output/f'{pair:02}-case.json',{'pair':pair,'persona':persona,'scenario':scenario,'card':CARDS[persona],
                    'seed':seed(persona,scenario),'fixture':{},'window':120,'prompt':SEED_NOTICE})
            return trial(output,pair,'seed',port_for(args,pair,0)).wait()
        outcomes=list(pool.map(one,enumerate(COMBINATIONS,1)))
    if any(outcomes):raise RuntimeError(f'Seed generation failed: {outcomes}')
    states={}
    for pair,(persona,scenario) in enumerate(COMBINATIONS,1):
        record=json.loads((output/f'{pair:02}-seed.json').read_text())
        state=record['soulState']
        # E32 compares presence versus absence of one concern. Preserve that treatment.
        candidate=max(state['intentions'],key=lambda item:item.get('weight',50))
        assert candidate['status']=='candidate'
        state['intentions']=[candidate]
        evidence=next(entry for entry in state['entries'] if entry['id']==candidate['reflectionId'])['evidence']
        assert evidence and set(evidence)<={entry['id'] for entry in seed(persona,scenario)['entries']}
        states[f'{persona}/{scenario}']=state
    write(output/'seeds.json',states)

def occ(*args,password=None):
    node=os.getenv('E32_CLOUD','as155h-Cloud_Drive-10.155.0.10')
    prefix=['docker','exec','-i',node]
    command=['runuser','-u','www-data','--','php','/var/www/html/occ',*args]
    if password is not None:
        prefix+=['sh','-c','IFS= read -r OC_PASS; export OC_PASS; exec "$@"','sh']
    subprocess.run(prefix+command,input=(password+'\n') if password is not None else None,
                   text=True,capture_output=True,check=True,timeout=40)

def verify_scope(fixture,password):
    username=fixture['username']
    root=f'{CLOUD}/remote.php/dav/files/{username}/'
    raw=cloud(username,password,'-X','PROPFIND','-H','Depth: 1',root)
    hrefs=ElementTree.fromstring(raw).findall('.//{DAV:}href')
    visible=[href.text for href in hrefs if href.text]
    expected=root.split(CLOUD)[1]+fixture['folder']+'/'
    if sorted(visible)!=sorted([root.split(CLOUD)[1],expected]):
        raise RuntimeError(f'Temporary Cloud account has unexpected visible paths: {visible}')
    return visible

def release_marker(command,path):
    resident=os.getenv('E32_BOB','as155h-bob-10.155.0.30')
    flags=['-f'] if command=='rm' else []
    subprocess.run(['docker','exec',resident,command,*flags,'--',path],check=True,capture_output=True,timeout=45)

def pair_run(output,args,pair,persona,scenario,seeds,nonce):
    rng=random.Random(args.seed+pair)
    username=f'e32-{nonce}-{pair:02}'
    password=uuid.uuid4().hex+uuid.uuid4().hex
    children=[]
    handles=None
    account_created=False
    release_file=None
    try:
        occ('user:add','--password-from-env',username,password=password)
        account_created=True
        fixture,handles=prepare_fixture(username,scenario,rng,username)
        visible=verify_scope(fixture,password)
        write(output/f'{pair:02}-scope.json',{'username':username,'visiblePaths':visible,'isolated':True})
        draft=probe(fixture,fixture['draftSha256'],password)
        case={'pair':pair,'persona':persona,'scenario':scenario,'card':CARDS[persona],
                'seed':seeds[f'{persona}/{scenario}'],'fixture':fixture,'window':args.window,'reviewConcerns':args.review_concerns,
                'prompt':(NOTICE+' '+SMOKE_NOTICE if args.phase=='smoke' else NOTICE).replace('{title}',SCENARIOS[scenario][0])}
        if case_factory:=getattr(args,'case_factory',None):
            case=case_factory(case)
        if case.get('worldRelease'):
            release_file=f'/tmp/emuvista-e33-release-{nonce}-{pair:02}'
            case['releaseFile']=release_file
        write(output/f'{pair:02}-case.json',case)
        arms=['concern','control']
        rng.shuffle(arms)
        children=[trial(output,pair,arm,port_for(args,pair,i),password,
                        script=getattr(args, "trial_script", None)) for i,arm in enumerate(arms)]
        until=time.monotonic()+110
        while not all((output/f'{pair:02}-{arm}.ready').exists() for arm in arms):
            if any(child.poll() is not None for child in children) or time.monotonic()>until:
                raise RuntimeError(f'Pair {pair} could not start')
            time.sleep(.5)
        start=round(time.time()*1000)
        release=start+args.release*1000
        clock={'startMs':start,'releaseMs':release,'cutoffMs':start+args.window*1000,
               'releaseLabel':datetime.fromtimestamp(release/1000,ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S（北京时间）')}
        write(output/f'{pair:02}-clock.json',clock)
        time.sleep(max(0,release/1000-time.time()))
        probe(fixture,fixture['draftSha256'],password)
        begin=round(time.time()*1000)
        for attempt in range(3):
            try:
                alice('-X','PUT','--data-binary','@-',handles[2],body=handles[4])
                break
            except subprocess.CalledProcessError as error:
                if attempt==2 or not any(code in (error.stderr or '') for code in ('423','500','502','503','504')):
                    raise
                time.sleep(1+attempt)
        committed=round(time.time()*1000)
        final=probe(fixture,fixture['finalSha256'],password)
        write(output/f'{pair:02}-publication.json',{'draftSha256':draft,'finalSha256':final,'writeStartMs':begin,
            'publishedMs':committed,'verifiedMs':round(time.time()*1000),'silent':True})
        if release_file:
            release_marker('touch',release_file)
        codes=[child.wait() for child in children]
        if any(codes):raise RuntimeError(f'Pair {pair} failed: {codes}')
        if pair_result:=getattr(args,'pair_result',None):
            pair_result(output, case)
        print(f'Pair {pair:02} complete. Draft and final hashes verified.',flush=True)
        return None
    except Exception as error:
        detail=getattr(error,'stderr',None) or ''
        if isinstance(detail,bytes):
            detail=detail.decode(errors='replace')
        write(output/f'{pair:02}-failure.json',{'error':type(error).__name__,'message':str(error),'detail':detail[-1600:]})
        return pair
    finally:
        for child in children:
            if child.poll() is None:child.wait()
        try:
            if release_file:release_marker('rm',release_file)
            if handles:cleanup(handles)
        finally:
            if account_created:occ('user:delete',username)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['seed','smoke','pilot','formal'])
    parser.add_argument('--label',default='')
    parser.add_argument('--port',type=int,default=14100)
    parser.add_argument('--parallel-pairs',type=int,default=6)
    parser.add_argument('--seed',type=int,default=3201)
    parser.add_argument('--seeds',type=Path)
    parser.add_argument('--review-concerns',action='store_true')
    args=parser.parse_args()
    if args.label and not args.label.isalnum():parser.error('Label must be alphanumeric')
    if args.parallel_pairs<1:parser.error('Concurrency must be positive')
    for user in ('ALICE','BOB'):
        if not os.environ.get(f'E32_{user}_PASSWORD'):parser.error(f'Set E32_{user}_PASSWORD')
    args.release,args.window=(90,360) if args.phase=='smoke' else (900,86400)
    output=HERE/'.runtime'/('-'.join(x for x in (args.phase,args.label) if x))
    output.mkdir(parents=True,exist_ok=False)
    nonce=uuid.uuid4().hex[:10]
    combination_order=COMBINATIONS if args.phase=='pilot' else COMBINATIONS*8
    if args.phase=='smoke':combination_order=COMBINATIONS[:2] if args.label=='scoped' else COMBINATIONS[:1]
    if args.phase=='formal':random.Random(args.seed).shuffle(combination_order)
    write(output/'design.json',{'phase':args.phase,'runId':nonce,'releaseSeconds':args.release,'windowSeconds':args.window,
        'rngSeed':args.seed,'reviewConcerns':args.review_concerns,'combinations':combination_order,'notice':NOTICE,'seedNotice':SEED_NOTICE,
        'sourceHashes':{p.name:sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob('*.py'))}})
    try:
        if args.phase=='seed':
            generate(output,args)
            return
        seeds=json.loads((args.seeds or HERE/'.runtime/seed/seeds.json').read_text())
        write(output/'frozen-seeds.json',seeds)
        with ThreadPoolExecutor(max_workers=args.parallel_pairs) as pool:
            jobs=[pool.submit(pair_run,output,args,i,persona,scenario,seeds,nonce)
                  for i,(persona,scenario) in enumerate(combination_order,1)]
            failures=[result for job in jobs if (result:=job.result()) is not None]
        write(output/'status.json',{'failedPairs':failures,'finished':True})
        if failures:raise RuntimeError(f'Failed pairs: {failures}')
    finally:
        template_cleanup(output,nonce)

if __name__=='__main__':main()
