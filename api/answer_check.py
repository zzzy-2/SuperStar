import hashlib
import html
import json
import re
import unicodedata


def parse_ai_answer(content, question_type):
    """Accept one answer string or an array without splitting strings into characters."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("AI message.content must be a nonempty string")
    text = content.strip()
    fenced = re.fullmatch(r"\x60{3}(?:json)?\s*(.*?)\s*\x60{3}", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict) or "Answer" not in payload:
        raise ValueError("AI response must be an object containing Answer")
    value = payload["Answer"]
    if isinstance(value, str):
        answers = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        answers = value
    else:
        raise ValueError("Answer must be a string or an array of strings")
    if not answers or any(not item.strip() for item in answers):
        raise ValueError("Answer must not be empty or contain blank items")
    if question_type == "single" and len(answers) != 1:
        raise ValueError("A single-choice question must have exactly one Answer item")
    return "\n".join(item.strip() for item in answers)


def answer_cache_key(question):
    """Scope cached answers to the exact title, type and option order."""
    context = {key: question.get(key, "") for key in ("title", "type", "options")}
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    return "matched-v2:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _choice_text(value, cosmetic=False):
    text = unicodedata.normalize("NFKC", html.unescape(str(value)))
    text = re.sub(r"\s+", "", text)
    if cosmetic:
        # Preserve decimal points and numeric separators; normalize prose punctuation only.
        text = re.sub(r"(?<!\d),|,(?!\d)|[。、]", "", text)
    return text


def _choice_options(options):
    if not isinstance(options, str):
        return None
    parsed = {}
    for line in options.splitlines():
        if not line.strip():
            continue
        line = unicodedata.normalize("NFKC", html.unescape(line)).strip()
        match = re.fullmatch(r"([A-Za-z])(?:[.、:：)）]\s*|\s+)?(.+)", line)
        if not match or not match.group(2):
            return None
        label, text = match.group(1).upper(), match.group(2)
        if label in parsed:
            return None
        parsed[label] = text
    return parsed or None


def _resolve_choice_item(value, options):
    """Require a unique whole-option match or an unambiguous explicit option reference."""
    value = unicodedata.normalize("NFKC", str(value)).strip()
    if not value:
        return None
    matches = set()
    for cosmetic in (False, True):
        target = _choice_text(value, cosmetic)
        matches = {label for label, text in options.items()
                   if target and _choice_text(text, cosmetic) == target}
        if matches:
            break
    references = set()
    if re.fullmatch(r"[A-Za-z]", value):
        label = value.upper()
        if label in options:
            references.add(label)
    else:
        explicit = re.fullmatch(r"([A-Za-z])(?:[.、:：)）]\s*|\s+)(.+)", value, flags=re.DOTALL)
        if explicit:
            label, text = explicit.group(1).upper(), explicit.group(2)
            if label in options and any(
                    _choice_text(text, soft) == _choice_text(options[label], soft)
                    for soft in (False, True)):
                references.add(label)
    candidates = matches | references
    return next(iter(candidates)) if len(candidates) == 1 else None


def _letter_set(value, options):
    if not re.fullmatch(r"[A-Za-z\s,，、#|;；/]+", value):
        return None
    letters = re.sub(r"[\s,，、#|;；/]+", "", value).upper()
    if letters and all(letter in options for letter in letters):
        return set(letters)
    return None


def resolve_answer(answer, question_type, options=None, true_list=None, false_list=None):
    """Return a submission value only when the entire answer can be resolved; else None."""
    if not isinstance(answer, str) or not answer.strip():
        return None
    value = answer.strip()
    if question_type in ("single", "multiple"):
        parsed = _choice_options(options)
        if not parsed:
            return None
        whole = _resolve_choice_item(value, parsed)
        if question_type == "single":
            return whole
        letters = _letter_set(unicodedata.normalize("NFKC", value), parsed)
        if whole:
            # Literal option text and compact letter references must not disagree.
            if letters and letters != {whole}:
                return None
            return whole
        if letters:
            return "".join(sorted(letters))
        parts = [value]
        for separator in ("\n", "\r", "\t", "#", "|", ";", "；", ",", "，", "、"):
            candidate = [item.strip() for item in value.split(separator) if item.strip()]
            if len(candidate) > 1:
                parts = candidate
                break
        resolved = [_resolve_choice_item(item, parsed) for item in parts]
        if any(item is None for item in resolved):
            return None
        return "".join(sorted(set(resolved)))
    if question_type == "judgement":
        normalize = lambda item: unicodedata.normalize("NFKC", str(item)).strip().casefold()
        positives = {normalize(item) for item in (true_list or [])}
        negatives = {normalize(item) for item in (false_list or [])}
        positives.update(("正确", "对", "是", "√", "true"))
        negatives.update(("错误", "错", "否", "×", "false"))
        normalized = normalize(value)
        if normalized in positives and normalized not in negatives:
            return "true"
        if normalized in negatives and normalized not in positives:
            return "false"
        return None
    if question_type in ("completion", "shortanswer"):
        return value
    return None


def check_single(answer):
    if answer is None:
        return False

    text = str(answer).strip()
    if not text:
        return False

    # 单选答案文本中常见逗号（中英文）是句内标点，不应据此判定为多选。
    # 仅在出现明显“多段答案”分隔符时，才判定为非单选。
    strong_delimiters = ["\n", "|", "#", "\t", "\r", "、"]
    for sep in strong_delimiters:
        parts = [p.strip() for p in text.split(sep) if p.strip()]
        if len(parts) > 1:
            return False

    return True


def check_multiple(answer):
    _t = cut(answer)
    if _t is not None and len(_t) > 0:
        return True
    return False


def check_judgement(answer, true_list, false_list):
    if answer in true_list:
        return 1
    elif answer in false_list:
        return 0
    else:
        return -1


def check_completion(answer):
    if len(answer) > 0:
        return True
    else:
        return False


def check_answer(answer, type, tiku, options=None):  # 只会写小杯代码，这里用个tiku感觉怪怪的，但先这么写着
    if options is not None:
        return resolve_answer(answer, type, options, tiku.true_list, tiku.false_list) is not None
    if type == 'single':
        if check_single(answer) and check_judgement(answer, tiku.true_list, tiku.false_list) == -1:
            return True
    elif type == 'multiple':
        if check_multiple(answer) and check_judgement(answer, tiku.true_list, tiku.false_list) == -1:
            return True
    elif type == 'completion':
        if check_completion(answer):
            return True
    elif type == 'judgement':
        if check_judgement(answer, tiku.true_list, tiku.false_list) != -1:
            return True
    else:  # 未知类型不匹配
        return True
    return False


def cut(answer):
    cut_char = [
    "\n", "\r", "\t", "#", "|",
    ",", "，", "*", "-", "_", "+",
    "@", "~", "/", "\\", ".", "&", " ", "、",
    ]
    if answer is None:
        return None

    answer = str(answer)
    for char in cut_char:
        if char not in answer:
            continue
        res = [opt.strip() for opt in answer.split(char) if opt.strip()]
        if res:
            return res
    stripped = answer.strip()
    return [stripped] if stripped else None
