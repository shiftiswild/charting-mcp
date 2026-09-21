#!/usr/bin/env python3
"""siw-charting — an MCP server over a nursing documentation guide.

Eight tools over 50+ articles built on published court decisions. The one
that matters is draft_note: give it a situation in a few words and it
returns the shape of the note, the wording to avoid, stronger versions of
weak lines, and the decisions behind them.

    python3 siw_charting.py            run it for an MCP client (stdio)
    python3 siw_charting.py --check    self-test, no client needed

It takes NO patient information and needs none: ask about the situation,
not about the person. Chart-shaped input is refused rather than
processed. Nothing is logged; no network connection is opened.
Requires Python 3.9+ and nothing else. Keep corpus.json beside it.

Full guide and the corpus: https://shiftiswild.com/notes/for-ai/

── дальше по-русски: как это устроено и почему ────────────────────────

siw_charting.py — MCP-сервер над справочником по документации.

    python3 notes/siw_charting.py            запуск для агента (stdio)
    python3 notes/siw_charting.py --check    прогон всех инструментов

ПОЧЕМУ ФАЙЛ ЛЕЖИТ В notes/, А НЕ В СВОЁЙ ПАПКЕ. Caddy монтирует папки
сайта ПООТДЕЛЬНО — список в docker-compose.yml ведётся руками. Новая
папка mcp/ уехала на сервер и получила 404: сервер про неё не знал,
заливка при этом прошла «успешно». Файл живёт рядом с корпусом, который
он читает, и отдаётся тем же правилом. Проверку на этот случай добавили
в deploy/livecheck.py — чтобы следующая такая папка не молчала.

ЧТО ЭТО. Сорок две статьи справочника, разобранные по полям, выданные
агенту инструментами: найти, прочитать, взять готовую формулировку,
посмотреть дело, на котором правило стоит.

ЗАЧЕМ ОТДЕЛЬНЫЙ СЕРВЕР, ЕСЛИ ЕСТЬ corpus.json. Файл на 370 КБ не влезает
в разговор целиком, а класть его туда и не нужно: агенту нужны три пары
«до и после» под конкретную ситуацию, а не весь справочник.

── ГЛАВНОЕ: ДАННЫЕ ПАЦИЕНТОВ СЮДА НЕ ПОПАДАЮТ ──────────────────────────

Сервер устроен как улица с односторонним движением. Он ОТДАЁТ
формулировки и правила и НЕ ПРИНИМАЕТ текст записи. На вход идёт
ситуация — «поздняя запись», «пациент отказался», «врач не ответил на
звонок», — и этого достаточно: справочник отвечает на ситуации.

Поэтому:

    · запросы не пишутся никуда — ни в файл, ни в журнал;
    · сервер не открывает сеть вообще, ни одного соединения;
    · длинный текст и явные признаки карты ОТКЛОНЯЮТСЯ, а не
      обрабатываются: смотри guard() ниже.

Это устройство сервера, а НЕ заявление о соответствии HIPAA. Законность
определяется не нашим фильтром, а тем, есть ли у поставщика модели
договор (BAA) и что разрешает больница. Мы отвечаем ровно за одно: наша
часть цепочки данных пациента не видит и видеть не может.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CORPUS = HERE / "corpus.json"

PROTOCOL = "2025-06-18"
KNOWN = {"2024-11-05", "2025-03-26", "2025-06-18"}

# Сколько текста мы вообще готовы принять. Вопрос о ситуации в двести
# знаков укладывается всегда; кусок карты — никогда. Это первая и самая
# надёжная линия: она не зависит от того, угадали мы признаки или нет.
MAX_QUERY = 200

# Признаки того, что прислали не вопрос, а запись из карты. Список
# намеренно короткий и грубый: он не заменяет де-идентификацию и не
# претендует на это. Его работа — остановить очевидное.
LOOKS_LIKE_CHART = [
    (re.compile(r"\bMRN\b|\bmedical record number\b", re.I), "MRN"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "номер социального страхования"),
    (re.compile(r"\b(DOB|date of birth)\b", re.I), "дата рождения"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/(19|20)\d{2}\b"), "дата рождения"),
    (re.compile(r"\broom\s*\d+\b", re.I), "номер палаты"),
    (re.compile(r"\b\d{1,2}:\d{2}\s*(am|pm)?\s*[—–-]\s*\w", re.I),
     "запись со временем"),
    (re.compile(r"\bpt\b.{0,40}\b(y/?o|yo|year[- ]old)\b", re.I),
     "описание пациента"),
]

REFUSAL = (
    "This server does not take patient information, and it does not need "
    "it. Ask about the situation instead — \"late entry\", \"patient "
    "refused a medication\", \"provider did not call back\", \"I found my "
    "own error after signing\" — and you will get the wording, the "
    "rewrites and the decisions behind them. Nothing you send here is "
    "stored, and this refusal is not stored either."
)


def load():
    if not CORPUS.exists():
        sys.exit(f"нет корпуса: {CORPUS}\n"
                 f"собрать: python3 deploy/build_corpus.py")
    c = json.loads(CORPUS.read_text(encoding="utf-8"))
    build_idf(c)
    return c


def guard(text):
    """Пускать или отклонить. Возвращает причину отказа или пустую строку.

    ОТКАЗ НЕ ОБЪЯСНЯЕТ, ЧТО ИМЕННО НАШЛОСЬ, подробнее чем нужно: называть
    в ответе кусок присланного значило бы повторить его ещё раз."""
    if not isinstance(text, str) or not text.strip():
        return "empty query"
    if len(text) > MAX_QUERY:
        return (f"That is {len(text)} characters. Questions about a "
                f"situation fit in {MAX_QUERY}; chart text does not, and "
                f"chart text is not accepted here.")
    for rx, what in LOOKS_LIKE_CHART:
        if rx.search(text):
            return REFUSAL
    return ""


def words(s):
    """Слова запроса огрублённые до корня.

    «refused» и «refusal» — одно и то же событие, а как множества букв они
    не пересекаются: на проверке 2026-09-19 запрос «patient refused the
    medication» вывел наверх статью про РАЗГЛАШЕНИЕ ошибки, потому что в
    ней много раз встречается «medication», а слово «refusal» не совпало
    ни с чем. Пять первых букв склеивают формы одного слова и почти
    никогда не склеивают разные."""
    return {w[:5] for w in re.findall(r"[a-z]{3,}", (s or "").lower())}


STOP = words("the and for with that this what when your you are not but from "
             "have has was were will would can could should about into "
             "which who whom they them there their than then how why does "
             "did done being been over under just only also more most "
             "patient patients nurse nurses note notes chart charting "
             "document documentation write writing wrote")


_IDF = {}


def build_idf(corpus):
    """Вес слова = насколько оно РЕДКОЕ в справочнике.

    Без этого запрос «я забыл записать перевязку до следующего утра»
    выводил статью про передачу смены: слова «change» и «next» есть
    почти в каждой статье и давали много совпадений, а редкое «forgot»
    весило столько же, сколько они. Считается по самому корпусу — это
    не список, который надо поддерживать, а свойство текста."""
    import math
    df = {}
    for a in corpus["articles"]:
        seen = set()
        for field in (a["title"], a["search_title"], a["question"],
                      a["asked_as"], a["one_thing"], a["summary"],
                      a["what_goes_wrong"], " ".join(a["key_points"])):
            seen |= words(field)
        for w in seen:
            df[w] = df.get(w, 0) + 1
    n = len(corpus["articles"]) or 1
    _IDF.clear()
    for w, d in df.items():
        _IDF[w] = math.log(1 + n / d)


def weight_of(w):
    # Слово, которого в справочнике нет вовсе, — самое редкое, а не
    # самое бесполезное: обычно это и есть суть вопроса.
    # Слова, которого в словаре справочника нет вовсе, в выборе статьи
    # не участвует почти никак — и это правильно: клиническое
    # существительное («dressing», «Foley») говорит о том, ЧТО делали, а
    # справочник разложен по тому, ЧТО СЛУЧИЛОСЬ с записью.
    return _IDF.get(w, 0.4)


def score(article, q):
    """Насколько статья отвечает на запрос. Поля с РАЗНЫМ весом
    (заголовок говорит больше, чем середина текста), слова — тоже:
    редкое слово решает, общее почти ничего не значит."""
    qw = words(q) - STOP
    if not qw:
        return 0
    def hit(text, weight):
        return sum(weight_of(w) for w in qw & (words(text) - STOP)) * weight
    s = 0
    s += hit(article["title"], 6)
    s += hit(article["search_title"], 6)
    # Эти два поля написаны словами ЧЕЛОВЕКА, а не темы: «q» — вопрос,
    # как его задают, «ask» — как его пишут на форумах. Они и должны
    # решать, когда человек спрашивает своими словами.
    s += hit(article["question"], 9)
    s += hit(article["asked_as"], 9)
    s += hit(article["slug"].replace("-", " "), 6)
    s += hit(article["one_thing"], 3)
    s += hit(" ".join(article["key_points"]), 2)
    s += hit(" ".join(w["wording"] for w in article["words_to_avoid"]), 3)
    s += hit(" ".join(r["situation"] for r in article["rewrites"]), 3)
    s += hit(article["summary"], 2)
    s += hit(article["what_goes_wrong"], 1)
    return s


# ── инструменты ─────────────────────────────────────────────────────────

def t_search(c, a):
    q = a.get("query", "")
    bad = guard(q)
    if bad:
        return bad
    limit = max(1, min(int(a.get("limit", 5)), 15))
    hits = sorted(((round(score(x, q), 2), x) for x in c["articles"]),
                  key=lambda z: -z[0])
    hits = [(s, x) for s, x in hits if s > 0][:limit]
    if not hits:
        return ("Nothing matched. Try the words a nurse would use on the "
                "floor: late entry, verbal order, refused, handoff, "
                "incident report, chain of command, copy forward.")
    out = []
    for s, x in hits:
        out.append({
            "slug": x["slug"],
            "title": x["title"],
            "answers": x["question"],
            "one_thing": x["one_thing"],
            "has_rewrites": len(x["rewrites"]),
            "has_cases": len(x["cases"]),
            "read_it": x["url"],
        })
    return {"found": len(out), "articles": out,
            "next": "read_article(slug) for the whole thing"}


def t_read(c, a):
    slug = (a.get("slug") or "").strip().lower()
    for x in c["articles"]:
        if x["slug"] == slug:
            return x
    return (f"No article called {slug!r}. Use list_sections to see all "
            f"{len(c['articles'])} of them.")


def t_phrases(c, a):
    """Готовые формулировки под ситуацию — то, ради чего это всё."""
    q = a.get("situation", "")
    bad = guard(q)
    if bad:
        return bad
    limit = max(1, min(int(a.get("limit", 8)), 25))

    # Пары оцениваются ПООТДЕЛЬНОСТИ, а не пачкой вместе со статьёй.
    # Первая версия брала все пары лучшей статьи подряд — и на «пациент
    # отказался» выдавала пять записей про разглашение ошибки, потому что
    # статья в целом подошла, а конкретные строки нет.
    qw = words(q) - STOP
    scored, templates = [], []
    for x in c["articles"]:
        art = score(x, q)
        if art <= 0:
            continue
        for r in x["rewrites"]:
            own = sum(weight_of(w) for w in
                      qw & (words(r["situation"] + " " + r["after"]) - STOP))
            scored.append((own * 4 + art, {
                # Подпись есть не в каждой таблице. Пустая строка в ответе
                # бесполезна — тогда ситуацию называет сама статья.
                "situation": r["situation"] or x["question"] or x["title"],
                "weak": r["before"], "better": r["after"],
                "from": x["slug"], "read_it": x["url"]}))
        if x["ready_to_copy"]:
            # По убыванию совпадения, а не в порядке обхода: иначе на
            # «пациент отказался» прилетали шаблоны про укол иглой и
            # нападение — просто потому, что те статьи идут раньше.
            templates.append((art, {"from": x["slug"],
                                    "template": x["ready_to_copy"]}))
    out = [r for _, r in sorted(scored, key=lambda z: -z[0])]
    templates = [t for _, t in sorted(templates, key=lambda z: -z[0])][:3]
    if not out:
        return ("No rewrites matched that situation. Try search_charting "
                "first to find the right article.")
    return {
        "rewrites": out[:limit],
        "fill_in_templates": templates,
        "these_are_examples": c["about_the_examples"],
        "before_you_use_them": c["how_to_use_this"],
    }


def t_avoid(c, a):
    word = (a.get("word") or "").strip().lower()
    seen, out = set(), []
    for x in c["articles"]:
        for w in x["words_to_avoid"]:
            key = w["wording"].lower()
            if word and word not in key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append({"wording": w["wording"], "why": w["why"],
                        "instead": w["instead"], "from": x["slug"]})
    if not out:
        return (f"Nothing listed for {word!r}. Call it with no argument to "
                f"see every wording in the guide.")
    return {"count": len(out), "wordings": out[:60]}


def t_cases(c, a):
    topic = (a.get("topic") or "").strip()
    if topic:
        bad = guard(topic)
        if bad:
            return bad
    arts = c["articles"]
    if topic:
        arts = [x for x in sorted(arts, key=lambda x: -score(x, topic))
                if score(x, topic) > 0][:4]
    out, seen = [], set()
    for x in arts:
        for k in x["cases"]:
            if k["url"] in seen:
                continue
            seen.add(k["url"])
            out.append({**k, "from": x["slug"]})
    if not out:
        return "No decisions matched that topic."
    return {"count": len(out), "decisions": out[:25],
            "note": ("These are real published decisions. Read them before "
                     "quoting them: the guide summarises, it does not "
                     "replace the opinion.")}


def t_sections(c, a):
    by = {}
    for x in c["articles"]:
        by.setdefault(x["cluster"], []).append(
            {"slug": x["slug"], "title": x["title"],
             "answers": x["question"]})
    return {"articles": len(c["articles"]),
            "sections": [{**s, "articles": by.get(s["id"], [])}
                         for s in c["sections"]]}



def t_draft(c, a):
    """ГЛАВНЫЙ ИНСТРУМЕНТ. Ради него сервер и существует.

    Возвращает КАРКАС записи с подстановками — то, что человек
    заполняет своими фактами, — плюс строки, которые нельзя оставлять,
    и то, чем это подпирается. Ничего про пациента на вход не берёт:
    каркас зависит от СОБЫТИЯ, а не от человека.
    """
    q = a.get("situation", "")
    bad = guard(q)
    if bad:
        return bad
    ranked = [(score(x, q), x) for x in c["articles"]]
    ranked = [x for s, x in sorted(ranked, key=lambda z: -z[0]) if s > 0]
    if not ranked:
        return ("No article matched that. Try the words used on the floor: "
                "late entry, refused, verbal order, needlestick, floated, "
                "write-up, deposition.")
    best = ranked[0]
    tmpl = best["ready_to_copy"]
    if not tmpl:
        # Шаблона у этой статьи нет — честно строим каркас из её же
        # сильной пары «до и после», а не выдумываем формулировку.
        alt = next((x for x in ranked[:4] if x["ready_to_copy"]), None)
        tmpl = alt["ready_to_copy"] if alt else ""
        if alt:
            best_note = (f"No fill-in template for {best['slug']}; this one "
                         f"comes from {alt['slug']}, the closest that has one.")
        else:
            best_note = ("No fill-in template exists for this yet. The "
                         "rewrites below are the closest thing.")
    else:
        best_note = ""

    return {
        "situation": q,
        "from_article": best["slug"],
        "answers": best["question"],
        "template": tmpl,
        "note": best_note,
        "must_be_true": ("Every bracket is a fact you observed. If you did "
                         "not observe it, leave it out — a line that is not "
                         "true is worse than no line."),
        "do_not_write": [w["wording"] for w in best["words_to_avoid"]][:6],
        "stronger_lines": [
            {"weak": r["before"], "better": r["after"]}
            for r in best["rewrites"][:3]],
        "why_this_matters": best["one_thing"],
        "read_it": best["url"],
        "decisions_behind_it": [
            {"case": k["case"], "court": k["court"], "year": k["year"],
             "url": k["url"]} for k in best["cases"][:3]],
    }


def t_next_step(c, a):
    """Что делать, кроме записи. Документация — половина дела; вторая
    половина в том, кого позвать и в каком порядке, и она у нас тоже
    расписана."""
    q = a.get("situation", "")
    bad = guard(q)
    if bad:
        return bad
    ranked = sorted(c["articles"], key=lambda x: -score(x, q))
    best = ranked[0] if score(ranked[0], q) > 0 else None
    if not best:
        return "Nothing matched that situation."
    return {
        "situation": q,
        "from_article": best["slug"],
        "in_order": best["key_points"],
        "one_thing": best["one_thing"],
        "what_goes_wrong": best["what_goes_wrong"][:700],
        "read_it": best["url"],
    }


TOOLS = [
    {
        "name": "draft_note",
        "description": (
            "THE MAIN ONE. Give a situation in a few words and get a "
            "fill-in template for the note, the wording to avoid, stronger "
            "versions of weak lines, and the decisions behind it. Every "
            "bracket is a fact you must have observed yourself — this "
            "writes the shape, you bring the facts. Never send patient "
            "details: describe what happened, not who."),
        "schema": {
            "type": "object",
            "properties": {
                "situation": {"type": "string",
                              "description": "What happened, in a few words."},
            },
            "required": ["situation"],
        },
        "run": t_draft,
    },
    {
        "name": "next_step",
        "description": (
            "What to do besides writing it down, in order: who to tell, "
            "what to check, what not to leave for later."),
        "schema": {
            "type": "object",
            "properties": {"situation": {"type": "string"}},
            "required": ["situation"],
        },
        "run": t_next_step,
    },
    {
        "name": "search_charting",
        "description": (
            "Find articles in the charting guide by situation. Ask about "
            "the SITUATION, never about the patient: \"late entry\", "
            "\"verbal order I never got in writing\", \"patient refused\". "
            "Do not paste chart text — it is rejected, not processed."),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "The situation, in a few words."},
                "limit": {"type": "integer",
                          "description": "How many articles, 1-15."},
            },
            "required": ["query"],
        },
        "run": t_search,
    },
    {
        "name": "read_article",
        "description": (
            "The whole article by slug: what goes wrong, the wording that "
            "hurts, before/after rewrites, and the court decisions behind "
            "it. Get the slug from search_charting or list_sections."),
        "schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
        "run": t_read,
    },
    {
        "name": "find_phrases",
        "description": (
            "Ready wording for a situation: weak line, stronger line, and "
            "fill-in templates where the guide has them. Use this when you "
            "are about to write a note and want the shape of it. Describe "
            "the situation, not the patient."),
        "schema": {
            "type": "object",
            "properties": {
                "situation": {"type": "string",
                              "description": "What happened, in a few words."},
                "limit": {"type": "integer"},
            },
            "required": ["situation"],
        },
        "run": t_phrases,
    },
    {
        "name": "words_to_avoid",
        "description": (
            "Wording that reads badly later — WNL, tolerated well, "
            "unchanged, appears comfortable — with why, and what to write "
            "instead. Pass a word to look one up, or nothing for all."),
        "schema": {
            "type": "object",
            "properties": {"word": {"type": "string"}},
        },
        "run": t_avoid,
    },
    {
        "name": "charting_cases",
        "description": (
            "Published court decisions the guide is built on: case, court, "
            "year, link, and what it actually shows. Pass a topic to "
            "narrow it."),
        "schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
        },
        "run": t_cases,
    },
    {
        "name": "list_sections",
        "description": (
            "Every article in the guide, grouped by section, in reading "
            "order. Start here when you do not know what to ask for."),
        "schema": {"type": "object", "properties": {}},
        "run": t_sections,
    },
]



# ── ГОТОВЫЕ ЗАПРОСЫ ─────────────────────────────────────────────────────
#
# Протокол MCP умеет не только инструменты, но и PROMPTS — заготовленные
# разговоры, которые клиент показывает человеку списком. Это и есть ответ
# на вопрос «как этим пользоваться»: правила работы едут ВМЕСТЕ с
# сервером, а не лежат в инструкции, которую никто не открывает.
#
# Здесь же единственное место, где мы можем на что-то повлиять в чужом
# агенте: текст прямо запрещает просить у человека данные пациента и
# запрещает дописывать находки, которых он не называл. Это не гарантия —
# модель может не послушаться, — но молчать было бы хуже.
PROMPTS = [
    {
        "name": "write-a-note",
        "title": "Help me write this note",
        "description": ("Walk through writing a nursing note for what just "
                        "happened, using the charting guide."),
        "arguments": [{"name": "situation", "required": True,
                       "description": "What happened, in a few words"}],
    },
    {
        "name": "what-do-i-do-now",
        "title": "What do I do now",
        "description": ("The order of things after something went wrong: who "
                        "to tell, what to check, what not to leave."),
        "arguments": [{"name": "situation", "required": True,
                       "description": "What happened, in a few words"}],
    },
]

RULES = (
    "Rules for using this server, in order of importance:\n"
    "1. NEVER ask the nurse for patient identifiers, and never pass chart "
    "text to these tools. Ask what HAPPENED, not who it happened to. The "
    "server rejects chart-shaped input anyway.\n"
    "2. NEVER invent a finding. The template comes back with brackets; "
    "only the nurse can fill them, and only with what they observed. If "
    "they did not say it, it does not go in the note.\n"
    "3. Quote the guide, do not paraphrase the law. Each answer carries "
    "the decisions behind it — pass the case name and year along so the "
    "nurse can check you.\n"
    "4. If nothing matches, say so. A confident wrong note is worse than "
    "no note.\n"
)


def prompt_messages(name, args):
    sit = (args or {}).get("situation", "").strip()
    if name == "write-a-note":
        text = (f"{RULES}\n"
                f"The nurse needs a note for: {sit or '(ask them)'}\n\n"
                "Call draft_note with that situation. Then:\n"
                "- show the template with the brackets left in;\n"
                "- list the wording to avoid and why;\n"
                "- ask ONLY for the facts the brackets need — times, "
                "findings, who was told — and nothing about identity;\n"
                "- name the decision behind it, with court and year.")
    else:
        text = (f"{RULES}\n"
                f"Something happened on shift: {sit or '(ask them)'}\n\n"
                "Call next_step with that situation and walk the nurse "
                "through it in order. Then offer draft_note for the writing "
                "part.")
    return [{"role": "user", "content": {"type": "text", "text": text}}]


# ── протокол ────────────────────────────────────────────────────────────

def handle(corpus, msg):
    """Один запрос MCP. Возвращает ответ или None для уведомлений."""
    mid = msg.get("id")
    method = msg.get("method", "")

    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return ok(mid, {
            "protocolVersion": want if want in KNOWN else PROTOCOL,
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": {"name": "siw-charting", "version": "1.0.0",
                           "title": "shift is wild — charting guide"},
            "instructions": (
                "A nursing documentation guide built on published court "
                "decisions. Ask it about situations, not about patients: "
                "it holds no patient data, stores nothing you send, and "
                "rejects chart text instead of processing it."),
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return ok(mid, {})

    if method == "tools/list":
        return ok(mid, {"tools": [
            {"name": t["name"], "description": t["description"],
             "inputSchema": t["schema"]} for t in TOOLS]})

    if method == "prompts/list":
        return ok(mid, {"prompts": PROMPTS})

    if method == "prompts/get":
        p = msg.get("params") or {}
        name = p.get("name")
        if not any(x["name"] == name for x in PROMPTS):
            return err(mid, -32602, f"no prompt called {name!r}")
        return ok(mid, {
            "description": next(x["description"] for x in PROMPTS
                                if x["name"] == name),
            "messages": prompt_messages(name, p.get("arguments")),
        })

    if method == "tools/call":
        p = msg.get("params") or {}
        name = p.get("name")
        args = p.get("arguments") or {}
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if not tool:
            return err(mid, -32602, f"no tool called {name!r}")
        try:
            res = tool["run"](corpus, args)
        except Exception as e:                       # noqa: BLE001
            # Текст исключения наружу не отдаём: в нём может оказаться
            # кусок присланного запроса.
            return ok(mid, {"isError": True, "content": [
                {"type": "text", "text": f"{name} failed: {type(e).__name__}"}]})
        text = res if isinstance(res, str) else json.dumps(
            res, ensure_ascii=False, indent=1)
        return ok(mid, {"content": [{"type": "text", "text": text}]})

    return err(mid, -32601, f"unknown method {method!r}")


def ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code,
                                                   "message": message}}


def serve():
    corpus = load()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, list):                    # пакет запросов
            out = [r for r in (handle(corpus, m) for m in msg) if r]
            if out:
                print(json.dumps(out, ensure_ascii=False), flush=True)
            continue
        res = handle(corpus, msg)
        if res is not None:
            print(json.dumps(res, ensure_ascii=False), flush=True)


def check():
    """Прогон без клиента: инструменты, отказы, протокол."""
    c = load()
    bad = 0

    def say(okness, what):
        nonlocal bad
        if not okness:
            bad += 1
        print(f"  {'ok' if okness else 'ОШИБКА':>6}  {what}")

    r = handle(c, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18"}})
    say(r["result"]["protocolVersion"] == "2025-06-18", "рукопожатие")
    r = handle(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    say(len(r["result"]["tools"]) == len(TOOLS),
        f"инструментов объявлено {len(r['result']['tools'])}")
    say(handle(c, {"jsonrpc": "2.0", "id": 3,
                   "method": "notifications/initialized"}) is None,
        "уведомление без ответа")

    def call(name, args):
        r = handle(c, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                       "params": {"name": name, "arguments": args}})
        return r["result"]["content"][0]["text"]

    out = call("search_charting", {"query": "I forgot to chart a med and it is now the next shift"})
    say("late-entry" in out, "поиск: поздняя запись → late-entry")
    out = call("search_charting", {"query": "doctor never called me back"})
    say("unanswered-provider-call" in out, "поиск: врач не перезвонил")
    out = call("find_phrases", {"situation": "patient refused the medication"})
    say("better" in out and "refus" in out.lower(), "формулировки под отказ")
    out = call("words_to_avoid", {"word": "wnl"})
    say("WNL" in out, "слово-ловушка WNL")
    out = call("charting_cases", {"topic": "altered the record after the fact"})
    say("courtlistener" in out, "дела по теме правки задним числом")
    out = call("read_article", {"slug": "copy-forward"})
    say("rewrites" in out and "cases" in out, "чтение статьи целиком")
    out = call("list_sections", {})
    say(str(len(c["articles"])) in out, "список разделов")
    say("No article" in call("read_article", {"slug": "нет-такой"}),
        "несуществующая статья — внятный отказ")

    # КАЧЕСТВО ПОИСКА — ТОЖЕ ГЕЙТ. Иначе правка весов «чтобы стало лучше»
    # незаметно ломает то, что работало: так уже вышло с «forgot to chart
    # the dressing change», когда редкое клиническое слово перевесило суть
    # вопроса. Цели названы словами человека, а не словами справочника.
    r = handle(c, {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"})
    say(len(r["result"]["prompts"]) == len(PROMPTS),
        f"заготовок объявлено {len(r['result']['prompts'])}")
    r = handle(c, {"jsonrpc": "2.0", "id": 5, "method": "prompts/get",
                   "params": {"name": "write-a-note",
                              "arguments": {"situation": "late entry"}}})
    txt = r["result"]["messages"][0]["content"]["text"]
    say("NEVER ask the nurse for patient identifiers" in txt,
        "заготовка несёт запрет на данные пациента")
    say("NEVER invent a finding" in txt,
        "заготовка несёт запрет выдумывать находки")
    say("error" in handle(c, {"jsonrpc": "2.0", "id": 6, "method": "prompts/get",
                              "params": {"name": "нет-такой"}}),
        "несуществующая заготовка — внятный отказ")

    print()
    ASKED = [
        ("I forgot to chart it until the next morning", "late-entry"),
        ("patient refused the medication", "refusal"),
        ("doctor never called me back", "unanswered-provider-call"),
        ("the order looks wrong to me", "order-looks-wrong"),
        ("I got stuck with a used needle", "needlestick"),
        ("a patient hit me", "workplace-violence"),
        ("I copied yesterday's assessment", "copy-forward"),
        ("I signed it and then saw the mistake", "fix-it-now"),
        ("how do I ask for vacation days", "asking-for-time-off"),
        ("verbal order over the phone", "verbal-orders"),
        ("charting WNL", "charting-by-exception"),
        ("I pulled the med but never gave it", "pulled-not-given"),
    ]
    first = 0
    for q, want in ASKED:
        top = [x["slug"] for x in
               sorted(c["articles"], key=lambda x: -score(x, q))[:3]]
        if top and top[0] == want:
            first += 1
        # Требуем попадания в тройку: агент видит все три и выбирает сам.
        # Требовать первого места значило бы подгонять веса под список.
        say(want in top, f"«{q}» → {top[0] if top else '—'}")
    print(f"  первым местом: {first} из {len(ASKED)}")

    print()
    chart = ("1830 — Pt in room 412, MRN 88213, c/o chest pressure 7/10. "
             "Dr. Patel paged.")
    say(REFUSAL[:40] in call("search_charting", {"query": chart}),
        "кусок карты ОТКЛОНЁН, а не обработан")
    say(REFUSAL[:40] in call("find_phrases", {"situation": chart}),
        "то же самое во втором инструменте")
    say("characters" in call("search_charting", {"query": "x" * 400}),
        "длинный текст отклонён")
    for probe, what in (("DOB 03/14/1961", "дата рождения"),
                        ("SSN 123-45-6789", "номер страховки"),
                        ("pt is a 74 y/o male", "описание пациента")):
        say(REFUSAL[:40] in call("search_charting", {"query": probe}),
            f"отклонено: {what}")
    say("late" in call("search_charting", {"query": "late entry"}).lower(),
        "обычный вопрос при этом проходит")

    print()
    print(f"  ──────────────────────────────────────────────")
    print(f"  {'всё чисто' if not bad else f'ОШИБОК: {bad}'}"
          f" · статей {len(c['articles'])}"
          f" · решений {sum(len(x['cases']) for x in c['articles'])}"
          f" · пар «до/после» {sum(len(x['rewrites']) for x in c['articles'])}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else serve())
