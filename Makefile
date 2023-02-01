# SCCJS App

.PHONY: help
help: ## Show this help.
	@fgrep -h "##" $(MAKEFILE_LIST) | fgrep -v fgrep | sed -e 's/\\$$//' | sed -e 's/##//'

.PHONY: login-ecr
login-ecr: ## Log into ECR registry
	@aws ecr-public get-login-password --region us-east-1 | docker login --username AWS --password-stdin public.ecr.aws/h1l0a3x3

.PHONY: build-ecs
build-ecs: ## Building ECS image
	@docker build -t sccjs .

.PHONY: push-ecs
push-ecs: ## Push ECS image to ECR
	@docker tag sccjs:latest public.ecr.aws/h1l0a3x3/sccjs:latest
	@docker push public.ecr.aws/h1l0a3x3/sccjs:latest

.PHONY: release-ecs
release-ecs: login-ecr build-ecs push-ecs ## Build and push new ECS image to ECR

test-ecs-local: export SCCJS_USERNAME ?= $(shell bash -c 'read -p "Username: " username; echo $$username')
test-ecs-local: export SCCJS_PASSWORD ?= $(shell bash -c 'read -p "Password: " password; echo $$password')

.PHONY: test-ecs-local
test-ecs-local: ## Test ECS image locally
	@docker run -it --rm --env-file .env sccjs "$$SCCJS_USERNAME" "$$SCCJS_PASSWORD" 2023-02-06 2023-02-07 courtroom

test-ecs-live: export SCCJS_USERNAME ?= $(shell bash -c 'read -p "Username: " username; echo $$username')
test-ecs-live: export SCCJS_PASSWORD ?= $(shell bash -c 'read -p "Password: " password; echo $$password')
test-ecs-live: export OVERRIDES = {"containerOverrides": [{"name": "sccjs", "command": ["${SCCJS_USERNAME}", "${SCCJS_PASSWORD}", "2022-10-10", "2022-10-14"], "environment": [{"name": "SCCJS_SEND_EMAIL", "value": "1"}, {"name": "SCCJS_EMAIL_TO", "value": "james.g.bradshaw@gmail.com"}]}]}
test-ecs-live: export NETWORK = awsvpcConfiguration={subnets=[subnet-0b12f999d81ec4965],assignPublicIp=ENABLED}

.PHONY: test-ecs-live
test-ecs-live: ## Test ECS image in AWS
	@aws ecs run-task --cluster sccjs --launch-type=FARGATE --task-definition='sccjs:2' --overrides="$$OVERRIDES" --network-configuration="$$NETWORK"

.PHONY: lambda-local
lambda-local: ## Run lambda function locally
	@chalice local

lambda-local-request: export SCCJS_USERNAME ?= $(shell bash -c 'read -p "Username: " username; echo $$username')
lambda-local-request: export SCCJS_PASSWORD ?= $(shell bash -c 'read -p "Password: " password; echo $$password')

.PHONY: lambda-local-request
lambda-local-request: ## Make a request to the locally running lambda server
	@curl -X POST -H 'Content-Type: application/json' -d "{\"username\": \"${SCCJS_USERNAME}\", \"password\": \"${SCCJS_PASSWORD}\", \"search_type\": \"courtroom\", \"start_date\": \"2023-02-06\", \"end_date\": \"2023-02-07\"}" localhost:8000
