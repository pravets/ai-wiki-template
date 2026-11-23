# Интерпретатор для скриптов vault. python3 в PATH на Windows может оказаться
# заглушкой Microsoft Store: проверяем, что он запускается, иначе берём python.
PY ?= $(shell python3 -c "import sys" >/dev/null 2>&1 && echo python3 || echo python)
S  := 90-meta/scripts

.PHONY: help index search search-full hub test check-paths check-hook

help:
	@echo "make index       — перегенерировать index.md из frontmatter"
	@echo "make search      — пересобрать поисковый индекс (инкрементально)"
	@echo "make search-full — пересобрать поисковый индекс с нуля"
	@echo "make hub         — перегенерировать 42-repos/hub.md (нужен gh CLI)"
	@echo "make test        — прогнать тесты поиска (корпуса, свежесть, строгость, соседи)"
	@echo "make check-paths — проверить, что пути из документации существуют"
	@echo "make check-hook  — проверить, что git-хук включён"

index:
	$(PY) $(S)/gen_index.py --write

search:
	$(PY) $(S)/wiki_search.py index

search-full:
	$(PY) $(S)/wiki_search.py index --full

hub:
	$(PY) $(S)/gh_repos_sync.py --hub

test:
	$(PY) $(S)/test_wiki_search.py

check-paths:
	$(PY) $(S)/check_paths.py

check-hook:
	@test "$$(git config core.hooksPath)" = ".githooks" \
		|| (echo "хук не включён: git config core.hooksPath .githooks" && exit 1)
	@test -x .githooks/pre-commit || (echo ".githooks/pre-commit не исполняемый" && exit 1)
	@echo "хук на месте"
