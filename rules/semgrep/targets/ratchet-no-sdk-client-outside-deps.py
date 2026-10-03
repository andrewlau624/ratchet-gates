import boto3

# ruleid: ratchet-no-sdk-client-outside-deps
client = boto3.client("ses")
