#!/usr/bin/env python3
"""Сборка карты обязательств во времени в самодостаточный HTML.

Запуск (как скрипт, не как модуль — каталог viz нарочно без __init__.py,
чтобы визуализация не стала частью пакета npp_act):

    python3 act/viz/build_map.py --dir /tmp/led --out act/viz/map.html
    python3 act/viz/build_map.py --ledger person:anna=/tmp/anna.jsonl \\
        --place venue-clinic-nord="Клиника Норд" \\
        --travel "Клиника Норд>Клиника Зюд=45" --capacity-hours 6 --json

Почему HTML, а не график в терминале: «невозможная фигура» видна только когда
отрезки стоят рядом в одной шкале. Текстом конфликт перечисляется, но не
показывается — а показать надо именно то, что два отрезка стоят в одном часе.

Почему всё в одном файле, без CDN и библиотек: карта содержит историю действий
владельца (§10.2). Файл, который тянет скрипт со стороны, эту историю из
браузера и утечёт. Самодостаточный HTML открывается с диска, в самолёте и через
десять лет — в отличие от страницы, которая ждёт d3 с чужого адреса.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from act.npp_act.calendar import (  # noqa: E402
    DEFAULT_CAPACITY_HOURS, DEFAULT_DURATION_MIN, TravelMatrix,
    build_timeline, detect_conflicts, explain, to_payload,
)
from act.npp_act.ledger import Ledger  # noqa: E402

PROFILES = ("person", "vendor", "venue", "institution", "broker")


# ────────────────────────────────────────────────────────────────────────────
# Разбор аргументов
# ────────────────────────────────────────────────────────────────────────────


def party_from_filename(path: Path) -> str:
    """Имя профиля по имени файла журнала.

    Журналы в тестах и демонстрации кладутся как `person_anna.jsonl` — двоеточие
    в имени файла допустимо не везде. Обратное преобразование делается только
    для известных ролей (§3), чтобы не превратить в профиль случайный файл.
    """
    stem = path.stem
    head, _, tail = stem.partition("_")
    if head in PROFILES and tail:
        return f"{head}:{tail}"
    return stem


def parse_pairs(items: list[str], what: str) -> dict[str, str]:
    """Разобрать аргументы вида «ключ=значение»."""
    out: dict[str, str] = {}
    for raw in items or []:
        if "=" not in raw:
            raise SystemExit(f"✗ {what}: ожидается «ключ=значение», получено {raw!r}")
        key, value = raw.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def collect_ledgers(args: argparse.Namespace) -> dict[str, Ledger]:
    """Собрать журналы сторон: из --ledger и/или из каталога --dir."""
    paths: dict[str, Path] = {}

    for party, path in parse_pairs(args.ledger, "--ledger").items():
        paths[party] = Path(path)

    for directory in args.dir or []:
        folder = Path(directory)
        if not folder.is_dir():
            raise SystemExit(f"✗ --dir: каталога нет: {folder}")
        for file in sorted(folder.glob("*.jsonl")):
            paths.setdefault(party_from_filename(file), file)

    if not paths:
        raise SystemExit("✗ не указан ни один журнал: нужен --ledger или --dir")

    ledgers: dict[str, Ledger] = {}
    for party, path in paths.items():
        if not path.exists():
            raise SystemExit(f"✗ журнала нет: {path}")
        ledgers[party] = Ledger(path, owner=party)
    return ledgers


# ────────────────────────────────────────────────────────────────────────────
# HTML
# ────────────────────────────────────────────────────────────────────────────

TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #f6f7f9;        --panel: #ffffff;     --ink: #15181d;
  --muted: #5d6673;     --line: #dfe3e8;      --bar: #3f6fb5;
  --bar-ink: #ffffff;   --ok: #2f7d4f;        --warn: #b4531b;
  --bad: #b3303a;       --grid: #eceff3;      --chip: #eef1f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c;      --panel: #1b1f26;     --ink: #e8ecf2;
    --muted: #9aa5b4;   --line: #2b323c;      --bar: #5b8ad0;
    --bar-ink: #0d1014; --ok: #6ec28c;        --warn: #e08a4e;
    --bad: #e2707a;     --grid: #222832;      --chip: #232a33;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 56px; background: var(--bg); color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1060px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 16px; margin: 28px 0 10px; }
h3 { font-size: 13px; margin: 0 0 8px; color: var(--muted); font-weight: 600;
     text-transform: uppercase; letter-spacing: 0.06em; }
.sub { color: var(--muted); font-size: 13px; margin: 0 0 20px; }
.panel { background: var(--panel); border: 1px solid var(--line);
         border-radius: 10px; padding: 16px; margin-bottom: 14px; }
.tiles { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
        padding: 10px 14px; min-width: 112px; flex: 1 1 112px; }
.tile .n { font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
.tile .k { font-size: 12px; color: var(--muted); }
.verdict { font-weight: 650; }
.verdict.ok { color: var(--ok); }
.verdict.bad { color: var(--bad); }
.axis { position: relative; height: 18px; margin-left: 150px; border-bottom: 1px solid var(--line); }
.axis span { position: absolute; top: 0; font-size: 11px; color: var(--muted);
             transform: translateX(-50%); font-variant-numeric: tabular-nums; }
.track { display: flex; align-items: stretch; border-bottom: 1px solid var(--grid); }
.track:last-child { border-bottom: 0; }
.name { width: 150px; flex: 0 0 150px; padding: 8px 10px 8px 0; font-size: 13px;
        color: var(--muted); overflow-wrap: anywhere; }
.lane { position: relative; flex: 1 1 auto; min-height: 42px; }
.bar { position: absolute; height: 26px; min-width: 3px; border-radius: 5px;
       background: var(--bar); color: var(--bar-ink); font-size: 11px; line-height: 1.25;
       padding: 3px 6px; overflow: hidden; cursor: default; }
.bar b { font-weight: 600; }
.bar.c-overlap  { background: var(--bad); }
.bar.c-travel   { background: var(--warn); }
.bar.c-capacity { outline: 2px dashed var(--warn); outline-offset: -2px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--muted); }
.key { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 13px; height: 13px; border-radius: 3px; display: inline-block; }
ul.conflicts { list-style: none; margin: 0; padding: 0; }
ul.conflicts li { border-left: 3px solid var(--bad); padding: 7px 0 7px 12px;
                  margin-bottom: 10px; font-size: 14px; }
ul.conflicts li.travel   { border-left-color: var(--warn); }
ul.conflicts li.capacity { border-left-color: var(--warn); }
ul.conflicts li .why { color: var(--muted); font-size: 12.5px; }
.chip { display: inline-block; background: var(--chip); border-radius: 20px;
        padding: 1px 9px; font-size: 11.5px; color: var(--muted);
        margin-right: 6px; font-variant-numeric: tabular-nums; }
.empty { color: var(--muted); font-style: italic; }
footer { margin-top: 32px; color: var(--muted); font-size: 12px; }
@media (max-width: 620px) {
  .axis { margin-left: 0; }
  .track { display: block; }
  .name { width: auto; flex: none; padding: 8px 0 0; }
  .lane { min-height: 36px; }
}
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <p class="sub">NPP-Act · карта обязательств во времени, собранная из хэш-цепей журналов.
     Конфликт здесь — не предупреждение, а основание для отказа до исполнения.</p>
  <div class="tiles" id="tiles"></div>
  <div id="timeline"></div>
  <h2>Невозможные фигуры</h2>
  <div class="panel" id="conflicts"></div>
  <div class="panel">
    <h3>Условные обозначения</h3>
    <div class="legend">
      <span class="key"><i class="swatch" style="background:var(--bar)"></i> исполнимое обязательство</span>
      <span class="key"><i class="swatch" style="background:var(--bad)"></i> пересечение по времени</span>
      <span class="key"><i class="swatch" style="background:var(--warn)"></i> не успеть по дороге</span>
      <span class="key"><i class="swatch" style="outline:2px dashed var(--warn);outline-offset:-2px"></i> день перегружен</span>
    </div>
  </div>
  <footer id="foot"></footer>
</div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const hhmm = iso => iso.slice(11, 16);

/* Время в данных НАИВНОЕ («2026-10-12T09:00», без зоны) — так же, как в
   calendar.py. new Date() истолковал бы такую строку как местное время браузера
   и сдвинул бы подписи оси на часовой пояс читателя. Поэтому арифметика идёт в
   минутах через Date.UTC: один и тот же файл показывает одно и то же в Берлине
   и в Токио. */
const ABS = iso => {
  const [d, t] = iso.split('T'), [h, m] = t.split(':');
  return Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10), +h, +m) / 60000;
};
const FMT = min => {
  const dt = new Date(min * 60000);
  return String(dt.getUTCHours()).padStart(2, '0') + ':' +
         String(dt.getUTCMinutes()).padStart(2, '0');
};

/* Тяжесть конфликта определяет цвет отрезка: пересечение сильнее дороги,
   дорога сильнее перегрузки дня. Иначе один отрезок перекрашивался бы
   случайным порядком обхода. */
const RANK = { overlap: 3, travel: 2, capacity: 1 };
function worst(kinds) {
  let best = null;
  (kinds || []).forEach(k => { if (!best || RANK[k] > RANK[best]) best = k; });
  return best;
}

function tiles() {
  const s = DATA.summary;
  const v = s.feasible
    ? '<span class="verdict ok">исполнимо</span>'
    : '<span class="verdict bad">неисполнимо</span>';
  const cells = [
    [s.entries, 'обязательств'],
    [s.busy_hours.toFixed(1) + ' ч', 'занято времени'],
    [s.money.toFixed(2), 'денег по журналу'],
    [s.days.length, s.days.length === 1 ? 'день' : 'дней'],
    [s.conflicts, 'конфликтов'],
    [v, 'вердикт'],
  ];
  document.getElementById('tiles').innerHTML = cells.map(
    ([n, k]) => `<div class="tile"><div class="n">${n}</div><div class="k">${esc(k)}</div></div>`
  ).join('');
}

function render() {
  tiles();
  const host = document.getElementById('timeline');
  if (!DATA.entries.length) {
    host.innerHTML = '<div class="panel empty">В журналах нет обязательств с распознаваемым временем.</div>';
  } else {
    const byParty = {};
    DATA.entries.forEach(e => {
      (byParty[e.party] = byParty[e.party] || {});
      (byParty[e.party][e.day] = byParty[e.party][e.day] || []).push(e);
    });
    host.innerHTML = Object.keys(byParty).sort().map(party => {
      const days = byParty[party];
      const blocks = Object.keys(days).sort().map(day => dayBlock(days[day])).join('');
      return `<h2>${esc(party)}</h2>${blocks}`;
    }).join('');
  }
  conflicts();
  document.getElementById('foot').textContent =
    'Собрано ' + DATA.generated_at.replace('T', ' ') + ' UTC · ' +
    'стороны: ' + DATA.summary.parties.join(', ');
}

function dayBlock(entries) {
  /* Окно дня — от начала первого обязательства до конца последнего, округлённое
     до часа. Рисовать все 24 часа бессмысленно: отрезки сожмутся в полоски. */
  const starts = entries.map(e => ABS(e.starts_at));
  const ends = entries.map(e => ABS(e.ends_at));
  const H = 60;
  const from = Math.floor(Math.min(...starts) / H) * H - H / 2;
  const to = Math.ceil(Math.max(...ends) / H) * H + H / 2;
  const span = Math.max(to - from, H);
  const pos = t => ((t - from) / span) * 100;

  const ticks = [];
  for (let t = Math.ceil(from / H) * H; t <= to; t += H) {
    ticks.push(`<span style="left:${pos(t).toFixed(2)}%">${FMT(t)}</span>`);
  }

  const tracks = {};
  entries.forEach(e => { (tracks[e.track] = tracks[e.track] || []).push(e); });

  const rows = Object.keys(tracks).sort().map(name => {
    /* Внутри одной дорожки отрезки могут накладываться — именно это и есть
       интересный случай. Поэтому они раскладываются по подстрокам жадно, а не
       рисуются друг на друге: иначе невозможная фигура спряталась бы под
       верхним отрезком. */
    const items = tracks[name].slice().sort((a, b) => ABS(a.starts_at) - ABS(b.starts_at));
    const busyUntil = [];
    const placed = items.map(e => {
      const s = ABS(e.starts_at), f = ABS(e.ends_at);
      let row = busyUntil.findIndex(end => end <= s);
      if (row < 0) row = busyUntil.length;
      busyUntil[row] = f;
      return [e, row];
    });
    const bars = placed.map(([e, row]) => {
      const kind = worst(DATA.conflict_refs[e.ref]);
      const left = pos(ABS(e.starts_at));
      const width = Math.max(pos(ABS(e.ends_at)) - left, 1.2);
      const tip = `${e.label}\n${hhmm(e.starts_at)}–${hhmm(e.ends_at)} · ${e.place}` +
                  `\n${e.money} ${e.currency} · ${e.service}:${e.verb}\nзапись ${e.ref}`;
      return `<div class="bar${kind ? ' c-' + kind : ''}" title="${esc(tip)}"
        style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%;top:${6 + row * 32}px">
        <b>${esc(hhmm(e.starts_at))}</b> ${esc(e.label)}</div>`;
    }).join('');
    const height = 12 + Math.max(busyUntil.length, 1) * 32;
    return `<div class="track"><div class="name">${esc(name)}</div>
            <div class="lane" style="min-height:${height}px">${bars}</div></div>`;
  }).join('');

  return `<div class="panel"><h3>${esc(entries[0].day)}</h3>
          <div class="axis">${ticks.join('')}</div>${rows}</div>`;
}

function conflicts() {
  const host = document.getElementById('conflicts');
  if (!DATA.conflicts.length) {
    host.innerHTML = '<p class="empty">Неисполнимого не найдено: расписание можно исполнить целиком.</p>';
    return;
  }
  host.innerHTML = '<ul class="conflicts">' + DATA.conflicts.map(c => {
    const chips = c.refs.map(r => `<span class="chip">${esc(r)}</span>`).join('');
    return `<li class="${esc(c.kind)}"><div>${esc(c.message)}</div>
            <div class="why">${chips}<span class="chip">${esc(c.kind)}</span>
            ${esc(c.day)}</div></li>`;
  }).join('') + '</ul>';
}

render();
</script>
</body>
</html>
"""


def render_html(payload: dict, title: str) -> str:
    """Встроить данные в шаблон.

    `</` экранируется не из суеверия: строка «</script>» внутри JSON закрыла бы
    тег раньше времени и превратила бы карту в кашу из текста.
    """
    raw = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", title).replace("__PAYLOAD__", raw)


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="NPP-Act: карта обязательств во времени и поиск неисполнимого",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--ledger", action="append", metavar="ПРОФИЛЬ=ПУТЬ",
                    help="журнал одной стороны, можно повторять")
    ap.add_argument("--dir", action="append", metavar="КАТАЛОГ",
                    help="каталог с *.jsonl: профиль берётся из имени файла")
    ap.add_argument("--place", action="append", metavar="СЕРВИС=МЕСТО",
                    help="как называется место сервиса на карте")
    ap.add_argument("--role", action="append", metavar="СЕРВИС=РОЛЬ",
                    help="дорожка (работа, здоровье, семья) для сервиса")
    ap.add_argument("--travel", action="append", metavar="A>B=МИНУТЫ",
                    help="время дороги между местами, можно повторять")
    ap.add_argument("--travel-default", type=int, default=0, metavar="МИНУТЫ",
                    help="дорога между необъявленными парами мест (по умолчанию 0: "
                         "карта не выдумывает конфликт из незнания)")
    ap.add_argument("--capacity-hours", type=float, default=DEFAULT_CAPACITY_HOURS,
                    help=f"дневная ёмкость в часах (по умолчанию {DEFAULT_CAPACITY_HOURS})")
    ap.add_argument("--duration-min", type=int, default=DEFAULT_DURATION_MIN,
                    help="длительность обязательства, если она не объявлена "
                         f"(по умолчанию {DEFAULT_DURATION_MIN})")
    ap.add_argument("--title", default="Карта обязательств во времени")
    ap.add_argument("--out", default=str(ROOT / "act/viz/map.html"),
                    help="куда положить HTML")
    ap.add_argument("--json", action="store_true",
                    help="выдать данные карты в stdout одним объектом JSON")
    ap.add_argument("--quiet", action="store_true", help="без отчёта в stdout")
    args = ap.parse_args(argv)

    ledgers = collect_ledgers(args)
    timeline = build_timeline(
        ledgers,
        place_of=parse_pairs(args.place, "--place"),
        role_of=parse_pairs(args.role, "--role"),
        default_duration_min=args.duration_min,
    )

    try:
        matrix = TravelMatrix.parse(args.travel or [])
    except ValueError as e:
        raise SystemExit(f"✗ --travel: {e}")
    matrix.default_between = args.travel_default

    conflicts = detect_conflicts(timeline, travel=matrix,
                                 capacity_hours=args.capacity_hours)
    payload = to_payload(timeline, conflicts)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(payload, args.title), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.quiet:
        s = payload["summary"]
        total_commitments = sum(len(led.by_kind("commitment")) for led in ledgers.values())
        print(f"Журналов: {len(ledgers)} · обязательств на карте: {s['entries']}"
              f" из {total_commitments} · занято {s['busy_hours']} ч")
        if s["entries"] < total_commitments:
            print(f"  ⓘ {total_commitments - s['entries']} обязательств без "
                  f"распознаваемого времени — на карту не попали")
        if conflicts:
            print(f"Неисполнимо ({len(conflicts)}):")
            for c in conflicts:
                print("  " + explain(c))
        else:
            print("Неисполнимого не найдено: расписание можно исполнить целиком.")
        print(f"Карта: {out}")

    # Код возврата отличает «карта построена» от «карта построена и в ней
    # невозможные фигуры»: так CLI годится в проверку перед принятием решения.
    return 2 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
