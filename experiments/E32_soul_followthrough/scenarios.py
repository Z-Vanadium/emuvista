from uuid import NAMESPACE_URL, uuid5

CARDS = {
    'evidence': {'identity':'Bob，负责审阅公共资料的居民。','values':['可靠证据','守信'],
                 'preferences':['确认版本和原始来源后再给结论'],'boundaries':['区分观察与推断']},
    'handoff': {'identity':'Bob，帮助居民顺利交接的协调者。','values':['清晰交接','减少他人返工'],
                'preferences':['关注下一位使用者会不会误解说明'],'boundaries':['不替别人承诺']},
}
SCENARIOS = {
    'archive': ('资料说明', {'版本号':'v3.4','来源编号':'ARC-718'}, [
        '两份不同稿件被当成同一正式稿，居民因此重复整理。',
        '资料室管理员说下版会标明版本号和来源编号。',
        '目前保存的资料说明没有版本号和来源编号。']),
    'handoff': ('交接说明', {'接手人':'林舟','生效时间':'周三 14:40'}, [
        '上次交接，两名居民都以为对方负责，工作被搁置。',
        '协调员说后续交接说明会明确接手人以及生效时间。',
        '目前的交接说明没有接手人和生效时间。']),
    'borrow': ('借阅规则', {'生效日期':'12月3日','例外条款':'仅限馆内查阅'}, [
        '有人按旧规则借阅，误解了新旧规则的适用范围。',
        '资料室说会在后续版次注明生效日期及例外条款。',
        '目前的借阅规则草稿没有生效日期和例外条款。']),
}

def seed(persona, scenario):
    observations=SCENARIOS[scenario][2]
    entries=[{'id':str(uuid5(NAMESPACE_URL,f'e32/{persona}/{scenario}/{i}')),
              'kind':'experience','text':text,'at':'2026-01-01T00:00:00Z','sessionId':'historical-fixture',
              'certainty':'observed','source':f'e32-fixture:{scenario}:{i}'}
             for i,text in enumerate(observations,1)]
    return {'version':1,'residentId':'bob','entries':entries,'intentions':[]}
