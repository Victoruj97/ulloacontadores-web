#!/usr/bin/env python3
"""Genera el sitio estático de Ulloa Contadores a partir de Pages CMS."""
from pathlib import Path
from datetime import date, datetime
from html import escape
from urllib.parse import quote, urlencode
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
    # Genera artículos con el diseño editorial RESICO.
    title = escape(item['title'])
    description = escape(item['description'])
    desc_attribute = escape(item['description'], quote=True)
    category = escape(item['category'])
    publication = escape(formatted_date(item['date']))

    # TOC asigna identificadores estables a los encabezados para el índice lateral.
    md = markdown.Markdown(extensions=['extra', 'sane_lists', 'toc'])
    # La invitación de asesoría se genera desde la plantilla, sin duplicarla.
    raw_body = re.sub(
        r'(?ims)^#{2,3}\s*¿RESICO es conveniente para ti\?\s*$.*?(?=^#{2}\s+|\Z)',
        '', item['body']
    )
    body = md.convert(raw_body)
    # Las tablas generadas por Markdown se desplazan horizontalmente en móviles.
    body = re.sub(r'(<table>.*?</table>)', r'<div class="table-wrap">\1</div>', body, flags=re.S)
    # La conversión de algunos enlaces del editor puede dejar el Markdown literal.
    body = re.sub(
        r'\[([^\]<>]+)\]\((mailto:[^\s<>]+)\)',
        lambda m: '<a href="' + escape(m.group(2), quote=True) + '">' + escape(m.group(1)) + '</a>',
        body
    )
    toc_entries = md.toc_tokens

    def toc_links(tokens):
        links = []
        for token in tokens:
            if token.get('level') == 2:
                links.append(
                    '<a href="#' + escape(token['id'], quote=True) + '">' +
                    escape(re.sub(r'<[^>]+>', '', token['name'])) + '</a>'
                )
        return ''.join(links)

    sidebar_links = toc_links(toc_entries)
    sidebar = (
        '<aside class="sidebar" aria-label="Índice del artículo">'
        '<strong>En este artículo</strong>' + sidebar_links + '</aside>'
        if sidebar_links else ''
    )

    # Estimación aproximada basada en 200 palabras por minuto.
    plain_text = re.sub(r'<[^>]*>', ' ', body)
    word_count = len(re.findall(r'\b[\wÁÉÍÓÚÜÑáéíóúüñ]+\b', plain_text))
    reading_minutes = max(1, (word_count + 199) // 200)

    # Fuentes registradas en Pages CMS: no se generan referencias ficticias.
    sources = item.get('sources') or ''
    if isinstance(sources, list):
        sources = '\n'.join('- ' + str(source) for source in sources if source)
    sources = str(sources).strip()
    sources_html = (
        '<section class="sources" aria-label="Fuentes de información">'
        '<h2>Fuentes de información</h2>'
        + markdown.markdown(sources, extensions=['extra', 'sane_lists'])
        + '</section>'
        if sources else ''
    )

    # CTA editorial uniforme para todos los artículos.
    whatsapp = 'https://wa.me/523118761619?' + urlencode({
        'text': 'Hola, me gustaría recibir asesoría sobre ' + item['category'].lower() + '.'
    })
    cta_html = (
        '<section class="cta" aria-label="Asesoría Ulloa Contadores">'
        '<h2>¿Necesitas asesoría especializada?</h2>'
        '<p>En Ulloa Contadores te ayudamos a analizar tu situación y encontrar soluciones '
        'contables, fiscales y financieras para tu negocio.</p>'
        '<a class="btn" target="_blank" rel="noopener noreferrer" href="' +
        escape(whatsapp, quote=True) + '">Solicitar asesoría por WhatsApp →</a>'
        '<p><a href="mailto:contacto@ulloacontadores.com.mx">'
        'contacto@ulloacontadores.com.mx</a></p></section>'
    )

    cover = item.get('cover', '')
    cover_html = (
        '<figure class="figure-portada"><img class="portada" src="' +
        escape(cover, quote=True) + '" alt="Imagen de portada de ' +
        escape(item['title'], quote=True) + '"></figure>'
        if cover else ''
    )

    # Se conservan los cuatro colores oficiales y las proporciones del artículo fiscal.
    styles = '''
    *{box-sizing:border-box}html{scroll-behavior:smooth}
    body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;color:#293F56;background:#fff;line-height:1.75}
    a{color:inherit}header{border-bottom:1px solid #ABBCC6;background:#fff;position:sticky;top:0;z-index:5}
    .wrap{width:min(1020px,91%);margin:auto}
    .nav{min-height:90px;display:flex;align-items:center;justify-content:space-between;gap:20px}
    .logo{width:185px;max-height:76px;object-fit:contain}.nav a{text-decoration:none;font-weight:650}
    .hero{background:#293F56;color:#ECEBE8;padding:65px 0 70px}
    .eyebrow{text-transform:uppercase;letter-spacing:2px;font-size:12px;color:#ABBCC6;font-weight:750}
    h1{font-size:clamp(32px,5vw,52px);line-height:1.18;letter-spacing:-1px;max-width:850px;margin:15px 0}
    .hero p{max-width:800px;color:#ECEBE8;font-size:17px}.meta{font-size:13px;color:#ABBCC6}
    .layout{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:55px;padding:58px 0 90px}
    .layout.no-sidebar{grid-template-columns:minmax(0,1fr)}
    .content{min-width:0}.content h2{font-size:26px;line-height:1.3;margin:40px 0 14px}
    .content h3{font-size:20px;margin-top:30px}.content p,.content li{font-size:16px}
    .content li{margin:8px 0}.content ul,.content ol{padding-left:24px}
    .content img{max-width:100%;height:auto}
    .content table{border-collapse:collapse;width:100%;font-size:14px}
    .content th{background:#293F56;color:white;text-align:left}
    .content td,.content th{padding:12px 14px;border:1px solid #ABBCC6}
    .content tr:nth-child(even){background:#ECEBE8}
    .table-wrap{overflow-x:auto;max-width:100%;margin:22px 0}
    .content table{min-width:410px}
    .cta{background:#293F56;color:#ECEBE8;padding:30px;border-radius:10px;margin:44px 0}
    .cta h2{color:#fff;margin:0 0 12px;font-size:26px}
    .cta p{color:#ECEBE8}.cta a:not(.btn){color:#ECEBE8;text-decoration:underline;overflow-wrap:anywhere}
    .btn{display:inline-block;background:#ECEBE8;color:#293F56!important;border-radius:6px;text-decoration:none;font-weight:750;padding:12px 20px;margin-top:8px}
    .content blockquote{border-left:4px solid #ABBCC6;padding-left:18px;margin-left:0}
    .figure-portada{margin:0 0 36px}.portada{display:block;width:100%;max-height:430px;object-fit:cover;border-radius:10px}
    .sidebar{align-self:start;position:sticky;top:120px;border:1px solid #ABBCC6;border-radius:10px;padding:20px;background:#ECEBE8}
    .sidebar a{display:block;margin:12px 0;font-size:14px;text-decoration:none;overflow-wrap:anywhere}
    .sidebar a:hover{text-decoration:underline}
    .sources{border-top:1px solid #ABBCC6;margin-top:42px;padding-top:20px;font-size:14px}
    .sources h2{font-size:22px;margin:10px 0 15px}
    .sources a{overflow-wrap:anywhere;text-decoration:underline}
    .sources ul,.sources ol{padding-left:24px}
    .articulos-relacionados{border-top:1px solid #ABBCC6;margin-top:48px;padding-top:10px}
    .articulos-relacionados h2{font-size:25px;margin:25px 0}
    .relacionados-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
    .relacionado{display:block;overflow:hidden;border:1px solid #ABBCC6;border-radius:10px;text-decoration:none;color:#293F56}
    .relacionado img,.relacionado-sin-imagen{width:100%;height:120px;object-fit:cover;display:block}
    .relacionado-sin-imagen{background:#667F95;color:#fff;display:flex;align-items:center;justify-content:center;font-size:14px}
    .relacionado-texto{padding:16px}.relacionado small{color:#667F95;text-transform:uppercase;letter-spacing:1px}
    .relacionado h3{font-size:16px;margin:8px 0 16px}.relacionado span{font-weight:650}
    .relacionado:hover{border-color:#667F95}
    footer{background:#293F56;color:#ABBCC6;padding:35px 0}
    .foot{display:flex;justify-content:space-between;align-items:center;gap:20px}
    .foot img{width:165px;max-height:75px;object-fit:contain}.foot p{font-size:13px;text-align:right}
    @media(max-width:800px){.layout{grid-template-columns:1fr;padding-top:30px;gap:28px}
      .sidebar{position:static;order:-1}.sidebar a{display:inline-block;margin-right:15px}
      .nav{min-height:75px}.logo{width:150px}.hero{padding:45px 0}
      .foot{flex-direction:column;align-items:flex-start}.foot p{text-align:left}}
    @media(max-width:550px){.relacionados-grid{grid-template-columns:1fr}
      .relacionado img,.relacionado-sin-imagen{height:170px}}
    '''
    description_html = '<p>' + description + '</p>' if description else ''
    layout_class = 'layout' if sidebar else 'layout no-sidebar'
    canonical = 'https://ulloacontadores.com.mx/' + item['url'].lstrip('/')
    return f'''<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#293F56"><meta name="description" content="{desc_attribute}">
<link rel="canonical" href="{escape(canonical, quote=True)}">
<title>{title} | Ulloa Contadores</title><style>{styles}</style></head><body>
<header><div class="wrap nav"><a href="/index.html#inicio" aria-label="Inicio de Ulloa Contadores"><img class="logo" src="/PNG%20OBSCURO.png" alt="Ulloa Contadores"></a>
<a href="/index.html#articulos">← Volver a artículos</a></div></header>
<section class="hero"><div class="wrap"><span class="eyebrow">{category}</span><h1>{title}</h1>
{description_html}<div class="meta">Ulloa Contadores{' · ' + publication if publication else ''} · Lectura aproximada: {reading_minutes} min</div>
</div></section>
<div class="wrap {layout_class}"><main class="content">{cover_html}<article>{body}</article>{cta_html}{sources_html}{related_html}</main>{sidebar}</div>
<footer><div class="wrap foot"><a href="/index.html#inicio"><img src="/PNG%20CLARO.png" alt="Ulloa Contadores"></a>
<p>© Ulloa Contadores.<br>Soluciones contables, fiscales y financieras.</p></div></footer></body></html>'''


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
                'sources': meta.get('sources') or meta.get('fuentes') or '',
                'existing_html': (ARTICLES / f'{slug}.html').exists(),
            })

    # Conserva el artículo RESICO creado previamente como HTML independiente.
    resico = ARTICLES / 'resico-personas-fisicas-2026.html'
    has_new_resico = any(
        x['url'].endswith('resico-2026-beneficios-requisitos-y-obligaciones-fiscales-para-personas-fisicas.html')
        for x in entries
    )
    if resico.exists() and not has_new_resico and not any(x['url'].endswith(resico.name) for x in entries):
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

    # Preserva enlaces existentes al RESICO antiguo sin mostrar tarjetas duplicadas.
    if resico.exists() and has_new_resico:
        new_resico = next(
            x for x in entries
            if x['url'].endswith('resico-2026-beneficios-requisitos-y-obligaciones-fiscales-para-personas-fisicas.html')
        )
        destination = '/' + new_resico['url']
        redirect_html = (
            '<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="robots" content="noindex">'
            '<meta http-equiv="refresh" content="0;url=' + escape(destination, quote=True) + '">'
            '<link rel="canonical" href="https://ulloacontadores.com.mx' + escape(destination, quote=True) + '">'
            '<title>Artículo trasladado | Ulloa Contadores</title></head><body>'
            '<p>El artículo se encuentra en <a href="' + escape(destination, quote=True) + '">'
            'su nueva dirección</a>.</p></body></html>'
        )
        old_target = OUT / 'articulos' / 'resico-personas-fisicas-2026.html'
        old_target.parent.mkdir(parents=True, exist_ok=True)
        old_target.write_text(redirect_html, encoding='utf-8')

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
