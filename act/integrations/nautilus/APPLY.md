# Как принять NPP-Act в svend4/nautilus

Инструкция для владельца репозитория Наутилуса. Девять шагов, десять минут,
все изменения обратимы одним `git revert`. Прав на запись в `svend4/nautilus`
у автора пакета нет — поэтому пакет готов, а решение за вами.

Обозначения: `$NAUT` — корень клона `svend4/nautilus`, `$DATEN2` — корень клона
`svend4/daten2`.

```bash
export NAUT=~/git/nautilus
export DATEN2=~/git/daten2
```

Шаги 1–5 обязательны: после них адаптер работает. Шаги 6–8 приводят
документацию и схемы в согласие с реальностью. Шаг 9 — проверка.

---

## 1. Скопировать адаптер (1 мин)

```bash
cp "$DATEN2/act/integrations/nautilus/npp_act_adapter.py" "$NAUT/adapters/npp_act.py"
```

Имя файла меняется на `npp_act.py` — так требует соглашение
`adapters/<format>.py`. Внутри файла менять **нечего**: первая строка импорта
`from .base import BaseAdapter, PortalEntry, fuzzy_match` начинает работать
сама, как только файл оказывается внутри пакета `adapters`.

Зависимостей у файла нет: только стандартная библиотека.

## 2. Зарегистрировать класс в `adapters/__init__.py` (1 мин)

Добавить строку импорта после `from .ai_research import AIResearchAdapter`:

```python
from .npp_act import NppActAdapter
```

И в список `__all__`, в конец:

```python
    "NppActAdapter",
```

## 3. Подключить адаптер в `portal.py` (1 мин)

В блоке импорта `from adapters import (...)` добавить `NppActAdapter,`.

В конструкторе `NautilusPortal.__init__`, в словарь `self.adapters`, после
строки `"ai_research":  AIResearchAdapter(),`:

```python
            "npp_act":      NppActAdapter(),
```

Адаптер сам ищет манифесты: переменная окружения `NPP_ACT_MANIFESTS`
(пути через `os.pathsep`), затем каталог `act/manifests` рядом с собой, затем
вкомпилированный минимум с `is_fallback=True`. Если клона daten2 на машине нет,
портал всё равно поднимется — просто записи будут помечены как fallback, и
релевантность у них по §5.1 вдвое ниже. Чтобы подключить настоящий каталог:

```bash
export NPP_ACT_MANIFESTS="$DATEN2/act/manifests"
```

Либо явно, в коде, если путь постоянный:

```python
            "npp_act":      NppActAdapter(["/путь/к/daten2/act/manifests"]),
```

Живое чтение манифестов у работающих сервисов включено по умолчанию
(`live=True`): адаптер читает `GET {base_url}/.well-known/npp-act.json`.
Это чтение **объявления**, не действия; ни один глагол адаптер вызвать не может.
Выключается `NppActAdapter(live=False)`.

## 4. Положить паспорт (1 мин)

```bash
cp "$DATEN2/act/integrations/nautilus/passport-daten2.md" "$NAUT/passports/npp_act.md"
```

Имя файла обязано быть `npp_act.md`: `BridgeRegistry._load()` берёт имя
адаптера из `md_file.stem`, а `health_check.check_passports()` ищет
`passports/{adapter}.md`. Любое другое имя — и мосты не загрузятся, а health
покажет `exists: false`.

## 5. Добавить запись в `nautilus.json` (2 мин)

Содержимое `act/integrations/nautilus/registry-entry.json` вставить в массив
`registry` последним элементом (не забыть запятую у предыдущего):

```json
    {
      "repo": "svend4/daten2",
      "adapter": "npp_act",
      "name": "npp_act",
      "format": "daten2-act",
      "compatibility": 4,
      "passport": "passports/npp_act.md",
      "act_manifest": "act/manifests/flower-shop.act.json",
      "note": "NPP-Act 1.0 — уровень 4 (Actionable): манифест глаголов + губернатор + журнал. Единица — действие, а не документ. format_type='action' деградирует к 'document' по §4.1."
    }
```

Поле `act_manifest` — новое, введено NPP-Act. Читатели v1.2 его игнорируют:
по §6.2 обязательны только `repo`, `adapter`, `format`, `compatibility`.

Там же, в корне файла, поднять версию реестра — реестр теперь содержит
уровень, которого в v1.2 не было. Найти строку

```json
  "version": "1.2",
```

и заменить на

```json
  "version": "1.3",
```

## 6. Поднять потолок совместимости в `passport_schema.json` (1 мин)

Сейчас схема запрещает уровень 4 буквально:

```json
    "compatibility": {
      "type": "integer",
      "minimum": 0,
      "maximum": 3,
      "description": "0=обнаруживаемый · 1=читаемый · 2=связанный · 3=интерактивный"
    },
```

Заменить на:

```json
    "compatibility": {
      "type": "integer",
      "minimum": 0,
      "maximum": 4,
      "description": "0=обнаруживаемый · 1=читаемый · 2=связанный · 3=интерактивный · 4=действующий (NPP-Act)"
    },
```

Это единственное изменение в схеме. Все существующие паспорта остаются
валидными: потолок поднимается, пол и обязательные поля не трогаются.

## 7. Добавить метку уровня в `generate_passport.py` (1 мин)

В словарь `COMPAT_LABELS`:

```python
    4: "действующий",
```

Без этой строки генератор поставит в таблицу паспорта пустую метку
(`{compatibility} — `) — не упадёт, но получится некрасиво.

## 8. Дописать протокол: `PORTAL-PROTOCOL.md` (3 мин)

Четыре правки, все — добавление строк.

**8.1.** Найти заголовок

```
### 4.1. `format_type` Values
```

и добавить строку в его таблицу:

```
| `action` | Verb with declared consequence (NPP-Act Level 4). Unknown to pre-1.3 readers → treated as `document` per this section |
```

**8.2.** Найти заголовок

```
## 8. Compatibility Levels
```

и добавить строку в таблицу уровней:

```
| **4** | Actionable | Verb manifest + governor + persistent ledger | `fetch()` returns `format_type="action"` entries with `metadata.effect`, `metadata.consent`, `metadata.reversible` |
```

И после таблицы — абзац со ссылкой:

```
Level 4 is defined by the **NPP-Act 1.0** extension, maintained in
`svend4/daten2` ([SPEC-NPP-ACT.md](https://github.com/svend4/daten2/blob/main/act/SPEC-NPP-ACT.md)).
Levels 0–3 are unchanged: the extension adds the *consequence* dimension
(what happens if this is invoked) without touching the read layer. A Level 4
repository MUST publish a valid manifest, MUST declare `consent` and
reversibility for every verb with `effect ≠ read`, MUST keep a persistent
execution ledger, and MUST reject calls lacking a declared idempotency key.
Reference implementation: `act/npp_act/` (556 checks, zero external dependencies).
```

**8.3.** Найти заголовок

```
### 8.1. Current Ecosystem Distribution
```

и добавить строку в таблицу распределения:

```
| 4 | 1 | daten2 (npp_act) |
```

Итог под таблицей: «Total registered adapters: **15**. Passports: **13**».

**8.4.** Найти заголовок

```
### 9.3. Per-Format Projection Rules
```

и добавить строку в таблицу проекций:

```
| npp_act | `effect`→b5b4b3, `¬reversible`→b2, `consent`→b1b0 | deterministic |
```

Желательно там же одно предложение оговорки, потому что проекция у NPP-Act
другая, чем в §9.2 (где `b5b4` — класс CA):

```
NPP-Act projects *consequences*, not concepts, into the same 64-vertex space.
Bits b5b4b3 form a binary severity field, not a Gray code: Hamming adjacency
inside that field MUST NOT be read as semantic adjacency. An address shared
with a concept entry is a §9.4 collision, not an identity.
```

## 9. Проверить (2 мин)

```bash
cd "$NAUT"

# адаптер отвечает протоколу: оба абстрактных метода реализованы
python3 -c "
from adapters.npp_act import NppActAdapter
from adapters.base import BaseAdapter, PortalEntry
a = NppActAdapter()
assert isinstance(a, BaseAdapter)
d = a.describe()
assert d['format'] and d['native_unit'] and d['compatibility'] == 4
es = a.fetch('')
assert es and all(isinstance(e, PortalEntry) for e in es)
print('ok:', d['total_services'], 'сервисов,', d['total_verbs'], 'глаголов;',
      'fallback' if d['sources']['fallback'] else 'живые источники')
"

# портал видит новый адаптер и ищет по нему
python3 -c "
from portal import NautilusPortal
p = NautilusPortal()
assert 'npp_act' in p.adapters
r = p.query('money')
print('найдено:', len(r.entries), '| действий:',
      sum(1 for e in r.entries if e.format_type == 'action'))
"

# мосты паспорта загрузились
python3 -c "
from bridge_registry import BridgeRegistry
b = BridgeRegistry('passports')
print(b.summary()['adapters_with_bridges'])
print(len(b.all_for('npp_act')), 'мостов у npp_act')
"

# паспорт по форме, которую требует health_check
python3 health_check.py | head -40

# поиск по адресу последствия: деньги, необратимо, нужно подтверждение
python3 -c "
from adapters.npp_act import NppActAdapter, decode_q6
print(decode_q6('011110'))
print([e.id for e in NppActAdapter().fetch('011110')])
"
```

Ожидаемое: `compatibility == 4`, `npp_act` в списке адаптеров портала,
5 мостов, паспорт без `missing_fields`.

---

## Что НЕ нужно делать

- **Не нужно** копировать `act/` целиком в Наутилус. Переносится ровно один
  файл адаптера плюс паспорт. Рантайм (губернатор, журнал, шлюз) остаётся в
  daten2: Наутилус — каталог, а не исполнитель.
- **Не нужно** открывать Наутилусу доступ к исполнению глаголов. Адаптер
  физически не умеет вызвать `POST /api/orders`; единственный его сетевой
  запрос — чтение манифеста. Если когда-нибудь появится желание добавить
  «кнопку выполнить» в `index.html`, она обязана идти в `act/gateway.py`
  (`POST /act/perform`), где стоят губернатор и журнал, а не в сервис напрямую.
- **Не нужно** трогать существующие адаптеры, паспорта и уровни 0–3.
  Расширение аддитивно: ни одна старая запись не меняет ни тип, ни адрес.

## Если принимать не хочется

Пакет остаётся работоспособным и без переноса: `act/integrations/nautilus/`
запускается внутри daten2, адаптер отдаёт валидные `PortalEntry`, а тест
`act/tests/test_nautilus_adapter.py` сверяет его с **настоящим** исходником
протокола (`adapters/base.py` из клона Наутилуса), а не с собственным дублёром.
Тогда это просто доказательство, что уровень 4 реализуем без правок в v1.2.
