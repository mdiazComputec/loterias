"""Actualiza los resultados de las loterías y del Baloto, y arma la página pública.

Lo corre GitHub Actions todos los días (ver .github/workflows/actualizar.yml en el repo loterias).
También se puede correr a mano:  python scripts/actualizar.py

- Lee astroluna.co (Bogotá, Boyacá, Cundinamarca) y baloto.com (Baloto y Revancha).
- Solo agrega sorteos con fecha posterior al último guardado. Nunca borra ni cambia los ya guardados:
  si la fuente muestra un resultado distinto para una fecha guardada, lo avisa en el registro y no lo toca.
- Arma index.html a partir de plantilla.html con los datos incluidos.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATOS = os.path.join(RAIZ, 'datos')
MES = {'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
       'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12}
LOTERIAS = {'sorteos': 'bogota', 'boyaca': 'boyaca', 'cundinamarca': 'cundinamarca'}


def bajar(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (actualizador de loterias)'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode('utf-8', 'ignore')


def texto(html):
    t = re.sub(r'<script.*?</script>|<style.*?</style>', '', html, flags=re.S)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t))


def leer_astroluna(slug):
    t = texto(bajar(f'https://www.astroluna.co/{slug}'))
    t = t[t.find('Fecha N'):]
    patron = r'\b(\d{1,2}) (' + '|'.join(MES) + r') (\d{4}) (\d{4}) (\d{3})\b'
    return [{'fecha': dt.date(int(y), MES[m], int(d)).isoformat(), 'numero': n, 'serie': s}
            for d, m, y, n, s in re.findall(patron, t)]


def leer_baloto(paginas=3):
    res = {'baloto': [], 'revancha': []}
    for p in range(1, paginas + 1):
        html = bajar(f'https://baloto.com/resultados?page={p}')
        for tr in re.findall(r'<tr>(.*?)</tr>', html, re.S):
            k = re.search(r'/(baloto|revancha)-kind', tr)
            fe = re.search(r'(\d{1,2}) de (\w+) de (\d{4})', tr)
            nums = re.search(r'>\s*((?:\d{1,2}\s*-\s*){5})<span[^>]*>(\d{1,2})</span>', tr)
            so = re.search(r'/resultados-(?:baloto|revancha)/(\d+)', tr)
            if k and fe and nums and fe[2].lower() in MES:
                n = sorted(int(x) for x in re.findall(r'\d+', nums[1]))
                sb = int(nums[2])
                if len(set(n)) == 5 and all(1 <= x <= 43 for x in n) and 1 <= sb <= 16:
                    res[k[1]].append({'fecha': dt.date(int(fe[3]), MES[fe[2].lower()], int(fe[1])).isoformat(),
                                      'n': n, 'sb': sb, 'sorteo': int(so[1]) if so else None})
    return res


def cargar(nombre):
    with open(os.path.join(DATOS, nombre + '.json'), encoding='utf-8') as f:
        return json.load(f)


def guardar(nombre, lista):
    lista.sort(key=lambda x: x['fecha'])
    with open(os.path.join(DATOS, nombre + '.json'), 'w', encoding='utf-8') as f:
        json.dump(lista, f, ensure_ascii=False, separators=(',', ':'))


def unir(nombre, nuevos, igual):
    actuales = cargar(nombre)
    por_fecha = {x['fecha']: x for x in actuales}
    ultima = max(por_fecha) if por_fecha else ''
    agregados = []
    for x in sorted(nuevos, key=lambda x: x['fecha']):
        if x['fecha'] in por_fecha:
            if not igual(por_fecha[x['fecha']], x):
                print(f'  AVISO {nombre} {x["fecha"]}: la fuente dice {x} y está guardado {por_fecha[x["fecha"]]}; no se cambia')
        elif x['fecha'] > ultima:
            actuales.append(x)
            por_fecha[x['fecha']] = x
            agregados.append(x)
    if agregados:
        guardar(nombre, actuales)
    print(f'  {nombre}: {len(agregados)} nuevo(s) {[a["fecha"] for a in agregados]}')
    return len(agregados)


def armar_pagina():
    data = {c: cargar(c) for c in ['sorteos', 'boyaca', 'cundinamarca']}
    data['baloto'], data['revancha'] = [], []
    hist = {h: {'sorteos': cargar(h)} for h in ['baloto', 'revancha']}
    ultimo = max(max(x['fecha'] for x in v) for v in list(data.values()) + [h['sorteos'] for h in hist.values()] if v)
    hoy = (dt.datetime.utcnow() - dt.timedelta(hours=5)).date()
    fmt = lambda d: f"{d.day} de {list(MES)[d.month - 1]} de {d.year}"

    pagina = open(os.path.join(RAIZ, 'plantilla.html'), encoding='utf-8').read()
    stub = '''<script>
window.__PUBLICO = true;
const __DATA = %s, __HIST = %s;
window.claude = { use: async n => n !== "db" ? null : {
  collection: c => ({ onSnapshot: next => { setTimeout(() => next({ docs: (__DATA[c] || []).map(d => ({ id: d.fecha, data: () => d })) }), 0); return () => {}; } }),
  doc: p => ({ onSnapshot: next => { const k = p.split("/")[1]; setTimeout(() => next({ exists: !!__HIST[k], data: () => __HIST[k] }), 0); return () => {}; },
               set: async () => { throw { code: "invalid_argument" }; }, delete: async () => { throw { code: "invalid_argument" }; } })
} };
</script>''' % (json.dumps(data, separators=(',', ':')), json.dumps(hist, separators=(',', ':')))
    estilos = '''<style>
#form, #b-form, .bulk, .actions, .del, #ia-box,
[aria-labelledby="t-add"] > div:first-child, [aria-labelledby="t-badd"] > div:first-child,
[aria-labelledby="t-aciertos"], [aria-labelledby="t-bseg"], .msg { display: none !important; }
.publico-aviso { background: var(--accent-soft); color: var(--ink); border: 1px solid var(--accent); border-radius: 6px; padding: 10px 14px; font-size: .88rem; }
</style>'''
    aviso = (f'<div class="publico-aviso">Versión pública de solo lectura · se actualiza sola todos los días · '
             f'último sorteo registrado: {fmt(dt.date.fromisoformat(ultimo))} · revisado el {fmt(hoy)}. '
             'Cualquier número tiene la misma probabilidad de caer; esto es un análisis estadístico, no una garantía.</div>')
    pagina = pagina.replace('<div class="wrap">', '<div class="wrap">\n  ' + aviso, 1)
    html = ('<!doctype html>\n<html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style>'
            + estilos + '</head><body>\n' + stub + '\n' + pagina + '\n</body></html>\n')
    with open(os.path.join(RAIZ, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Página armada: último sorteo {ultimo}, {len(html) // 1024} KB')


def main():
    errores = 0
    print('Buscando resultados nuevos…')
    for col, slug in LOTERIAS.items():
        try:
            unir(col, leer_astroluna(slug), lambda a, b: a['numero'] == b['numero'] and a['serie'] == b['serie'])
        except Exception as e:
            errores += 1
            print(f'  ERROR leyendo {slug}: {e}')
    try:
        bal = leer_baloto()
        for juego in ('baloto', 'revancha'):
            unir(juego, bal[juego], lambda a, b: a['n'] == b['n'] and a['sb'] == b['sb'])
    except Exception as e:
        errores += 1
        print(f'  ERROR leyendo baloto.com: {e}')
    armar_pagina()
    if errores == 4:
        sys.exit('No se pudo leer ninguna fuente')


if __name__ == '__main__':
    main()
