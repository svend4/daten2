# ⚠️ levels/ — устаревшие снимки, не актуальный код

Этот каталог был собран в самом начале работы из старых коммитов истории
`main`. **В нём нет контрактного кода** (`/api/health`, `/api/products`,
`/api/orders`): проверено сравнением с ветками — ни один из семи уровней здесь
не совпадает с тем, что реально реализует единый контракт.

Актуальный код уровней лежит на ветках:

| Уровень | Ветка с контрактом |
|---|---|
| L1 PHP | `claude/level1-php-GBpVR` |
| L2 Flask | `claude/level2-flask-GBpVR` |
| L3 Django | `claude/level3-django-GBpVR` |
| L4 Express | `claude/level4-express-GBpVR` |
| L5 React + Flask API | `claude/level5-react-flask-GBpVR` |
| L6 Next.js | `claude/level6-nextjs-GBpVR` |
| L7 микросервисы | `claude/level7-enterprise-GBpVR` |

Достать ветку, не меняя рабочее дерево:

```bash
mkdir -p /путь/к/пустому/каталогу
git archive origin/claude/level1-php-GBpVR | tar -x -C /путь/к/пустому/каталогу
```

Каталог оставлен, а не удалён, потому что это история работы. Удаление —
решение владельца репозитория. Рекомендация: удалить, чтобы не было двух
источников истины. См. `docs/RETRO-2026-10.md`.

Измерения и манифесты `act/` опираются только на ветки, не на этот каталог.
