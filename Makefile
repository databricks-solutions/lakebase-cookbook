# Lakebase Cookbook — documentation site (Docusaurus on Cloudflare Workers)
#
# The site source lives in docs/. These targets wrap the npm/wrangler workflow.
# Deploys require a per-machine Cloudflare login (`make login`); no secrets are
# stored in this repo.

DOCS_DIR := docs

.DEFAULT_GOAL := help

.PHONY: help install dev build serve preview deploy login logout clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install site dependencies
	cd $(DOCS_DIR) && npm install

dev: ## Run the local dev server with hot reload (http://localhost:3000)
	cd $(DOCS_DIR) && npm start

build: ## Build the static site into docs/build
	cd $(DOCS_DIR) && npm run build

serve: build ## Build, then serve the production build locally
	cd $(DOCS_DIR) && npm run serve

preview: build ## Build, then validate the Cloudflare deploy without publishing (dry run)
	cd $(DOCS_DIR) && npm run deploy:preview

deploy: build ## Build and deploy the site to Cloudflare (maintainers only)
	cd $(DOCS_DIR) && npm run deploy

login: ## Authenticate this machine with Cloudflare (one-time, interactive)
	cd $(DOCS_DIR) && npx wrangler login

logout: ## Remove the local Cloudflare credentials from this machine
	cd $(DOCS_DIR) && npx wrangler logout

clean: ## Remove the build output and Docusaurus cache
	cd $(DOCS_DIR) && npm run clear && rm -rf build
