# Требования к сторонним плагинам (API v1)

Этот документ обязателен для внешних разработчиков плагинов.
Он описывает рабочий контракт для текущей версии приложения (Plugin API v1).

## 1. Базовые принципы (обязательные)

1. `aimn.core` и `aimn.ui` не должны знать о конкретных плагинах.
2. Нельзя требовать хардкод в core/UI по `plugin_id`, модулю или "списку известных плагинов".
3. Плагин должен быть self-describing через `plugin.json` (+ опционально `plugin_passport.json`).
4. Пользовательские тексты для карточек плагина и инструкций хранятся в `plugin.json`.
5. `plugin_passport.json` не используется для UI-копирайта (`product_name`, `highlights`, `description`, `icon_key` из него игнорируются).
6. Плагин не должен импортировать `aimn.core.*` (это проверяется при загрузке).

## 2. Структура плагина

Минимально:

```text
plugins/<group>/<plugin_package>/
  plugin.json
  plugin_passport.json         # опционально
  <plugin_package>.py
```

Код плагина должен лежать рядом с manifest-файлами в package-каталоге плагина.
Имя Python-модуля должно совпадать с именем package-каталога.

Маска именования для production-плагинов:
- каталог: `plugins/<group>/<plugin_package>/`
- модуль: `plugins/<group>/<plugin_package>/<plugin_package>.py`
- entrypoint: `plugins.<group>.<plugin_package>.<plugin_package>:Plugin`

Пример:
- каталог: `plugins/service/prompt_manager/`
- модуль: `plugins/service/prompt_manager/prompt_manager.py`
- entrypoint: `plugins.service.prompt_manager.prompt_manager:Plugin`

## 3. `plugin.json`: обязательные поля

Обязательные поля:
- `id`
- `name`
- `product_name`
- `highlights`
- `description`
- `version`
- `api_version` (сейчас `"1"`)
- `entrypoint` (`module:ClassName`)
- `hooks`
- `artifacts`

Рекомендуемые поля:
- `ui_stage`
- `tags`
- `howto`
- `ui_schema.settings`
- `capabilities`
- `dependencies`
- `distribution`

Формальная схема манифеста:
- `apps/ai_meeting_manager/plugins/schemas/plugin_manifest.schema.json`

Пример:

```json
{
  "id": "text_processing.my_plugin",
  "name": "My Plugin",
  "product_name": "My Plugin",
  "highlights": "Коротко: что дает плагин",
  "description": "Подробно: что делает, ограничения, где полезен",
  "ui_stage": "llm_processing",
  "tags": ["Minutes", "Summary"],
  "howto": [
    "Откройте Settings > AI Processing.",
    "Выберите плагин.",
    "Запустите обработку встречи."
  ],
  "version": "0.1.0",
  "api_version": "1",
  "entrypoint": "plugins.text_processing.my_plugin.my_plugin:Plugin",
  "dependencies": ["requests==2.32.3"],
  "distribution": {
    "channel": "catalog",
    "owner_type": "first_party",
    "pricing_model": "free",
    "requires_platform_edition": true,
    "catalog_enabled": true
  },
  "hooks": [
    { "name": "postprocess.after_transcribe", "mode": "optional", "priority": 100 }
  ],
  "artifacts": ["edited"],
  "ui_schema": {
    "settings": [
      { "key": "max_items", "label": "Max Items", "value": "12", "advanced": false }
    ]
  }
}
```

## 4. `plugin_passport.json`: для runtime/provider/model metadata

Passport используйте для:
- `provider` (имя/описание провайдера),
- `models` (статический каталог моделей),
- `capabilities` (runtime/ui/models/health и т.д.).

Не храните там UI-копирайт карточек плагина.

## 4.1 `distribution`: для product/distribution metadata

Если плагин должен распространяться через удаленный каталог или marketplace, используйте
`plugin.json.distribution`.

Рекомендуемые поля:

- `channel`
- `owner_type`
- `pricing_model`
- `requires_platform_edition`
- `catalog_enabled`
- `billing_product_id`
- `fallback_plugin_id`

Важно:

- это metadata для catalog/entitlement слоя, а не повод ветвить `aimn.core` по `plugin_id`;
- runtime по-прежнему должен работать только с локально установленным плагином;
- фактические коммерческие правила могут доопределяться локальной политикой приложения.

Пример локальных файлов моделей:

```json
{
  "capabilities": {
    "models": {
      "local_files": {
        "root_setting": "models_dir",
        "default_root": "models/whisper",
        "glob": "ggml-*.bin"
      }
    }
  }
}
```

## 5. Контракт hook/artifact

1. Любой `kind`, который пишет плагин, должен быть:
   - объявлен в `plugin.json.artifacts`;
   - зарегистрирован через `ctx.register_artifact_kind(...)`.
2. `content_type` и `user_visible` должны совпадать со схемой.
3. Пустые артефакты запрещены.
4. Ошибки/варнинги должны быть машинно понятны (стабильные коды), чтобы UI мог локализовать сообщения.

### 5.1 `ctx` в `Plugin.register(ctx)` (PluginContext)

Доступные методы:
- `register_hook_handler(hook_name, handler, mode="optional", priority=100, handler_id=None)`
- `register_artifact_kind(kind, ArtifactSchema | dict)`
- `subscribe(event_name, handler)` (подписка на внутренние события)
- `register_settings_schema(provider_callable)`
- `register_actions(provider_callable)`
- `register_job_provider(provider_callable)`
- `register_service(service_name, provider_callable)`
- `get_service(service_name)`
- `get_settings()` / `set_settings(new_settings, secret_fields=[...])`
- `get_setting(key, default=None)`
- `get_plugin_config()`
- `get_secret(key, default=None)` / `set_secret(key, value)`
- `get_storage_path()`
- `get_logger()`

Как получить свои настройки из `ui_schema.settings`:
- в `register(...)`: `settings = ctx.get_settings()`;
- в hook: используйте `ctx.plugin_config` (это объединенные plugin settings + stage params для запуска).

Пример:

```python
def register(self, ctx) -> None:
    settings = ctx.get_settings()
    max_items = int(settings.get("max_items", 12))
```

### 5.2 `ctx` в hook-функции (HookContext)

Поля:
- `plugin_id`, `meeting_id`, `alias`
- `input_text`, `input_media_path`
- `force_run`
- `plugin_config`

Методы:
- `get_artifact(kind) -> Artifact | None`
- `list_artifacts() -> list[ArtifactMeta]`
- `write_artifact(kind, content, content_type=...)`
- `emit_warning(code)`
- `build_result()`
- `get_setting(key, default=None)`
- `get_secret(key, default=None)`
- `get_service(name)`
- `log(level, message)` / `logger`
- `artifacts.get_artifact(...)`, `artifacts.list_artifacts()`, `artifacts.save_artifact(...)`

Важно:
- для доступа к другим артефактам используйте `get_artifact(...)` и `list_artifacts()`;
- прямой доступ к `aimn.core.*` запрещен.
- `meeting_path`/`artifacts_dir` в `HookContext` в API v1 не предоставляются.
- `storage_path` теперь доступен в `HookContext` (персональная папка плагина для state/cache).

Доступ к настройкам в hook:
- `cfg = dict(ctx.plugin_config or {})`
- `max_items = int(cfg.get("max_items", 12))`

Важно по именам API:
- `ctx.settings[...]` в API v1 нет;
- `ctx.get_config()` в API v1 нет;
- используйте `ctx.plugin_config` в hook и `ctx.get_settings()` в `register(...)`.

Где брать входные данные по типам hook:
- `transcribe.run`: входной медиа-файл в `ctx.input_media_path`.
- `postprocess.after_transcribe`: текст транскрипции в `ctx.input_text`.
- `derive.after_postprocess`: текст после постобработки в `ctx.input_text`.
- `derive.after_summary`: чаще используйте `ctx.get_artifact(KIND_SUMMARY)` / `ctx.get_artifact(KIND_EDITED)`; `ctx.input_text` может быть пустым.

Референс реальных интерфейсов в коде:
- `apps/ai_meeting_manager/src/aimn/plugins/interfaces.py`
- `apps/ai_meeting_manager/src/aimn/core/contracts.py`
- `apps/ai_meeting_manager/src/aimn/core/plugin_services.py`

### 5.3 Координация между плагинами (event bus / зависимости)

Текущее поведение API v1:
- поддерживается подписка через `subscribe(event_name, handler)`;
- публикация собственных событий из hook-контекста не поддерживается как публичный API;
- гарантированный путь оркестрации: hooks + приоритеты + артефакты.

Рекомендуемый паттерн для "дождаться другого плагина":
1. Первый плагин пишет артефакт стабильного `kind`.
2. Второй плагин в своем hook читает его через `ctx.get_artifact(kind)`.
3. При необходимости фиксируйте порядок через `priority` и отдельные hook-имена.

Практические event names, на которые обычно подписываются service-плагины:
- `artifact_written`
- `cache_hit`
- `plugin_notice`
- `warning`
- `stage_progress`
- `settings.updated`

### 5.4 Управление зависимостями (Dependencies)

Текущее поведение API v1:
- для изолированных hooks/actions поддерживается plugin-specific runtime (`config/plugin_envs/<plugin_id>/venv`);
- runtime учитывает `plugin.json.dependencies` и `requirements.txt` в папке плагина;
- при отсутствии зависимостей или при ошибке подготовки окружения есть fallback на Python-окружение приложения.

Рекомендуемый контракт:
- объявляйте сторонние библиотеки в `plugin.json.dependencies` (опционально), например `["requests==2.32.3", "nltk>=3.9"]`;
- при сложных зависимостях добавляйте `requirements.txt` в корень плагина;
- проверяйте манифест через `python -m aimn.cli plugin validate ...` до запуска UI;
- если библиотека обязательна, отдавайте понятную ошибку/warning при импорте (`dependency_missing:<name>`).
- авто-установку можно отключить через `AIMN_PLUGIN_AUTO_INSTALL_DEPS=0`.

### 5.5 Логирование

Рекомендуемый путь:
- используйте `logger = ctx.get_logger()` в `Plugin.register(...)`;
- не используйте `print()` как основной канал отладки.

Fallback (если логгер нужно получить вне `register`):
- `logging.getLogger("aimn.plugin.<plugin_id>")`.

### 5.6 Локальное хранилище и state

Текущее поведение API v1:
- `ctx.storage_path` существует и указывает на персональную папку плагина;
- state/настройки плагина по-прежнему можно хранить через `get_settings()` / `set_settings(...)`.

Где физически хранится:
- обычные данные: `apps/ai_meeting_manager/config/settings/plugins/<plugin_id>.json`;
- файловый state/cache плагина: `apps/ai_meeting_manager/config/plugin_state/<plugin_id>/`;
- секреты: `apps/ai_meeting_manager/config/secrets.toml` (или `AIMN_<PREFIX>_<FIELD>` env).

Правила:
- не пишите state в папку кода плагина;
- для дедупликации (например Todoist) храните ids/hash в settings payload плагина.

Секреты в `ui_schema.settings` (API v1):
- отдельного типа поля (`"type": "password"` / `"secret"`) как контракта пока нет;
- masking в UI включается по имени ключа (`api_key`, `*_token`, `*_secret`, `password`, и т.п.);
- если поле должно быть секретным, называйте ключ в этой конвенции.
- секреты в `secrets.toml` шифруются на Windows через DPAPI (совместимо с legacy plain значениями).

### 5.7 Жизненный цикл и async

Текущее поведение API v1:
- hook handlers поддерживают и `def`, и `async def` (корутина будет `await`);
- публичного `unregister(...)` для hooks/events нет.
- hooks запускаются в pipeline worker (не в UI-потоке), поэтому UI обычно не зависает, но сама стадия конвейера ждет завершения хука.

Lifecycle:
- если плагину нужно освободить ресурсы, реализуйте `shutdown(self)` в классе плагина;
- рантайм вызывает `plugin.shutdown()` при остановке менеджера плагинов (best-effort).

Рекомендации:
- для HTTP-интеграций используйте таймауты и retry;
- если операция долгая, возвращайте машинно понятные warnings/codes, чтобы UI мог объяснить задержку.
- для тяжелых/сетевых плагинов используйте изоляцию hook в subprocess (`isolated_hook_plugins`), чтобы отделить выполнение от процесса UI.

### 5.8 Внутренние сервисы через `ctx`

Что есть в API v1:
- логгер: `ctx.get_logger()` (в `Plugin.register(...)`);
- в hook-функции используйте `logging.getLogger(f"aimn.plugin.{ctx.plugin_id}")`;
- доступ к артефактам: `ctx.get_artifact(...)`, `ctx.list_artifacts()`, `ctx.write_artifact(...)`;
- настройки плагина: `ctx.get_settings()` / `ctx.set_settings(...)` в `register`, `ctx.plugin_config` в hook.
- сервисы: `register_service(...)` / `get_service(...)` в `Plugin.register(...)`, `ctx.get_service(...)` в hook.
- секреты: `ctx.get_secret(...)` в `register` и hook.
- storage: `ctx.get_storage_path()` в `register`, `ctx.storage_path` в hook.
- helper API для плагинов: `aimn.plugins.api` (`load_prompt_presets`, `resolve_prompt`, `build_prompt`, `open_management_store`, `get_content`).

Чего нет в публичном API v1:
- встроенного HTTP-клиента;
- публичного доступа к файловой системе встречи (`ctx.meeting_path`, `ctx.artifacts_dir`);
- выделенной plugin sandbox path (`ctx.plugin_storage_path`).
- `ctx.prompts` / `ctx.db` / `ctx.http`.

Важно:
- если нужен доступ к prompt presets, используйте `aimn.plugins.api.load_prompt_presets(...)` + `resolve_prompt(...)`;
- если нужен доступ к локальной БД задач/проектов/повесток, используйте `aimn.plugins.api.open_management_store(ctx)`.
- shared services (например `llm`, `embeddings`) считаются опциональными: плагин должен иметь fallback, если `ctx.get_service(...)` вернул `None`.

### 5.9 Reference API (`ctx`) для разработки "вслепую"

Ниже минимальный публичный reference для Plugin API v1.

`PluginContext` (`register(self, ctx)`):
- `register_hook_handler(hook_name, handler, mode="optional", priority=100, handler_id=None) -> None`
- `register_artifact_kind(kind, ArtifactSchema | dict) -> None`
- `subscribe(event_name, handler) -> None`
- `register_settings_schema(provider_callable) -> None`
- `register_actions(provider_callable) -> None`
- `register_job_provider(provider_callable) -> None`
- `register_service(service_name, provider_callable) -> None`
- `get_service(service_name) -> Any`
- `get_settings() -> dict`
- `get_setting(key: str, default: Any = None) -> Any`
- `set_settings(new_settings: dict, secret_fields: Iterable[str]) -> None`
- `get_plugin_config() -> dict`
- `get_secret(key: str, default: str | None = None) -> str | None`
- `set_secret(key: str, value: str | None) -> None`
- `get_storage_path() -> str`
- `get_logger() -> logging.Logger`

`HookContext` (hook-функции):
- поля: `plugin_id`, `meeting_id`, `alias`, `input_text`, `input_media_path`, `force_run`, `plugin_config`
- поля: `storage_path`, `settings`, `logger`, `artifacts`
- `get_artifact(kind: str) -> Artifact | None`
- `list_artifacts() -> list[ArtifactMeta]`
- `write_artifact(kind: str, content: Any, content_type: str | None = None) -> None`
- `emit_warning(message: str) -> None`
- `build_result() -> PluginResult`
- `get_setting(key: str, default: Any = None) -> Any`
- `get_secret(key: str, default: str | None = None) -> str | None`
- `get_service(name: str) -> Any`
- `log(level: PluginLogLevel | str, message: str) -> None`

Краткие ответы на частые вопросы:
- Можно ли `ctx.log.info(...)`? Нет, используйте `ctx.get_logger()` в `register` или `logging.getLogger(...)` в hook.
- Можно ли `ctx.storage_dir`/`ctx.storage_path`? `ctx.storage_dir` нет; `ctx.storage_path` есть (персональная папка плагина).
- Можно ли взять задачи из LLM-этапа? Да: `ctx.get_artifact("tasks")` (если артефакт такого `kind` был записан).
- Есть ли `ctx.prompts.get(...)`? Нет, используйте `aimn.plugins.api.load_prompt_presets()` и `resolve_prompt(...)`.
- Есть ли `ctx.db.query_tasks(...)`? Нет, используйте `aimn.plugins.api.open_management_store(ctx)` и методы `ManagementStore`.
- Где брать входные данные?
1. Текстовые hooks: `ctx.input_text`.
2. Транскрибация: `ctx.input_media_path`.
3. Доп. данные: через `ctx.get_artifact(...)`/`ctx.list_artifacts()`.

### 5.10 Долгие операции: actions/jobs вместо async hooks

Для внешних API (Todoist/Notion/Trello/LM Studio) в API v1 рекомендуется:
- в hook делать только быстрый шаг подготовки/валидации;
- сетевую интеграцию запускать через plugin actions и job provider.

Контракт:
- объявляйте action через `register_actions(...)` и `ActionDescriptor`;
- для фоновых операций ставьте `run_mode="async"` (ядро вернет `job_id` и ведет статус встроенным worker);
- при необходимости полного контроля можно дополнительно использовать `register_job_provider(...)` (`get_status(job_id)`, `cancel(job_id)`).

Важно:
- `async def hook_*` поддерживается;
- любой hook (sync/async) выполняется в рамках стадии, поэтому долгий HTTP внутри hook задержит завершение стадии.

### 5.11 Хуки индексации и события pipeline

Для search/index плагинов выделенного hook `on_meeting_processed` в API v1 нет.

Рабочие варианты:
- подписка на события в `register(...)`: `ctx.subscribe("artifact_written", handler)` и/или `ctx.subscribe("pipeline_finished", handler)`;
- стабильные алиасы для интеграций: `ctx.subscribe("on_artifact_stored", handler)`, `ctx.subscribe("on_meeting_completed", handler)`;
- обновление индекса в обычных hooks (`postprocess.after_transcribe`, `derive.after_postprocess`, `derive.after_summary`) по артефактам.

Payload события (через `subscribe`) содержит поля:
- `event_type`, `meeting_id`, `base_name`, `stage_id`, `alias`, `kind`, `relpath`, `progress`, `timestamp`, `event_message`.

Практика:
- для инкрементального индекса используйте `artifact_written`;
- для финальной консолидации по встрече используйте `pipeline_finished`.

### 5.12 Иерархия `group.id`

Соглашение по именам:
- формат: `<group>.<name>`;
- рекомендуемые группы: `transcription`, `text_processing`, `llm`, `management`, `service`, `search`, `ui`;
- допускаются новые группы, если они не конфликтуют с существующими.

Рекомендации:
- используйте стабильный vendor/domain в `name` (`service.todoist_sync`, `text_processing.acme_refiner`);
- не переиспользуйте чужие `plugin_id`.

### 5.13 Magic Strings & Constants (закрытые перечни)

`ui_stage`:
- `transcription`
- `llm_processing`
- `management`
- `service`
- `other`

Секреты в `ui_schema.settings` (конвенции имен ключей):
- `*_token`
- `*_secret`
- `*_api_key`
- `password`

Рекомендуемые hook names:
- `transcribe.run`
- `postprocess.after_transcribe`
- `derive.after_postprocess`
- `derive.after_summary`

Базовые `kind` для артефактов:
- `transcript`
- `edited`
- `summary`
- `tasks`
- `projects`
- `agendas`
- `segments`

## 6. UI и тема: новые требования

### 6.1 Предпочтительный путь (для большинства плагинов)

Используйте только декларативный UI через `ui_schema.settings` и `capabilities`.
Не требуйте встраивания произвольных виджетов в core/UI.

### 6.2 Если плагин все же создает Qt UI (например, `ui.*` плагины)

Обязательные правила:

1. Используйте стандартные компоненты из `aimn.ui.widgets.standard_components`:
   - `StandardPanel`
   - `StandardCard`
   - `StandardBadge`
   - `StandardActionButton`
   - `StandardTextSourceView`
2. Не хардкодьте "чисто белые/чисто черные" фоны и бордеры.
3. Используйте полупрозрачные поверхности и контрастный текст (UI поддерживает 4 темы: `light`, `dark`, `light_mono`, `dark_mono`).
4. Не хардкодьте английские статусы в интерфейсе. Статусы должны быть кодами, а отображение локализуется в UI.
5. Не ломайте синхронный UX текста/сегментов (скролл и выделение управляются контейнерным UI).

Ограничение API v1:
- публичной точки расширения для "вклейки" произвольного `StandardPanel` в главное окно нет;
- для внешних плагинов поддерживаемый UI-путь: `ui_schema.settings` + actions + capabilities.

## 7. Локализация: обязательные правила

1. Все user-facing тексты плагина должны быть собраны в manifest-данных (`plugin.json`), а не размазаны по коду.
2. Для `ui_schema.settings` заполняйте человекочитаемые `label` и `options.label`.
3. Если плагин отправляет текст в UI через `ActionResult.message`, избегайте только англоязычных фраз:
   - либо отдавайте нейтральный код (`ok`, `model_missing`, `invalid_input`),
   - либо отдавайте локализуемый payload в `data` и код в `message`.
4. Учтите, что текущий core не подменяет тексты `plugin.json` по locale автоматически: формулируйте тексты понятно для вашей целевой локали.

## 8. Контракт для search-плагинов (если реализуете global search)

Action `search` должен возвращать:

```json
{
  "query": "строка",
  "total": 10,
  "hits": [
    {
      "meeting_id": "...",
      "stage_id": "...",
      "alias": "...",
      "kind": "transcript",
      "relpath": "...",
      "snippet": "...[найденное]...",
      "segment_index": 123,
      "start_ms": 456000,
      "end_ms": 458000,
      "content": "полный текст документа (опционально)",
      "context": "контекст (рекомендуется: 3 строки)"
    }
  ]
}
```

Важно:
- `snippet` с маркерами `[...]` используется для объяснимости выдачи.
- `context` обязателен для UX выдачи (в результатах показываются текстовые выборки, кликабельные для перехода к артефакту).
- `segment_index/start_ms/end_ms` считаются опциональными навигационными подсказками, не обязательным контрактом.

## 9. Чеклист перед передачей

1. Плагин загружается без ошибок в `Plugins` табе.
2. Все declared hooks реально зарегистрированы в `Plugin.register(...)`.
3. Все output kinds зарегистрированы через `ctx.register_artifact_kind(...)`.
4. Нет импортов `aimn.core.*` внутри плагина.
5. Нет хардкода цветов/тем (для UI-плагинов).
6. Нет хардкода только английских пользовательских текстов.
7. Обновлены `README/спецификации` плагина и примеры настроек.

## 10. Минимальный шаблон кода

```python
from aimn.plugins.interfaces import HookContext, PluginResult, PluginOutput, ArtifactSchema, KIND_EDITED


class Plugin:
    def register(self, ctx) -> None:
        ctx.register_artifact_kind(KIND_EDITED, ArtifactSchema(content_type="text/markdown", user_visible=True))
        ctx.register_hook_handler("postprocess.after_transcribe", hook_postprocess, mode="optional", priority=100)


def hook_postprocess(ctx: HookContext) -> PluginResult:
    text = (ctx.input_text or "").strip()
    if not text:
        text = "_No input text._"
    return PluginResult(
        outputs=[PluginOutput(kind=KIND_EDITED, content=text, content_type="text/markdown", user_visible=True)],
        warnings=[],
    )
```

## 11. Локальная валидация плагина (CLI)

Перед запуском UI можно проверить манифест и entrypoint:

```bash
python -m aimn.cli plugin validate <path-to-plugin.json-or-plugin-dir>
```

Alias для CI/линтинга:

```bash
python -m aimn.cli plugin lint <path-to-plugin.json-or-plugin-dir>
```

Пример:

```bash
python -m aimn.cli plugin validate plugins/search/simple
```

Проверка каталога всех плагинов:

```bash
python -m aimn.cli plugin lint
```

Проверка валидирует:
- обязательные поля `plugin.json`;
- корректность `entrypoint`;
- формат поля `dependencies` (если указано);
- JSON Schema (`plugin_manifest.schema.json`);
- `ui_stage` (только допустимые enum-значения);
- формат `ui_schema.settings[].options` (только объекты `{label, value}`);
- частые API-ошибки (`resolve_prompt(...)` сигнатура, несуществующие методы `ManagementStore`).

Type stubs для IDE (рекомендуется подключить в проекте плагина):
- `apps/ai_meeting_manager/src/aimn/plugins/interfaces.pyi`
- `apps/ai_meeting_manager/src/aimn/plugins/api.pyi`
- `apps/ai_meeting_manager/src/aimn/plugins/prompt_manager.pyi`

---

Если вам нужна "официальная" точка входа для команды, используйте этот файл как основной onboarding-документ для разработки новых плагинов.
