import urllib.request, json
data = json.loads(urllib.request.urlopen('http://qdrant:6333/collections').read())
for col in data.get('result', {}).get('collections', []):
    name = col['name']
    info = json.loads(urllib.request.urlopen('http://qdrant:6333/collections/' + name).read())
    cfg = info['result']['config']['params']['vectors']
    if isinstance(cfg, dict):
        size = cfg.get('size')
        dist = cfg.get('distance')
    else:
        size = 'multi'
        dist = 'n/a'
    pts = info['result'].get('points_count', 0)
    print(f'{name:30s} dim={size!s:>5} dist={dist!s:8s} points={pts}')
