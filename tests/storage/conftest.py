"""Shared moto fixture for repository tests (ROADMAP.md 1.3). ``table`` gives each test its own
in-memory DynamoDB, so tests never touch a real AWS account or need Docker."""

from __future__ import annotations

from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table


@pytest.fixture
def table() -> Iterator[Table]:
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
            TableName="Texas42",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield resource.Table("Texas42")
