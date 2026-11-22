---
name:
type: repo
created:
updated:
tags: []
repo: owner/name
role: maintainer | contributor | watcher | archived
status: active | on-demand | paused | archived | unknown
upstream: ""        # owner/name, только для форков с собственными коммитами
local_path: ""      # ~/project, если клон есть на машине
stack: []
sources:
  - https://github.com/owner/name
---
## Что это

Одна-две фразы: зачем проект существует и для кого. Не пересказ README — смысл.

## Моя роль

Что именно делаю: мейнтейню и решаю по PR, шлю изменения к чужому мейнтейнеру, слежу за upstream. Что здесь моё, а что чужое.

## Что важно помнить

3–6 пунктов того, что не выводится из кода и README, но нужно при возвращении через
полгода: неочевидные ограничения, грабли, договорённости, «почему сделано именно так».
Пункт без этой информации — это пересказ README, и его тут быть не должно.

## Журнал

События — append-only в `42-repos/log.md`, строками `## [YYYY-MM-DD] owner/name | суть`.
Здесь — только устойчивое: зачем репозиторий в базе.

## Ссылки

- Репозиторий: https://github.com/owner/name
