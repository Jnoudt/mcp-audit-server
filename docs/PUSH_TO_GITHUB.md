# Push Project 1 to GitHub

Use the nested `mcp-audit-server` directory as the repository root. Do not initialize Git from `C:\Projects` or the enclosing portfolio folder: those locations contain sibling project material and an unrelated ZIP archive.

## 1. Open and verify the exact project folder

In VS Code, choose **File → Open Folder…** and open:

```text
C:\Projects\Remote MCP Tool Server for Domain & Audit Workflows\mcp-audit-server
```

In the VS Code terminal, confirm the current directory and Git root before staging:

```powershell
Get-Location
git rev-parse --show-toplevel
```

The expected root is the `mcp-audit-server` folder above. If Git reports that this is not a repository, initialize it only after confirming the terminal is at that exact path:

```powershell
git init -b main
git rev-parse --show-toplevel
```

If `git rev-parse` reports a parent folder or a sibling project, stop and correct the VS Code folder/terminal before proceeding.

## 2. Review ignore and secret/config readiness

Inspect `.gitignore` before staging. It excludes the Python virtual environment, local Functions settings, `.env` files, frontend dependencies/build output, and tool caches. Check representative paths with:

```powershell
git check-ignore -v .venv frontend\node_modules frontend\dist .env local.settings.json
```

`frontend\package-lock.json` should remain trackable after `npm install`. Keep real keys, local settings, `.env` files, Azure credentials, connection strings, function keys, and bearer tokens out of source and Git. Commit only sanitized examples such as `.env.example`; never put real values in an example file. Review each new file and scan staged changes manually for credentials before pushing.

## 3. Configure and verify the GitHub remote

Check existing remotes:

```powershell
git remote -v
```

If none is configured, create an empty GitHub repository for this project, then add its URL:

```powershell
git remote add origin https://github.com/<OWNER>/<REPOSITORY>.git
git remote -v
```

Confirm that the remote is the intended Project 1 repository and not the portfolio parent or another project.

## 4. Stage and inspect only this project

From the verified `mcp-audit-server` root, stage its contents and review the exact index:

```powershell
git add -A
git status --short
git diff --cached --name-only
git diff --cached
```

Check that no `.venv`, `node_modules`, `dist`, local settings, environment files, credentials, or unrelated portfolio files are staged. Because the repository root is nested inside Project 1, do not run `git add` from `C:\Projects` or the enclosing Project 1 folder.

After review, create the initial commit and push the intended branch:

```powershell
git commit -m "Initial Project 1 MCP audit server"
git push -u origin main
```

Review the staged diff and repository remote before committing; do not commit or push until you have explicitly approved that step.

## 5. Verify GitHub Actions and deployment configuration

After the push, open the repository's **Actions** tab and inspect the runs for:

- **Test and deploy MCP audit server** (`.github/workflows/app-deploy.yml`): pull requests and pushes run compilation, Ruff, and pytest. A push to `main` proceeds to deployment only after tests pass.
- **Security and vulnerability checks** (`.github/workflows/secops.yml`): runs Ruff, pytest, Bandit, and pip-audit. Optional commercial scanners run only when their enablement variables and credentials are configured.

For Azure deployment, configure repository variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, and `AZURE_FUNCTIONAPP_NAME`, plus the matching federated OIDC credential in Azure. The workflow uses OIDC; do not add publish profiles, client secrets, function keys, Cosmos keys, or connection strings to the repository. A failed or skipped deploy without Azure configuration is not evidence that local tests failed.

The current workflows deploy the Azure Function only. They do not publish the React frontend; configure and review a separate frontend hosting workflow only if that deployment is later required.
