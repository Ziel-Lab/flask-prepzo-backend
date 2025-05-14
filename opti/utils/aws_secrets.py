import os
import boto3
import json

def load_aws_secrets(secret_name, region_name="us-east-1"):  # Change region if needed
    """Fetch secrets from AWS Secrets Manager and inject into os.environ"""
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)

    try:
        response = client.get_secret_value(SecretId=secret_name)
        secret_string = response['SecretString']
        secrets = json.loads(secret_string)

        for key, value in secrets.items():
            os.environ[key] = value
        print(f"✅ Loaded secrets from AWS Secrets Manager ({secret_name})")

    except Exception as e:
        print(f"❌ Failed to load secrets from AWS Secrets Manager: {e}")
