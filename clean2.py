import re

def clean(fpath):
    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    content = re.sub(r'(?s)let currentLang =.*?\}\);\n', '', content)
    # duplicate btn-close
    content = re.sub(r'const btnClose = document.getElementById\(\'btn-close\'\);\n\nconst btnClose = document.getElementById\(\'btn-close\'\);\n', 'const btnClose = document.getElementById(\'btn-close\');\n', content)
    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(content)

clean(r'f:\project\期末大作业\frontend\report_renderer.js')
