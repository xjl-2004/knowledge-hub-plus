"""分页契约：camelCase 入参、边界校验与统一返回结构。"""

import pytest
from pydantic import ValidationError

from app.schemas.ai import QuerySessionDto
from app.schemas.base import page_result


def test_page_result_shape():
    payload = page_result([{"id": "1"}], 1, 1, 20)

    assert payload == {
        "items": [{"id": "1"}],
        "total": 1,
        "page": 1,
        "pageSize": 20,
    }


def test_query_dto_accepts_camel_case():
    dto = QuerySessionDto(pageSize=50)

    assert dto.page == 1
    assert dto.page_size == 50


@pytest.mark.parametrize(
    "payload",
    [
        {"page": 0},
        {"pageSize": 0},
        {"pageSize": 101},
    ],
)
def test_query_dto_rejects_out_of_range(payload):
    with pytest.raises(ValidationError):
        QuerySessionDto(**payload)
