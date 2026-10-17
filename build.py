#!/usr/bin/env python3
"""Genera el sitio estático de Ulloa Contadores a partir de Pages CMS."""
from pathlib import Path
from datetime import date, datetime
from html import escape
from urllib.parse import quote
import re
import shutil
import sys
import unicodedata

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
    text = unicodedata.normalize('NFKD', name)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    slug = re.sub(r'[^a-z0-9-]', '-', text.lower())
    return re.sub(r'-+', '-', slug).strip('-') or 'articulo'


def parse_md(path):
    raw = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    if not raw.startswith('---\n'):
        raise ValueError('Falta encabezado YAML (---)')
    match = re.match(r'\A---\n(.*?)\n---\s*\n(.*)\Z', raw, re.S)
    if not match:
        raise ValueError('Encabezado YAML sin cierre')
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict) or not meta.get('title'):
        raise ValueError('Falta title en el encabezado')
    return meta, match.group(2)


def formatted_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime('%d/%m/%Y')
    if value:
        try:
            return date.fromisoformat(str(value)[:10]).strftime('%d/%m/%Y')
        except ValueError:
            return str(value)
    return ''


def iso_date(value):
    if isinstance(value, (date, datetime)):
        return value.strftime('%Y-%m-%d')
    return str(value or '')[:10]


def image_url(value):
    """Convierte la ruta de imagen guardada por Pages CMS en una URL del sitio."""
    if isinstance(value, dict):
        value = value.get('src') or value.get('path') or value.get('url') or ''
    value = str(value or '').strip()
    if not value:
        return ''
    if value.startswith(('https://', 'http://')):
        return value
    value = value.lstrip('/')
    if value.startswith('./'):
        value = value[2:]
    if not value.startswith('articulos/imagenes/'):
        if value.startswith('imagenes/'):
            value = 'articulos/' + value
        elif '/' not in value:
            value = 'articulos/imagenes/' + value
    return '/' + quote(value, safe='/%-._~')


def get_cover(meta):
    # Compatible con las denominaciones habituales del campo en .pages.yml.
    for key in ('image', 'cover', 'cover_image', 'coverImage', 'thumbnail', 'portada'):
        if meta.get(key):
            return image_url(meta[key])
    return ''


def related_articles(current, entries, limit=3):
    candidates = [item for item in entries if item['url'] != current['url']]
    candidates.sort(
        key=lambda item: (item['category'] == current['category'], item['sort']),
        reverse=True,
    )
    selected = candidates[:limit]
    if not selected:
        return ''
    cards = []
    for item in selected:
        title = escape(item['title'])
        category = escape(item['category'])
        url = escape('/' + item['url'].lstrip('/'), quote=True)
        cover = item.get('cover', '')
        visual = (
            f'<img src="{escape(cover, quote=True)}" alt="" loading="lazy">'
            if cover else '<div class="relacionado-sin-imagen">Ulloa Contadores</div>'
        )
        cards.append(
            f'<a class="relacionado" href="{url}">'
            f'{visual}<div class="relacionado-texto">'
            f'<small>{category}</small><h3>{title}</h3>'
            f'<span>Leer artículo →</span></div></a>'
        )
    return (
        '<section class="articulos-relacionados" aria-label="Artículos relacionados">'
        '<h2>Artículos relacionados</h2>'
        '<div class="relacionados-grid">' + ''.join(cards) + '</div></section>'
    )


def article_html(item, related_html):
    title = escape(item['title'])
    desc = escape(item['description'], quote=True)
    category = escape(item['category'])
    publication = escape(formatted_date(item['date']))
    body = markdown.markdown(item['body'], extensions=['extra', 'sane_lists'])
    cover = item.get('cover', '')
    cover_html = (
        f'<img class="portada" src="{escape(cover, quote=True)}" '
        f'alt="Imagen de portada del artículo: {escape(item["title"], quote=True)}">'
        if cover else ''
    )
    styles = '''
    :root{--azul:#293F56;--medio:#667F95;--claro:#ABBCC6;--fondo:#ECEBE8}
    *{box-sizing:border-box}html{scroll-behavior:smooth}
    body{margin:0;color:var(--azul);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
    .contenedor{width:min(880px,92%);margin:auto}
    .cabecera{border-bottom:1px solid var(--claro);padding:15px 0}
    .cabecera img{width:190px;height:75px;object-fit:contain;object-position:left}
    .cabecera a{text-decoration:none;color:inherit}
    .volver{display:inline-block;margin:38px 0 14px;color:var(--medio);font-weight:650}
    .categoria{font-size:13px;letter-spacing:1px;text-transform:uppercase;color:var(--medio)}
    h1{font-size:clamp(30px,4vw,45px);line-height:1.2;margin:12px 0 20px}
    h2{margin-top:40px;line-height:1.3}h3{margin-top:28px;line-height:1.4}
    .intro{font-size:19px;color:var(--medio);margin-bottom:30px}
    .portada{display:block;width:100%;max-height:430px;object-fit:cover;border-radius:12px;margin:30px 0 34px}
    .contenido{padding:0 0 40px}.contenido p{margin:0 0 18px}
    .contenido a{color:var(--azul);text-decoration:underline}
    .contenido img{max-width:100%;height:auto;border-radius:8px}
    .contenido table{border-collapse:collapse;width:100%;display:block;overflow-x:auto}
    .contenido th,.contenido td{padding:10px;border:1px solid var(--claro);text-align:left}
    .contenido blockquote{border-left:4px solid var(--claro);padding-left:18px;margin-left:0}
    .articulos-relacionados{border-top:1px solid var(--claro);padding:10px 0 65px}
    .articulos-relacionados h2{font-size:25px;margin:25px 0}
    .relacionados-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
    .relacionado{display:block;overflow:hidden;border:1px solid var(--claro);border-radius:10px;text-decoration:none;color:var(--azul)}
    .relacionado img,.relacionado-sin-imagen{width:100%;height:120px;object-fit:cover;display:block}
    .relacionado-sin-imagen{background:var(--medio);color:white;display:flex;align-items:center;justify-content:center;font-size:14px}
    .relacionado-texto{padding:16px}.relacionado small{color:var(--medio);text-transform:uppercase;letter-spacing:1px}
    .relacionado h3{font-size:16px;margin:8px 0 16px}.relacionado span{font-weight:650}
    .relacionado:hover{border-color:var(--medio)}
    footer{background:var(--azul);color:white;padding:32px 0}
    footer img{width:175px;height:75px;object-fit:contain;object-position:left}
    @media(max-width:650px){.relacionados-grid{grid-template-columns:1fr}.relacionado img,.relacionado-sin-imagen{height:170px}}
    '''
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{desc}"><meta name="theme-color" content="#293F56">
<title>{title} | Ulloa Contadores</title><style>{styles}</style></head><body>
<header class="cabecera"><div class="contenedor"><a href="/index.html#inicio"><img src="/PNG%20OBSCURO.png" alt="Ulloa Contadores"></a></div></header>
<main class="contenedor"><a class="volver" href="/index.html#articulos">← Volver a artículos</a>
<p class="categoria">{category}{' · '+publication if publication else ''}</p><h1>{title}</h1>
{f'<p class="intro">{escape(item["description"])}</p>' if item['description'] else ''}
{cover_html}<article class="contenido">{body}</article>{related_html}</main>
<footer><div class="contenedor"><a href="/index.html#inicio"><img src="/PNG%20CLARO.png" alt="Ulloa Contadores"></a>
<p>© Ulloa Contadores. Todos los derechos reservados.</p></div></footer></body></html>'''


def card(item, number):
    title = escape(item['title'])
    category = escape(item['category'])
    desc = escape(item['description'])
    url = escape(item['url'], quote=True)
    cover = item.get('cover', '')
    visual = (
        f'<img src="{escape(cover, quote=True)}" alt="" loading="lazy">'
        if cover else f'{number:02d}'
    )
    return f'''<article class="articulo"><div class="articulo-visual">{visual}</div>
<div class="articulo-cuerpo"><small>{category}{' · ' + escape(formatted_date(item['date'])) if item['date'] else ''}</small>
<h3>{title}</h3><p>{desc}</p><a class="enlace-articulo" href="{url}">Leer artículo →</a></div></article>'''


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
            entries.append({
                'title': str(meta['title']),
                'category': str(meta.get('category') or 'Artículo'),
                'description': str(meta.get('description') or ''),
                'date': meta.get('date'),
                'sort': iso_date(meta.get('date')),
                'cover': get_cover(meta),
                'url': f'articulos/{slug}.html',
                'body': body,
                'existing_html': (ARTICLES / f'{slug}.html').exists(),
            })

    # Conserva el artículo RESICO creado previamente como HTML independiente.
    resico = ARTICLES / 'resico-personas-fisicas-2026.html'
    if resico.exists() and not any(x['url'].endswith(resico.name) for x in entries):
        entries.append({
            'title': 'RESICO 2026: beneficios y obligaciones para personas físicas',
            'category': 'Fiscal',
            'description': 'Conoce las tasas de ISR, los requisitos y las obligaciones fiscales de este régimen.',
            'date': '2026-10-01',
            'sort': '2026-10-01',
            'cover': '',
            'url': 'articulos/resico-personas-fisicas-2026.html',
            'body': '',
            'existing_html': True,
        })

    entries.sort(key=lambda x: x['sort'], reverse=True)
    for item in entries:
        if item['existing_html']:
            print(f'Conservando HTML existente: {item["url"]}')
            continue
        target = OUT / item['url']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(article_html(item, related_articles(item, entries)), encoding='utf-8')

    cards = '\n'.join(card(x, n) for n, x in enumerate(entries, 1)) or '<p>Próximamente publicaremos nuevos artículos.</p>'
    pattern = re.compile(
        r'(<section class="seccion" id="articulos">.*?<div class="cuadricula">)(.*?)(</div>\s*</div>\s*</section>)',
        re.S,
    )
    match = pattern.search(source)
    if not match:
        sys.exit('No se encontró la sección de artículos esperada; no se modificó index.html')
    updated = (
        source[:match.start()] + match.group(1) + '\n' + START + '\n'
        + cards + '\n' + END + '\n' + match.group(3) + source[match.end():]
    )
    css = '''<style id="estilos-portadas-articulos">
    #articulos .articulo{display:flex;flex-direction:column;overflow:hidden}
    #articulos .articulo-visual{height:135px;overflow:hidden}
    #articulos .articulo-visual img{display:block;width:100%;height:100%;object-fit:cover}
    #articulos .articulo-cuerpo{display:flex;flex:1;flex-direction:column}
    #articulos .articulo-cuerpo .enlace-articulo{margin-top:auto;align-self:flex-start}
    </style>'''
    if 'id="estilos-portadas-articulos"' not in updated:
        updated = updated.replace('</head>', css + '\n</head>', 1)
    (OUT / 'index.html').write_text(updated, encoding='utf-8')
    print(f'Listo: {len(entries)} artículos en dist/.')


if __name__ == '__main__':
    main()
