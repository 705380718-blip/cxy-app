from app.extractor import extract


def test_at_me_and_question_match():
    result = extract("@我 请问什么时候处理？", ("延期",), True)
    assert result is not None
    assert result.category == "question"
    assert "@我" in result.rules


def test_noise_is_ignored():
    assert extract("收到，谢谢", ("延期",), False) is None


def test_custom_keyword_matches():
    result = extract("这个节点可能延期", ("延期",), False)
    assert result is not None
    assert result.category == "keyword"


def test_target_person_mention_matches():
    result = extract("@项目经理 请同步一下进度", (), False, ("项目经理", "产品负责人"))
    assert result is not None
    assert result.category == "target_mention"
    assert "@项目经理" in result.rules
