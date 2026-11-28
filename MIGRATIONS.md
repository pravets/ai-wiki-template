# MIGRATIONS — что делать форку, отставшему на версию шаблона

Каждая запись: инкремент версии, что нового, шаги миграции. Шаги выполняются
вручную — скрипта миграции сознательно нет, потому что некому проверять
скрипт, который переписывает чужой vault: цена ошибки выше цены пятнадцати
минут ручной работы по чеклисту.

Перед миграцией: `git pull`, `make gate` (должен быть зелёным на текущей
версии), коммит незавершённых правок.

## v1 → v2 (2026-11-28)

Ремонт, из которого выросли все изменения: контракт frontmatter не
выполнялся ни одной страницей из двухсот, журнал рос без лимита, каталог
вирал руками, зоны `05-chats` не существовало.

**Новые файлы:**

- `90-meta/scripts/lint_frontmatter.py` — линт контракта по зонам
  (`--strict`, `--baseline`, `--git-dates`, `--changed`, `--json`)
- `90-meta/scripts/rotate_log.py` — ротация `log.md` по байтам (100 КБ),
  архив `90-meta/log/<год>.md`
- `90-meta/scripts/canon_tags.py` — канонизация тегов, хвост в `kw`
- `90-meta/scripts/stamp_frontmatter.py` — `created`/`updated` из git-дат
- `90-meta/scripts/link_raw.py` — привязка `10-wiki` → `01-raw` полем `raw:`
- `90-meta/lint-baseline.json` — бэклог нарушений (пути, не счётчики)
- `Makefile` (`lint` / `gate` / `log` / `index` / `test` / `check-paths` / `check-hook`)
- `.githooks/pre-commit` — гейт на изменённых файлах вики-слоя
- `90-meta/templates/chat-transcript.md` — шаблон дампа чата
- `05-chats/` — зона дампов чатов с LLM (маркер `.llm-rw`)

**Изменённые:**

- `90-meta/scripts/gen_index.py` — разделы `40-projects` (папки с README,
  вложенные страницы), `25-interactions`, `70-personal`; лимит строки 120
  символов проверяется в `--check`
- `90-meta/scripts/wiki_search.py` — `90-meta/log` в `SKIP_DIRS`
- `90-meta/scripts/lint_frontmatter.py` — зона `05-chats` (`type: chat`,
  поля `project/model/session/messages`, `tags` опциональны, G3 отключён:
  `updated` у дампа — дата диалога), `90-meta/log` в `SKIP_DIRS`
- `90-meta/schema.md` — ротация по байтам, версия шаблона, лимит строки
- `AGENTS.md` — зоны `05-chats`/`35-courses`/`42-repos`, поля по зонам,
  заметки про `TAGS_OPTIONAL` и `EXEMPT_STALE`
- `README.md` — таблица инструментов, прямые скрипты
- `skills/wiki-lint/SKILL.md` — машинный проход `make gate`, проверка
  покрытия зон контрактом, проверка навигации

**Шаги миграции:**

1. Скопировать новые файлы; проверить, что `canon_tags.py` видит `TAGS` и
   `CANON` из соседнего `lint_frontmatter.py` (импорт, не копия словаря).
2. `python3 90-meta/scripts/lint_frontmatter.py --write-baseline
   90-meta/lint-baseline.json` — зафиксировать текущий бэклог путями.
   Дальше бэклог только сокращается: исправил — `--prune-baseline`.
3. `python3 90-meta/scripts/stamp_frontmatter.py --write` — даты из git
   (G3: руками даты не пишутся).
4. Подключить хук: `git config core.hooksPath .githooks`; проверить
   `make check-hook`.
5. `make log` — первая ротация; затем ещё раз (запись о ротации сама
   вытолнивает хвост). Проверить маркер `90-meta/log/.llm-append` —
   `rotate_log.py` его не создаёт, без него архив read-only.
6. `make index && make gate` — каталог перегенерирован, гейт зелёный.
7. Заполнить «Инициализацию» в `90-meta/schema.md` (один раз, по скиллу
   `wiki-init`).

**Проверка:** `make gate` — 0 новых нарушений; `make test` — 11 OK;
`make check-paths` — пути из документации существуют.
