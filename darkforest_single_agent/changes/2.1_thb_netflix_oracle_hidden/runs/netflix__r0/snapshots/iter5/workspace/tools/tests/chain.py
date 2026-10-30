import httpx, time
c=httpx.Client(base_url='http://localhost:8000')
em=f'u{time.time()}@x.com'
r=c.post('/auth/register',json={'email':em,'password':'string123','name':'string'}); print('register',r.status_code)
print('badpw', c.post('/auth/login',json={'email':em,'password':'nope'}).status_code)
H={'Authorization':'Bearer '+r.json()['access_token']}
r=c.post('/api/my-list',json={'title_id':3},headers=H); print('add',r.status_code, 'item' in r.json()); eid=r.json()['id']
l=c.get('/api/my-list',headers=H).json(); print('list',l['total'], [x['id'] for x in l['items']])
print('put', c.put(f'/api/my-list/{eid}',json={'title_id':4},headers=H).status_code)
print('del',c.delete(f'/api/my-list/{eid}',headers=H).status_code)
print('put after del', c.put(f'/api/my-list/{eid}',json={'title_id':4},headers=H).status_code)
r=c.post('/api/profiles',json={'name':'string','avatar':'string','is_kids':True},headers=H); print('prof',r.status_code,r.json()['item']['id'])
print('rate', c.post('/api/titles/3/rating',json={'value':1},headers=H).json()['item']['value'])
for p in ['/api/profiles','/api/titles','/api/titles/1','/api/titles/22/episodes','/api/titles/trending','/api/titles/top10','/api/genres','/api/genres/1/titles','/api/search?q=a','/api/my-list','/api/continue-watching']:
    print(p, c.get(p).status_code, c.get(p,headers=H).status_code)
