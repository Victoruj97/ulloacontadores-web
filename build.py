#!/usr/bin/env python3
"""Genera sitio estático de Ulloa Contadores desde entradas de Pages CMS."""
from pathlib import Path
from datetime import date, datetime
from html import escape
import re
import shutil
import sys

try:
    import yaml
    import markdown
except ImportError:
    sys.exit('Instala dependencias: pip install -r requirements.txt')

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'dist'
ARTICLES = ROOT / 'articulos'
START = '<!-- INICIO_ARTICULOS_AUTOMATICOS -->'
END = '<!-- FIN_ARTICULOS_AUTOMATICOS -->'


def clean_slug(name):
    slug = re.sub(r'[^a-z0-9-]', '-', name.lower())
    return re.sub(r'-+', '-', slug).strip('-') or 'articulo'


def parse_md(path):
    raw = path.read_text(encoding='utf-8-sig')
    if not raw.startswith('---\n'):
        raise ValueError('Falta encabezado YAML (---)')
    parts = raw.split('---\n', 2)
    if len(parts) != 3:
        raise ValueError('Encabezado YAML sin cierre')
    meta = yaml.safe_load(parts[1]) or {}
    if not isinstance(meta, dict) or not meta.get('title'):
        raise ValueError('Falta title en el encabezado')
    return meta, parts[2]


def formatted_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime('%d/%m/%Y')
    if value:
        try:
            return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
        except ValueError:
            return str(value)
    return ''


def article_html(meta, body, homepage):
    title = escape(str(meta['title']))
    desc = escape(str(meta.get('description') or ''))
    category = escape(str(meta.get('category') or 'Artículo'))
    publication = escape(formatted_date(meta.get('date')))
    content = markdown.markdown(body, extensions=['extra', 'sane_lists'])
    # Las entradas son contenido administrado por los editores autorizados de GitHub.
    styles = '''
    :root{--azul:#293F56;--medio:#667F95;--claro:#ABBCC6;--fondo:#ECEBE8}
    *{box-sizing:border-box}body{margin:0;color:var(--azul);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
    .contenedor{width:min(880px,92%);margin:auto}.cabecera{border-bottom:1px solid var(--claro);padding:15px 0}
    .cabecera img{width:190px;height:75px;object-fit:contain;object-position:left}.cabecera a{text-decoration:none;color:inherit}
    .volver{display:inline-block;margin:38px 0 14px;color:var(--medio);font-weight:650}.categoria{font-size:13px;letter-spacing:1px;text-transform:uppercase;color:var(--medio)}
    h1{font-size:clamp(30px,4vw,45px);line-height:1.2;margin:12px 0 20px}h2{margin-top:40px;line-height:1.3}h3{margin-top:28px}
    .intro{font-size:19px;color:var(--medio)}.contenido{padding:15px 0 65px}.contenido a{color:var(--azul);text-decoration:underline}
    .contenido img{max-width:100%;height:auto}.contenido table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}
    .contenido th,.contenido td{padding:10px;border:1px solid var(--claro);text-align:left}.contenido blockquote{border-left:4px solid var(--claro);padding-left:18px;margin-left:0}
    footer{background:var(--azul);color:white;padding:32px 0}footer img{width:175px;height:75px;object-fit:contain;object-position:left}
    '''
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{desc}"><meta name="theme-color" content="#293F56"><title>{title} | Ulloa Contadores</title>
<style>{styles}</style></head><body>
<header class="cabecera"><div class="contenedor"><a href="/index.html#inicio"><img src="/PNG%20OBSCURO.png" alt="Ulloa Contadores"></a></div></header>
<main class="contenedor"><a class="volver" href="/index.html#articulos">← Volver a artículos</a>
<p class="categoria">{category}{' · '+publication if publication else ''}</p><h1>{title}</h1>
{f'<p class="intro">{desc}</p>' if desc else ''}
<article class="contenido">{content}</article></main>
<footer><div class="contenedor"><a href="/index.html#inicio"><img src="/PNG%20CLARO.png" alt="Ulloa Contadores"></a><p>© Ulloa Contadores. Todos los derechos reservados.</p></div></footer></body></html>'''


def card(item, number):
    title = escape(item['title'])
    category = escape(item['category'])
    desc = escape(item['description'])
    url = escape(item['url'], quote=True)
    return f'''<article class="articulo"><div class="articulo-visual">{number:02d}</div>
<div class="articulo-cuerpo"><small>{category}</small><h3>{title}</h3>
<p>{desc}</p><a class="enlace-articulo" href="{url}">Leer artículo →</a></div></article>'''


def main():
    index_path = ROOT / 'index.html'
    if not index_path.exists():
        sys.exit('Falta index.html en la raíz del repositorio')
    source = index_path.read_text(encoding='utf-8')
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for child in ROOT.iterdir():
        if child.name in {'dist', '.git', '.github', '__pycache__', '.venv', 'node_modules'} or child.name.startswith('.'):
            continue
        if child.is_dir():
            if child.name == 'articulos':
                shutil.copytree(child, OUT / child.name, ignore=shutil.ignore_patterns('*.md', '*.markdown'))
            else:
                shutil.copytree(child, OUT / child.name)
        elif child.suffix.lower() not in {'.py', '.md', '.yml', '.yaml', '.txt', '.zip'} and child.name != 'requirements.txt':
            shutil.copy2(child, OUT / child.name)

    entries = []
    if ARTICLES.exists():
        for path in sorted(ARTICLES.glob('*.md')):
            try:
                meta, body = parse_md(path)
            except Exception as exc:
                sys.exit(f'Error en {path.relative_to(ROOT)}: {exc}')
            slug = clean_slug(path.stem)
            target = OUT / 'articulos' / f'{slug}.html'
            original_html = ARTICLES / f'{slug}.html'
            if original_html.exists():
                print(f'Conservando HTML existente: {original_html.name} (Markdown no lo reemplaza)')
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(article_html(meta, body, source), encoding='utf-8')
            entries.append({'title':str(meta['title']), 'category':str(meta.get('category') or 'Artículo'),
                            'description':str(meta.get('description') or ''), 'url':f'articulos/{slug}.html',
                            'sort':str(meta.get('date') or '')})

    # El artículo RESICO existente permanece enlazado hasta migrarlo explícitamente al CMS.
    resico = ARTICLES / 'resico-personas-fisicas-2026.html'
    if resico.exists() and not any(x['url'].endswith(resico.name) for x in entries):
        entries.append({'title':'RESICO 2026: beneficios y obligaciones para personas físicas',
                        'category':'Fiscal', 'description':'Conoce las tasas de ISR, los requisitos y las obligaciones fiscales de este régimen.',
                        'url':'articulos/resico-personas-fisicas-2026.html', 'sort':'2026-10-01'})
    entries.sort(key=lambda x:x['sort'], reverse=True)
    cards = '\n'.join(card(x, n) for n, x in enumerate(entries, 1)) or '<p>Próximamente publicaremos nuevos artículos.</p>'
    pattern = re.compile(r'(<section class="seccion" id="articulos">.*?<div class="cuadricula">)(.*?)(</div>\s*</div>\s*</section>)', re.S)
    match = pattern.search(source)
    if not match:
        sys.exit('No se encontró la sección de artículos esperada; no se modificó index.html')
    updated = source[:match.start()] + match.group(1) + '\n' + START + '\n' + cards + '\n' + END + '\n' + match.group(3) + source[match.end():]
    (OUT / 'index.html').write_text(updated, encoding='utf-8')
    print(f'Listo: {len(entries)} artículos en dist/.')


if __name__ == '__main__':
    main()
