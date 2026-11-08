"""The LLM part: builds the prompt from the CURRENT checklist, calls the model, checks the answer.

Providers:
  gemini  - Google Gemini API (free tier key from aistudio.google.com)
  openai  - any OpenAI-compatible API (default: Groq free tier)
  mock    - no key: simple rules so the UI can be tested
The model only returns answers, explanations and message numbers. Points are calculated in scoring.py.
"""
import json
import re
import time

from . import http_util, settings
from .facts import facts_to_text
from .scoring import validate_items


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    pass


# ---------------------------------------------------------------- prompt
SYSTEM_RULES = """Ты — эксперт отдела контроля качества брокерской компании. Ты оцениваешь работу ОПЕРАТОРА в диалоге с клиентом (чат или звонок) строго по чек-листу ниже.

## Общие правила
- Оценивается только оператор (speaker = operator). Реплики bot и system — контекст. Приветствие, согласие на обработку данных и ответы бота НЕ засчитываются оператору.
- Системные события («Личность клиента подтверждена», «Customer identity verified», «Клиенттің жеке басы расталды», «Оператор закрыл чат» и т.п.) — факты, на них можно ссылаться как на доказательство.
- Диалоги на русском, казахском и английском. Оценивай по смыслу на языке оригинала.
- Звонки — автоматическая расшифровка речи: в ней бывают ошибки распознавания и скрытые данные вида [Имя скрыто]. Не наказывай оператора за ошибки распознавания. «Меня зовут [Имя скрыто]» = оператор представился.
- "no" — действие требовалось, но оператор его не выполнил или выполнил неправильно.
- "na" — только если критерий допускает N/A и его условие неприменимости выполнено. Не путай «не сделал» и «не требовалось».
- Шкальный критерий: answer = "score", value = ровно одна ступень из перечисленных (или "na", если разрешено).
- Критерий грубой ошибки: "yes" = нарушение ЕСТЬ, "no" = нарушения нет.
- Безопасность: если оператор сообщил данные конкретного счёта (баланс, ограничения, позиции, операции, статус платежа) или выполнил защищённое действие ДО системного подтверждения личности — это нарушение идентификации и раскрытие конфиденциальной информации. Учитывай это в критерии идентификации и в критерии грубых ошибок. Совет клиенту обойтись без проверки личности — ошибочная рекомендация.
- Если клиенту пришлось повторить вопрос, потому что оператор его проигнорировал или ответил не на то, — это сбой ведения диалога, учитывай в соответствующем критерии.
- «Предложил помощь» засчитывается только если это прямо сказано в репликах оператора; не додумывай подразумеваемое.
- Не выдумывай. Опирайся только на транскрипт и блок «Факты».
- Не считай баллы и итог — это делает система.

## Правила команды для спорных случаев (приоритетны)
- Завершение (c07): "yes" только если оператор (подвёл итог ИЛИ предложил дальнейшую помощь) И попрощался. Одно прощание без итога и без предложения помощи = "no". Чат оборвался до возможности завершить = "na". Итог или предложение помощи должны прозвучать в конце диалога рядом с прощанием; «Чем могу помочь?» в начале не считается. «Хорошего дня/вечера», «До свидания», «Спасибо за обращение» — это только прощание, помощь не предлагается.
- Идентификация (c03): клиент спросил про СВОЙ счёт, но оператор данные счёта не раскрыл и защищённого действия не выполнял = "na". Данные счёта раскрыты или действие выполнено до проверки личности = "no". Личность подтверждена системой до раскрытия = "yes".
- Выявление потребности (c02): клиент сразу дал все нужные детали (в том числе боту до перевода на оператора), и оператор ответил без уточнений = "na". Переспрос того, что клиент уже сообщил (оператору или боту), — это "no", а не "yes". Если деталей не хватало и оператор уточнил (или не уточнил, хотя было нужно) — "yes"/"no".
- Корректная и полная консультация (c04): ответил ли оператор на вопросы клиента, нет ли в ответе ошибочной информации, объяснил ли нужные действия.
- Не оцениваются: порог первой реакции 3 минуты, теги, вложения.
- Грубая ошибка (c08) не меняет баллы других критериев: только отметка.

## Обоснование и доказательства
- explanation: 1–2 предложения НА РУССКОМ, со ссылками на номера реплик в квадратных скобках, например: «Оператор поздоровался и назвал имя в первой реплике [10]».
- evidence_ids: номера реплик (целые числа из транскрипта), 1–3 штуки, которые подтверждают ответ.
- Если действие пропущено ("no" или не высшая ступень): в evidence_ids — реплика, где действие ожидалось или где ошибка; в checked_range — [первый, последний] номер реплик проверенного участка.
- Если "na": explanation начинается с условия неприменимости; evidence_ids — реплика, которая это показывает (если есть).
- Иначе checked_range = null.
"""

OUTPUT_FORMAT = """## Формат ответа
Верни ТОЛЬКО JSON, без markdown:
{"items": [{"criterion_id": "...", "explanation": "...", "evidence_ids": [12], "checked_range": null, "answer": "yes|no|na|score", "value": null}]}
Ровно один элемент на каждый критерий: %s. Для шкальных — value = ступень, для остальных value = null."""


def _fmt_num(x) -> str:
    return f"{float(x):g}"


def checklist_to_text(cl: dict) -> str:
    out = []
    sections = cl.get("sections") or []
    groups = [(s, [c for c in cl["criteria"] if c.get("section") == s["id"]]) for s in sections]
    orphans = [c for c in cl["criteria"] if c.get("section") not in {s["id"] for s in sections}]
    if orphans:
        groups.append(({"title": "Прочее"}, orphans))
    for s, crits in groups:
        if not crits:
            continue
        out.append(f"### {s['title']}")
        for c in crits:
            if c["type"] == "scale":
                kind = "ШКАЛА " + "/".join(_fmt_num(x["value"]) for x in c["scale"]) + (" или N/A" if c.get("na_allowed") else "")
            elif c["type"] == "critical":
                kind = "ГРУБАЯ ОШИБКА: yes = нарушение есть, no = нет (без баллов)"
            else:
                kind = "yes/no" + ("/na" if c.get("na_allowed") else "")
            weight = "" if c["type"] == "critical" else f", вес {_fmt_num(c.get('weight', 0))}"
            out.append(f"- **{c['id']}. {c['title']}** — {kind}{weight}")
            if c.get("yes_rule"):
                out.append(f"  - {'Нарушение' if c['type'] == 'critical' else 'Да'}: {c['yes_rule']}")
            if c["type"] == "scale":
                for step in c["scale"]:
                    out.append(f"  - {_fmt_num(step['value'])}: {step.get('label', '')}")
            if c.get("na_allowed") and c.get("na_rule"):
                out.append(f"  - N/A: {c['na_rule']}")
            if c.get("note"):
                out.append(f"  - Примечание: {c['note']}")
    return "\n".join(out)


def build_system(cl: dict) -> str:
    extra = []
    if cl.get("wait_threshold_sec"):
        extra.append(f"Порог ожидания ответа оператора в чате: {round(cl['wait_threshold_sec'] / 60, 1):g} мин "
                     f"(фактические паузы посчитаны системой в блоке «Факты»).")
    if cl.get("extra_rules"):
        extra.append(cl["extra_rules"])
    ids = ", ".join(c["id"] for c in cl["criteria"])
    return (SYSTEM_RULES
            + f"\n## Чек-лист «{cl.get('name', '')}» (версия {cl.get('version', '?')})\n"
            + checklist_to_text(cl)
            + ("\n\n## Дополнительно\n" + "\n".join(f"- {x}" for x in extra) if extra else "")
            + "\n\n" + OUTPUT_FORMAT % ids)


def _clock(sec) -> str:
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def transcript_to_text(conv: dict) -> str:
    lines = []
    for t in conv["transcript"]:
        time_label = _clock(t["offset_sec"]) if conv.get("is_call") and t.get("offset_sec") is not None else t.get("timestamp", "")
        text = re.sub(r"\s+", " ", str(t.get("text") or "")).strip()
        lines.append(f"[{t['id']}] {time_label} {t.get('speaker')}: {text}")
    return "\n".join(lines)


def build_user(conv: dict, facts: dict) -> str:
    return (f"## Факты, посчитанные системой\n{facts_to_text(facts)}\n\n"
            f"## Транскрипт ({conv['conversation_id']})\n{transcript_to_text(conv)}")


# ---------------------------------------------------------------- answer parsing
_ANSWER_ALIASES = {"да": "yes", "нет": "no", "n/a": "na", "н/д": "na", "true": "yes", "false": "no", "scored": "score"}


def _to_int(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    m = re.search(r"\d+", str(x))
    return int(m.group()) if m else None


def _to_num(x):
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(x) if float(x).is_integer() else float(x)
    m = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*", str(x))
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return int(v) if v.is_integer() else v


def parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def normalize_items(cl: dict, raw) -> list[dict]:
    raw_items = raw.get("items") if isinstance(raw, dict) else raw
    by_id = {c["id"]: c for c in cl["criteria"]}
    out = []
    for it in raw_items or []:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("criterion_id", "")).strip()
        c = by_id.get(cid)
        answer = str(it.get("answer", "")).strip().lower()
        answer = _ANSWER_ALIASES.get(answer, answer)
        value = None
        if c and c["type"] == "scale":
            if answer != "na":
                value = _to_num(it.get("value"))
                if value is None:
                    value = _to_num(answer)
                answer = "score" if value is not None else answer
        evidence = [e for e in (_to_int(x) for x in (it.get("evidence_ids") or [])) if e is not None]
        rng = it.get("checked_range")
        rng = [_to_int(x) for x in rng] if isinstance(rng, list) and len(rng) == 2 else None
        if rng and None in rng:
            rng = None
        out.append({
            "criterion_id": cid, "answer": answer, "value": value,
            "explanation": str(it.get("explanation") or "").strip(),
            "evidence_ids": list(dict.fromkeys(evidence))[:5],
            "checked_range": sorted(rng) if rng else None,
        })
    return out


def _drop_bad_refs(items: list[dict], n: int) -> list[dict]:
    """Last resort: remove message numbers that do not exist instead of failing the whole evaluation."""
    for it in items:
        it["evidence_ids"] = [e for e in it["evidence_ids"] if 0 <= e < n]
        r = it.get("checked_range")
        if r and not (0 <= r[0] <= r[1] < n):
            it["checked_range"] = [max(0, min(r[0], n - 1)), max(0, min(r[1], n - 1))]
    return items


# ---------------------------------------------------------------- providers
def _backoff(fn, label: str, quick: bool = False):
    """quick=True: with several keys a per-minute 429 is not waited out - the caller tries the next key."""
    waits = [5, 15, 30, 60]
    for attempt in range(len(waits) + 1):
        try:
            return fn()
        except http_util.HttpError as e:
            quota = re.search(r'"quotaId"\s*:\s*"([^"]+)"', e.body or "")
            quota = quota.group(1) if quota else ""
            if e.status == 429 and "PerDay" in quota:  # daily limit: waiting will not help, switch provider now
                raise RateLimited(f"{label}: дневной лимит исчерпан ({quota}), сброс в полночь по тихоокеанскому времени") from None
            retryable = e.status in (0, 429, 500, 502, 503, 504)  # 0 = timeout / no connection
            if quick and e.status == 429:
                raise RateLimited(f"{label}: лимит запросов в минуту") from None
            if retryable and attempt < (1 if e.status == 0 else len(waits)):
                try:
                    wait = float(e.headers.get("retry-after") or waits[attempt])
                except ValueError:
                    wait = waits[attempt]
                time.sleep(min(wait, 90))
                continue
            if e.status == 429:
                raise RateLimited(f"{label}: лимит запросов исчерпан{f' ({quota})' if quota else ''}") from None
            hint = " Проверьте название модели в .env." if e.status == 404 else ""
            raise LLMError(f"{label}: HTTP {e.status}: {e.body[:300]}{hint}") from None


def _gemini_schema(cl: dict) -> dict:
    item = {
        "type": "OBJECT",
        "properties": {
            "criterion_id": {"type": "STRING", "enum": [c["id"] for c in cl["criteria"]]},
            "explanation": {"type": "STRING"},
            "evidence_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
            "checked_range": {"type": "ARRAY", "items": {"type": "INTEGER"}, "nullable": True},
            "answer": {"type": "STRING", "enum": ["yes", "no", "na", "score"]},
            "value": {"type": "NUMBER", "nullable": True},
        },
        "required": ["criterion_id", "explanation", "evidence_ids", "answer"],
        "propertyOrdering": ["criterion_id", "explanation", "evidence_ids", "checked_range", "answer", "value"],
    }
    return {"type": "OBJECT", "properties": {"items": {"type": "ARRAY", "items": item}}, "required": ["items"]}


_dead: set[tuple[str, int]] = set()  # (model, key number) whose DAILY free limit is used up: skipped until restart
_key_calls: dict[int, int] = {}      # key number -> successful requests in this process (never the key itself)


def gemini_models() -> list[str]:
    """GEMINI_MODEL may be a comma-separated list; the best model goes first."""
    return [m.strip() for m in settings.GEMINI_MODEL.split(",") if m.strip()]


def gemini_keys() -> list[str]:
    """All keys in order (number = position + 1): GEMINI_API_KEYS, then GEMINI_API_KEY if it is not among them."""
    keys = [k.strip() for k in (settings.GEMINI_API_KEYS or "").split(",") if k.strip()]
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY not in keys:
        keys.append(settings.GEMINI_API_KEY)
    if settings.GEMINI_MAX_KEYS > 0:
        keys = keys[:settings.GEMINI_MAX_KEYS]
    return keys


def call_gemini(system: str, turns: list[dict], cl: dict) -> tuple[str, dict]:
    """For each model (best first): try every key; on a daily limit go to the next key, and only when all keys
    are used up for this model go to the next model."""
    keys = gemini_keys()
    if not keys:
        raise LLMError("Не задан GEMINI_API_KEY / GEMINI_API_KEYS в .env")
    last: Exception | None = None
    for attempt in range(4):  # extra passes only when everything was limited per minute (not daily)
        minute_limited = False
        for model in gemini_models():
            for n, key in enumerate(keys, 1):
                if (model, n) in _dead:
                    continue
                try:
                    text, usage = _call_gemini_model(model, key, system, turns, cl)
                except RateLimited as e:
                    last = e
                    if "дневной" in str(e):
                        _dead.add((model, n))
                    else:
                        minute_limited = True
                    print(f"[gemini] ключ {n} / {model}: лимит, перехожу дальше", flush=True)
                    continue
                except LLMError as e:
                    last = e
                    print(f"[gemini] ключ {n} / {model}: {str(e)[:80]}", flush=True)
                    break  # not a key problem (timeout, bad answer): try the next model
                _key_calls[n] = _key_calls.get(n, 0) + 1
                usage["model"], usage["key"] = model, n
                return text, usage
        if not minute_limited:
            break
        time.sleep(15)
    raise last or LLMError("Не задана модель Gemini")


def _call_gemini_model(model: str, key: str, system: str, turns: list[dict], cl: dict) -> tuple[str, dict]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    contents = [{"role": "model" if t["role"] == "assistant" else "user", "parts": [{"text": t["content"]}]}
                for t in turns]

    def send(use_schema: bool, use_thinking: bool = True):
        config = {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 16384}
        if use_schema:
            config["responseSchema"] = _gemini_schema(cl)
        if use_thinking and settings.GEMINI_THINKING:
            config["thinkingConfig"] = {"thinkingLevel": settings.GEMINI_THINKING}
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "generationConfig": config}
        return http_util.post_json(url, body, headers={"x-goog-api-key": key}, timeout=100)

    quick = len(gemini_keys()) > 1
    try:
        res = _backoff(lambda: send(True), f"Gemini {model}", quick)
    except LLMError as e:
        if "HTTP 400" not in str(e):
            raise
        # some models reject the schema or the thinking setting; plain JSON mode is enough
        res = _backoff(lambda: send(False, False), f"Gemini {model}", quick)
    cand = (res.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text:
        raise LLMError(f"Gemini {model} вернул пустой ответ (finishReason={cand.get('finishReason')})")
    u = res.get("usageMetadata") or {}
    usage = {"input_tokens": u.get("promptTokenCount", 0),
             "output_tokens": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}
    return text, usage


def call_openai(system: str, turns: list[dict], cl: dict) -> tuple[str, dict]:
    if not settings.OPENAI_API_KEY:
        raise LLMError("Не задан OPENAI_API_KEY в .env")
    body = {
        "model": settings.OPENAI_MODEL, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}] + turns,
    }
    res = _backoff(lambda: http_util.post_json(
        settings.OPENAI_BASE_URL + "/chat/completions", body,
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}, timeout=180), "OpenAI-compatible")
    text = ((res.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    u = res.get("usage") or {}
    return text, {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}


CALLERS = {"gemini": call_gemini, "openai": call_openai}
MODELS = {"gemini": lambda: settings.GEMINI_MODEL, "openai": lambda: settings.OPENAI_MODEL, "mock": lambda: "mock"}


def provider_chain() -> list[str]:
    if settings.PROVIDER and settings.PROVIDER != "auto":
        chain = [p.strip() for p in settings.PROVIDER.split(",") if p.strip()]
        return chain or ["mock"]
    chain = []
    if gemini_keys():
        chain.append("gemini")
    if settings.OPENAI_API_KEY:
        chain.append("openai")
    return chain or ["mock"]


def active_model() -> dict:
    chain = provider_chain()
    return {"provider": chain[0], "model": MODELS.get(chain[0], lambda: chain[0])(), "chain": chain}


# ---------------------------------------------------------------- mock (no key)
def mock_items(cl: dict, conv: dict, facts: dict) -> list[dict]:
    tr = conv["transcript"]
    first, last = facts["first_operator_id"], facts["last_operator_id"]
    verified = next((t["id"] for t in tr if t.get("speaker") == "system"
                     and re.search(r"подтвержд|verified|расталды", t.get("text") or "", re.I)), None)
    items = []
    for c in cl["criteria"]:
        it = {"criterion_id": c["id"], "answer": "yes", "value": None, "evidence_ids": [first] if first is not None else [],
              "checked_range": None, "explanation": "[MOCK] Заглушка без ИИ: добавьте ключ модели в .env."}
        if c["type"] == "critical":
            it.update(answer="no", evidence_ids=[], explanation="[MOCK] Признаков грубых нарушений не найдено.")
        elif c["type"] == "scale":
            it.update(answer="score", value=c["scale"][0]["value"] if first is not None else c["scale"][-1]["value"])
        elif re.search(r"идентиф|identif", c.get("title", ""), re.I):
            if verified is not None:
                it.update(evidence_ids=[verified], explanation=f"[MOCK] Система подтвердила личность [{verified}].")
            elif c.get("na_allowed"):
                it.update(answer="na", evidence_ids=[], explanation="[MOCK] Запрос не требовал идентификации.")
        elif re.search(r"заверш|closing", c.get("title", ""), re.I) and last is not None:
            it["evidence_ids"] = [last]
        if first is None and it["answer"] == "yes" and c["type"] == "binary":
            it.update(answer="no", checked_range=[0, len(tr) - 1], explanation="[MOCK] Оператор не писал в диалоге.")
        items.append(it)
    return items


# ---------------------------------------------------------------- main entry
def _evaluate_with(provider: str, cl: dict, conv: dict, facts: dict) -> dict:
    caller = CALLERS.get(provider)
    if caller is None:
        raise LLMError(f"Неизвестный провайдер: {provider}")
    system, n = build_system(cl), len(conv["transcript"])
    turns = [{"role": "user", "content": build_user(conv, facts)}]
    usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    used_model = None
    items, errors = [], []
    for attempt in range(2):
        text, u = caller(system, turns, cl)
        usage["input_tokens"] += u["input_tokens"]
        usage["output_tokens"] += u["output_tokens"]
        usage["calls"] += 1
        used_model = u.get("model") or used_model
        usage["key"] = u.get("key", usage.get("key"))
        try:
            items = normalize_items(cl, parse_json(text))
            errors = validate_items(cl, items, n)
        except (json.JSONDecodeError, ValueError):
            items, errors = [], ["Ответ не является корректным JSON"]
        if not errors:
            break
        if attempt == 0:
            turns += [{"role": "assistant", "content": text[:20000]},
                      {"role": "user", "content": "Ответ не прошёл проверку:\n- " + "\n- ".join(errors)
                       + "\nИсправь и верни полную оценку заново, только JSON."}]
    if errors and items:
        _drop_bad_refs(items, n)
        errors = validate_items(cl, items, n)
    if errors:
        raise LLMError("Модель вернула некорректную оценку: " + "; ".join(errors[:5]))
    return {"items": items, "usage": usage, "provider": provider, "model": used_model or MODELS[provider]()}


def evaluate(cl: dict, conv: dict, facts: dict) -> dict:
    started = time.time()
    chain = provider_chain()
    result, last_error = None, None
    if chain == ["mock"]:
        result = {"items": mock_items(cl, conv, facts), "usage": {"input_tokens": 0, "output_tokens": 0, "calls": 0},
                  "provider": "mock", "model": "mock"}
    else:
        for i, provider in enumerate(chain):
            if provider == "mock":
                result = {"items": mock_items(cl, conv, facts), "usage": {"input_tokens": 0, "output_tokens": 0,
                                                                         "calls": 0}, "provider": "mock", "model": "mock"}
                break
            try:
                result = _evaluate_with(provider, cl, conv, facts)
                break
            except RateLimited as e:  # free-tier limit: try the next provider in the chain
                last_error = e
            except LLMError as e:
                last_error = e
                if i == len(chain) - 1:
                    raise
        if result is None:
            raise last_error or LLMError("Нет доступного провайдера")
    u = result["usage"]
    u["latency_ms"] = int((time.time() - started) * 1000)
    u["cost_usd"] = round(u["input_tokens"] * settings.PRICE_INPUT_PER_1M / 1e6
                          + u["output_tokens"] * settings.PRICE_OUTPUT_PER_1M / 1e6, 6)
    return result
