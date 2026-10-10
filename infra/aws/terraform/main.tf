# 234's web search (docs/web.md): an Amazon Bedrock AgentCore Gateway (MCP, IAM inbound) with the managed
# web-search connector as its target, and one IAM user that may invoke that gateway and nothing else.
# The user's access key is not made here (a key in the state is a key on disk): tools/aws-search.sh makes it and
# puts it straight into the connectors Worker's secrets. us-east-1 only: the Web Search tool is offered there.
#
#   cd infra/aws/terraform && terraform init && terraform apply     (or: tools/aws-search.sh up)

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = { app = "234", purpose = "web-search" }
  }
}

variable "gateway_name" {
  type    = string
  default = "ask234-web-search"
}

variable "target_name" {
  type        = string
  default     = "web-search-tool"
  description = "Names the gateway target, and so the tool (<target>___WebSearch). 234 expects the default."
}

variable "caller_name" {
  type    = string
  default = "ask234-web-search-caller"
}

data "aws_caller_identity" "me" {}
data "aws_region" "here" {}

resource "aws_iam_role" "gateway" {
  name        = "${var.gateway_name}-gateway"
  description = "What the gateway acts as when it calls the managed Web Search tool."
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.me.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:bedrock-agentcore:${data.aws_region.here.region}:${data.aws_caller_identity.me.account_id}:gateway/*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "invoke_web_search" {
  name = "InvokeWebSearch"
  role = aws_iam_role.gateway.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "bedrock-agentcore:InvokeWebSearch"
      Resource = "arn:aws:bedrock-agentcore:${data.aws_region.here.region}:aws:tool/web-search.v1"
    }]
  })
}

resource "aws_bedrockagentcore_gateway" "search" {
  name            = var.gateway_name
  description     = "Web search for 234, called with IAM (SigV4)."
  authorizer_type = "AWS_IAM"
  role_arn        = aws_iam_role.gateway.arn

  depends_on = [aws_iam_role_policy.invoke_web_search]
}

resource "aws_bedrockagentcore_gateway_target" "web_search" {
  gateway_identifier = aws_bedrockagentcore_gateway.search.gateway_id
  name               = var.target_name
  description        = "The managed Web Search connector."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      connector {
        source {
          connector_id = "web-search"
        }
        configuration {
          name = "WebSearch"
        }
      }
    }
  }
}

resource "aws_iam_user" "caller" {
  name = var.caller_name
}

resource "aws_iam_user_policy" "invoke_this_gateway_only" {
  name = "InvokeThisGatewayOnly"
  user = aws_iam_user.caller.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "bedrock-agentcore:InvokeGateway"
      Resource = aws_bedrockagentcore_gateway.search.gateway_arn
    }]
  })
}

output "gateway_url" {
  description = "The MCP endpoint, for SEARCH_GATEWAY_URL."
  value       = aws_bedrockagentcore_gateway.search.gateway_url
}

output "caller_name" {
  value = aws_iam_user.caller.name
}
