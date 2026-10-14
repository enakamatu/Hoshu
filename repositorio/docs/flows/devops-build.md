* **Onde salvar:** `hoshu/docs/flows/devops-build.md`  
* **O que colocar:** O fluxo de compilação com Git.

```markdown
# Fluxo: DevOps & Compilação Git

```mermaid
flowchart TD
    A[Disparo da Compilação] --> B[Git Fetch / Pull]
    B --> C{Conflito no Git?}
    C -- Sim --> D[Abortar e Notificar Operador]
    C -- Não --> E[Executar Compilador CLI]
    E --> F{Exit Code == 0?}
    F -- Não --> G[Exibir Logs de Erro de Sintaxe]
    F -- Sim --> H[Gerar Repositório/Artefato]
    H --> I[Concluído com Sucesso]