# Lakebase Cookbook — documentation site (Astro on Cloudflare Workers)
#
# The site source lives in site/. These targets wrap the npm/wrangler workflow.
# Deploys require a per-machine Cloudflare login (`make login`); no secrets are
# stored in this repo.

SITE_DIR := site

.DEFAULT_GOAL := help

.PHONY: help install dev build serve preview deploy login logout clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install site dependencies
	cd $(SITE_DIR) && npm install

dev: ## Run the local dev server with hot reload (http://localhost:3000)
	cd $(SITE_DIR) && npm run dev

build: ## Build the static site into site/dist
	cd $(SITE_DIR) && npm run build

serve: build ## Build, then serve the production build locally
	cd $(SITE_DIR) && npm run preview

preview: build ## Build, then validate the Cloudflare deploy without publishing (dry run)
	cd $(SITE_DIR) && npm run deploy:preview

deploy: build ## Build and deploy the site to Cloudflare (maintainers only)
	cd $(SITE_DIR) && npm run deploy

login: ## Authenticate this machine with Cloudflare (one-time, interactive)
	cd $(SITE_DIR) && npx wrangler login

logout: ## Remove the local Cloudflare credentials from this machine
	cd $(SITE_DIR) && npx wrangler logout

clean: ## Remove the build output and Astro cache
	cd $(SITE_DIR) && rm -rf dist .astro
