### 5. Diagramas de Fluxo
* **Onde salvar:** `hoshu/docs/flows/patch-pipeline.md`  
* **O que colocar:** A máquina de estados da aplicação do patch com rollback automático.

```markdown
# Fluxo: Pipeline de Aplicação de Patch

```mermaid
stateDiagram-v2
    [*] --> Idle: Aguardando patch
    Idle --> ValidandoArquivo: Upload/Seleção (.ptm)
    ValidandoArquivo --> ParandoServicos: Arquivo íntegro
    ValidandoArquivo --> ErroValidacao: Arquivo corrompido/inválido
    
    ParandoServicos --> CriandoBackup: Serviços parados (Exit 0)
    ParandoServicos --> FalhaParada: Timeout ao parar serviço
    
    CriandoBackup --> AplicandoPatch: Backup concluído
    AplicandoPatch --> SubindoServicos: Aplicação OK (Exit 0)
    AplicandoPatch --> RestaurandoBackup: Aplicação Falhou (Exit != 0)
    
    RestaurandoBackup --> SubindoServicos: Backup Restaurado
    SubindoServicos --> Finalizado: Serviços ativos
    Finalizado --> [*]