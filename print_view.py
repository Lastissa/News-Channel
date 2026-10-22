with open('HOME/views.py') as f:
    content = f.read()

lines = content.splitlines()
for i,l in enumerate(lines[164:300], 165):
    print(f'{i}: {l}')
