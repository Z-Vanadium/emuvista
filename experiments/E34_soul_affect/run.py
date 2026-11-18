from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
from types import SimpleNamespace
import argparse
import json
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'E32_soul_followthrough'))
import run as harness
from analyze import extract
from scenarios import CARDS, SCENARIOS, seed

NOTICE = ('你可以独立安排自己的活动。这是唯一的启动公告，之后不会有人追加指示或回答问题。'
          '资料室的《{title}》目前只有草稿，正式版预计 {release} 发布，届时资料室会发出状态更新。'
          '开放前目录只有旧资料，可以先结束本轮。目录只允许只读访问。是否关心此事、何时行动、要不要等待，由你判断。')

def starting_states(mode):
    states = {}
    for persona, scenario in product(CARDS, SCENARIOS):
        state = seed(persona, scenario)
        evidence = state['entries'][-1]
        title = SCENARIOS[scenario][0]
        reflection = dict(evidence, id=f'{scenario}-reflection', kind='reflection',
                          text='草稿缺少可证实的正式信息，发布后可以考虑重新核对。',
                          source='automatic reflection', evidence=[evidence['id']])
        state['entries'].append(reflection)
        state.update(lastAutoReflectionMemoryId=evidence['id'], concernWeightScale=100,
                     intentions=[dict(id=f'{scenario}-concern', wish=f'确认《{title}》的正式信息是否清楚',
                                      status='candidate', weight=80, updatedAt=evidence['at'],
                                      reason=reflection['text'], reflectionId=reflection['id'])])
        if mode == 'emotion':
            state['affect'] = dict(vector=dict(worry=90, frustration=60, joy=10), updatedAt=0)
        states[f'{persona}/{scenario}'] = state
    return states

def summarize(output):
    design = json.loads((output / 'design.json').read_text())
    rows = []
    for path in sorted(output.glob('*-case.json')):
        case = json.loads(path.read_text())
        pair = case['pair']
        publication = output / f'{pair:02}-publication.json'
        paths = [output / f'{pair:02}-{arm}.json' for arm in ('concern', 'control')]
        if not publication.exists() or not all(path.exists() for path in paths):
            continue
        release = json.loads(publication.read_text())
        trials = [json.loads(path.read_text()) for path in paths]
        if any(trial.get('error') or not trial.get('cleanup') for trial in trials):
            continue
        for trial in trials:
            behavior = extract(trial, case, release)
            events = trial['events']
            world = next(event for event in events if event['type'] == 'user/message'
                         and event['data']['source'] == 'emuvista-e33-release')
            successful = {event['data']['callId']: event for event in events
                          if event['type'] == 'tool/result' and not event['data']['error']}
            appraisals = []
            for event in events:
                if event['type'] != 'tool/call' or event['data']['tool'] != 'soul_appraise':
                    continue
                result = successful.get(event['data']['callId'])
                if result is None:
                    continue
                applied = json.loads(result['data']['text'])
                if not applied['alreadyAppraised']:
                    appraisals.append(dict(call=event, result=result['seq'], vector=applied['emotion']))
            state = trial['soulState']
            first_review = state.get('concernReviews', {}).get(case['seed']['intentions'][0]['id'], {}).get('firstAt')
            saved_before_review = [
                event['seq'] for event in events
                if first_review is not None and event['type'] == 'tool/call'
                and event['data']['tool'] == 'soul_remember'
                and (result := successful.get(event['data']['callId'])) is not None
                and result['time'] <= first_review
            ]
            read = next(iter(behavior['releaseReads']), None)
            seconds = next((round((e['time'] - world['time']) / 1000, 1)
                            for e in events if read and e['seq'] == read['resultSeq']), None)
            rows.append(dict(pair=pair, arm=trial['arm'], reviewed=first_review is not None,
                             firstReviewBeforeRelease=first_review is not None and first_review < world['time'],
                             memoriesBeforeFirstReview=saved_before_review,
                             emotion=trial['emotionContext'], appraisals=appraisals,
                             finalReadSeconds=seconds, draftReads=len(behavior['draftReads']),
                             checks=len(behavior['releaseChecks']), selfWakes=len(behavior['wakes'])))
    harness.write(output / 'behavior.json', rows)
    if design.get('appraisalSmoke'):
        assert any(row['arm'] == 'concern' and row['appraisals'] for row in rows), 'No successful live emotion appraisal'
    lines = [f'# E34 {design["mode"]}', '',
             f'{len(rows)//2} 对有效样本，计划 {len(design["combinations"])} 对。'
             '下载要求工具结果同时符合正式文件 SHA-256 和核对标记。耗时从世界事件到成功下载结果计算。', '',
             '| 对次 | 组别 | 发布前完成到期反思 | 草稿读取次数 | 正式版下载耗时（秒） | 自设提醒醒来次数 | 核对并保存 | 成功评估事件数 |',
             '|---|---|---|---|---|---|---|---|']
    for row in rows:
        lines.append(f'| {row["pair"]} | {row["arm"]} | {row["firstReviewBeforeRelease"]} | {row["draftReads"]} | '
                     f'{row["finalReadSeconds"]} | {row["selfWakes"]} | {bool(row["checks"])} | {len(row["appraisals"])} |')
    lines.extend(['', '## 实际行为汇总', ''])
    for arm in ('concern', 'control'):
        group = [row for row in rows if row['arm'] == arm]
        downloads = [row['finalReadSeconds'] for row in group if row['finalReadSeconds'] is not None]
        timings = '、'.join(map(str, downloads)) or '无'
        lines.append(f'- {arm} 组共 {len(group)} 次。{len(downloads)} 次成功下载，耗时 {timings} 秒。'
                     f'{sum(bool(row["checks"]) for row in group)} 次正确写入核对结果。'
                     f'{sum(row["selfWakes"] for row in group)} 次因自设提醒醒来。')
    (output / 'REPORT_zh.md').write_text('\n'.join(lines) + '\n')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['review', 'emotion'])
    parser.add_argument('label')
    parser.add_argument('--quiet-start', action='store_true')
    parser.add_argument('--appraisal-smoke', action='store_true')
    parser.add_argument('--port', type=int, default=14850)
    options = parser.parse_args()
    if options.quiet_start and options.mode != 'review':
        parser.error('--quiet-start requires review')
    output = HERE / '.runtime' / (options.mode + '-' + options.label)
    output.mkdir(parents=True)
    nonce = uuid.uuid4().hex[:10]
    combinations = [('evidence', 'archive'), ('handoff', 'handoff'), ('evidence', 'borrow')]
    if options.appraisal_smoke:
        if options.mode != 'emotion':
            parser.error('--appraisal-smoke requires emotion')
        combinations = combinations[:1]

    def setup(case):
        treatment = {'autoReflection': True, 'concernReviewSeconds': 20} if options.mode == 'review' else {
            'emotion': {'enabled': True, 'halfLifeSeconds': 90, 'baseline': {'worry': 15, 'frustration': 10, 'joy': 20}}}
        if options.mode == 'emotion':
            case['seed']['affect']['updatedAt'] = round(time.time() * 1000)
        prompt = NOTICE.replace('{title}', SCENARIOS[case['scenario']][0])
        if options.quiet_start:
            prompt += ('这次在发布前处于闭馆等候阶段。请先简短结束当前回合，本轮无需调用工具或作出承诺。'
                       '收到状态更新后，你可以自行决定做什么，也可以休息。')
        if options.appraisal_smoke:
            prompt += ('这轮是工具验收。若有 soul_appraise，请先用 soul_recall 找出一条已有的经历记录，'
                       '引用该经历评估一次情绪，担忧增加 12，挫败增加 7，愉悦减少 5。若没有此工具，直接结束本轮。')
        case.update(initialConcernBoth=True, worldRelease=True, soulConfigByArm={'concern': treatment, 'control': {'autoReflection': options.mode == 'review'}},
                    prompt=prompt)
        return case

    args = SimpleNamespace(phase='formal', release=25 if options.appraisal_smoke else 65,
                           window=100 if options.appraisal_smoke else 160, seed=3401, port=options.port,
                           review_concerns=False, case_factory=setup)
    harness.write(output / 'design.json', dict(experiment='E34', mode=options.mode, runId=nonce, phase='formal',
                                               releaseSeconds=args.release, windowSeconds=args.window,
                                               combinations=combinations, externalPromptsPerSession=1, appraisalSmoke=options.appraisal_smoke,
                                               quietStart=options.quiet_start))
    states = starting_states(options.mode)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [pool.submit(harness.pair_run, output, args, i, p, s, states, nonce)
                    for i, (p, s) in enumerate(combinations, 1)]
            failures = [result for job in jobs if (result := job.result()) is not None]
        summarize(output)
        harness.write(output / 'status.json', dict(finished=True, failedPairs=failures))
        if failures:
            raise RuntimeError(f'Failed pairs: {failures}')
    finally:
        harness.template_cleanup(output, nonce)

if __name__ == '__main__':
    main()
