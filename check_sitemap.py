with open('HOME/tests.py') as f:
    lines = f.readlines()
for i,l in enumerate(lines[1600:1800], 1600):
    if 'sitemap' in l.lower():
        print(i+1, l.rstrip())
