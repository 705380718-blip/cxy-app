"""Conservative evidence gate for new tasks; never invent actions from questions."""
import re

ACTION = r'(?:整理|汇总|补充|提交|上传|发送|提供|安排|处理|修复|排查|核对|确认|更新|完成|交付|测试|部署|对接|跟进|修改|落实|收集|填写|制作|合并|审核|复核|评审|通知|准备|加入|拉齐|同步|沟通|协调|联系|评估|检查|验收|开通|配置|迁移|回复|反馈|编写|撰写)'
REQUEST = re.compile(r'(?:请(?!问)|麻烦|帮忙|需要|务必|记得|要求|负责(?!人)|我来|我会|我们会|今天|明天|后天|本周|下周|周[一二三四五六日天]|把).{0,50}?' + ACTION)
IMPERATIVE = re.compile(r'^\s*' + ACTION + r'.{1,60}(?:一下|下吧|之前|以前|前提交|前完成|，|。|$)')
COMPLETED = re.compile(r'(?:已经|早就|之前|上周|昨天|刚才|已).{0,12}' + ACTION + r'|(?:完成了|提交了|上传了|处理好了|已搞定)')
NEGATED = re.compile(r'(?:不用|不需要|无需|不要|不必|取消|暂不).{0,20}' + ACTION)
STRONG_INTENT = re.compile(r'(?:请(?!问)|麻烦|帮忙|务必|记得|要求|负责(?!人)|我来|我会(?!不会)|我们会)')
QUESTION = re.compile(r'(?:[?？]|吗|是否|是不是|哪个|什么|多少|怎么|如何)')


def actionable_quote(message, quote):
    """Require a literal, substantive quote and inspect its entire clause."""
    if not quote or len(quote.strip()) < 4 or quote not in message or not re.search(ACTION,quote):
        return False
    # Retain question punctuation. Splitting it away could turn a question into an imperative.
    clauses = re.split(r'[。！!；;\n]', message)
    relevant = [c for c in clauses if quote in c]
    if not relevant:
        relevant = [message]  # Multi-clause quotes still use full context.
    for clause in relevant:
        if NEGATED.search(clause):
            continue
        if QUESTION.search(clause) and not STRONG_INTENT.search(clause):
            continue
        explicit = REQUEST.search(clause)
        if explicit:
            # A completed action may be followed by a genuinely new request.
            action_clause = clause[explicit.start():]
            requested_action = re.findall(ACTION, explicit.group())[-1]
            completions = COMPLETED.findall(action_clause)
            same_action_done = any(requested_action in completion or completion in ('完成了','处理好了','已搞定') for completion in completions)
            if not same_action_done:
                return True
        if not QUESTION.search(clause) and not COMPLETED.search(clause) and IMPERATIVE.search(clause):
            return True
    return False


def supported_task(candidate, messages):
    if candidate.type != 'task' or candidate.target_item_id is not None:
        return True  # Updates refer to an already established task, including waiting results.
    basis = candidate.task_basis
    if basis is None or basis.message_id not in candidate.evidence_message_ids:
        return False
    message = messages.get(basis.message_id, {})
    return actionable_quote(message.get('text', ''), basis.quote)
