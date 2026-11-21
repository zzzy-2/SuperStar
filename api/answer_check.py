import json
import re


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


def _matches_single_option(answer, options):
    """A complete option may itself contain punctuation such as an enumeration comma."""
    if not isinstance(answer, str) or not isinstance(options, str):
        return False
    target = re.sub(r"\s+", "", answer)
    if not target:
        return False
    for option in options.splitlines():
        option = option.strip()
        # Chaoxing prefixes each extracted option with its letter.
        option_text = re.sub(r"^[A-Za-z]\s*[.、:：)?）]?\s*", "", option)
        for candidate in (option, option_text):
            if candidate and re.sub(r"\s+", "", candidate) == target:
                return True
    return False


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
    if type == 'single':
        if _matches_single_option(answer, options):
            return True
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
