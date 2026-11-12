# Call-site sweep before any removal (routing-v2 task 5.1)

Run mechanically on 2026-11-11 at the head that holds tasks 2.1 to 4.2 (so `settings.py`,
`__main__.py` and `server.py` already carry the router margin, the evidence holder and the
startup warnings of 4.2; none of those touches a reader below). The raw `rg` output is kept per
command, then each reader is classified with the task that must change it. Later tasks tick items
off the checklist at the end; task 8.1 re-runs the same commands and compares.

### 1. tier table, tier names and tier sentences

`rg -n "dynamic_target|DYNAMIC_PRESETS|dynamic_route|tier_of|tier_runs|describe_tiers|classifier_sentence|TIER_NAMES" src tests`

```
src/mcp_perplexity_pro/__main__.py:54:    from mcp_perplexity_pro.routing import describe_tiers
src/mcp_perplexity_pro/__main__.py:87:        logger.info("routing mode dynamic: %s", describe_tiers(settings))
src/mcp_perplexity_pro/settings.py:25:TIER_NAMES = ("light", "standard", "complex")
src/mcp_perplexity_pro/settings.py:174:            wanted = {f"TIER_{t.upper()}": getattr(self, f"tier_{t}") for t in TIER_NAMES}
src/mcp_perplexity_pro/settings.py:176:            wanted = {f"TIER_{t.upper()}": getattr(self, f"tier_{t}") for t in TIER_NAMES}
src/mcp_perplexity_pro/settings.py:214:        unused = ["model"] if self.routing == "custom" else [f"tier_{t}" for t in TIER_NAMES]
src/mcp_perplexity_pro/settings.py:235:DYNAMIC_PRESETS = {"light": "fast", "complex": "medium"}
src/mcp_perplexity_pro/settings.py:238:def dynamic_target(settings: Settings, tier: str) -> tuple[str | None, str | None]:
src/mcp_perplexity_pro/settings.py:245:    return (model, None) if model is not None else (None, DYNAMIC_PRESETS[tier])
src/mcp_perplexity_pro/settings.py:248:def tier_runs(settings: Settings, tier: str) -> str:
src/mcp_perplexity_pro/settings.py:250:    model, preset = dynamic_target(settings, tier)
src/mcp_perplexity_pro/routing.py:14:from mcp_perplexity_pro.settings import TIER_NAMES, Settings, dynamic_target, tier_runs
src/mcp_perplexity_pro/routing.py:49:def dynamic_route(
src/mcp_perplexity_pro/routing.py:59:    model, preset = dynamic_target(settings, tier)
src/mcp_perplexity_pro/routing.py:63:def tier_of(settings: Settings, preset: str | None, model: str | None) -> str:
src/mcp_perplexity_pro/routing.py:71:    routes = {tier: dynamic_route(settings, tier) for tier in TIER_NAMES}
src/mcp_perplexity_pro/routing.py:73:        matches = [t for t in TIER_NAMES if routes[t].preset == preset]
src/mcp_perplexity_pro/routing.py:75:        matches = [t for t in TIER_NAMES if routes[t].model == model]
src/mcp_perplexity_pro/routing.py:95:        return dynamic_route(settings, "standard", selected_by="default", reason="search off")
src/mcp_perplexity_pro/routing.py:98:            return dynamic_route(settings, "standard", selected_by="default")
src/mcp_perplexity_pro/routing.py:101:    if previous in TIER_NAMES and TIER_NAMES.index(previous) > TIER_NAMES.index(tier):
src/mcp_perplexity_pro/routing.py:103:    return dynamic_route(settings, tier, reason=_cap(reason), classifier=classification.classifier)
src/mcp_perplexity_pro/routing.py:151:        if tier not in TIER_NAMES:
src/mcp_perplexity_pro/routing.py:152:            raise _bad("tier", f"must be one of {', '.join(TIER_NAMES)}.")
src/mcp_perplexity_pro/routing.py:154:            route = dynamic_route(settings, tier, selected_by="tier")
src/mcp_perplexity_pro/routing.py:181:def describe_tiers(settings: Settings) -> str:
src/mcp_perplexity_pro/routing.py:184:    for tier in TIER_NAMES:
src/mcp_perplexity_pro/routing.py:185:        route = dynamic_route(settings, tier)
src/mcp_perplexity_pro/routing.py:191:def classifier_sentence(settings: Settings) -> str:
src/mcp_perplexity_pro/routing.py:214:            f"the prompt: light runs {tier_runs(settings, 'light')}, standard runs "
src/mcp_perplexity_pro/routing.py:215:            f"{tier_runs(settings, 'standard')}, complex runs {tier_runs(settings, 'complex')}. "
src/mcp_perplexity_pro/routing.py:217:            f"{classifier_sentence(settings)}"
src/mcp_perplexity_pro/routing.py:245:            f"light = {tier_runs(settings, 'light')} (short lookups), "
src/mcp_perplexity_pro/routing.py:246:            f"standard = {tier_runs(settings, 'standard')} (everyday work), "
src/mcp_perplexity_pro/routing.py:247:            f"complex = {tier_runs(settings, 'complex')} (analysis, long or multi-part prompts). "
src/mcp_perplexity_pro/routing.py:249:            f"server's choice. {classifier_sentence(settings)}"
src/mcp_perplexity_pro/routing_decisions.py:31:from mcp_perplexity_pro.settings import TIER_NAMES, Settings
src/mcp_perplexity_pro/routing_decisions.py:90:    if choice not in TIER_NAMES:
src/mcp_perplexity_pro/routing_decisions.py:101:    if TIER_NAMES.index(base.tier) > TIER_NAMES.index(tier):
src/mcp_perplexity_pro/help_text.py:15:from mcp_perplexity_pro.settings import Settings, tier_runs
src/mcp_perplexity_pro/help_text.py:253:            f"{tier_runs(settings, 'light')}, standard {tier_runs(settings, 'standard')}, "
src/mcp_perplexity_pro/help_text.py:254:            f"complex {tier_runs(settings, 'complex')})."
src/mcp_perplexity_pro/help_text.py:360:            f"light = {tier_runs(settings, 'light')} (short lookups), "
src/mcp_perplexity_pro/help_text.py:361:            f"standard = {tier_runs(settings, 'standard')} (everyday), "
src/mcp_perplexity_pro/help_text.py:362:            f"complex = {tier_runs(settings, 'complex')} (analysis, long or multi-part prompts). "
src/mcp_perplexity_pro/tools/chat.py:36:from mcp_perplexity_pro.routing import description_sentence, resolve, tier_of
src/mcp_perplexity_pro/tools/chat.py:237:        floor = None if previous is None else tier_of(app.settings, *previous)
src/mcp_perplexity_pro/tools/models.py:13:from mcp_perplexity_pro.settings import TIER_NAMES, Settings, dynamic_target
src/mcp_perplexity_pro/tools/models.py:152:        for tier in TIER_NAMES:
src/mcp_perplexity_pro/tools/models.py:153:            model, preset = dynamic_target(settings, tier)
src/mcp_perplexity_pro/tools/models.py:165:        wanted = [(t, getattr(settings, f"tier_{t}")) for t in TIER_NAMES]
tests/test_routing.py:13:    dynamic_route,
tests/test_routing.py:16:    tier_of,
tests/test_routing.py:181:    assert dynamic_route(dynamic, "light") == Route("dynamic", "light", None, "fast", "classifier")
tests/test_routing.py:182:    assert dynamic_route(dynamic, "standard").model == "perplexity/sonar"
tests/test_routing.py:183:    assert dynamic_route(dynamic, "standard").preset is None
tests/test_routing.py:184:    assert dynamic_route(dynamic, "complex").preset == "medium"
tests/test_routing.py:185:    assert dynamic_route(dynamic, "complex").model is None
tests/test_routing.py:189:    assert dynamic_route(make_settings(routing="dynamic", model="x/m"), "standard").model == "x/m"
tests/test_routing.py:191:    assert dynamic_route(both, "standard").model == "x/s"
tests/test_routing.py:196:    light, complex_ = dynamic_route(s, "light"), dynamic_route(s, "complex")
tests/test_routing.py:201:def test_dynamic_route_ignores_the_custom_tier_fields_of_another_mode(make_settings):
tests/test_routing.py:203:    assert dynamic_route(make_settings(routing="dynamic"), "light").preset == "fast"
tests/test_routing.py:376:                    assert dynamic_route(s, tier).preset not in LONG_DEPTHS
tests/test_routing.py:379:# --- tier_of: the tier a stored turn ran ----------------------------------------------------
tests/test_routing.py:382:def test_tier_of_reads_the_stored_preset_first(dynamic):
tests/test_routing.py:383:    assert tier_of(dynamic, "fast", "perplexity/sonar") == "light"
tests/test_routing.py:384:    assert tier_of(dynamic, "medium", "perplexity/sonar") == "complex"
tests/test_routing.py:385:    assert tier_of(dynamic, "medium", None) == "complex"
tests/test_routing.py:388:def test_tier_of_matches_a_model_against_the_tiers_models(dynamic, make_settings):
tests/test_routing.py:389:    assert tier_of(dynamic, None, "perplexity/sonar") == "standard"
tests/test_routing.py:391:    assert tier_of(s, None, "anthropic/claude-opus-5-5") == "complex"
tests/test_routing.py:392:    assert tier_of(s, "medium", "perplexity/sonar") == "standard"  # a replaced tier has no preset
tests/test_routing.py:396:    assert tier_of(dynamic, None, "vendor/explicit") == "standard"
tests/test_routing.py:397:    assert tier_of(dynamic, None, None) == "standard"
tests/test_routing.py:398:    assert tier_of(dynamic, "low", "vendor/explicit") == "standard"
tests/test_routing.py:403:    assert tier_of(s, None, "x/same") == "standard"
tests/test_routing.py:405:    assert tier_of(s, None, "x/same") == "complex"
tests/test_routing.py:409:    assert tier_of(s, None, "x/same") == "complex"
tests/test_routing_dynamic_tools.py:83:async def test_a_replaced_tier_runs_its_model_as_an_explicit_model_call_would(world):
```

`rg -n "resolve\(" src`

```
src/mcp_perplexity_pro/routing.py:106:def resolve(
src/mcp_perplexity_pro/storage/migrate.py:47:MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
src/mcp_perplexity_pro/storage/migrate.py:162:    versions = (script_location / "versions").resolve()
src/mcp_perplexity_pro/storage/migrate.py:165:        path = Path(frame.filename).resolve()
src/mcp_perplexity_pro/routing_decisions.py:4:and returns a ``rules.Classification``; the caller hands it to ``routing.resolve(...,
src/mcp_perplexity_pro/tools/chat.py:245:        route = resolve(
src/mcp_perplexity_pro/tools/chat.py:588:                route=resolve(app.settings, depth=depth, tier=tier, model=model, search=search),
src/mcp_perplexity_pro/tools/ask.py:228:            route=resolve(
src/mcp_perplexity_pro/tools/ask.py:253:                route=resolve(
```

(Only `routing.py:106` defines `resolve`; the `storage/migrate.py` hits are `Path.resolve`.)

`rg -n "wants_decider" src tests`

```
src/mcp_perplexity_pro/routing_decisions.py:111:def wants_decider(
src/mcp_perplexity_pro/tools/chat.py:37:from mcp_perplexity_pro.routing_decisions import classify_dynamic, wants_decider
src/mcp_perplexity_pro/tools/chat.py:239:        if floor != "complex" and wants_decider(
src/mcp_perplexity_pro/tools/chat.py:586:            )  # the rules, or the Decisions classifier (``wants_decider``), run in ``_send``
src/mcp_perplexity_pro/tools/ask.py:26:from mcp_perplexity_pro.routing_decisions import classify_dynamic, wants_decider
src/mcp_perplexity_pro/tools/ask.py:224:        decider = wants_decider(app.settings, depth=depth, tier=tier, model=model, search=search)
```

`rg -n "upto_0003|upto_0004|head_revision|current_revision" tests`

```
tests/test_chats_migration.py:17:    current_revision,
tests/test_chats_migration.py:60:def upto_0003(tmp_path):
tests/test_chats_migration.py:117:def test_a_fresh_database_reaches_0003(settings, db, upto_0003):
tests/test_chats_migration.py:118:    result = migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:120:    assert current_revision(db) == "0003"
tests/test_chats_migration.py:125:    settings, db, upto_0002, upto_0003
tests/test_chats_migration.py:143:    result = migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:152:def test_up_down_up_leaves_projects_and_usage_events_untouched(settings, db, upto_0003):
tests/test_chats_migration.py:153:    migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:167:    result = downgrade(settings, "0002", script_location=upto_0003)
tests/test_chats_migration.py:169:    assert current_revision(db) == "0002"
tests/test_chats_migration.py:175:    again = migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:186:def test_every_column_and_foreign_key_rule_is_as_designed(settings, db, upto_0003):
tests/test_chats_migration.py:187:    migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:214:def test_the_orm_models_match_the_migrated_tables(settings, db, upto_0003):
tests/test_chats_migration.py:215:    migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:229:def test_sqlite_sequence_holds_chats_and_a_deleted_newest_id_is_not_reused(settings, db, upto_0003):
tests/test_chats_migration.py:230:    migrate(settings, script_location=upto_0003)
tests/test_chats_migration.py:241:    settings, db, upto_0003
tests/test_chats_migration.py:243:    migrate(settings, script_location=upto_0003)
tests/test_usage_events_migration.py:17:    current_revision,
tests/test_usage_events_migration.py:19:    head_revision,
tests/test_usage_events_migration.py:112:    assert current_revision(db) == head_revision()
tests/test_usage_events_migration.py:139:    assert current_revision(db) == "0001"
tests/test_usage_events_migration.py:146:    assert current_revision(db) == head_revision()
tests/test_embeddings_migration.py:12:    current_revision,
tests/test_embeddings_migration.py:51:def upto_0004(tmp_path):
tests/test_embeddings_migration.py:149:    assert current_revision(db) == "0005" and "embedding_chunks" in names(db)
tests/test_embeddings_migration.py:153:    settings, db, upto_0004, upto_0005
tests/test_embeddings_migration.py:155:    migrate(settings, script_location=upto_0004)
tests/test_embeddings_migration.py:180:    assert result.applied == ("0005",) and current_revision(db) == "0004"
tests/test_storage_migrate.py:22:    current_revision,
tests/test_storage_migrate.py:24:    head_revision,
tests/test_storage_migrate.py:31:HEAD = head_revision()
tests/test_storage_migrate.py:147:    assert head_revision() == f"{numbers[-1]:04d}"
tests/test_storage_migrate.py:154:    head = head_revision()
tests/test_storage_migrate.py:155:    assert current_revision(db) == head
tests/test_storage_migrate.py:156:    while current_revision(db) is not None:  # one downgrade per revision proves each works
tests/test_storage_migrate.py:157:        before = current_revision(db)
tests/test_storage_migrate.py:162:    assert current_revision(db) == head
tests/test_storage_migrate.py:171:    assert current_revision(db) == head_revision() == HEAD
tests/test_storage_migrate.py:204:    assert current_revision(db) == HEAD
tests/test_storage_migrate.py:210:    assert current_revision(db) == NXT
tests/test_storage_migrate.py:220:    assert current_revision(db) is None
tests/test_storage_migrate.py:250:    assert current_revision(db) == HEAD
tests/test_storage_migrate.py:264:    assert current_revision(db) is None
tests/test_storage_migrate.py:289:def test_current_revision_of_a_non_database_file_is_a_migration_error(tmp_path):
tests/test_storage_migrate.py:293:        current_revision(bad)
tests/test_storage_migrate.py:382:    assert current_revision(db) == NXT
tests/test_jobs_migration.py:17:    current_revision,
tests/test_jobs_migration.py:19:    head_revision,
tests/test_jobs_migration.py:57:def upto_0004(tmp_path):
tests/test_jobs_migration.py:62:def upto_0003(tmp_path):
tests/test_jobs_migration.py:135:def test_a_fresh_database_reaches_0004(settings, db, upto_0004):
tests/test_jobs_migration.py:136:    result = migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:138:    assert current_revision(db) == "0004"
tests/test_jobs_migration.py:143:    settings, db, upto_0003, upto_0004
tests/test_jobs_migration.py:145:    migrate(settings, script_location=upto_0003)
tests/test_jobs_migration.py:159:    result = migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:178:    assert current_revision(db) == head_revision()
tests/test_jobs_migration.py:185:def test_up_down_up_leaves_projects_chats_and_usage_events_untouched(settings, db, upto_0004):
tests/test_jobs_migration.py:186:    migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:201:    result = downgrade(settings, "0003", script_location=upto_0004)
tests/test_jobs_migration.py:203:    assert current_revision(db) == "0003"
tests/test_jobs_migration.py:208:    again = migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:215:def test_every_column_key_index_and_the_unique_response_id_are_as_designed(settings, db, upto_0004):
tests/test_jobs_migration.py:216:    migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:249:def test_the_orm_model_matches_the_migrated_table(settings, db, upto_0004):
tests/test_jobs_migration.py:250:    migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:265:def test_a_deleted_newest_job_id_is_not_reused(settings, db, upto_0004):
tests/test_jobs_migration.py:266:    migrate(settings, script_location=upto_0004)
tests/test_jobs_migration.py:275:async def test_a_project_deleted_with_two_jobs_removes_and_counts_them(settings, db, upto_0004):
tests/test_jobs_migration.py:276:    migrate(settings, script_location=upto_0004)
```

`rg -n "AssistantTurn|last_route" src tests`

```
src/mcp_perplexity_pro/storage/chats.py:25:class AssistantTurn:
src/mcp_perplexity_pro/storage/chats.py:63:def _messages(chat_id: int, user_text: str, turn: AssistantTurn, now: datetime):
src/mcp_perplexity_pro/storage/chats.py:98:    session: AsyncSession, project_id: int, title: str, user_text: str, turn: AssistantTurn
src/mcp_perplexity_pro/storage/chats.py:114:    session: AsyncSession, project_id: int, chat_id: int, user_text: str, turn: AssistantTurn
src/mcp_perplexity_pro/storage/chats.py:160:async def last_route(session: AsyncSession, chat_id: int) -> tuple[str | None, str | None] | None:
src/mcp_perplexity_pro/tools/chat.py:40:    AssistantTurn,
src/mcp_perplexity_pro/tools/chat.py:49:    last_route,
src/mcp_perplexity_pro/tools/chat.py:222:                previous = await last_route(session, chat_id)
src/mcp_perplexity_pro/tools/chat.py:294:    turn = AssistantTurn(
tests/chat_support.py:78:    from mcp_perplexity_pro.storage.chats import AssistantTurn, append_turn, create_chat
tests/chat_support.py:84:        first = AssistantTurn(f"resp_{tag}1", f"answer {tag}1", "openai/gpt-6-luna", "fast", "[]")
tests/chat_support.py:87:            turn = AssistantTurn(f"resp_{tag}{n}", f"answer {tag}{n}", "openai/gpt-6-luna", "fast")
tests/test_chat_storage.py:9:    AssistantTurn,
tests/test_chat_storage.py:15:    last_route,
tests/test_chat_storage.py:35:def turn(n: int, text_: str | None = None) -> AssistantTurn:
tests/test_chat_storage.py:36:    return AssistantTurn(
tests/test_chat_storage.py:216:async def test_last_route_is_the_preset_and_model_of_the_last_assistant_turn(engine):
tests/test_chat_storage.py:220:        assert await last_route(session, cid) == ("fast", "openai/gpt-6-luna")
tests/test_chat_storage.py:223:            session, pid, cid, "question 2", AssistantTurn("resp_2", "a", "x/m", None)
tests/test_chat_storage.py:226:        assert await last_route(session, cid) == (None, "x/m")  # the newest assistant row wins
tests/test_chat_storage.py:229:async def test_last_route_of_a_chat_without_an_assistant_turn_or_a_missing_chat_is_none(engine):
tests/test_chat_storage.py:235:        assert await last_route(session, cid) is None
tests/test_chat_storage.py:236:        assert await last_route(session, cid + 99) is None
tests/test_chat_storage.py:239:async def test_last_route_reads_only_its_own_chat(engine):
tests/test_chat_storage.py:245:                session, pid, "two", "q", AssistantTurn("resp_o", "a", "x/o", "medium")
tests/test_chat_storage.py:249:        assert await last_route(session, first) == ("fast", "openai/gpt-6-luna")
tests/test_chat_storage.py:250:        assert await last_route(session, other) == ("medium", "x/o")
```

`rg -n "neither, the tier is picked|tier is picked from the prompt" src tests`

```
src/mcp_perplexity_pro/routing.py:138:                " (with neither, the tier is picked from the prompt)."
```

`rg -n "\.preset|ConfiguredModel" src`

```
src/mcp_perplexity_pro/tools/ask.py:34:class Routing(BaseModel):
src/mcp_perplexity_pro/tools/models.py:16:class ConfiguredModel(BaseModel):
src/mcp_perplexity_pro/tools/models.py:26:class RoutingSection(BaseModel):
src/mcp_perplexity_pro/tools/models.py:28:    models: Annotated[list[ConfiguredModel], Field(description="The configured model or tiers")]
src/mcp_perplexity_pro/tools/models.py:79:        RoutingSection, Field(description="Active routing; configuration, not live data")
src/mcp_perplexity_pro/tools/models.py:148:def routing_section(listing: Listing, settings: Settings) -> RoutingSection:
src/mcp_perplexity_pro/tools/models.py:155:                models.append(ConfiguredModel(name=tier, id=None, preset=preset, known=None))
src/mcp_perplexity_pro/tools/models.py:157:                models.append(ConfiguredModel(name=tier, id=model, known=model in live))
src/mcp_perplexity_pro/tools/models.py:158:        return RoutingSection(
src/mcp_perplexity_pro/tools/models.py:168:    return RoutingSection(
src/mcp_perplexity_pro/tools/models.py:170:        models=[ConfiguredModel(name=n, id=i, known=i in live) for n, i in wanted],
```

`rg -n "instructions_text|description_sentence" src tests`

```
src/mcp_perplexity_pro/routing.py:202:def description_sentence(settings: Settings) -> str:
src/mcp_perplexity_pro/routing.py:230:def instructions_text(settings: Settings) -> str:
src/mcp_perplexity_pro/tools/chat.py:36:from mcp_perplexity_pro.routing import description_sentence, resolve, tier_of
src/mcp_perplexity_pro/tools/chat.py:614:            f"{inspect.cleandoc(perplexity_chat.__doc__)}\n\n{description_sentence(settings)}{POINTER}"
src/mcp_perplexity_pro/tools/ask.py:25:from mcp_perplexity_pro.routing import Route, description_sentence, resolve
src/mcp_perplexity_pro/tools/ask.py:285:        description=f"{inspect.cleandoc(perplexity_ask.__doc__)}\n\n{description_sentence(settings)}{POINTER}",
src/mcp_perplexity_pro/server.py:36:from mcp_perplexity_pro.routing import instructions_text
src/mcp_perplexity_pro/server.py:281:        instructions=instructions_text(settings),
tests/test_routing_decisions_tools.py:14:from mcp_perplexity_pro.routing import description_sentence, instructions_text
tests/test_routing_decisions_tools.py:310:    for text in (instructions_text(settings), description_sentence(settings)):
tests/test_routing_decisions_tools.py:317:    for text in (instructions_text(settings), description_sentence(settings)):
tests/test_routing_decisions_tools.py:323:    assert w.server.instructions == instructions_text(w.settings)
tests/test_routing.py:1:"""routing.resolve and routing.instructions_text (routing-modes-config, task 1.2)."""
tests/test_routing.py:12:    description_sentence,
tests/test_routing.py:14:    instructions_text,
tests/test_routing.py:136:    text = instructions_text(standard)
tests/test_routing.py:144:    text = instructions_text(custom)
tests/test_routing.py:153:        text = instructions_text(settings)
tests/test_routing.py:154:        assert text == instructions_text(settings)
tests/test_routing.py:160:        assert "perplexity_help" in instructions_text(settings)
tests/test_routing.py:416:    text = instructions_text(dynamic)
tests/test_routing.py:428:    text = instructions_text(s)
tests/test_routing.py:434:    for text in (instructions_text(dynamic), description_sentence(dynamic)):
tests/test_routing.py:436:    assert instructions_text(dynamic) == instructions_text(dynamic)
tests/test_routing.py:437:    assert description_sentence(dynamic) == description_sentence(dynamic)
tests/test_routing.py:440:def test_the_dynamic_description_sentence_states_mode_tiers_and_override(dynamic):
tests/test_routing.py:441:    text = description_sentence(dynamic)
tests/test_routing.py:449:def test_the_other_modes_description_sentences_are_unchanged(standard, custom):
tests/test_routing.py:450:    assert "Routing mode: standard" in description_sentence(standard)
tests/test_routing.py:451:    assert "dynamic" not in description_sentence(standard)
tests/test_routing.py:452:    assert "Routing mode: custom" in description_sentence(custom)
tests/test_routing.py:453:    assert "dynamic" not in description_sentence(custom)
tests/test_routing.py:454:    assert "dynamic" not in instructions_text(standard) + instructions_text(custom)
tests/test_server.py:231:    from mcp_perplexity_pro.routing import instructions_text
tests/test_server.py:242:    assert text == instructions_text(cfg) and "standard" in text and "perplexity/sonar" in text
```

`rg -n "wants_decider|classify_dynamic" tests`

```
tests/test_routing_decisions.py:1:"""Task 1.2 (routing-decisions-classifier): ``classify_dynamic`` against ``MockTransport`` and the
tests/test_routing_decisions.py:23:from mcp_perplexity_pro.routing_decisions import CRITERIA, classify_dynamic
tests/test_routing_decisions.py:92:    return await classify_dynamic(app, prompt, project=project, tool=tool)
```

## Readers, by owner (the checklist later tasks tick off)

Legend: 5.3a = media-owned scaffolding (router-free), 5.2 = migration 0006, 5.3 = request
builder, 5.4 = router-owned wiring (one commit), 6.1 = polish only.

### The tier table and its helpers (all removed or rewritten by 5.4)

- [ ] `settings.py:235` `DYNAMIC_PRESETS`, `:238` `dynamic_target`, `:248` `tier_runs` (5.4 removes the first two; `tier_runs` text says `router` or the pinned model)
- [ ] `routing.py:14` import of `dynamic_target`, `tier_runs`; `:49` `dynamic_route`; `:63` `tier_of` (replaced by the stored tier plus the legacy preset match); `:71-75`, `:95-103`, `:151-154` readers of `dynamic_route`; `:181` `describe_tiers`; `:191` `classifier_sentence`; `:202` `description_sentence`; `:214-217`, `:245-249` `tier_runs` readers inside `description_sentence` and `instructions_text` (`:230`) (5.4 first wording, 6.1 polish; each description grows at most 70 bytes)
- [ ] `__main__.py:54`, `:87` `describe_tiers` startup log line (5.4)
- [ ] `help_text.py:15` import; `:253-254`, `:360-362` `tier_runs` text of the `routing` topic and the `ask`/`chat` pages (5.4 reads, 6.1 polishes)
- [ ] `tools/models.py:13` import; `:16-22` `ConfiguredModel.preset` (removed, -117 bytes); `:129-130`, `:152-155` `dynamic_target` reader that builds the preset rows; `:26` `RoutingSection` gains one `evidence` string (5.4)
- [ ] `tools/chat.py:36`, `:237` `tier_of` (the follow-up floor) (5.4)
- [ ] `tools/ask.py:25`, `:285` and `tools/chat.py:614` `description_sentence`; `server.py:36`, `:281` `instructions_text` (5.4 wording, 6.1 polish)
- [ ] `tests/test_routing.py:13-16`, `:181-205`, `:376`, `:379-409`, `:416-451` (dynamic_route, tier_of, instructions and description of dynamic mode) (5.4 rewrites; the standard and custom tests stay)
- [ ] `tests/test_routing_dynamic_tools.py:43-174` (classifier preset routes, search-off, refusals), `:205-340` (chat follow-ups and the `Routing` schema test at `:340`) (5.4 rewrites)
- [ ] `tests/test_routing_decisions_tools.py:14`, `:310-323` (`instructions_text`, `description_sentence`, the Decisions classifier with the tools) (5.4)

### The resolve sites (5.3a builds the D16 order; 5.4 adds the router)

- [ ] `routing.py:106` `resolve` (5.3a: `required_input`, `provisional` ignored; 5.4: `evidence`, `matrix`, `tool`, the dynamic path, `Route.effort`, `selected_by` `router`/`fallback`)
- [ ] `tools/ask.py:224` `wants_decider`, `:228` first `resolve`, `:253` second `resolve` after the classifier (5.3a order; 5.4 inputs)
- [ ] `tools/chat.py:245` the real `resolve` of a send, `:239` `wants_decider`, `:588` the validation-path `resolve`, `:586` comment (5.3a order; 5.4 inputs and the hold)
- [ ] `routing_decisions.py:111` `wants_decider` (5.4 drops the `search` condition), `:4` docstring that names `routing.resolve`
- [ ] `routing.py:138` the refusal text "with neither, the tier is picked from the prompt" and its tests (5.4: model and effort are picked instead)
- [ ] `tests/test_routing_decisions.py` (`wants_decider`, `classify_dynamic`), `tests/test_live_capture.py` (names `classify_dynamic`) (5.4 checks; the live capture needs no edit)

### Chat storage (5.2 migration and ORM, 5.4 write and read paths)

- [ ] `storage/chats.py:25` `AssistantTurn` (gains `tier`, `routed_model`), `:63` `_messages`, `:98`, `:114` `create_chat`/`append_turn` callers, `:160` `last_route` (returns tier and routed model)
- [x] `storage/models.py` `ChatMessage` ORM (5.2 adds the two nullable columns) (done in 5.2, migration `0006_chat_message_route.py`)
- [ ] `tools/chat.py:222` `last_route` (the follow-up hold of design D12), `:294` `AssistantTurn(...)` construction at the write path (5.4)
- [ ] `tests/chat_support.py:78-87` and `tests/test_chat_storage.py:9-250` build `AssistantTurn` positionally and assert `last_route` tuples (5.4 rewrites the `last_route` assertions; the positional constructors keep working because the two new fields default to `None`)

### Migration tests (5.2)

- [x] `tests/test_chats_migration.py:214` (rewritten in 5.2 to compare the ORM with the schema through 0006) `test_the_orm_models_match_the_migrated_tables` (ORM columns against the schema at 0003) BREAKS when the ORM gains columns: rewrite for the added columns. Its other tests build their own `upto_0003` directory and keep passing.
- [x] `tests/test_jobs_migration.py` (re-run unedited in 5.2, green; no jobs column; `head_revision()` at `:178` follows the head) and `tests/test_embeddings_migration.py` (its scratch directory is truncated at 0005, `:149` and `:180` stay true) are NOT affected: re-run, do not edit
- [ ] `tests/test_usage_events_migration.py:112`, `:146`, `tests/test_storage_migrate.py:31`, `:147-171`, `:204-264`, `:382` compare with `head_revision()` and follow the head by themselves: re-run, do not edit (`tests/test_storage_migrate.py:154-162` downgrades one revision at a time, so 0006's `downgrade()` must run there)

### Not readers of the tier table (checked, no change)

- `routing_decisions.py:31`, `:90`, `:101` and `settings.py:25`, `:174-214` use `TIER_NAMES` as the vocabulary of tier names, which stays.
- `storage/migrate.py:47`, `:162`, `:165` match `resolve` only as `Path.resolve`.
