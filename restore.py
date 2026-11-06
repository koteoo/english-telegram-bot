import base64, os, re
text = open('project.txt', encoding='utf-8').read()
blocks = text.split('###FILE### ')[1:]
blocks = [b for b in blocks if '###END###' in b and re.match(r'^[\w./-]+\s*\n', b)]
for b in blocks:
    name, rest = b.split('\n', 1)
    name = name.strip()
    payload = rest.split('###END###')[0]
    payload = ''.join(l.strip() for l in payload.splitlines() if l.strip())
    payload = ''.join(c for c in payload if c.isascii())  # защита от мусора при копировании
    os.makedirs(os.path.dirname(name) or '.', exist_ok=True)
    open(name, 'wb').write(base64.b64decode(payload))
    if name.endswith('.sh'):
        os.chmod(name, 0o755)
print('restored', len(blocks), 'files OK')
