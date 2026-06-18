import json

def main(text) -> dict:
    """
    判断输入数组长度是否满足条件
    返回 {"valid": bool, "count": int, "message": str}
    """

    if isinstance(text, dict):
        data = text
    else:
        data = json.loads(text)

    # 支持单个对象或数组两种格式
    if isinstance(data, list):
        items = data
    else:
        items = data.get("sub_questions", [])

    count = len(items)

    return {
        "valid": count > 0,
        "count": count,
        "sub_questions": items,
        "message": f"数组长度为 {count}"
    }

 