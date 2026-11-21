# Run Project 1 locally

These commands are for the `mcp-audit-server` folder only. In PowerShell, change to that folder first:

```powershell
Set-Location "C:\Projects\Remote MCP Tool Server for Domain & Audit Workflows\mcp-audit-server"
```

## 1. Create and activate Python 3.12 environment

Install Python 3.12 and Azure Functions Core Tools v4 before continuing. From the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

The version should report Python 3.12.x. If PowerShell blocks activation, allow scripts for this terminal only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Install the project's runtime, development, and security-check dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-sec.txt
```

## 2. Run Python checks

Run these commands from `mcp-audit-server` with `.venv` active:

```powershell
python -m pytest -q
ruff check function_app.py src tests
mypy function_app.py src tests
bandit -r function_app.py src
pip-audit -r requirements.txt -r requirements-dev.txt -r requirements-sec.txt
```

`pip-audit` checks package advisories and needs access to its package advisory service. It does not need application credentials. Address findings through dependency review rather than suppressing them without justification.

## 3. Start the local MCP server

In a PowerShell terminal at the project folder, start Azure Functions Core Tools:

```powershell
func start
```

The local endpoint is `http://127.0.0.1:7071/api/mcp`. The audit store uses process-local memory when `COSMOS_ENDPOINT` is not set; local demo requests do not require Azure or Cosmos DB. The memory store is not durable and is cleared when the function host stops.

The MCP route uses Function-level authorization. If your local host requires a key, use its locally generated function key in the frontend's **Azure Functions key** field. Do not add keys to source files, command history, endpoint query strings, or checked-in settings.

## 4. Run the React frontend

Use a second terminal and keep the function host running. Install Node.js/npm if they are not already available:

```powershell
Set-Location "C:\Projects\Remote MCP Tool Server for Domain & Audit Workflows\mcp-audit-server\frontend"
npm install
npm run lint
npm run build
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). Vite proxies `/api` requests to `http://127.0.0.1:7071`, avoiding a browser CORS setup for local development. Use **Connect to backend** and select the needed authorization type. The key field is held only in the open page's React component state and is not stored in `localStorage` or `sessionStorage`.

If the MCP host is stopped, the console remains usable in explicitly labeled **Offline / local demo mode**. Its fixture results and audit rows are illustrative and are not requests or records from the backend. A separately hosted frontend requires the MCP endpoint's approved CORS and authentication configuration.
