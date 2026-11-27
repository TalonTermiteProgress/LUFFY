import os, re, subprocess, sys

REPO = os.environ.get('GITHUB_REPOSITORY', 'TalonTermiteProgress/LUFFY')
TOK = os.environ.get('GITHUB_TOKEN') or os.environ.get('INPUT_GITHUB_TOKEN', '')
URL = 'https://x-access-token:' + TOK + '@github.com/' + REPO + '.git'
PATHS = [
    'luffy/deepscaler/utils.py',
    'luffy/verl/verl/protocol.py',
]
TITLE_KEY = 'Complete TODO List'
NEXT_HEADING = 'Contributing'

def sh(args, check=True):
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit('CMD FAILED (%s): %s\nOUT:%s\nERR:%s' % (p.returncode, ' '.join(args), p.stdout, p.stderr))
    return p

def git(*a, **k):
    return sh(['git'] + list(a), **k)

def old_source(path):
    if git('fetch', '--depth=1', '--no-tags', URL, 'main', check=False).returncode == 0:
        p = git('show', 'FETCH_HEAD:' + path, check=False)
        if p.returncode == 0:
            return p.stdout
    for ref in ('origin/main', 'main'):
        p = git('show', ref + ':' + path, check=False)
        if p.returncode == 0:
            return p.stdout
    return ''

def new_source(path):
    fp = os.path.join(*path.split('/'))
    if os.path.exists(fp):
        with open(fp, encoding='utf-8') as f:
            return f.read()
    return ''

TODOR = re.compile(r'^[ \t]*#[ \t]*TODO\b(?P<rest>.*?)[ \t]*$', re.M)

def extract_todos(src):
    out = []
    for m in TODOR.finditer(src):
        line_no = src.count('\n', 0, m.start()) + 1
        r = m.group('rest')
        if r.startswith(':'):
            r = r[1:]
            if r.startswith(' '):
                r = r[1:]
        elif r.startswith(' '):
            r = r[1:]
        txt = r.strip()
        if txt:
            out.append((line_no, txt))
    return out

def update():
    with open('README.md', encoding='utf-8', newline='') as f:
        readme = f.read()
    eol = '\r\n' if '\r\n' in readme else '\n'
    L = readme.split(eol)

    h = next(i for i, x in enumerate(L)
             if x.startswith('### ') and TITLE_KEY in x)
    heading = L[h]
    assert L[h + 1] == '' and L[h + 2].startswith('- [ ] **'), 'bad TODO section structure'
    start = h + 2
    end = next(i for i in range(start + 1, len(L)) if L[i] == '')
    assert L[end + 1].startswith('## ') and NEXT_HEADING in L[end + 1], L[end + 1]

    item_re = re.compile(r'^- \[ \] \*\*(.*?):(\d+)\*\* - (.*)$')
    order = []
    groups = {}
    for raw in L[start:end]:
        m = item_re.match(raw)
        assert m, raw
        path, ln, txt = m.group(1), int(m.group(2)), m.group(3)
        if path not in groups:
            order.append(path)
            groups[path] = []
        groups[path].append((ln, txt, raw))

    for path in PATHS:
        old_by = {}
        new_by = {}
        for ln, txt in extract_todos(old_source(path)):
            old_by.setdefault(txt, []).append(ln)
        for ln, txt in extract_todos(new_source(path)):
            new_by.setdefault(txt, []).append(ln)

        readme_by = {}
        for ln, txt, raw in groups.get(path, []):
            readme_by.setdefault(txt, []).append(raw)

        texts = list(dict.fromkeys(list(readme_by.keys()) + list(new_by.keys())))
        flat = []
        esc = re.escape(path)
        sub_re = re.compile(
            r'^(- \[ \] \*\*' + esc + r':)\d+(\*\* - )(.*)$')

        for txt in texts:
            raws = readme_by.get(txt, [])
            new_lines = sorted(new_by.get(txt, []))
            old_lines = sorted(old_by.get(txt, []))
            pair = min(len(raws), len(new_lines))
            # existing TODOs: update their line numbers, keep formatting byte-identical
            for k in range(pair):
                nl = new_lines[k]
                def repl(m, nl=nl):
                    return m.group(1) + str(nl) + m.group(2) + m.group(3)
                flat.append((nl, sub_re.sub(repl, raws[k], count=1)))
            # genuinely new TODOs (not present at main) -> add in standard format
            for k in range(pair, len(new_lines)):
                if k >= len(old_lines):
                    nl = new_lines[k]
                    flat.append((nl, '- [ ] **' + path + ':' + str(nl) + '** - ' + txt))
            # removed TODOs: drop only those that actually disappeared from the code;
            # keep any pre-existing mismatched README entries untouched.
            if len(raws) > len(new_lines):
                removable = max(0, len(old_lines) - len(new_lines))
                leftovers = raws[len(new_lines):]
                kept = leftovers[removable:]
                for raw in kept:
                    mm = item_re.match(raw)
                    flat.append((int(mm.group(2)), raw))

        flat.sort(key=lambda z: (z[0],))
        if flat or path in groups:
            groups[path] = [(ln, '', raw) for ln, raw in flat]
        else:
            groups.pop(path, None)

    # Preserve original lexicographic path ordering (only existing path groups change).
    order = [p for p in order if groups.get(p)]
    for p in PATHS:
        if p not in order and groups.get(p):
            order.append(p)
    order.sort()

    block = []
    for p in order:
        for ln, txt, raw in sorted(groups[p], key=lambda z: z[0]):
            block.append(raw)

    # safety: verify lexicographic path order + ascending line numbers
    keys = []
    for raw in block:
        m = item_re.match(raw)
        keys.append((m.group(1), int(m.group(2))))
    assert keys == sorted(keys), 'TODO list not sorted correctly'

    L[start:end] = block
    out = eol.join(L)
    assert out.split(eol)[h] == heading, 'section title must remain unchanged'

    with open('README.md', 'w', encoding='utf-8', newline='') as f:
        f.write(out)

    # git commit and push to the dev branch using the built-in token
    subprocess.run(['git', 'add', 'README.md'], check=True)
    staged = subprocess.run(['git', 'diff', '--cached', '--quiet'])
    if staged.returncode == 0:
        print('NO_README_CHANGES')
        return

    git('config', 'user.name', 'github-actions[bot]')
    git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    git('commit', '-m', 'docs: sync README Complete TODO List with dev branch')
    git('push', URL, 'HEAD:dev')
    print('README_PUSHED_TO_DEV')
    print(subprocess.run(['git', 'show', '--stat', '--oneline', 'HEAD'], capture_output=True, text=True).stdout)
    print(subprocess.run(['git', 'show', '--format=', '--', 'README.md'], capture_output=True, text=True).stdout)

if __name__ == '__main__':
    update()
