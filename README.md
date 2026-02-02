# ADO Agent – Streamlit UI (PoC)

A minimal **Streamlit** UI that calls your **Azure AI Foundry Agent** which uses a **Logic App** action to fetch Azure DevOps work items.

## 1) Run locally

```bash
# 1) Authenticate to Azure (so DefaultAzureCredential works)
az login

# 2) Clone / unzip this folder, cd into it, then set env vars
export AZURE_AI_PROJECT_ENDPOINT="https://<id>.services.ai.azure.com/api/projects/<project>"
export AZURE_AI_AGENT_ID="<your-agent-id>"

# 3) Install & run
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL (usually http://localhost:8501), fill **Area Path** (e.g. `WorkTop - Demo\BFSI\NT`) and press **Fetch from Agent**.

> The UI calls the Agents API (Threads → Messages → Runs → poll) and prints the agent’s reply. The reply should include the JSON returned by your Logic App tool.

## 2) Deploy to Azure App Service (quick demo path)

1. Create **Linux** Web App (Python).  
2. In the App Service **Configuration → Application settings**, add:
   - `AZURE_AI_PROJECT_ENDPOINT` = your Foundry project endpoint
   - `AZURE_AI_AGENT_ID`       = your agent id
3. Enable **System-assigned Managed Identity** on the Web App, and grant it **Azure AI User** (or equivalent) on the Foundry project.  
4. Deploy these files (ZIP deploy or VS Code).  
5. Set **Startup Command** to:
   ```bash
   bash /home/site/wwwroot/streamlit.sh
   ```
6. Browse the app URL.

> Notes:
> - Streamlit must listen on **0.0.0.0:8000** on App Service; the provided `streamlit.sh` configures that.  
> - The **Agents SDK** uses `DefaultAzureCredential`, which will use the Web App’s managed identity in Azure.

## 3) Files

- `app.py` – Streamlit UI + Agents API client
- `requirements.txt` – Python deps
- `streamlit.sh` – Start script for App Service
- `.deployment` – disables Oryx build (optional)
- `.env.sample` – env var template for local dev

---
### References
- Azure AI Foundry Agent Service – **threads / runs** pattern & SDK usage.  
- Streamlit on Azure App Service – **run on 0.0.0.0:8000** with a startup script.
