import pytest

from tests.models.contract import CONTRACT_REQUEST, CONTRACT_RESPONSE, assert_contract_response
from usta.core.errors import ProviderQuotaError
from usta.models.fake import FakeModel, call, reply


async def test_fake_meets_the_contract_and_records_requests() -> None:
    model = FakeModel([CONTRACT_RESPONSE])
    assert_contract_response(await model.complete(CONTRACT_REQUEST))
    assert model.requests == [CONTRACT_REQUEST]


async def test_script_can_raise_and_compute() -> None:
    model = FakeModel([ProviderQuotaError("cap"), lambda req: reply(req.prompt_version)])
    with pytest.raises(ProviderQuotaError):
        await model.complete(CONTRACT_REQUEST)
    assert (await model.complete(CONTRACT_REQUEST)).message.text() == "contract-v1"


async def test_exhausted_script_fails_loudly() -> None:
    with pytest.raises(AssertionError, match="script exhausted"):
        await FakeModel([]).complete(CONTRACT_REQUEST)


def test_call_helper_builds_a_tool_use_response_with_unique_ids() -> None:
    a, b = call("todo", {"items": []}), call("todo", {"items": []})
    assert a.stop == "tool_use"
    assert a.tool_calls()[0].name == "todo"
    assert a.tool_calls()[0].id != b.tool_calls()[0].id
