"""AWS adapters for the application ports.

Every adapter takes an already-built boto3 client (or a signer/sender) so tests can pass
stubbed clients and nothing here creates AWS resources. ``application`` and ``domain`` stay free
of AWS imports; only the deployable apps (``api``, ``workers``) depend on this package.
"""

from aws_adapters.appsync import AppSyncEventsPublisher
from aws_adapters.iot import IotDataCommandPublisher
from aws_adapters.s3 import S3RawMessageStore
from aws_adapters.secrets import database_url_from_secret
from aws_adapters.sqs import SqsCommandQueue, SqsJobQueue

__all__ = [
    "AppSyncEventsPublisher",
    "IotDataCommandPublisher",
    "S3RawMessageStore",
    "SqsCommandQueue",
    "SqsJobQueue",
    "database_url_from_secret",
]
