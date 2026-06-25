import re
import os

def clean(fpath, encoding='utf-8'):
    with open(fpath, 'r', encoding=encoding) as f:
        content = f.read()
    content = re.sub(r'<script src="i18n\.js"></script>\s*', '', content)
    content = re.sub(r' data-i18n="[^"]*"', '', content)
    content = re.sub(r'(?s)let currentLang =.*?\}\);\n', '', content)
    with open(fpath, 'w', encoding=encoding) as f:
        f.write(content)

clean(r'f:\project\期末大作业\frontend\index.html', 'utf-8')
clean(r'f:\project\期末大作业\frontend\report.html', 'utf-8')
try:
    clean(r'f:\project\期末大作业\frontend\report_renderer.js', 'utf-8')
except UnicodeDecodeError:
    clean(r'f:\project\期末大作业\frontend\report_renderer.js', 'gbk')
